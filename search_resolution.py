"""Mode-aware, language-aware source confidence for plausible search groups."""

from dataclasses import asdict, dataclass, replace

try:
    from .canonical_identity import edition_identity
    from .cross_source_fallback import build_cross_source_plan
    from .inventory_comparison import SourceInventory, compare_inventories, inspect_source_inventory
except ImportError:
    from canonical_identity import edition_identity
    from cross_source_fallback import build_cross_source_plan
    from inventory_comparison import SourceInventory, compare_inventories, inspect_source_inventory


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
    return workflow != 'volume' or inventory.native_volumes > 0


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


def _choose_primary(inventories, workflow):
    eligible = [row for row in inventories if inventory_is_eligible(row, workflow)]
    if not eligible:
        return None
    return sorted(eligible, key=lambda row: (
        0 if row.complete else 1,
        -row.chapter_count,
        -row.native_volumes,
        row.source_id,
    ))[0]


def _inventory_cache_get(cache, key):
    if hasattr(cache, 'get_inventory'):
        hit = cache.get_inventory(key)
        if hit is None:
            return None
        try:
            return SourceInventory(**dict(hit.value))
        except Exception:
            return None
    return cache.get(key)


def _inventory_cache_put(cache, key, inventory):
    if hasattr(cache, 'put_inventory'):
        try:
            cache.put_inventory(key, asdict(inventory))
        except Exception:
            pass
    else:
        cache[key] = inventory


def resolve_search_group(registry, candidates, preferred_language, workflow,
                         metadata_cache=None, inventory_cache=None, check_cancel=None,
                         include_adult=False):
    """Resolve one already-relevant canonical group without fetching page bytes."""
    candidates = tuple(dict(candidate) for candidate in candidates or ())
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
            cache_key = (workflow, source.source_id, _reference(source, candidate), language)
            inventory = _inventory_cache_get(inventory_cache, cache_key)
            if inventory is None:
                inventory = inspect_source_inventory(source, candidate, language, workflow=workflow)
                _inventory_cache_put(inventory_cache, cache_key, inventory)
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
