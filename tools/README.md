# Development tools

The application lives in subsystem packages described in [ARCHITECTURE.md](../ARCHITECTURE.md). Calibre starts it through the root descriptor and action; these scripts are development entry points.

| Tool | Purpose |
| --- | --- |
| `build_plugin.py` | Validate package dependencies and build a fresh installable ZIP in `../../builds`. Existing ZIPs are preserved. |
| `build_native.py` | Optional Windows native pixel-kernel rebuild. |
| `run_source_tests.py`, `source_test_module.py` | Process-isolated Calibre/Python/Qt regression runner; unavailable private fixtures are reported explicitly. |
| `source_bootstrap.py` | Development namespace and old-filename test-fixture resolver for the organized tree. |
| `verify_source_build.py` | Compare rebuilt entry hashes with the recorded organized runtime reference. |
| `run_source_smoke.py`, `source_calibre_smoke.py` | Actual installed-plugin toolbar/resource smoke in a disposable profile/library. |
| `run_qt_checks.py` | Assertions-enabled individual Qt harness. |

The image probe and Kobo helper are retained for tests. `labs/` and `popup_lab/` contain unregistered historical helpers, excluded from the regular package. The full historical investigation harnesses and private captures remain in the original development worktree rather than being copied here. See [BUILDING.md](../BUILDING.md) for commands, dependencies and safety boundaries.
