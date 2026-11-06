# Configuration, upgrades and recovery

Public branding is MangaAnkā; internal compatibility names are intentionally mixed. Do not perform a global MangaNana → MangaAnkā replacement.

## Windows runtime qualification limits

The current hardening pass tests native Windows 11 x64 primarily with Calibre 9.13.0 (Python 3.14.6, Qt 6.10.1), plus affected checks on portable 9.17.0 (Python 3.14.8, also Qt 6.10.1). Neither a higher Calibre number nor passing Python-only tests establishes that a Qt issue is fixed.

Qt 6.10.1 retains hidden `_q_titlebar` HWNDs after windows are destroyed. Fresh Qt and Calibre controls without this plugin reproduce it. Qt 6.10.2 source explicitly destroys that handle, and an independent 6.10.2 control did not retain titlebars. Do not inject replacement Qt DLLs or destroy Qt-owned handles from the plugin. This remains a host-runtime caveat pending a supported Calibre runtime with the upstream correction.

**MangaAnkā 1.0 requires Calibre 9.13+.** Calibre 7.0 support was removed from the release requirement because of native evidence. The portable 7.0.0 runtime (Python 3.11.5, Qt 6.5.3) failed actual plugin startup with native heap-corruption exit `0xC0000374` on this machine. The same exit was reproduced with the preserved pre-hardening plugin in a short-path disposable profile. A no-plugin Calibre control completed 100 dialog cycles. A separate long-resource-path font failure was isolated and repaired by loading the unchanged bundled font bytes; that repair does not establish the cause or resolution of the native exit. Three manual-scaling assertions also failed on this older Qt. No native stack identified the faulty allocation, so a specific native culprit is not claimed.

The 1.0 release minimum is now 9.13, matching the tested runtime. Supporting older versions requires a separate compatibility investigation; the font repair alone does not establish safe startup on Calibre 7. Linux/macOS were unavailable and remain untested; the source runners are preparation for those hosts, not substitute platform validation.

## Persistent surfaces

Paths below are relative to the **active Calibre configuration**, not the source checkout. Use Calibre's own configuration-directory controls to find/back it up; do not share a live profile between test processes.

| Surface | Owner / path / behavior |
|---|---|
| Plugin identity | `MangaNanaCalibrePlugin`, `name='MangaNana'`, `plugin-import-name-manganana.txt`, `calibre_plugins.manganana` and installed `MangaNana.zip` remain stable |
| Preferences | `app/settings/config.py`: `JSONConfig('plugins/manganana')`, normally `plugins/manganana.json`. Defaults are additive; no global versioned migration/validation of arbitrary old values exists |
| Provider settings | `source_enabled` maps stable source IDs to bool; unknown entries are preserved by policy helpers. Do not change IDs to rename providers |
| Search/reference cache | `plugins/MangaNana-search-cache.sqlite3`; schema 4 preserves valid schema-3 tables, replaces other cache-table versions, and has TTL/algorithm/inventory contracts. Corrupt cache can be renamed `.corrupt` and recreated. This is disposable cache, not Favorites |
| Bookmarks | `plugins/MangaNana-saved-manga.json`, schema 2, 500-record/1 MiB bounds. Version 1 migrates in memory; malformed/unsupported versions become read-only with a warning and preserve the file |
| Search thumbnails | Separate `MangaNana-search-thumbnails.json` persistence; search and publication artwork ownership remain separate. URLs/cache state can become stale without losing acquisition identity |
| Google Books key | `plugins/manganana/private/google_books_api_key.json`; only version-1 locally verified records activate. The legacy environment arguments are ignored. Stored locally, not a system credential vault; back up privately and do not commit |
| Update state | `update_auto_check`, last-attempt/success, ignored version, Later deadline. Stable release channel pinned to `jgog2/MangaNana-calibre`; a dev 0.14 build does not offer an older stable, but stable 0.14.0 may upgrade equal numeric prerelease |
| Sound / scale | `completion_sounds` defaults true; scale defaults Auto/100, manual factor clamps to 85–115%. This adjusts plugin text/layout, not a uniform image zoom; reopen applies persisted settings |
| Geometry/session | Saved client dimensions/position/maximized plus session query/mode/layout and recent searches. Geometry is clamped to current display; old valid dimensions intentionally remain |
| Metadata/output | Language, layout/direction, cover/processing/framing presets, format and duplicate policy remain preference-owned. Per-output overrides use exact output identity; ambiguous old override keys are preserved for review rather than assigned arbitrarily |
| Library metadata | Current virtual library and tag are `MangaAnkā`. Books retain provider identifiers plus `mangaanka_output`/`mangaanka_kind`; do not rename or strip them |
| Recovery/history | `plugins/MangaAnka-prepared-output` holds blocked prepared files; `plugins/MangaAnka-output-history` keeps the latest ten ledgers. In-session Resume is not restored after restart. Inspect history and actual records before manual recovery |
| Extracted resources | Content-addressed `plugins/manganana-ui` and `plugins/manganana-native` caches; old hashes are not rewritten as new assets |

Failed or interrupted bookmark saves can leave `.manganana-favorites-*` files beside the committed JSON. A completed pending write is fsynced before replacement; if replacement fails, its bytes are retained and the error names the recovery path. After restart, a warning identifies interrupted writes while the last committed bookmarks remain active. Partial files may be invalid: preserve and inspect them before any deliberate recovery. Do not automatically apply an orphan or share one live configuration across multiple Calibre processes. A successful same-process retry removes only recovery files owned by that writer.

Exact-output replacement backups under `plugins/MangaAnka-import-recovery` can survive a forced process exit between Calibre's separate format and metadata writes. Recovery is deliberate, not an automatic transaction rollback after a restart. First verify the original library path/UUID, book ID and exact output identifier; a book ID alone is not a globally unique recovery target. Retain the original format/OPF/cover and output ledger until the actual library record has been checked.

## Upgrading from older MangaNana builds

The locally retained `v0.9.8-beta` source uses the same plugin/config namespace, so the installer can replace that plugin without a cosmetic identity migration. Its volume-layout and common language/duplicate settings still have recognized values. New defaults apply where absent. This is static/synthetic evidence, not a real user's full upgrade qualification.

**Confirmed gap:** that tag used virtual-library name/tag `MangaNana`, whereas current r10 uses `MangaAnkā`. No automatic library-tag migration was found. Old books are not deleted, but the newer virtual library may omit them, and old bibliographic-only records can conflict conservatively with exact-output import. Do not bulk-retag user books or guess identities during an upgrade. The owner must choose and test a migration/communication policy.

Other risks: malformed preference types, stale publication/input contracts, unsupported Favorites versions, old manually set Google key environments, expired artwork URLs, and Calibre/PyQt API changes. Schema-3 cache preservation does not prove all historical cache combinations; algorithm checks still determine reuse. A damaged cache may be replaced by existing recovery code, so back up the profile before upgrading.

Restart Calibre after installing to avoid mixed loaded modules/native handles. Back up both configuration and library first; test a **copy** in a disposable profile. Do not downgrade a newer profile blindly: older code may not understand new fields/schema. Use the backup and matching plugin as a unit, preserving generated books and identifiers. Production upgrade behavior still requires owner/manual validation.

## Non-modal destination policy

Each window pins its opening library path and UUID. Calibre may switch independently, but MangaAnkā must not redirect imports. Return to the indicated destination and explicitly Resume held files, or close/reopen the window to choose another library. Do not interpret a partial import as an atomic all-or-nothing transaction. Already verified books remain; every other output needs a named terminal outcome.
