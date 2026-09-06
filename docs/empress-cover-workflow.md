# MangaAnkā cover workflow implementation

Implemented Stamp Existing Cover and Generate Cover in the existing Empress
workspace. No custom-cover editor, branch operation, commit, tag, push, merge,
plugin installation, or release was performed.

## UI and behavior

The **Cover mode** selector and **Preview Cover** button are in
**Finalization → Book Creation & Metadata**, below the source-cover and
zero-padding checkboxes. Options are Keep Existing Cover (default), Stamp
Existing Cover, and Generate Cover. The selection persists with session settings.

Keep mode retains the existing source-cover checkbox behavior and existing
EXIF normalization. Stamp explicitly uses source artwork; Generate does not
fetch artwork. The source-cover checkbox is disabled in these two explicit modes
while retaining its value for Keep mode. Changing mode invalidates Final Outputs
and requires the existing review refresh before download. Controls lock during
download. Descriptions follow the existing accessibility convention.

Select a Final Outputs row and choose Preview Cover to see a 220 × 300 preview.
The same compositor produces preview and final covers. Fetching, composition,
and thumbnail resizing run on a QThread. Closing the preview requests
interruption; late results cannot update a closed dialog. A completed preview
also updates that row's existing cover thumbnail. Metadata edits clear it.

## Metadata and numbering

- Generated text uses the applied base **Title**, then **Series**, then
  `Untitled Manga`. Automatically appended book suffixes are not repeated in
  the artwork. Author remains ordinary Calibre metadata and is not drawn.
- A volume book uses its resolved output volume, including detected/manual
  volumes assembled through Chapter mode.
- An individual chapter book uses its chapter number, never its parent volume.
- Standalone chapter collections have no single index and retain an empty badge.
- Zero-padding follows the existing checkbox: `08`, `16`, `103`, `08.5`.
- The pure renderer accepts series index as a fallback when an explicit number
  is absent. Invalid, negative, nonfinite, or pathological numbers are omitted.
- Titles wrap and reduce in size within the main title area. Extremely long
  metadata is bounded and ellipsized at a readable minimum font size.
- Missing stamp artwork omits the cover with an Activity Log explanation.
  Missing title metadata does not prevent generation. Rendering errors are
  logged and retain available original artwork without failing manga output.

## PSD translation

Read the complete supplied handoff before editing. The actual attached file is
`C:/Users/Jerry/Desktop/Test Images/MangaAnka/Cover Generation MangaAnka.psd`
(without the handoff's `(1)` suffix). Its dimensions and all six layer names
match the updated handoff. SHA-256:
`47aaddcba78e8f305235f9da6f909b142c30dad3dc5946636f02d0123f3c9018`.

The final canvas is 880 × 1200. The main art occupies x=0–739 and the exact PSD
stamp occupies x=740–879. The stamp asset includes its texture, vertical red
Bebas Neue wordmark, and empty circular badge. The example number was excluded.
The badge is centered at (811, 1068); dynamic text is fitted inside its circle.

Generated covers composite the exact background layer over Midnight Blue,
then the anchor at (123, 437), retaining the PSD's existing transparency,
then dynamic title text with a dark stroke and restrained pale glow. The
stamp and dynamic badge number come last. The anchor's maximum alpha is 156;
it has not been replaced with a newly drawn or opaque anchor.

Stamped covers EXIF-orient and center-fit/crop the source into 740 × 1200,
then add only the stamp and number. No tint or generated-background layer
touches the art. Original PSD source art and example title are not bundled.

The unmodified Bebas Neue font is bundled with its SIL OFL license. PSD reading
is development-only; runtime uses the project's existing Pillow stack.
`tools/extract_cover_assets.py` reproduces the three static asset exports from
the supplied PSD using psd-tools. Calibre ZIP resources load in memory.

## Cover/page separation

DownloadWorker writes the resulting portrait PNG to the existing separate
`*_cover.png` metadata path. The established Calibre import consumes this path.
Cover bytes never enter `output_page_jobs`, page processing settings, landscape
pairing, dithering, or the CBZ ZIP. Generate mode skips cover-specific fetching.

## Exact files changed in this pass

Existing files extended (their pre-existing workspace edits were retained):

- `main.py` — Finalization controls, preview worker, mode propagation, compositor integration.
- `config.py` — default cover mode.
- `tools/build_plugin.py` — compositor and cover resource manifest.
- `THIRD_PARTY_NOTICES.md` — bundled font attribution.
- `tests/test_empress_pipeline.py` — expose the compositor to the existing production-worker harness.

New files:

- `cover_rendering.py`
- `assets/covers/background.png`
- `assets/covers/anchor.png`
- `assets/covers/stamp.png`
- `assets/covers/BebasNeue-Regular.ttf`
- `assets/covers/OFL.txt`
- `tests/test_cover_rendering.py`
- `tools/extract_cover_assets.py`
- `tools/cover_calibre_smoke.py`
- `docs/empress-cover-workflow.md`

## Validation and limits

- All Python source syntax checks and Git whitespace checks passed; inspected
  the cover-related Git diff while preserving the pre-existing Empress changes.
- 78 focused tests passed: cover renderer/workers, Empress pipeline, derived
  preview covers, chapter output planning, and Finalization UI contracts.
- 42 High Priestess UI checks passed after retaining accessibility descriptions
  instead of introducing tooltips.
- Full unittest suite before the production-reference alignment: **782 passed,
  3 failed, 0 errors, 0 skipped** (785 total). The three failures were stale
  0.19 expectations in `tests/test_screen_emulation.py` and the accepted lab
  JSON; production already intentionally used CFA strength 0.10. Those
  references now use 0.10 and the focused screen-emulation suite passes.
- A plain pytest attempt could not initialize because it imports Calibre's
  plugin entry point outside Calibre. Validation uses the repository's unittest
  harness and the actual Calibre runtime instead.
- Real Calibre offscreen Qt smoke passed both branded modes, grouped volume,
  chapter and standalone downloads, actual preview dialog, event-loop
  responsiveness, review invalidation, and download locking. Synthetic network
  responses were used; real external network calls were forbidden.
- Compared complete CBZ entry maps (including ComicInfo) across Keep, Stamp,
  and Generate for identical books. They are identical in both portrait and
  landscape processing. Cover pixels remain independent of page adjustments.
- Confirmed stamp placement, unchanged art pixels, EXIF handling, PSD anchor
  transparency, title bounds, badge bounds and values, missing metadata, preview
  cancellation, and ZIP-style resource loading.
- Visually inspected the PSD, generated volume cover, stamped chapter cover,
  long title with fractional chapter badge, and Finalization screenshot.
- Package manifest resolves all 61 files, including all five cover resources.
  No distributable ZIP was built or installed in this pass.

Artifacts and detailed suite log are under
`C:/MangaNana-Dev/Test-Data/manganana-cover-validation/` and
`C:/MangaNana-Dev/Test-Data/manganana-cover-suite.log`. Qt configuration is
isolated under Test-Data; worker downloads used Test-Downloads and were cleaned
up. No Calibre library was opened or modified. A fake database object displayed
the permitted Test-Library path during the GUI smoke.

Remaining limits: actual provider failures and real Calibre database import were
not exercised; the desktop GUI was exercised offscreen, not manually across
physical DPI configurations. Bebas Neue supplies its own character coverage;
this initial implementation does not add a multilingual font fallback system.
