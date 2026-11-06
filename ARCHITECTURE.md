# Source organization

This is the applied organization of the audited Python-cleanup r1 source. It is a separate copy; the earlier development worktree and packages are preserved. `SOURCE_LAYOUT.json` maps every former root module to its current location.

| Folder | Responsibility |
| --- | --- |
| `app/` | Main dialog, workflow state, settings, updates, notifications |
| `providers/` | Five acquisition adapters, contracts, registry and transport policy |
| `discovery/` | Search, canonical grouping, ranking, caches, Bookmarks and recent searches |
| `publication/` | Inventory, validated volume/episode associations and reviewed bridges |
| `metadata/` | Display metadata and publication-reference integrations |
| `books/imaging/` | Artwork, framing, image processing and cover generation |
| `books/preview/` | Preview state, detailed inspection and screen emulation |
| `books/output/` | Output identity, effective metadata, finalization and CBZ/PDF export |
| `books/imports/` | Local books, pinned destination, Calibre import and accounting |
| `presentation/` | Qt layout, widgets, scaling, non-modal ownership and hero rendering |
| `diagnostics/` | Bounded diagnostic, performance and thumbnail tracing |
| `common/` | Shared helpers, translations and source-resource root resolution |
| `assets/`, `images/`, `native/` | Original packaged resources and optional acceleration |
| `tests/` | Deterministic and Qt regression tests; explicit private-fixture exclusions |
| `tools/` | Maintained build/test tools and unregistered laboratory helpers |
| `experimental/` | Unregistered reference prototype retained for tests |

The root `__init__.py` is Calibre's plugin descriptor. `ui.py` remains the lazy action entry point. `version_info.py` remains lightweight version metadata. `build_info.py` is generated inside each plugin ZIP. The compatibility namespace is still `calibre_plugins.manganana`; persistent identifiers, preferences and library tags are not renamed.

Application imports use explicit canonical subsystem paths. There are no legacy module shims or application-wide alias registrations. Calibre loads the nested packages from the ZIP. Source tests use `tools/source_bootstrap.py` to supply that namespace without executing Calibre's descriptor outside its loader.

`common/plugin_paths.py` supplies the full source/plugin root for development resource fallbacks and the credential safety boundary. Installed resources still use Calibre's injected resource loader. Resource keys and asset bytes are unchanged.

The regular package manifest is explicit in `tools/build_plugin.py`; it excludes tests, experimental modules and popup laboratories. Rebuilding the optional DLL is a separate opt-in operation. Follow [BUILDING.md](BUILDING.md) for building and isolated testing.

This reorganization does not split the large main controller into new abstractions. Such refactoring would be a separate behavioral change. Provider facts, publication identity, output identity and editable bibliography keep their existing ownership.
