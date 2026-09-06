# Empress: preview efficiency and bounded final rendering

## Scope / preserved foundation

The existing native C implementation, ABI 1, Python dithering math, ctypes loader,
validation, content-hash extraction and DLL are unchanged byte-for-byte from the
live-qualified native build. No dependencies or native recompilation were needed.
The supplied prompt's live baseline (~330 seconds portable, ~30 seconds native
serial for Steel Ball Run Vol. 3) is user qualification evidence, not a measurement
repeated by this pass. The earlier native report is reference only.

## Preview

Existing authoritative landscape analysis now has a planning-only mode: it emits
ordered page definitions without constructing/processing canvases. Pairing,
direction, spreads, supplemental-page isolation and sample-boundary extension
remain the same. Acquisition calls, limits and normalized source cache are unchanged.

Overview renders each planned page with the existing layout and Resolution, then
applies a 720x540 working ceiling before grayscale/Gamma/contrast/saturation/depth/
diffusion. This is approximately twice the existing 360x270 display thumbnail.
Pillow aspect-preserving thumbnail reduction never upscales. Actual output-size
captions still describe the full processed page, not the reduced working image.
Overview is representative, not pixel-identical to full-size error diffusion.
No ceiling is used for final output or full-quality Detail.

The Overview worker also creates bounded 360x270-or-smaller QImages. Entering or
switching Detail paints that page's existing image immediately, marked provisional,
at the full page's logical geometry. Only the selected output-page job is then
processed at full quality. The canvas is not cleared to a white loading pixel.
Full refinement replaces the provisional image with existing normalized viewport
center preservation. Fit, all zoom steps, actual-pixel geometry, pan and menu remain.

Changing processing while Detail is active marks Overview dirty and renders only
the selected full-quality page. Back cancels/stale-discards outstanding Detail
work and refreshes Overview only if dirty, through the existing 160 ms debounce.
One preview worker, newest-generation ownership, Finalization invalidation, atomic
Reset and session-only settings are preserved. The 64 MiB selected Detail cap and
128 MiB normalized sample cap remain. Additional provisional storage is bounded by
the acquired sample (at most 14 thumbnails, approximately 5.2 MiB RGBA); no full-size
multi-page processed cache or zoom cache was added.

## Final rendering

Download completes before planning or rendering begins, as before, per output
book/volume. The same layout analysis emits jobs; no provider work or pairing
decisions run in the pool. Each job composites, processes via the existing shared
transform/native backend, and encodes one already-defined page.

Only active nonzero-strength dithering with validated native acceleration selects
parallel workers:

`min(4, max(1, (os.cpu_count() or 2) // 2))`

Portable dithering, neutral, hard quantization and nondithered output stay serial.
The pool bounds submitted plus completed-but-not-consumed jobs to `workers * 2`
(maximum eight). Completion may be out of order; yielding/writing is strictly in
output-index order on the owning DownloadWorker thread. ZIP writing is never
concurrent. Source downloads are not pipelined with rendering. Existing downloaded
source records remain resident; this pass bounds render work/backlog, not the total
source inventory or absolute final-render MiB usage.

If native becomes unavailable mid-batch, existing cancellation checkpoints acquire
a shared portable-work gate held until that page finishes. This prevents concurrent
portable error-diffusion loops without changing native code. On failure/cancel, no
more jobs are submitted, pending work is cancelled, running calls finish/check
cancellation safely, and the original useful error propagates. No thread is killed.
CBZ output is written to a sibling `.part`, finalized, then atomically published;
failed/cancelled work never silently publishes a partial book.

## Progress, logs and timing

The existing progress signal/bar transitions from acquisition to `Processing 0/N`,
then advances on completed output pages, not submissions. It finishes with CBZ
metadata/finalization and the existing Calibre import status. No extra bar is added.
Activity Log has phase boundaries, backend/worker context and 25/50/75% milestones,
not one rendering log per page. Preview uses its existing status text for Overview
updates/full-quality refinement, then returns to inspection instructions.

`perf_counter()` measures per-output acquisition, rendering, serial ZIP I/O,
preparation total, preview updates and Calibre import. Total Download & Add combines
the existing worker elapsed duration with import duration. Timing is diagnostic,
not a profiler: parallel render wall time includes overlap with ordered serial ZIP
writes; ZIP I/O is separately timed and these figures must not be blindly summed.
Writes drain completed pages while the remaining render batch runs, avoiding a
whole-book encoded backlog. There is no download/render overlap.

## Verification

- 16 new orchestration tests: worker rule, native eligibility, portable serial path,
  300-job bounded queue, forced out-of-order completion, ordered consumption, errors,
  cancellation, consumer closure and serialized runtime fallback.
- Tests cover reduced working dimensions, no upscaling, representative grayscale,
  selected-page-only Detail, dirty hidden Overview, exact legacy layout bytes for
  both reading directions/spreads/extras, ordered final pages, serial ZIP writes,
  neutral/covers, progress milestones, timings and no partial publication.
- 163 focused / 505 broader / 718 full-suite tests pass, including native fixtures.
- 112 source/test/tool Python files compile; diff inspection/check passes.
- Real Calibre offscreen Qt smoke passes in native and simulated missing-DLL modes:
  immediate provisional images, page switches, zoom/pan/menu, center preservation,
  deferred Overview refresh, Reset, close and zero network calls.
- Native Python modules and DLL match the preceding qualified ZIP exactly.

## Benchmark

Real Calibre runtime, synthetic 12-page 1680x1264 RGB workload, eight levels/channel,
Atkinson at 100%, PNG encoding and ordered ZIP_STORED writing. Native was validated
before timing; input creation/acquisition was excluded. No native code changes.

| Path | Workers | Pages | Wall seconds | Peak outstanding |
|---|---:|---:|---:|---:|
| Serial native | 1 | 12 | 3.0438 | 1 |
| Bounded parallel native | 4 | 12 | 0.9239 | 8 |

Speedup: **3.295x**. Page names/order and encoded page-byte hashes are identical.
This single synthetic timing is not a predicted end-to-end manga-volume speedup.
The real Ryzen 5 5600 / Steel Ball Run Vol. 3 / same settings / physical Kobo rerun
remains manual. Overview intentionally uses representative reduced-resolution math;
use full-quality Detail for pixel inspection. Very large source pages still incur
layout/resize work and individual native calls finish before cancellation takes effect.

## Files changed in this pass

- `main.py`: planning/render jobs, Preview routing/provisional images, final pool and feedback.
- `image_processing.py`: optional Overview-only working ceiling; full-output semantics unchanged.
- `page_rendering.py` (new): bounded ordered executor and native eligibility/fallback gate.
- `tests/test_page_rendering.py` (new), `tests/test_empress_pipeline.py`, `tests/test_preview_detail.py`.
- `tools/benchmark_page_rendering.py` (new), `tools/empress_qt_smoke.py`, `tools/build_plugin.py`.
- This report. Earlier uncommitted work remains preserved.

No commit, push, tag, merge, branch change, dependency installation, persistent-cache
clearing, normal Calibre-library modification or unrelated processing feature was done.

## Final artifact

Built exactly once: `dist/MangaNana-Calibre-dev.zip`.

SHA-256: `EA6384260489F9456F51E0AB99F890AE73E7E79C280056A06EC6E2F9C88C1B34`.

ZIP integrity, exact 52-entry manifest, all 46 packaged Python compile checks and
source/resource parity passed. The actual ZIP was installed into an isolated
Calibre configuration and generated valid Portrait/Landscape CBZs with native
parallel selection and simulated missing-DLL portable fallback. Cover/neutral
encoding and native/Python parity checks passed, with zero network calls. The
native resource used the unchanged existing DLL content hash. Eight pool tests
were additionally repeated ten times (80 checks), all passing.

Only the newly created disposable Qt/benchmark/loader configurations are removed
after verification. The source build/native cache and all user persistent caches
are left intact. Restart Calibre after installing the build before live qualification.
