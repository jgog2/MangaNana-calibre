# Adding a manga provider

This guide describes the **audited code in the organized source tree**, not a proposed external-provider SDK. Providers are in-tree Python modules instantiated by `app/main.py`. The abstract interface is useful but does not eliminate provider-specific contracts or integration work. Start with the smallest relevant existing adapter and the network-free [example](examples/provider_template.py).

## 1. Entry points and ownership

`providers.source_adapter.SourceAdapter` is a synchronous, Calibre-independent ABC. Methods run inside application workers; adapters must not create Qt widgets, call Calibre's database or own a dialog. `providers.source_registry.SourceRegistry.register()` accepts actual SourceAdapter instances, rejects blank/duplicate `source_id`, preserves registration order, and returns the adapter. `identify(value)` calls each `parse_manga_ref` and returns `SourceMatch(source, reference)` or None.

Current instances are `MANGADEX_SOURCE`, `MANGAPILL_SOURCE`, `WEEBCENTRAL_SOURCE`, `MANGAK_SOURCE`, `ATSU_SOURCE` in `app/main.py`; `SOURCE_REGISTRY` is initialized from them. `SourceCoordinator` attaches `source_id` and `source_name` to search records and tracks provider completion/failure. Its synchronous search is mainly a non-Qt/testing convenience; native GUI search uses workers and barriers.

Stable class attributes:

| Attribute | Meaning |
|---|---|
| `source_id`, `key` | Persistent lowercase provider identity; existing adapters set key = source_id |
| `display_name`, `domains` | Presentation name and recognized public hosts |
| `enabled_by_default` | Default search participation, overridden by `source_enabled` preferences |
| `capabilities` | Informational feature set; not a substitute for required ABC methods |
| `content_languages` | Nonempty fixed-language contract where the entire catalog is known; empty otherwise |
| `inventory_contract` | Optional adapter-owned cache contract; Atsu uses `atsu-groups-v1` |

## 2. Real method contracts

All methods below are required except `operation_context`, `with_cancel_check` and `resolve_manga_ref`. Match keyword signatures, not just method names.

| Method | Return / behavior |
|---|---|
| `parse_manga_ref(value)` | Stable provider series reference or None. Recognize supported URLs without network access. Reject wrong hosts/unsupported paths; do not guess from a title. |
| `get_manga(value, preferred='en')` | Metadata dict. Existing common fields include `uuid`, `title`, `author`, `titles`, `alternate_titles`, `main_cover_url`, `available_languages`, `year`; optional external IDs, description/status/rating fields vary. |
| `search(query, offset=0, limit=12, include_adult=False, preferred='en', availability_cache=None)` | Page dict containing `rows`, `offset`, `next_offset`, `limit`, `total`, `has_more`, usually `query`, `fetched_count` and filtered counts. Some total values are estimates, not exact catalog sizes. |
| `get_chapters(value, language, start_volume=None, end_volume=None)` | Ordered list of acquisition records: exact `id`, `chapter` label string, optional numeric `volume` or None, `title`, `pages` integer or None. Preserve provider-specific identity/provenance fields. |
| `get_download_plan(value, language, start_volume=None, end_volume=None)` | Dict with `volumes`, `pages_by_volume`, `chapters_by_volume`, `bonus_pages`, `bonus_chapters`, `aggregate_error`, `feed_error`. Counts are acquisition facts, not proof of publication completeness. |
| `get_volume_covers(value)` | Dict mapping numeric volume keys or None to provider-hosted cover URLs. None commonly denotes series artwork. Empty is valid. |
| `get_page_manifest(chapter_id, retry_callback=None)` | `{'full': [ordered URLs], 'data_saver': [aligned URLs]}`. Empty saver is allowed; an incomplete/empty readable full list should fail explicitly. |
| `fetch_binary(url, **kwargs)` | Bytes, honoring supported timeout/retry/cancellation transport policy. No image/QPixmap objects. |
| `fetch_preview_page(saver_url, full_url, page_number, log=None, check_cancel=None)` | `(bytes, used_full_quality_bool)` with provider fallback; check cancellation before/after work. |

Search rows normally contain `id`, exact public `url`, `title`, `full_title`, `alternate_titles`, `author`, `year`, `available_languages`, `cover_url`, `badge`, `score`; `external_ids`, `structured_titles`, `adult`, `medium` and `type` are optional evidence. `SourceCoordinator.complete()` supplies source attribution. Do not assign another provider's thumbnail or chapter count. Populate `chapter_count` only from a reliable listing-level response; do not add inventory calls solely for discovery counts.

`titles` uses existing title rows, not an arbitrary locale-to-string replacement. Follow `common.core_helpers.collect_titles`, `title_metadata` and each adapter's outputs. Preserve aliases and external identity evidence without claiming canonical certainty. Edition inference/grouping belongs to shared `canonical_identity`/`discovery_groups`; titles alone must not defeat contradictory trusted IDs or standard/color/webcomic differences.

### Interfaces are not fully uniform

The abstract docstring says parse returns a manga ID, but internal calls mostly pass public URLs to adapter methods. MangaDex's `_require_id` expects a URL even though parsed output is a UUID. Some other adapters accept additional reader URLs or IDs through internal helpers. Do not assume `source.get_manga(source.parse_manga_ref(url))` works for every existing provider.

There is no shared DTO validation layer. `with_cancel_check` is detected with `hasattr`, `expected_record_id` is MangaK-specific, and native Atsu acquisition has additional group reconciliation. `operation_context()` defaults to a null context; MangaPill uses ContextVar-scoped title-document reuse. Document any new exceptions rather than introducing unrelated provider branches everywhere.

## 3. Compare the five adapters

| Adapter | Search/inventory/read behavior that matters |
|---|---|
| `providers.mangadex_source.MangaDexSource` | JSON API. Search offsets count scanned API rows, so use returned `next_offset`, not visible row count. Chapter feeds request 500-row pages; external reader redirects are excluded. Exact IDs and logical `(volume, chapter)` releases are deduplicated by current policy; unnumbered records keep ID distinction. Aggregate/feed reconciliation and errors remain separate. At-home manifests provide full/data-saver lists. Constructor injects `api_json`/`fetch_binary`. |
| `providers.mangapill_source.MangaPillSource` | HTML parser, page-based search translated from offsets; next-link detection. Chapter links are acquisition IDs and may have separate numbering groups. Operation-local title HTML reuse avoids repeated metadata/inventory requests. No native collected volumes are invented; covers are series fallback. Reader `data-src` images are ordered. Constructor injects text/binary functions. |
| `providers.weebcentral_source.WeebCentralSource` | HTML/HTMX search and complete `full-chapter-list` inventory. Preserve File labels and Prologue namespace/ordinal plus exact uppercase IDs. Shared chapter ordering is used. Chapter-image endpoint is parsed and ordered by page suffix. Returns saver list equal to full list. Cooperative cancellation; explicit access-block errors. |
| `providers.mangak_source.MangaKSource` | Public Next.js title/reader props plus JSON chapter/search API. API internal index is **not** chapter number: preserve display label, reader URL and `_provider_record_id`. Reader validates requested URL, optional exact record ID and agreement of both image/page lists. A known three-image API capture is not a complete chapter manifest. Continuation handling is separately gated; do not enable it to repair unrelated code. |
| `providers.atsu_source.AtsuSource` | JSON search/title/allChapters/reader endpoints. Exact reader URL carries manga+chapter IDs. Preserve scanlation-group evidence and `_unit_kind`; some records represent packaged volumes. `atsu_acquisition` handles recommended groups/independent acquisition safeguards. Reader verifies exact chapter and contiguous zero-based page numbers before returning ordered images. |

Use the actual adapter and its tests as the source of truth. Existing limitations such as MangaDex logical-release deduplication and provider-specific filtering are policies to audit, not patterns to broaden blindly. A new provider must preserve distinct source IDs even when labels coincide.

## 4. Identity and publication mapping

Keep four concepts separate:

1. **Acquisition:** exact provider series/reader record, including edition/language context.
2. **Publication:** verified collected episode or volume association, when supported by evidence.
3. **Output:** a requested chapter book or collected-volume book, owned by `output_series_metadata` and its acquisition payload.
4. **Bibliography:** editable title/authors/series/numeric Series # passed to files and Calibre.

Do not use a formatted title, chapter number, row index or Series # as an acquisition ID. Prologue 1 and ordinary 1 are different namespaces; repeated labels can be different records. Preserve provider order, raw labels, group IDs and source URLs. If exact duplicate records are removed, do so by demonstrated source identity and account for exclusions. Unknown page count is None, not a fabricated zero.

`publication.publication_preparation.prepare_publication`, `publication_manifest`, `publication_identity` and `unified_volume` apply shared references and reviewed bridges. Adapters return provider facts. Never borrow reading pages from another provider or hardcode uncertain volume membership to fill coverage. Review [PUBLICATION_IDENTITY_BRIDGE_CONTRACT.md](PUBLICATION_IDENTITY_BRIDGE_CONTRACT.md) before proposing new bridge data. Existing reviewed JSON must stay unchanged during unrelated provider work.

Decorate a successful `get_chapters` with `SourceAdapter.capture_chapter_inventory` when its signature matches. `acquire_volume_inventory` then reuses the exact returned enumeration from a matching plan call. It falls back to enumeration if capture did not occur. Do not cache mutable rows on a global adapter to emulate this: concurrent workers and cancellation make that unsafe.

## 5. Registration checklist

- Add `<provider>_source.py` implementing the contract and injected transports. Keep constructor/network behavior lightweight.
- Import and instantiate it in `app/main.py`, append to `SOURCE_REGISTRY`; update explicit five-provider assertions to the reviewed new set.
- Add its Python/dependency files and resources to `tools/build_plugin.py`; do not rely on files next to the installed ZIP.
- `MangaSourcesDialog` uses the registry and `source_policy` preferences, but other allowlists remain: update `discovery.saved_manga.PROVIDERS` for Bookmarks and audit `search_cache` provider stamps, artwork routing and direct-link behavior. Registration alone is insufficient.
- Add `ProviderBrand` in `providers.provider_branding.PROVIDER_BRANDS`, supported public title URL pattern/host entry, and an appropriately licensed bundled icon. Add the icon to the package manifest. Neutral branding exists, but public-link safety does not guess unknown host patterns.
- Audit `presentation.choose_manga_background.PROVIDER_PRESETS` separately. Do not change one of the existing five mappings or the no-selection shader. A new shader requires an explicitly reviewed asset/mapping decision; the adapter does not automatically register one.
- Exercise source participation toggles, direct URLs, grouped/flat discovery, exact leaf selection, Bookmarks restart, thumbnail callback generation checks, preview/final acquisition and Calibre accounting.

## 6. Requests, errors and cancellation

Default transports use urllib and versioned User-Agent; constructors differ. MangaPill/MangaDex have ordinary sleep-based retry loops with their own limits, whereas WeebCentral/MangaK/Atsu support worker-local `with_cancel_check` and cooperative waits. There is no universal abortable-HTTP layer. An in-flight request may finish only at its timeout; closing the host can wait for it. Avoid claiming instant cancellation.

Use bounded timeouts/retries, honor rate limits, and never retry authorization/protection failures to bypass them. Propagate InterruptedError. Distinguish unavailable inventory from successfully empty inventory. Preserve useful error context without exposing tokens/cookies. `retry_callback` reports status; it must not write directly to Qt widgets from an adapter.

The application validates image bytes in acquisition/processing, maintains request generations and single-flight caches, and owns worker cleanup. Returning URLs is not proof that pages decoded or a book imported. Reuse those safeguards; do not spawn long-lived Qt owners or write metadata into another provider's cache. Revision changes that alter normalized inventories should update a deliberate cache contract, with tests for fresh/warm equivalence.

## 7. Practical tests

The example adapter has **no network transport or runtime registration**. Its deterministic tests cover exact IDs with repeated labels/prologues, pagination, metadata, one enumeration, manifest failure, cancellation and unknown languages:

```text
python -m unittest discover -s tests -p test_provider_template.py -v
python tools/run_source_tests.py --modules test_provider_template,test_source_registry,test_source_coordinator,test_mangadex_characterization,test_mangapill_source,test_weebcentral_source,test_mangak_source,test_atsu_source
```

For a real addition, inject small synthetic HTML/JSON through the existing provider constructor style. Test first/intermediate/final pagination and exhausted responses; source order versus reversed lists; duplicate **IDs** versus duplicate labels; Unicode titles; explicit editions; Prologue/Extra/decimal/unnumbered entries; malformed JSON/HTML; missing image lists; HTTP 403/429/timeouts; cancelled waits; exact reader-to-chapter association; full versus saver alignment and thumbnail provenance. Keep fixtures free of credentials and manga pixels.

After unit tests, build and run the actual installed action in disposable Calibre. Use controlled marker pages for page-order/accounting combinations and a small authorized live sample for delivery. Verify every selected identity through generated ComicInfo/PDF metadata and actual Calibre identifiers. Test provider/mode/library switches, Favorite reopening, stale image callbacks and closing during each stage. The public smoke is initialization-only; it cannot certify a new provider. Record all limitations and obtain review before enabling a provider by default.
