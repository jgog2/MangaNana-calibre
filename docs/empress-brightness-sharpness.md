# Empress: Brightness, Sharpness, manual Resolution removal

## Scope and implementation

Continues `feature/empress-processing-foundation`. Earlier uncommitted work is
preserved. The supplied Ryzen 5 5600 / Steel Ball Run Vol. 3 timings are user live
qualification, not measurements repeated here. The orchestration report remains
historical reference; its manual Resolution descriptions are superseded here.

Brightness uses `ImageEnhance.Brightness`: 25–200%, 5% steps, default 100%.
It multiplies pixel values; true black stays black and highlights clip according
to Pillow. Sharpness uses `ImageEnhance.Sharpness`: 0–200%, 5% steps, default 100%.
Zero softens, one is identity, two sharpens. Both enhancement calls are skipped
at factor 1, including when other processing is active. No custom pixel loops,
native changes, dependencies or sharpening parameters were introduced.

Both factors are validated immutable ProcessingSettings fields and participate
in existing equality/signatures, Finalization invalidation and local rerendering.
Reset blocks control signals and applies one combined settings transition.
Session-only behavior is unchanged. Saturation uses a 20–300%
range and Pillow Color semantics; Grayscale disables it without resetting it.
Gamma remains the currently qualified reciprocal LUT, unchanged by this pass.

UI order: Brightness, Contrast, Gamma, Saturation, Sharpness, Grayscale,
Output Depth, Dithering, Dither Strength.

## Shared order and dimensions

Decode → EXIF/orientation normalization → layout/canvas construction →
Grayscale when enabled → Brightness → Gamma → Contrast → Saturation when
applicable → Sharpness → Output Depth / dithering → encode.

Quantization and diffusion remain one existing shared operation; Sharpness feeds
that operation, not its already-quantized output. Alpha remains untouched.
Overview alone applies its existing 720x540 working ceiling after layout and
before adjustments. Full Detail and final pages have no working ceiling.

Removed the manual Resolution widget, callbacks, Reset/lock/log state,
ProcessingSettings field, manual scaling and exclusively manual `scaled_dimensions`
helper. Normal Portrait dimensions and 1680x1264 Landscape dimensions are retained.
Unrelated provider/reference identity resolution remains untouched.
Intentionally retained: EXIF/source normalization, landscape fitting/composition,
Pillow aspect-preserving Overview thumbnail reduction (no upscaling), thumbnail
display, Detail zoom geometry and the selected-page memory cap. The cap error no
longer advises choosing a removed Resolution control.

## Verification

- 166 focused, 508 broader and 721 full-suite tests pass.
- 113 source/test/tool Python files compile; Git diff inspection/check passes.
- Shared Preview/final pixel tests cover both layouts and adjusted grayscale,
  RGB, depth and diffusion. Neutral Portrait bytes and landscape encoding are
  unchanged; cover bytes are untouched.
- Real Calibre offscreen Qt smoke passes with native and simulated missing-DLL
  portable backends: ranges/steps/defaults, local adjustment changes, provisional
  Detail, zoom/pan, center preservation, dirty Overview, Back, Reset and closure.
  Zero HTTP calls. Screenshots inspected for the requested order and no Resolution.
- Pool tests retain four-worker/eight-outstanding limits, ordered serial ZIP
  consumption, errors/cancellation and serial portable fallback. The production
  dithering module, ctypes loader, DLL and render-orchestration module match the
  previous qualified ZIP byte-for-byte.
- Existing standalone environment emits a SciPy/NumPy ABI warning during optional
  Numba probing and Pillow deprecation warnings; tests pass. No dependencies changed.

## Representative performance and investigation

Calibre runtime, 12 synthetic 1680x1264 RGB PNG pages, eight levels/channel,
Atkinson 100%, native four-worker final jobs, PNG encoding and serial ZIP_STORED.
Warm-up/input creation/native validation are excluded. Three alternating timed
runs per setting; each archive passes integrity and ordered-name checks.

| Setting | Median seconds |
|---|---:|
| A: Brightness 100%, Sharpness 100% | 0.9896 |
| B: Brightness 125%, Sharpness 150% | 1.3042 |

This is **31.79%** / 0.3146 seconds extra for 12 pages. The first run measured
0.9300 vs 1.1978 seconds (+28.80%). Nonneutral overhead is measurable and must not
be described as zero or insignificant. These synthetic PNG timings do not predict
the supplied 107-page manga workload or establish a hard threshold against 4.41s.

Investigation measured zero Brightness/Sharpness calls in A, exactly 12 of each in
B, with native backend retained throughout. Diagnostic summed per-page elapsed
times in B were 0.4338s Brightness and 0.7941s Sharpness; depth took 2.3023s versus
2.7766s in A. These sums overlap across workers and are not additive wall time.
The added Pillow full-image operations explain the increase; there is no accidental
fallback or orchestration change. Encoding content also differs (1,325,172 versus
587,972 total bytes). No out-of-scope performance redesign was attempted.

## Files changed in this pass

- `image_processing.py`: immutable factors, neutral checks and shared Pillow operations;
  removes manual scaling.
- `main.py`: control order/mapping, manual Resolution removal, normal dimensions/logs.
- `preview_detail.py`: remove obsolete Resolution advice from memory-limit error.
- `tests/test_empress_processing.py`, `tests/test_empress_pipeline.py`,
  `tests/test_preview_detail.py`, `tests/test_page_rendering.py`, `tests/test_dithering.py`.
- `tools/empress_qt_smoke.py`, `tools/native_calibre_smoke.py`,
  new `tools/benchmark_adjustments.py`, and this report.

## Remaining qualification

Physical display/DPI and real manga-volume performance with nonneutral adjustments
remain manual qualification. Overview is intentionally representative, not exact
full-resolution diffusion. No real provider acquisition or normal Calibre library
was used. No commit, push, tag, merge, branch change, release, dependency install,
native modification or persistent-cache clearing was performed.

## Final artifact

Built exactly once after source verification: `dist/MangaNana-Calibre-dev.zip`.

SHA-256: `3D3B396C3ACFEDA6A62C94A092EC9B34731C1DE2586679268391814EA1E652B3`.

ZIP integrity, exact 52-entry manifest, source/resource parity, required runtime
modules and compilation of all 46 packaged Python modules pass. The actual ZIP
was installed into a disposable repo-local Calibre configuration. Native and
simulated missing-DLL portable smoke both generated valid, ordered Portrait and
Landscape CBZs, retained cover/neutral bytes and native/Python parity, with no
HTTP calls. Only the disposable configurations created for this pass are removed;
existing persistent caches remain intact. Restart Calibre after installing.
