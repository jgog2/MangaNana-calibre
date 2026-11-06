"""Mode-aware, language-aware source confidence for plausible search groups."""

from dataclasses import asdict, dataclass, replace
import json
import threading
import time

from calibre_plugins.manganana.providers.source_policy import supported_media
from calibre_plugins.manganana.discovery.canonical_identity import edition_identity
from calibre_plugins.manganana.publication.publication_specials import inventory_coverage
from calibre_plugins.manganana.providers.cross_source_fallback import build_cross_source_plan
from calibre_plugins.manganana.publication.inventory_comparison import (
    SourceInventory,
    compare_inventories,
    inspect_source_inventory,
)
from calibre_plugins.manganana.discovery.search_cache import (
    INVENTORY_TTL,
    PARTIAL_INVENTORY_REFRESH_SECONDS,
    PARTIAL_INVENTORY_RETRY_SECONDS,
)


@dataclass(frozen=True)
class SearchResolution:
    candidates: tuple
    inventories: tuple
    decision: object = None
    primary: object = None
    language: str = ''
    preferred_language: str = ''
    language_fallback: bool = False
    expected_source_ids: tuple = ()
    fallback_plan: object = None
    error: str = ''

    @property
    def usable(self):
        return self.primary is not None and bool(self.expected_source_ids)


def inventory_is_eligible(inventory, workflow):
    if inventory is None or not inventory.usable:
        return False
    return True


def _reference(source, result):
    value = result.get('url') or result.get('id') or ''
    return source.parse_manga_ref(value) or value


def _metadata(source, result, preferred_language, cache, check_cancel):
    key = (source.source_id, _reference(source, result))
    if key in cache:
        return cache[key]
    if check_cancel:
        check_cancel()
    try:
        value = result.get('url') or result.get('id')
        metadata = dict(source.get_manga(value, preferred=preferred_language) or {})
    except Exception:
        # Metadata enrichment is helpful but must not become a source failure.
        return {}
    cache[key] = metadata
    return metadata


def _enrich_candidate(candidate, metadata):
    result = dict(candidate or {})
    if not metadata:
        return result
    if metadata.get('source_url'):
        result['url'] = metadata['source_url']
    if metadata.get('available_languages') is not None:
        result['available_languages'] = list(metadata.get('available_languages') or ())
    if metadata.get('alternate_titles'):
        aliases = list(result.get('alternate_titles') or ())
        aliases.extend(metadata.get('alternate_titles') or ())
        result['alternate_titles'] = list(dict.fromkeys(str(alias) for alias in aliases if alias))
    for key in ('author', 'year'):
        if not result.get(key) and metadata.get(key):
            result[key] = metadata[key]
    return result


def _reported_languages(source, candidate, metadata):
    reported = metadata.get('available_languages')
    if reported is None:
        reported = candidate.get('available_languages')
    if reported is None:
        reported = getattr(source, 'content_languages', ()) or None
    return None if reported is None else tuple(str(value) for value in reported or ())


def _language_order(registry, candidates, metadata_rows, preferred_language):
    languages = []
    for candidate, metadata in zip(candidates, metadata_rows):
        source = registry.get(candidate.get('source_id'))
        reported = _reported_languages(source, candidate, metadata)
        for language in reported or ():
            language = str(language or '').strip()
            if language and language not in languages:
                languages.append(language)
    preferred = str(preferred_language or 'en')
    # Respect the explicit preference across every equivalent provider first.
    # If unavailable, Japanese is the conservative original-language fallback,
    # but only when a provider actually reported it.
    fallback = []
    if 'ja' in languages and preferred != 'ja':
        fallback.append('ja')
    fallback.extend(language for language in languages if language not in (preferred, 'ja'))
    return tuple([preferred] + fallback)


def _choose_primary(inventories, workflow, special_records=()):
    eligible = [row for row in inventories if inventory_is_eligible(row, workflow)]
    if not eligible:
        return None
    return sorted(eligible, key=lambda row: (
        0 if workflow != 'volume' or row.native_volumes else 1,
        0 if row.complete else 1,
        -inventory_coverage(row, special_records)['main'],
        -inventory_coverage(row, special_records)['specials'],
        -row.native_volumes,
        row.source_id,
    ))[0]


@dataclass(frozen=True)
class _InventoryCacheRecord:
    inventory: SourceInventory
    created_at: float
    retry_after: float = 0


# Claims cover one inventory key only. No lock is held during provider work.
_inventory_claim_lock = threading.RLock()
_inventory_claims = {}
_UNCONDITIONAL_INVENTORY_WRITE = object()


def _inventory_claim_key(cache, key):
    if hasattr(cache, 'inventory_claim_key'):
        return cache.inventory_claim_key(key)
    return ('memory', id(cache)), tuple(key)


def _inventory_clock(cache):
    return float(cache.clock() if hasattr(cache, 'clock') else time.time())


def inventory_cache_key(source, candidate, language):
    key = ('acquisition', source.source_id, _reference(source, candidate),
           language, edition_identity(candidate))
    if getattr(source, 'inventory_contract', ''):
        key += (source.inventory_contract,)
    return key


def _inventory_cache_snapshot(cache, key):
    if hasattr(cache, 'get_inventory_snapshot'):
        snapshot = cache.get_inventory_snapshot(key)
        if snapshot is None:
            return None, None
        try:
            value = json.loads(snapshot[0])
            value.pop('_inventory_snapshot_id', None)
            retry_after = float(value.pop('_inventory_retry_after', 0))
            return _InventoryCacheRecord(SourceInventory(**value), snapshot[1], retry_after), snapshot
        except (ValueError, TypeError, AttributeError):
            # Retain the token even for a malformed payload: repair it only if
            # nobody replaced it while acquisition was in flight.
            return None, snapshot
    if hasattr(cache, 'get_inventory'):
        hit = cache.get_inventory(key, allow_stale=True)
        if hit is None:
            return None, None
        try:
            value = dict(hit.value)
            retry_after = float(value.pop('_inventory_retry_after', 0))
            return _InventoryCacheRecord(SourceInventory(**value),
                                         _inventory_clock(cache) - hit.age_seconds, retry_after), hit.value
        except Exception:
            return None, hit.value
    value = cache.get(key)
    if isinstance(value, _InventoryCacheRecord):
        return value, value
    # Caller-owned legacy snapshots have no timestamp. Refresh partial ones
    # once; leave healthy snapshots reusable until replaced by this lifecycle.
    if isinstance(value, SourceInventory):
        return _InventoryCacheRecord(value, _inventory_clock(cache) if value.complete and not value.error else 0), value
    return None, value


def _inventory_cache_record(cache, key):
    return _inventory_cache_snapshot(cache, key)[0]


def _inventory_refresh_due(record, now):
    age = max(0, now - record.created_at)
    partial = record.inventory.usable and (not record.inventory.complete or record.inventory.error)
    return now >= record.retry_after and (age > INVENTORY_TTL or
                                         partial and age >= PARTIAL_INVENTORY_REFRESH_SECONDS)


def _inventory_cache_get(cache, key):
    record = _inventory_cache_record(cache, key)
    return record.inventory if record and not _inventory_refresh_due(record, _inventory_clock(cache)) else None


def inventory_refresh_due(cache, keys):
    """Read-only query-snapshot gate; never acquire chapters while rendering."""
    for key in keys:
        key = tuple(key)
        record = _inventory_cache_record(cache, key)
        with _inventory_claim_lock:
            if (record and record.inventory.usable and
                    _inventory_claim_key(cache, key) not in _inventory_claims and
                    _inventory_refresh_due(record, _inventory_clock(cache))):
                return True
    return False


def snapshot_inventory_contract_changed(registry, snapshot):
    """Reject saved qualifications made with an older adapter parser contract.

    This checks saved keys only, without HTTP, inventory reads or changing any
    other provider's cache. Adapter fixes must not leave old empty listings
    or old rankings in an otherwise fresh final query snapshot.
    """
    for key in snapshot.get('inventory_keys') or ():
        if len(key) < 5 or key[0] != 'acquisition':
            continue
        source = registry.get(key[1])
        contract = getattr(source, 'inventory_contract', '')
        if contract and (len(key) != 6 or key[-1] != contract):
            return True
    return False


def snapshot_inventory_refresh_due(cache, registry, snapshot, preferred_language):
    keys = snapshot.get('inventory_keys')
    if keys is None:
        # Older query snapshots lack exact qualification keys. Inspect only
        # already-cached matching records; no missing inventory triggers work.
        keys = []
        for card in snapshot.get('final_cards') or ():
            row = dict(card.get('provider_record') or card.get('primary') or {})
            source = registry.get(row.get('source_id'))
            if source is not None:
                languages = {preferred_language, *(row.get('available_languages') or ()),
                             *(getattr(source, 'content_languages', ()) or ())}
                keys.extend(inventory_cache_key(source, row, language) for language in languages)
    return inventory_refresh_due(cache, keys)


def _inventory_cache_put(cache, key, inventory, created_at=None, retry_after=0,
                         expected_snapshot=_UNCONDITIONAL_INVENTORY_WRITE, check_cancel=None):
    # A transport/parser failure is not evidence of permanent unavailability.
    if inventory.error and not inventory.usable:
        return False
    if hasattr(cache, 'put_inventory'):
        try:
            value = asdict(inventory)
            if retry_after:
                value['_inventory_retry_after'] = retry_after
            if expected_snapshot is not _UNCONDITIONAL_INVENTORY_WRITE and hasattr(cache, 'compare_and_set_inventory'):
                return cache.compare_and_set_inventory(key, value, expected_snapshot, created_at, check_cancel)
            cache.put_inventory(key, value, created_at=created_at)
            return True
        except InterruptedError:
            raise
        except Exception:
            return False
    else:
        if expected_snapshot is not _UNCONDITIONAL_INVENTORY_WRITE and cache.get(key) is not expected_snapshot:
            return False
        cache[key] = _InventoryCacheRecord(inventory,
            _inventory_clock(cache) if created_at is None else created_at, retry_after)
        return True


def _retains_cached_chapters(previous, current):
    # Exact rows, including opaque IDs and metadata, with duplicate multiplicity.
    # This permits progress from a larger partial snapshot without a guessed union.
    remaining = list(current.chapter_records)
    if not previous.chapter_records:
        return False
    for row in previous.chapter_records:
        try:
            remaining.remove(row)
        except ValueError:
            return False
    return True


def _cached_inventory(cache, key, inspect, check_cancel=None, force=False, refresh_allowed=True):
    """One worker refresh per key, retaining usable rows during/after failure."""
    claim = _inventory_claim_key(cache, key)
    while True:
        if check_cancel:
            check_cancel()
        record, snapshot = _inventory_cache_snapshot(cache, key)
        with _inventory_claim_lock:
            if record and not force and not _inventory_refresh_due(record, _inventory_clock(cache)):
                return record.inventory
            pending = _inventory_claims.get(claim)
            if record and record.inventory.usable and (pending or not refresh_allowed):
                return record.inventory
            if pending is None:
                pending = _inventory_claims[claim] = threading.Event()
                break
        # Only cold consumers wait. Existing partial data stays immediately usable.
        pending.wait(0.05)
        force = False
    try:
        # A previous owner can finish between our read and claiming this key.
        # Re-read after claiming, without holding the registry lock over SQLite.
        record, snapshot = _inventory_cache_snapshot(cache, key)
        if record and not force and not _inventory_refresh_due(record, _inventory_clock(cache)):
            return record.inventory
        if check_cancel:
            check_cancel()
        inventory = inspect()
        if check_cancel:
            check_cancel()
        now = _inventory_clock(cache)
        if inventory.error and not inventory.usable and not (record and record.inventory.usable):
            # Cold failures remain uncached. A competing process may nonetheless
            # have supplied a usable result while this acquisition failed.
            current = _inventory_cache_record(cache, key)
            if check_cancel:
                check_cancel()
            return current.inventory if current is not None else inventory
        if record and record.inventory.usable and (not inventory.complete or inventory.error):
            # A failed/partial refresh must not replace usable rows with an
            # empty or smaller prefix, or invent a union of different snapshots.
            created_at = now
            if not inventory.usable or not _retains_cached_chapters(record.inventory, inventory):
                created_at = record.created_at
                inventory = replace(record.inventory, complete=False,
                    error=record.inventory.error or inventory.error or 'Inventory refresh incomplete; cached chapters retained.')
            saved = _inventory_cache_put(cache, key, inventory, created_at,
                now + PARTIAL_INVENTORY_RETRY_SECONDS, expected_snapshot=snapshot, check_cancel=check_cancel)
        else:
            saved = _inventory_cache_put(cache, key, inventory, expected_snapshot=snapshot, check_cancel=check_cancel)
        if not saved and hasattr(cache, 'compare_and_set_inventory'):
            current = _inventory_cache_record(cache, key)
            if check_cancel:
                check_cancel()
            if current is not None:
                return current.inventory
            raise RuntimeError('Inventory cache changed or could not be saved; refresh not published.')
        return inventory
    finally:
        with _inventory_claim_lock:
            _inventory_claims.pop(claim, None)
            pending.set()


def session_plan_fresh(payload, now):
    """Presentation snapshots must not bypass acquisition cache expiry."""
    if payload is None or '_cached_at' not in payload:
        return False
    if '_expires_at' in payload:
        return payload['_cached_at'] <= now < payload['_expires_at']
    partial = bool(payload.get('inventory_error') or any(
        (payload.get('plan') or {}).get(key) for key in ('feed_error', 'aggregate_error')))
    lifetime = PARTIAL_INVENTORY_REFRESH_SECONDS if partial else INVENTORY_TTL
    age = now - payload['_cached_at']
    return 0 <= age < lifetime


def inventory_snapshot_deadline(cache, source, candidate, language):
    """Read on the acquisition worker, never deserialize chapter rows in paint."""
    record = _inventory_cache_record(cache, inventory_cache_key(source, candidate, language))
    if record is None:
        return _inventory_clock(cache)
    partial = not record.inventory.complete or bool(record.inventory.error)
    return max(record.retry_after, record.created_at + (
        PARTIAL_INVENTORY_REFRESH_SECONDS if partial else INVENTORY_TTL))


def cached_source_inventory(cache,source,candidate,language,workflow,check_cancel=None,force=False):
    """Share the existing validated acquisition cache and single-flight claims.

    Selected browsing and compatible-source inspection use the same provider,
    series, language, edition and adapter-contract identity as discovery.
    """
    return _cached_inventory(cache,inventory_cache_key(source,candidate,language),
        lambda:inspect_source_inventory(source,candidate,language,workflow=workflow),check_cancel,force=force)


class _InspectionBudgetExhausted(Exception):
    pass


def resolve_search_group(registry, candidates, preferred_language, workflow,
                         metadata_cache=None, inventory_cache=None, check_cancel=None,
                         include_adult=False, inspection_budget=None, refresh_inventory=False):
    """Resolve one already-relevant canonical group without fetching page bytes."""
    candidates = tuple(dict(candidate) for candidate in candidates or () if supported_media(candidate))
    metadata_cache = metadata_cache if metadata_cache is not None else {}
    inventory_cache = inventory_cache if inventory_cache is not None else {}
    metadata_rows = []
    enriched = []
    for candidate in candidates:
        if check_cancel:
            check_cancel()
        source = registry.get(candidate.get('source_id'))
        capabilities = set(getattr(source, 'capabilities', ()) or ()) if source else set()
        needs_metadata = (
            candidate.get('available_languages') is None or
            (not include_adult and 'adult_metadata' in capabilities and
             not isinstance(candidate.get('adult'), bool))
        )
        metadata = (_metadata(source, candidate, preferred_language, metadata_cache, check_cancel)
                    if source and needs_metadata else {})
        metadata_rows.append(metadata)
        enriched.append(_enrich_candidate(candidate, metadata))

    if not include_adult and any(
            candidate.get('adult') is True or metadata.get('adult') is True
            for candidate, metadata in zip(enriched, metadata_rows)):
        return SearchResolution(
            tuple(enriched), (), preferred_language=str(preferred_language or 'en'),
            error='Adult title blocked by the current search preference.',
        )

    expected_edition = edition_identity(enriched[0]) if enriched else 'original'
    attempts = []
    for language in _language_order(registry, enriched, metadata_rows, preferred_language):
        inventories = []
        for candidate, metadata in zip(enriched, metadata_rows):
            if check_cancel:
                check_cancel()
            source = registry.get(candidate.get('source_id'))
            if source is None:
                continue
            reported = _reported_languages(source, candidate, metadata)
            if reported is not None and language not in reported:
                continue
            # Inspection already records both native membership and chapter
            # rows. Reuse it across Chapter/Volume switches instead of issuing
            # the same provider inventory request again.
            cache_key = inventory_cache_key(source, candidate, language)
            def inspect():
                if inspection_budget is not None:
                    if inspection_budget[0] <= 0:
                        raise _InspectionBudgetExhausted()
                    inspection_budget[0] -= 1
                return inspect_source_inventory(source, candidate, language, workflow=workflow)
            try:
                inventory = _cached_inventory(inventory_cache, cache_key, inspect, check_cancel,
                    force=refresh_inventory,
                    refresh_allowed=inspection_budget is None or inspection_budget[0] > 0)
            except _InspectionBudgetExhausted:
                return SearchResolution(tuple(enriched),tuple(attempts)+tuple(inventories),error='Qualification budget exhausted.')
            inventories.append(inventory)
        attempts.extend(inventories)
        if not any(inventory_is_eligible(row, workflow) for row in inventories):
            continue
        decision = compare_inventories(inventories, expected_edition, workflow)
        primary = decision.selected or _choose_primary(inventories, workflow)
        if primary is None:
            continue
        eligible_count = sum(inventory_is_eligible(row, workflow) for row in inventories)
        fallback_plan = build_cross_source_plan(
            inventories, registry, primary=primary, workflow=workflow,
        ) if workflow == 'chapter' and eligible_count > 1 else None
        expected = [primary.source_id]
        if fallback_plan and fallback_plan.can_execute:
            expected.extend(
                item.source_id for item in fallback_plan.fallback_items
                if item.source_id not in expected
            )
        if decision.selected is not None:
            decision = replace(decision, fallback_plan=fallback_plan)
        return SearchResolution(
            tuple(enriched), tuple(inventories), decision, primary,
            language, str(preferred_language or 'en'),
            language != str(preferred_language or 'en'), tuple(expected),
            fallback_plan,
        )

    details = '; '.join(
        f'{row.source_name}: {row.summary}' for row in attempts
    )
    return SearchResolution(
        tuple(enriched), tuple(attempts), preferred_language=str(preferred_language or 'en'),
        error=details or f'No usable {workflow} inventory was found in any reported language.',
    )


def qualification_targets(ranked_groups, family_limit=3, record_limit=8):
    """Probe strong top families, including trusted single-provider records."""
    from dataclasses import replace
    families=[]; selected=[]; remaining=record_limit
    for ranked in ranked_groups:
        group=ranked.group
        if int(ranked.match.tier) < 5: continue
        work_ids={str(r.get('canonical_work_id') or '') for r in group.results}
        trusted=bool(len(work_ids)==1 and '' not in work_ids and all(
            r.get('_canonical_identity_confidence') == 'high' or r.get('external_ids') for r in group.results))
        if group.confidence != 'high' and not trusted: continue
        family=('work',next(iter(work_ids)),edition_identity(group.results[0])) if trusted else ('group',group.display_title,edition_identity(group.results[0]))
        if family not in families:
            if len(families)>=family_limit: continue
            families.append(family)
        rows=tuple(group.results[:remaining])
        if not rows: break
        selected.append(replace(ranked,group=replace(group,results=rows)))
        remaining-=len(rows)
    return tuple(selected)
