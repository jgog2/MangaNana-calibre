# Empress: Processing Presets implementation

## Architecture and scope

`processing_presets.py` is a pure module over the authoritative immutable
`ProcessingSettings`. It owns schema version 1, stable built-in IDs, immutable
definitions, strict serialization/deserialization, safe per-entry preference
loading, exact matching, normalized names, user-preset edits and a canonical
settings-snapshot API. It contains no image transformation, Qt, provider, cover,
layout, device or Screen Emulation behavior.

Only user definitions are stored under `processing_presets`; active selection is
not persisted. A fresh dialog always constructs neutral settings and selects
Original. Malformed stored entries are skipped independently. Names are whitespace
normalized and case-insensitively exclude Custom, built-ins and duplicate users.
Built-ins never appear in Manage and pure helpers reject their overwrite/rename/
delete. User presets can be saved, renamed, updated from current settings and
deleted through a compact menu. Persistence commits immediately.

The selector lists the five built-ins directly and shows a disabled MY PRESETS
separator only when user presets exist. Custom is an unsaved display state derived
from exact `ProcessingSettings` equality. Built-ins are matched first; manual edits
switch to Custom and exact restoration rematches automatically.

Applying any preset blocks signals for all five sliders, grayscale choices, depth,
dithering and strength; sets grayscale first; rebuilds valid depth choices; restores
depth/algorithm/strength; unblocks; and calls the existing state-update path once.
Thus one changed preset causes one Finalization invalidation and one debounced local
Preview update. Reset calls the same path with the Original built-in; there is no
second neutral definition. The newest-generation render owner remains authoritative
during rapid selection.

The existing sliders now store integer percentages internally while preserving
their 5% interactive step and public ranges. This is required so provisional code
values such as Color Enhancement Contrast 108% are restored exactly instead of
silently rounding to 110%. It does not change processing math or ranges.

## Built-ins

| ID / Name | Brightness | Contrast | Gamma | Saturation | Sharpness | Gray | Depth | Dither | Strength |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| `original` / Original | 100% | 100% | 1.00 | 100% | 100% | Off | Original | Off | 100% |
| `bw_manga` / B&W Manga | 100% | 115% | 1.00 | 100% | 110% | On | Original | Off | 100% |
| `high_contrast_manga` / High Contrast B&W | 100% | 130% | 0.95 | 100% | 120% | On | Original | Off | 100% |
| `soft_grayscale` / Soft Grayscale | 100% | 95% | 1.05 | 100% | 100% | On | Original | Off | 100% |
| `color_enhancement` / Color Enhancement | 100% | 108% | 1.00 | 125% | 110% | Off | Original | Off | 100% |

These values remain provisional and are documented in
`docs/empress-processing-preset-tuning.md` for manual tuning.

## Preserved systems

The processing pipeline, `image_processing.py`, native C/DLL/ABI/loader, diffusion,
worker pool, final encoding/layout, covers, providers, unified derived-volume repair,
BOOK WALKER cover repair, Finalization and chapter workflows are unchanged. Presets
apply only to reading-page settings. The later Preview-only Screen Emulation feature
remains outside ProcessingSettings and presets; no device settings appear in them.

## Verification

- 129 focused / 559 broader / 745 full-suite tests pass.
- 117 source/test/tool Python files compile; Git diff inspection/check passes.
- All five built-ins, exact values and neutral Original validate.
- Strict schema-v1 round trips cover grayscale/color reduced depth, all algorithms
  and strength. Malformed entries fail independently. User save/load/persistence,
  update, rename, delete and reserved/built-in protection pass.
- Atomic built-in/Reset application, one transition, grayscale depth rebuilding,
  Saturation disabled/preserved, Custom/rematching and newest-render-wins pass.
- Real offscreen Calibre Qt smoke passes with native and simulated missing-DLL
  portable backends. It covers selector grouping, 5% steps, exact preset application,
  one invalidation, save/update/rename, dialog-restart persistence, session Original,
  Preview, full Detail, Reset and zero external network calls. Screenshot inspected.
- Existing tests cover shared Preview/final settings, untouched covers, native and
  portable rendering, ordered CBZ creation and cancellation/progress behavior.

## Files changed/created in this pass

- New `processing_presets.py`.
- `main.py`: compact UI, exact matching, atomic application and user management.
- `config.py`: user-preset preference default.
- `tools/build_plugin.py`: package the production module.
- `tools/empress_qt_smoke.py`: real persistence/atomic/Custom smoke coverage.
- New `tests/test_processing_presets.py`; mechanical percentage-scale updates in
  existing Empress UI harness tests only.
- New tuning and implementation documents.

## Limitations

Built-in values are intentionally provisional and still require manual visual
tuning across representative manga. The management UI is deliberately compact;
there is no reordering, import/export, active-preset persistence, built-in editing,
device selection or Screen Emulation. Existing optional Numba/SciPy ABI and Pillow
deprecation warnings remain. No external provider or normal Calibre library is used.

No commit, push, tag, merge, branch change, release, dependency installation,
persistent-cache clearing or unrelated cleanup was performed.

## Final artifact

Built exactly once after source verification: `dist/MangaNana-Calibre-dev.zip`.

SHA-256: `B2F35CFBF38007364268032C9F01C7E53531523932BBFB019D90DAD411E11B8C`.

ZIP integrity, exact 53-entry manifest, source/resource parity, required runtime
modules and compilation of all 47 packaged Python modules pass. The actual ZIP was
installed into a disposable Calibre configuration. Packaged native and simulated
missing-DLL portable processing generated valid Portrait/Landscape CBZs, preserved
cover/neutral behavior and passed algorithm parity with zero network calls. The
installed ZIP also passed the complete preset Qt workflow, including persistence.
Disposable configurations created for this pass are removed; persistent caches
remain untouched. Restart Calibre after installing.
