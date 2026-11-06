# Building and testing MangaAnkā

## Requirements

Packaging needs **Python 3.10+** and its standard library. Running the plugin/Qt tests needs an installed Calibre providing `calibre-debug`, `calibre-customize`, `qt.core`, PyQt6, Pillow and Calibre PDF tools. Do not `pip install calibre` or put unrelated PyQt packages into its embedded environment. Optional NumPy/Numba acceleration is not required.

Reference validation used Windows x64, Calibre 9.13.0, Python 3.14.6, Qt 6.10.1/PyQt 6.10.0. Declared Calibre 7 and macOS/Linux support remain unqualified. On macOS CLI tools normally live in `/Applications/calibre.app/Contents/MacOS/`; see [Calibre's plugin guide](https://manual.calibre-ebook.com/creating_plugins.html).

## Build

Enter this `source` directory and run:

```text
python tools/build_plugin.py
```

Output is `../builds/MangaAnka-v1.0.0.zip`. The neighboring builds folder is separate from the source tree. Choose a fresh filename without editing the builder:

```text
python -c "from tools.build_plugin import build_plugin; print(build_plugin('MangaAnka-local-validation.zip'))"
python tools/verify_source_build.py ../builds/MangaAnka-local-validation.zip
```

The builder refuses to overwrite an existing ZIP. Use a fresh filename for every build. Do not package the whole tree with `calibre-customize -b .`: the curated manifest excludes tests and development state.

`PYTHON_FILES`, `ROOT_FILES`, `IMAGE_FILES`, `COVER_FILES`, `NATIVE_FILES` in `tools/build_plugin.py` and `UI_FILES` in `presentation/choose_manga_resources.py` are authoritative. Two icons come from `docs/ui/` and are renamed into `images/` in the plugin. The native DLL, cover font/assets, reviewed publication JSON, shaders/fallbacks and MP3 must remain in their original source paths. Missing manifest files fail packaging.

`build_info.py` is generated **inside the ZIP**, hashing input names/bytes and prefixing Git's short HEAD or `unknown` without Git history. No root generated module is required. A clean extraction should retain the recorded reference content suffix; the Git prefix can be `unknown` outside a repository. ZIP timestamps/compression can change whole-archive hashes; compare entries using `SOURCE_RUNTIME_REFERENCE.json`. Only generated `build_info.py` should differ when rebuilding this candidate; the recorded reference describes exact source bytes, not a blanket release-readiness approval. This does not qualify the rebuilt package for release. `version_info.py` defines `1.0.0`, Calibre tuple `(1, 0, 0)`, and codename `The World`. The stable updater expects tags such as `v1.0.0`, not `v1.0`.

`docs/ui/prototype` is a historical static design-test fixture, not the current Qt application. `experimental/mangabaka_reference.py` is an unregistered reference prototype retained for tests. The Google image probe and Kaleido surface helper are retained because deterministic tests import them; the old probe's opt-in CLI credential environment is separate from the production Google-key configuration. None is an alternative application entry point.

## Optional native compilation

The supplied Windows x64 DLL preserves the audited baseline input; source/header are included. In a disposable checkout with existing MSVC x64 tools and Windows SDK:

```text
python tools/build_native.py
```

The script replaces that checkout's DLL using strict floating-point/static-CRT flags and installs nothing. A different toolchain can change binary hashes; run native pixel-parity tests and requalify. See [asset provenance](ASSET_PROVENANCE.md) for handoff/CRT review. Other platforms use portable processing and do not load this Windows binary.

## Portable automated tests

With Calibre CLI on PATH:

```text
python tools/run_source_tests.py --calibre-debug calibre-debug
```

Or on Windows:

```powershell
python tools/run_source_tests.py --calibre-debug 'C:\Program Files\Calibre2\calibre-debug.exe'
```

Use `--modules test_mangapill_source,test_source_registry,test_provider_template` for focused checks. Reports are created under `../builds/source-tests/`; fresh per-module configurations/temporary files use the system temporary directory, or an explicit `--data-root`. Keep that data root outside the source checkout: credential safety tests deliberately reject storing private records inside plugin source. The runner discovers test modules, uses assertions-enabled compilation, blocks ordinary network access and isolates Calibre/Qt globals by process.

`tests/source_suite_policy.json` explicitly lists private-capture modules/methods unavailable in the source archive. Originals remain for maintainers; private build trees are not distributed. The current-source bulk-complexity and packaged publication-bridge contracts run independently of historical captures. Optional-backend/private-denial skips remain visible. The obsolete MangaNana virtual-library assertion now checks the approved MangaAnkā public name while preserving the internal MangaNana plugin identity. Do not call this a full private-suite pass. Plain `unittest discover` needs the larger development evidence set and does not isolate Qt globals.

## Storage and transport fault probes

These opt-in tools use the actual supplied plugin ZIP. They are separate from ordinary source tests because one intentionally terminates child processes and another opens a loopback HTTP server:

```text
calibre-debug -e tools/persistence_faults.py -- --root <new-disposable-data-directory> --library <new-short-test-library> --plugin <test-plugin.zip>
calibre-debug -e tools/transport_faults.py -- --plugin <test-plugin.zip> --out <new-report.json>
```

Set `CALIBRE_CONFIG_DIRECTORY` to a fresh disposable profile before either command. Never point the persistence root or library at an existing directory: the controller refuses that. `--library` keeps library writes separate from evidence/configuration; omitting it defaults to `ROOT/library`. On Windows choose a short library path such as `C:/MangaAnka-Test/library-01`; Calibre's library path must remain under 89 characters. Expected child exit codes 73 and 74 are deliberate interruption gates, not native crashes. The report verifies committed bookmarks, retained pending data, a real interrupted Calibre replacement and deliberate recovery in that test library only. It does not simulate power loss or recover production books.

The transport probe binds only `127.0.0.1`, generates controlled bytes, tests streaming cancellation for all five adapters, checks oversized/truncated responses, and verifies retry pacing. It makes no provider requests. In-flight connection/socket waits can still take their configured timeout; cooperative cancellation runs between reads and during retry waits.

Windows USER-handle measurements require native HWND classification: Qt 6.10.1 retains hidden `_q_titlebar` windows even in a plain Qt process without MangaAnkā. An independent Qt 6.10.2 control releases them. Calibre 9.13.0 and the independently checked 9.17.0 portable build here both bundle Qt 6.10.1. Do not replace Calibre's Qt DLLs or destroy Qt-owned HWNDs from plugin code. A newer Calibre version number alone does not establish that its bundled Qt contains this upstream correction.

## Disposable installation and startup smoke

Close normal Calibre before manual testing. PowerShell example with fresh paths:

```powershell
$previousConfig = $env:CALIBRE_CONFIG_DIRECTORY
try {
    $env:CALIBRE_CONFIG_DIRECTORY = Join-Path $PWD 'build\manual-review\config'
    & 'C:\Program Files\Calibre2\calibre-customize.exe' -a ..\builds\MangaAnka-local-validation.zip
    & 'C:\Program Files\Calibre2\calibre.exe' --with-library (Join-Path $PWD 'build\manual-review\library')
} finally {
    $env:CALIBRE_CONFIG_DIRECTORY = $previousConfig
}
```

Wait for the test Calibre to close before restoring the environment. Configuration override behavior is documented in [Calibre customization](https://manual.calibre-ebook.com/customize.html). Never select personal libraries for these checks.

For an offline actual Main/toolbar smoke:

```text
python tools/run_source_smoke.py --calibre-directory "C:/Program Files/Calibre2" --plugin ../builds/MangaAnka-local-validation.zip
```

This launcher creates fresh paths, refuses an ordinary running Calibre on Windows, installs into its new profile, checks resources/provider registration/non-modal ownership, and closes both windows. Use `--sandbox-root` and `--library-root` for separate disposable roots. It does not fetch pages, import books, install updates or replace native release qualification. Exact paths and exit codes are recorded.

The library defaults to a short directory under the system temporary directory, independent of the checkout/report path. Calibre 9.13's Windows library backend rejected a test library path of 89 or more characters during this audit; use a short `--library-root` if needed. The launcher checks that condition before installing. Configuration/report directories can remain separate.

Follow [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for later installed-ZIP, output/database, shutdown and physical display qualification.
