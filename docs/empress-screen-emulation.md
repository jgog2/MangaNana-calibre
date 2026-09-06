# Empress: eReader Screen Emulation

## Scope and firewall

Book Customization's Live eReader Preview card offers a session-only `eReader
Sim` selector with `Off` and `Kobo Libra Colour`. Fresh dialogs always start
Off. The selected profile is armed in Overview but the transform activates only
while one output canvas is open in Detail Preview.

The emulator is applied in `ProcessingPreviewWorker` after the normal shared
page render. It is not part of `ProcessingSettings`, presets, acquisition or
final-output signatures, final workers, CBZ writing, covers, metadata, or
provider code. Changing the selector makes no network request and does not
invalidate Finalization. Overview pixels and performance remain unchanged.

## Frozen Kobo Libra Colour profile

The final calibrated profile targets 100% frontlight and ComfortLight warmth 0.
It freezes black floor 62, white ceiling 232, gamma 1.05, saturation 0.22,
channel gains 1.03/1.00/0.92, 50% chroma resolution, and softness radius 0.10.
Hue correction is disabled. After the calibrated color transform, production
applies the accepted 3x3 diagonal RGB CFA at strength 0.10 with horizontal
canonical-panel mirroring, deterministic achromatic micro-grain at strength
1.0, and then panel softness.

Output Layout is the sole orientation authority. Individual Pages uses a
1264x1680 framebuffer. Paired Pages uses a 1680x1264 framebuffer. Production
returns and displays that full framebuffer directly; no physical bezel, frame
geometry, frame bytes, or frame asset participates in the plugin. The standalone
Kobo Emulation Lab and Kobo Emulation Lab v2 retain their own bezel controls and
assets for laboratory use.

## Detail presentation

Switching profiles with Detail open immediately clears the contradictory old
image before scheduling one newest-state-wins local render. Kobo never displays
a raw Overview thumbnail provisionally. Same-profile processing changes may
retain the prior completed device image while refinement runs.

The Detail scroll area uses the same complete logical preview rectangle with
simulation Off or Kobo selected. Fit is the ordinary largest-contained-image
calculation in both modes, with no device-PPI cap and no simulator-only aspect
host restriction. The simulated pixels remain a native 1264x1680 or 1680x1264
framebuffer; presentation scaling is independent and never accumulates across
refreshes or profile switches.

All explicit zooms scale and pan only the final 1264x1680 or 1680x1264 emulated
framebuffer. They never retain or reveal a higher-resolution processed source,
never invoke the emulator, and never request provider data. Kobo labels 100% as
`100% Device Pixels`; explicit zooms at or above 100% disable smooth scaling.
Off keeps the normal qualified Detail surface.

## Verification

Focused pure, worker, UI, stale-state, geometry, zoom, transform-failure, and
output-isolation controls cover both orientations. Native and forced-portable
Calibre smokes exercise Overview/Detail without provider access. Manual GUI
qualification should still compare the calibrated approximation against a
physical Kobo Libra Colour and representative manga pages.

The current qualification counts, timings, package hash, and installed-Calibre
smoke result are recorded in the release report for the build rather than frozen
in this architecture note.
