# Empress Processing Preset Tuning

The built-ins below are conservative starting points. Processing changes actual
reading-page pixels. Future Screen Emulation will preview already-processed pixels
without changing presets and remains a separate system.

| Preset | Brightness | Contrast | Gamma | Saturation | Sharpness | Grayscale | Depth | Dithering | Strength |
|---|---:|---:|---:|---:|---:|---|---|---|---:|
| Original | 100% | 100% | 1.00 | 100% | 100% | Off | Original | Off | 100% |
| B&W Manga | 100% | 115% | 1.00 | 100% | 110% | On | Original | Off | 100% |
| High Contrast B&W | 100% | 130% | 0.95 | 100% | 120% | On | Original | Off | 100% |
| Soft Grayscale | 100% | 95% | 1.05 | 100% | 100% | On | Original | Off | 100% |
| Color Enhancement | 100% | 108% | 1.00 | 125% | 110% | Off | Original | Off | 100% |

## Workflow

Select a built-in, compare Overview and full-quality Detail, adjust until the
selector reads Custom, and save the experiment under a user name. Test clean line
art, gradients/screentones, dark low-contrast pages, color pages, small text and
fine linework across several series. Promote settled values only by changing the
built-in constants in `processing_presets.py`; built-ins remain immutable in UI.

## Final values worksheet

Record Brightness, Contrast, Gamma, Saturation, Sharpness, Grayscale, Output Depth,
Dithering, Dither Strength and notes for B&W Manga, High Contrast B&W, Soft
Grayscale, and Color Enhancement. Do not tune for a device; that belongs to Screen
Emulation.
