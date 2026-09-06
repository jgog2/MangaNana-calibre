# Empress: optional native dithering, Windows x64

## Scope and integration

The supplied `MangaNana-Native-Acceleration-Handoff.zip` is the implementation
starting point. Its C kernel is retained, with ABI-1 export and integer/size
overflow guards added. Exact binary-fraction literals replace static floating
division because MSVC `/fp:strict` rejects those initializers; weights are
bit-identical. No algorithm or Python reference math was changed.

`dithering.quantize()` selects validated native C for active diffusion, otherwise
portable Python. Explicit Python and Numba backends remain for testing/benchmarking;
automatic fallback does not import Numba, NumPy or llvmlite. Original depth,
Dithering Off and zero strength keep their existing paths and do not load a DLL.

`main.py` and `image_processing.py` are unchanged from the preceding qualified
build. No preview, final-page orchestration, download, concurrency, processing
order, encoding, cover, progress or UI changes are part of this pass.

The C interface receives only distinct byte buffers, dimensions, channel count,
level count, strength and algorithm ID. It allocates its own three-row float32
buffer. The Python wrapper owns input/output storage and retains its `ctypes.CDLL`
handle for the session. CDLL releases the GIL during native execution. Existing
worker cancellation is checked before and after the native page call; the native
call itself is not interrupted. Portable cancellation remains every 16 rows.

## Loading and lifecycle

The ZIP contains `native/windows-x86_64/manganana_dither_abi1.dll` (108,544 bytes).
Calibre's injected `get_resources()` reads this resource lazily on first diffusion,
not at plugin startup. The worker extracts it atomically to:

`<Calibre config>/plugins/manganana-native/abi-1/windows-x86_64/<DLL SHA-256>/manganana_dither_abi1.dll`

The DLL SHA-256 for this build is:
`9a4e9516956dcdbc52d34332d2754f2de833b81deedfc04cf959ce7dea5711ed`.

Existing extracted bytes must match the packaged content hash. A new build with
different DLL bytes uses a different directory. Old content-addressed directories
are not deleted or reused for different content; no persistent caches are cleared.
Restart Calibre after installing a new plugin build: backend selection/handles
are intentionally session-scoped. Source-checkout tools use `build/native-cache`
when not running under Calibre; no DLL is searched for on PATH or in the cwd.

Before selection, the loader checks Windows x64, both required symbols, ABI 1,
and three tiny deterministic RGB cases (one for each algorithm) against hashes
from the portable reference. Missing resource, architecture mismatch, load error,
symbol/ABI mismatch, extraction corruption or validation failure disables native
selection for the session. A native return error discards its output and retries
from original pixels using Python. Cancellation does not disable the backend.

Backend selection and fallback reasons are logged once to the Calibre debug/session
log, without calling a Qt widget from the worker. A subsequent native runtime
failure produces one transition notice. This is not a progress/Activity Log UI change.

## Build

`python tools/build_native.py` uses already-installed Visual Studio 2022 MSVC
14.43 x64 tools and Windows SDK 10.0.22621.0 via absolute paths. No installation
or PATH modification occurs. `/O2 /MT /fp:strict /W4 /WX /Brepro`, baseline x64:
no fast-math, fused arithmetic or AVX requirement; static CRT. The resulting DLL
depends only on the operating system's `KERNEL32.dll`. No Python extension ABI,
Numba payload, external redistributable, CUDA or system-wide install is needed.
`tools/build_plugin.py` includes the prebuilt DLL explicitly; missing DLL fails
the development build rather than silently producing an unaccelerated ZIP.

## Verification

- All 112 supplied fixture cases retain their expected SHA-256 hashes: 105
  diffusion cases plus seven hard-quantization controls, with source PNG hashes
  checked against the handoff manifest.
- 3,444 additional comparisons cover all 0–200% strength ticks, relevant gray/RGB
  depths, algorithms, degenerate dimensions, serpentine edges and random pixels.
- Native and portable outputs match exactly, including all six full-size benchmark
  combinations. Existing preview/final/cover and neutral-output tests pass.
- 19 new tests; 147 focused, 489 broader, and 702 full-suite tests pass.
- 109 source/test/tool Python files compile; diff check/inspection passes.
- Real Calibre offscreen Qt smoke passes for native and synthetic missing-DLL
  fallback, with zero network calls. No normal Calibre library is used.

## Single-page benchmarks

Real Calibre runtime, synthetic 1680x1264 page, eight levels/channel, 100% strength.
Portable is one timing; native is the median of three calls including Python/Pillow
buffer conversion overhead, after startup validation. No page concurrency.

| Mode | Algorithm | Portable seconds | Native seconds | Speedup |
|---|---|---:|---:|---:|
| Gray | Floyd-Steinberg | 3.668434 | 0.056748 | 64.64x |
| Gray | Atkinson | 4.302721 | 0.057011 | 75.47x |
| Gray | Sierra-Lite | 2.891969 | 0.051547 | 56.10x |
| RGB | Floyd-Steinberg | 9.196894 | 0.143443 | 64.12x |
| RGB | Atkinson | 12.109038 | 0.160517 | 75.44x |
| RGB | Sierra-Lite | 7.859948 | 0.146416 | 53.68x |

These are kernel-stage page timings, not an end-to-end manga-volume claim. The
same Steel Ball Run Vol. 3 / Ryzen 5 5600 / physical Kobo test remains manual.
macOS, Linux, ARM and 32-bit processes use portable fallback; no binaries for
those targets are provided. In-process validation detects expected load/ABI/pixel
failures, not arbitrary malicious native code or every possible hardware fault.

## Files in this pass

- `dithering.py`: selector only; existing reference kernel retained.
- `native_dithering.py`: thin loader, extraction, ABI/probe validation, logging.
- `native/dither_native.c`, `native/manganana_dither.h`: handoff C/ABI adaptation.
- `native/windows-x86_64/manganana_dither_abi1.dll`: Windows resource.
- `tests/fixtures/native_dithering/`: supplied PNGs and expected hash manifest.
- `tests/test_native_dithering.py`: loader, extraction, ABI and exact-parity tests.
- `tests/test_dithering.py`: fallback tests target the selected backend explicitly.
- `tools/build_native.py`, `tools/benchmark_native.py`, `tools/native_calibre_smoke.py`.
- `tools/build_plugin.py`, `tools/empress_qt_smoke.py`: packaging and dual-backend smoke.
- This report. Earlier uncommitted Empress changes remain preserved.

No commit, push, tag, merge, branch change, dependency installation, persistent
cache clearing or normal-library modification was performed.

## Final artifact

Built exactly once: `dist/MangaNana-Calibre-dev.zip`.

SHA-256: `EDE99C7C5A2B6096B234BA81C9B816E28085C74410F34FF5A96217ABCFF228E5`.

ZIP integrity, exact 51-entry manifest, source/resource parity, AMD64 PE header,
all 45 packaged Python module compile checks and safety checks passed. Isolated
Calibre installation loaded the actual ZIP module and its injected resource
loader, validated/extracted the DLL into the content-hashed path, and generated
valid Portrait and Landscape CBZs. The same installed-ZIP smoke passed with a
synthetically missing native resource and portable fallback. Covers/neutral bytes
were unchanged, pixel parity passed, and network calls were zero in both modes.

The newly created disposable benchmark/Qt/loader configurations are removed after
verification. Normal Calibre configuration, library and persistent caches are not
used or cleared. Manual Steel Ball Run Vol. 3 qualification remains next.
