# Empress Phase 1: observation and implementation hypothesis

Baseline: clean `dev`, ad752badc9e16804034384e034cc4793d36dfd5c.

- PairingPreviewWorker acquires at most 12 pages, extending to 14 only to
  complete a Landscape pair. EXIF-normalized records previously died after
  thumbnail creation. Session preview entries retained thumbnails only.
- Restarting that worker on adjustment would repeat manifest and image HTTP.
  Retain one bounded normalized/decoded sample instead, with a memory ceiling.
- Existing Landscape helpers compose PIL canvases then JPEG-encode. Add a
  pre-encode processing boundary and an in-memory output option, retaining
  existing layout/pairing math. Portrait neutral output keeps source bytes.
- Local worker generations must differ from acquisition IDs. One running
  render plus a coalesced newest intent prevents queue growth. Cancellation
  and ownership checks reject obsolete callbacks, including after closure.
- Defaults are currently 1450x850 in config and 1500x950 in the constructor.
  Missing saved size will use one outer-frame target; actual Qt frame extents
  and available desktop determine client size. Valid saved dimensions remain.
- Shared order: decode -> EXIF normalization -> layout/canvas -> resolution
  scaling -> optional grayscale -> reciprocal Gamma -> Pillow Contrast
  -> Pillow Color/Saturation unless grayscale -> encode. Covers excluded.

Focused experiments precede UI integration: neutral identity, exact gamma
direction/order, mode/alpha safety, output formats, render tokens, sizing.

## Verified implementation

- A frozen ProcessingSettings is session-only and included in current_signature.
  Finalization invalidates through the existing explicit navigation workflow.
- A single-shot 160 ms Qt timer coalesces changes; release flushes promptly.
  One local worker may run, with one newest pending intent. Distinct render
  generations reject old results; sample context changes and closure cancel it.
- The one retained decoded sample keeps the existing 12/14-page limits and a
  conservative 128 MiB source-pixel ceiling. Context reset/replacement releases
  it. No thumbnail is ever used as the source of a new processing pass.
- Portrait neutral bytes are untouched. Landscape defaults preserve encoding,
  canvas sizing, page order and pairing. Non-neutral output transforms before
  encoding, with metadata and covers outside the processing path.
- Small-screen inspection justified a conditional scrollable shell when the
  available opening footprint is below the existing 1200x760 usable layout.
  The outer frame fits; all controls remain reachable rather than offscreen.
- 23 new deterministic tests: focused matrix 84, broader matrix 426, full
  repository 639. Syntax checks passed for 99 source/test/tool Python files.
- Real Calibre Qt offscreen smoke exercised both layouts, rapid sliders, Reset,
  preview-off behavior and fresh-session neutrality with synthetic images and
  a fake library. This is not live provider or native Windows/macOS GUI proof.
- Manual qualification still needs actual color/B&W manga, both output layouts,
  HTTP-log observation, ordinary covers, and physical-display/DPI inspection.

## Grayscale and resolution follow-up (historical Gamma specification)

- The reported Gamma inversion did not reproduce in the Phase 1 source or
  production value-mapping path. Slider ticks 10/20/40 map directly to displayed
  factors .5/1/2; midpoint 128 maps to 181/128/64. The LUT is already direct
  exponent, not reciprocal. A production-handler regression and real Qt smoke
  now lock this down; no unsupported inversion of the math was introduced.
- Grayscale defaults Off, uses Pillow L conversion, preserves alpha, and skips
  saturation. Its UI disables the Saturation slider without resetting the value.
- Resolution defaults Original; .9/.75/.5 scale both axes using LANCZOS and
  nearest-integer rounding, with a one-pixel minimum and no upscaling. Landscape
  scaling follows canvas composition. CBZ validation uses the same dimensions.
- Both fields live in ProcessingSettings, so the existing output signature,
  session-only lifetime, local-render ownership and atomic Reset also cover them.
- No reference/provider/cover architecture or dithering changes.
- Follow-up verification: nine new tests; 93 focused, 435 broader, and 648 full
  repository tests passed. All 99 source/test/tool Python files compile. Real
  Qt controls confirm midpoint results 181/128/64 at Gamma .5/1/2, disabled and
  restored Saturation, Grayscale/75% local renders, and neutral Reset/relaunch.

## Permanent Gamma semantics and Detail Preview

The subsequent brief explicitly supersedes the previous Gamma convention.
The LUT now uses `255 * (input / 255) ** (1 / gamma)`: left/darker, 1 neutral,
right/brighter. Midpoint 128 produces 64/128/181 at .5/1/2. Earlier tests passed
because they enforced the former requested direct-exponent convention; both
the math tests and the real production control mapping now enforce reciprocal.

Each local render reports actual processed dimensions before thumbnailing.
Clickable thumbnails open a nonmodal detail viewer with output-page selection
and Fit/50/75/100/125/150/200% zoom. The same local worker regenerates the selected
page from the normalized sample through the shared processing/layout path.
No provider or network access is added. Processing and page changes share the
existing render generations and 160 ms debounce; zoom needs no render job.

Only one selected full-size QImage is retained, limited to 64 MiB RGBA. The
worker checks the ceiling before conversion. Oversized detail pages show a
clear lower-Resolution suggestion without failing ordinary thumbnails. The
viewer paints at the chosen size without retaining zoomed copies. At 100%, one
processed pixel occupies one Qt logical pixel (image DPR explicitly 1); Fit
contains without enlargement. Old/new selected images may coexist transiently
during handoff, not as a multi-page cache. Context replacement and closure
release the selected detail image. Native DPI/real-manga inspection remains a
manual qualification step.

Verification for this pass: ten new detail tests, updated Gamma expectations,
103 focused / 445 broader / 658 full-suite tests passed. All 101 source/test/tool
Python files compile. Real Qt offscreen checks exercised clickable captions,
both layouts, page switching, all zooms, exact 100% widget/image sizing,
processing while open, close during an active render, and zero network calls.

## Embedded Detail, Output Depth and Dithering

This pass supersedes the separate detail-window UX above. Detail is now a
QWidget inside the existing preview stack, with Back to Overview, page selector,
Fit/25/50/75/100/125/150/200%, checked right-click zoom actions, Ctrl+wheel steps,
and drag/pan. 100% remains one processed pixel per Qt logical pixel. Completed
rerenders preserve normalized viewport center, including Resolution changes.
Only the selected full-resolution QImage is retained, under the same 64 MiB cap;
zoom paints that image without creating an additional image cache.

Shared processing order: decode -> existing EXIF normalization -> layout/canvas
-> Resolution -> Grayscale -> reciprocal Gamma -> Contrast -> Saturation unless
grayscale -> combined Output Depth quantization/error diffusion -> existing encode.
The latest live-qualified Gamma convention is unchanged (.5 darker, 2 brighter).
Covers never enter this processing path.

Output Depth is Original by default. Grayscale offers 16/8/4/2 gray levels;
color offers 4096/512/64 colors (16/8/4 independently per RGB channel). Original
disables both dithering controls. Reduced depth with Dithering Off still hard
quantizes. Active dithering offers Floyd-Steinberg, Atkinson and Sierra-Lite.
Strength is 0–200% in 5% steps and multiplies propagated error; zero is exactly
hard quantization. Defaults/reset are Original, Off, 100%. Reset blocks individual
signals before one effective settings update. Disabled algorithm/strength values
are retained in the UI but normalized out of effective ProcessingSettings.
Switching grayscale carries a supported per-channel level count; switching a
2-gray-level target to color returns to Original because RGB111 is not offered.
Saturation remains stored while disabled. All controls remain session-only.

The supplied Dither Lab is the math reference, not the application architecture.
Its canonical kernels, clipped old value, ideal float target and serpentine error
distribution are retained. Two numerical issues were resolved explicitly:

- The lab rounds hard-quantization values but truncates diffused values at uint8
  conversion. Both now use the same nearest-integer palette (notably 8 levels:
  0,36,73,109,146,182,219,255).
- NumPy 2 scalar promotion can make the lab's Python += path round intermediate
  additions differently from its Numba path. Both production backends now use
  float64 arithmetic and float32 error-buffer stores, matching the lab's Numba
  path independently of installed NumPy. A direct comparison against the supplied
  Numba function passed 72 RGB/grayscale/depth/strength cases after the deliberate
  final-palette correction; independent full-buffer regression oracles agree too.

One canonical diffusion function runs portably with standard-library buffers or
with optional lazy Numba/NumPy. Three float32 scanlines bound the error buffer.
Cancellation is checked every 16 rows, using existing worker-owned callbacks;
download cancellation does not disable acceleration. Import/compile failures
retry from original pixels using Python. No Numba/llvmlite payload or persistent
JIT cache is shipped. Pillow FS is not substituted because its palette, scanning
and strength contract differs. The existing 160 ms debounce, one-worker/newest
generation ownership, bounded normalized sample and finalization signature remain.

Benchmarks (`tools/benchmark_dithering.py`, synthetic 420x316, 8 levels/channel,
100% strength; seconds/page, informational single timings):

| Mode | Algorithm | Python | Numba warm |
|---|---|---:|---:|
| L | Floyd-Steinberg | .270 | .0025 |
| L | Atkinson | .348 | .0023 |
| L | Sierra-Lite | .206 | .0023 |
| RGB | Floyd-Steinberg | .719 | .0036 |
| RGB | Atkinson | .880 | .0046 |
| RGB | Sierra-Lite | .561 | .0029 |

First Numba specialization calls took .51–.77 seconds, excluding initial import.
The current Calibre runtime has no Numba; its Python timings were L .216–.324,
RGB .654–.956 seconds/page. Full-resolution/full-volume fallback performance is
therefore a known limitation, not an acceleration-packaging claim. The standalone
Python environment emits an existing SciPy/NumPy ABI warning while Numba probes
optional BLAS; diffusion still compiles and passes exact integer parity.

Encoding is unchanged: PNG stays PNG, existing JPEG/WebP paths remain lossy.
Exact palette membership is guaranteed before encoding, not after lossy decoding.
Manual real-manga, native DPI, live-provider and physical Kobo qualification remain
out of scope. Qt smoke uses synthetic pages/fake library and forbids urllib HTTP.

Full-size Calibre portable RGB 1680x1264 Atkinson: 12.258 seconds/page (8 levels
per channel, 100% strength). Native acceleration packaging is deferred to Emperor.

Verification: 25 additional deterministic tests; 128 focused, 470 broader, and
683 full-suite tests passed. All 104 source/test/tool Python files compile and
shared runtime imports pass. The isolated Calibre Qt smoke passed on the portable
backend, including controls, embedded navigation, zoom/menu/pan, center preservation
through gamma and resolution changes, session reset, closure, and zero HTTP calls.
Git diff inspection/check passed. No branch change, commit, push, tag, or merge.

Files changed in this pass: main.py, image_processing.py, preview_detail.py,
dithering.py (new), tests/test_empress_pipeline.py, tests/test_preview_detail.py,
tests/test_dithering.py (new), tools/empress_qt_smoke.py,
tools/benchmark_dithering.py (new), tools/build_plugin.py, and these notes.
Earlier uncommitted Empress configuration/version/window/render-state work is
preserved, not attributed to this pass.
