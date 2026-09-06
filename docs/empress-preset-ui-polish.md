# Empress: Processing Preset UI polish

## Narrow changes

- Renamed only the built-in display label `High Contrast Manga` to
  `High Contrast B&W`. Stable ID `high_contrast_manga` is unchanged, so exact
  settings matching and existing internal references retain their identity.
- Changed only Color Enhancement Saturation from 110% to 125%. Its Brightness
  100%, Contrast 108%, Gamma 1.00, Sharpness 110%, Grayscale Off, Original depth,
  Dithering Off and Strength 100% remain unchanged.
- Reduced only the left Book Customization card's vertical margins from 16 to
  12 px, vertical spacing from 10 to 7 px, and layout-card height range 68–74 px
  to a fixed 62 px. Card padding is 5 px vertically instead of 6. Slider sizes,
  font sizes, preset row, Reset, right Preview and panel proportions are unchanged.
- Replaced only the Landscape drawing with vendored `images/tabler-book.svg`.
  It has the specified five Tabler BOOK paths, 24x24 viewBox, no fill, round caps/
  joins, orange `#FF6740`, stroke 1.4, and a button icon size of 36x36 px. A local
  Landscape-only button adjusts only the icon 5 px left while retaining Qt's native
  text placement. Portrait retains its prior painter geometry and 38x28 icon size.
- Added the Tabler MIT notice to `THIRD_PARTY_NOTICES.md` and included both the
  SVG and notice in the plugin package. No runtime dependency was added.

## Preserved systems

Preset schema/persistence/management/atomic application, immutable settings,
Custom matching, Reset, processing semantics/order, Preview/Detail, native/portable
dithering, workers, providers, derived volumes, covers, Finalization and CBZ output
are unchanged. Screen Emulation remains absent and separate.

## Verification

- 134 focused / 564 broader / 750 full-suite tests pass.
- 119 source/test/tool Python files compile; Git diff inspection/check passes.
- Tests verify reviewed names/values, stable ID/matching, neutral Original, Custom,
  user presets, atomic application/Reset, absence of device fields, exact SVG XML,
  portrait constants, local density values, attribution and package declarations.
- Real offscreen Qt native and simulated missing-DLL portable smoke pass: complete
  preset workflow, exact 125% restoration, one invalidation, fresh Original,
  Overview/Detail, zero network calls, and visible in-bounds Reading Direction,
  preset and last processing controls at the normal 1764x1068 client size.
- Screenshot inspection confirms the left panel is balanced without scrolling,
  Reading Direction is unclipped, and the open-book icon is legible in the selected
  Landscape card while Portrait is unchanged.
- All qualified production files other than `main.py` and `processing_presets.py`
  match the preceding ZIP. The native DLL retains its qualified content hash.

## Files changed/created in this pass

- `processing_presets.py`
- `main.py`
- `images/tabler-book.svg` (new)
- `THIRD_PARTY_NOTICES.md` (new)
- `tools/build_plugin.py`, `tools/empress_qt_smoke.py`
- `tests/test_processing_presets.py`, `tests/test_empress_polish.py` (new)
- `docs/empress-processing-preset-tuning.md`, `docs/empress-processing-presets.md`
- This report.

The untracked developer reference `book_tabler_test.py` was inspected but not
modified or packaged.

## Limitations and safety

UI geometry was verified with deterministic offscreen Qt and visual screenshot
inspection, not every Windows DPI/theme combination. No live provider work or
normal Calibre library was used. Existing optional Numba/SciPy ABI and Pillow
deprecation warnings remain.

No commit, push, tag, merge, branch change, release, dependency installation,
persistent-cache clearing, Screen Emulation or unrelated cleanup was performed.

## Final artifact

Built exactly once after source verification: `dist/MangaNana-Calibre-dev.zip`.

SHA-256: `D4E3FD1316DEF8A489C30FC88A943DED20D1841D57F302CFBF7EB3256088885E`.

ZIP integrity, exact 55-entry manifest, all 47 packaged Python module compile
checks, source/resource parity, exact SVG structure, notice inclusion and unchanged
native DLL pass. The installed ZIP passes the complete Qt preset/layout/icon smoke.
Native and simulated missing-DLL portable paths generate valid Portrait/Landscape
CBZs with cover/neutral parity and zero network calls. Disposable configurations
created for this pass are removed; persistent caches remain untouched. Restart
Calibre after installing.
