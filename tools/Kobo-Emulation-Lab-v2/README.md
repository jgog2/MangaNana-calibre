# MangaNana Kobo Emulation Lab v2

Standalone Screen Emulation development lab. This is intentionally separate from
the MangaNana production plugin.

## One-click launch

Double-click:

`Start-Kobo-Emulation-Lab.bat`

Or:

```powershell
& "C:\Program Files\Calibre2\calibre-debug.exe" .\kobo_emulation_lab_v2.py
```

## Baseline preserved

The global controls start with the exact values used during the user's close
real-device comparison:

- Black floor: 62
- White ceiling: 232
- Gamma: 1.05
- Global saturation: 0.22
- Red gain: 1.03
- Green gain: 1.0
- Blue gain: 0.92
- Chroma resolution: 50%
- Panel softness: 0.41000000000000003

Panel softness remains at the historical tuned value for reproducibility. It can
now be typed precisely and reduced during manga-page testing.

## Precision controls

Every continuous setting has BOTH:

- a slider
- an editable numeric spin box

Changing either updates the other.

Global controls include 0.01 precision for gamma, gains, global saturation, and
panel softness. Hue-response adjustments use 0.5% precision.

## Exact Kobo border geometry

`KoboBoarderCenterFinder.png` contains a pure-green 1680 x 1264 target.

Measured target rectangle:

- x = 127
- y = 123
- width = 1680
- height = 1264

The lab therefore places the landscape framebuffer at that exact coordinate
before drawing `KoboBoarder.png` over it.

Portrait mode rotates the frame 90 degrees counterclockwise and transforms the
same exact rectangle to 1264 x 1680.

## Hue-response lab

Hue corrections default OFF and all values default to zero so the existing close
match is unchanged.

The Hue Response tab provides lightness and saturation adjustment anchors for:

- red
- orange
- yellow
- green
- cyan
- blue
- purple
- magenta

A saturation gate protects low-saturation colors. This is useful because the
pastel pink target already matched well while saturated magenta did not.

This is still a lab approximation. If the green/brown observations prove that
hue + saturation gating is insufficient, the next step is a small measured 3D
LUT rather than more global controls.

## Experimental Kaleido surface

The `Kaleido Surface` tab adds independently switchable, lab-only controls for:

- a device-coordinate 3x3 diagonal RGB CFA approximation;
- CFA strength from 0.00 through 0.35;
- a horizontal canonical-panel CFA mirror for handedness comparison;
- panel softness from 0.00 through 0.90 native pixels;
- deterministic achromatic micro-grain from 0.0 through 4.0 RGB code values.

The canonical portrait CFA is generated mathematically as `(x - y) % 3`, with
0=red, 1=green, and 2=blue. Landscape rotates that physical panel lattice 90
degrees clockwise. The source image never selects the device orientation; use
the explicit `Device Orientation` selector.

`Mirror CFA Horizontally` reflects only the canonical portrait CFA x coordinate
before the index is evaluated. It never mirrors the source page, framebuffer,
bezel, grain, or preview. Current landscape handedness appears as `/`; mirrored
landscape handedness appears as `\`. Missing profile values default to Current.

CFA modulation runs after the existing color and hue calibration, followed by
optional micro-grain and then panel softness. Disabled stages and zero strengths
are exact no-ops. The grain field uses a deterministic coordinate hash, is
applied equally to R/G/B, and is stable across page changes and rerenders.

The `Diagnostic` button generates a flat-color and thin-line target in memory.
No photographed or PNG screen texture is used. Existing device-border support
is retained for lab comparison.

Profiles saved by this version use schema 3 and store experimental controls in
the optional `kaleido_surface` object. Schema 1 and 2 profiles remain loadable;
missing surface settings default disabled and their stored panel softness is
preserved.

Focused pure tests:

```powershell
python .\test_kaleido_surface.py
```

## Production rule

All emulation is preview-only. These transforms must never modify a downloaded
or finalized CBZ.


## v2.1 startup fix

Fixed Calibre/PyQt strict typing for integer `QSpinBox` controls. Integer fields now receive integer ranges/values while decimal fields continue to use `QDoubleSpinBox`.
