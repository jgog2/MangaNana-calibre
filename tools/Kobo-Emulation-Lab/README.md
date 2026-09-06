# MangaNana Kobo Emulation Lab

Standalone development lab for tuning the Kobo Libra Colour Screen Emulation
profile before any production plugin code is changed.

## Run

```powershell
cd C:\MangaNana-Dev\MangaNana-calibre
& "C:\Program Files\Calibre2\calibre-debug.exe" .\tools\Kobo-Emulation-Lab\kobo_emulation_lab.py
```

Or run it from whatever folder you place the lab in:

```powershell
& "C:\Program Files\Calibre2\calibre-debug.exe" "C:\path\to\Kobo-Emulation-Lab\kobo_emulation_lab.py"
```

## Current behavior

- `No Emulation`
- `Kobo Libra Colour - 100% Frontlight`
- internal device rasterization to 1264x1680 portrait / 1680x1264 landscape
- full-resolution luminance with independently reduced chroma resolution
- tuneable black floor / white ceiling / gamma
- tuneable saturation and RGB gains
- tuneable chroma spatial resolution
- tuneable panel softness
- Fit through 200% zoom
- user-provided Kobo PNG composited automatically as the device frame
- device frame rotates automatically for portrait source material
- tuned profile can be saved as JSON

The initial profile values are provisional. They exist so the UI and transform
pipeline can be tested while the calibration photographs are quantitatively fit.

## Production rule

Screen Emulation is preview-only. None of these transforms should ever modify
the final CBZ.
