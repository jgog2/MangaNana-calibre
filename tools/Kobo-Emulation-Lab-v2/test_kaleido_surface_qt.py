"""Offscreen Calibre/Qt smoke for the standalone Kaleido surface lab."""
import json
import os
from pathlib import Path
import sys

from qt.core import QApplication
from PIL import ImageEnhance, ImageFilter


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kaleido_surface import LANDSCAPE, PORTRAIT, diagnostic_image, merge_lab_profile  # noqa: E402
from kobo_emulation_lab_v2 import (  # noqa: E402
    KoboEmulationLab, apply_channel_gains, apply_hue_corrections, apply_tone,
    contain_on_canvas, emulate, reduce_chroma_resolution,
)


app = QApplication.instance() or QApplication([])
lab = KoboEmulationLab()
lab.show()
app.processEvents()

assert lab.device_orientation.currentData() == PORTRAIT
assert not lab.cfa_enabled.isChecked()
assert not lab.mirror_cfa_horizontal.isChecked()
assert not lab.micro_grain_enabled.isChecked()
assert lab.cfa_strength.number.decimals() == 2
assert (lab.cfa_strength.number.minimum(), lab.cfa_strength.number.maximum()) == (0.0, 0.35)
assert lab.softness.number.decimals() == 2
assert (lab.softness.number.minimum(), lab.softness.number.maximum()) == (0.0, 0.9)
assert lab.grain_strength.number.decimals() == 1
assert (lab.grain_strength.number.minimum(), lab.grain_strength.number.maximum()) == (0.0, 4.0)
assert not lab.cfa_strength.isEnabled() and not lab.mirror_cfa_horizontal.isEnabled()
assert not lab.grain_strength.isEnabled()
assert "3x3 diagonal RGB approximation" in lab.surface_diagnostics.text()
assert "Anchor: device framebuffer" in lab.surface_diagnostics.text()
assert "Orientation: Portrait" in lab.surface_diagnostics.text()

lab.source = diagnostic_image((180, 240))
source_before = lab.source.tobytes()
legacy_values = lab.values()
legacy_values["kaleido_surface"] = {
    "cfa_enabled": False, "cfa_strength": .25,
    "micro_grain_enabled": False, "grain_strength": 3.0,
}
actual_legacy = emulate(lab.source, legacy_values, lab.profile)
expected_legacy = contain_on_canvas(lab.source, (1264, 1680))
expected_legacy = reduce_chroma_resolution(expected_legacy, legacy_values["chroma_resolution_percent"])
expected_legacy = apply_tone(expected_legacy, legacy_values["black_floor"],
                             legacy_values["white_ceiling"], legacy_values["gamma"])
expected_legacy = apply_channel_gains(expected_legacy, legacy_values["red_gain"],
                                      legacy_values["green_gain"], legacy_values["blue_gain"])
expected_legacy = ImageEnhance.Color(expected_legacy).enhance(legacy_values["saturation"])
expected_legacy = apply_hue_corrections(expected_legacy, legacy_values["hue_corrections"])
if legacy_values["softness_radius"] > 0:
    expected_legacy = expected_legacy.filter(
        ImageFilter.GaussianBlur(radius=legacy_values["softness_radius"]))
assert actual_legacy.tobytes() == expected_legacy.tobytes()
lab.cfa_enabled.setChecked(True)
assert lab.mirror_cfa_horizontal.isEnabled()
lab.cfa_strength.number.setValue(0.16)
lab.micro_grain_enabled.setChecked(True)
lab.grain_strength.number.setValue(2.0)
lab.softness.number.setValue(0.15)
assert lab.cfa_strength.slider.value() == 16 and lab.cfa_strength.value() == 0.16
assert lab.grain_strength.slider.value() == 20 and lab.grain_strength.value() == 2.0
assert lab.softness.slider.value() == 15 and lab.softness.value() == 0.15
lab.rebuild_now()
assert lab.source.tobytes() == source_before
assert lab.simulated.size == (1264, 1680)
assert lab.display_image.size == (1725, 1926), "Lab bezel must remain available"
current_pixels = lab.simulated.tobytes()
lab.mirror_cfa_horizontal.setChecked(True)
lab.rebuild_now()
assert lab.source.tobytes() == source_before
assert lab.simulated.tobytes() != current_pixels
assert "CFA Handedness: Mirrored Horizontal" in lab.surface_diagnostics.text()
assert "Visible Diagonal: /" in lab.surface_diagnostics.text()

simulated = lab.simulated
simulated_bytes = simulated.tobytes()
for index in range(lab.zoom.count()):
    lab.zoom.setCurrentIndex(index)
    app.processEvents()
assert lab.simulated is simulated and lab.simulated.tobytes() == simulated_bytes

lab.preview_mode.setCurrentIndex(lab.preview_mode.findData("source"))
assert lab.current_preview_image() is lab.source
lab.preview_mode.setCurrentIndex(lab.preview_mode.findData("emulated"))
assert lab.current_preview_image() is lab.display_image

lab.device_orientation.setCurrentIndex(lab.device_orientation.findData(LANDSCAPE))
lab.micro_grain_enabled.setChecked(False)
lab.cfa_strength.number.setValue(0.18)
lab.softness.number.setValue(0.50)
lab.rebuild_now()
assert "Orientation: Landscape" in lab.surface_diagnostics.text()
assert "Visible Diagonal: \\" in lab.surface_diagnostics.text()
assert lab.simulated.size == (1680, 1264)
assert lab.display_image.size == (1926, 1725)

old = json.loads((HERE / "baseline_tuned_profile.json").read_text(encoding="utf-8"))
lab.profile = merge_lab_profile(old, lab.default_profile)
lab.apply_profile_to_controls()
assert not lab.cfa_enabled.isChecked() and not lab.mirror_cfa_horizontal.isChecked()
assert not lab.micro_grain_enabled.isChecked()
assert abs(lab.softness.value() - 0.41000000000000003) < 1e-9

lab.close()
app.processEvents()
print("KALEIDO_SURFACE_QT_SMOKE=PASS")
print("LAB_BEZEL_SUPPORT=PASS")
print("ZOOM_REUSES_EMULATED_FRAMEBUFFER=PASS")
print("CFA_DISABLED_LEGACY_PIXEL_PARITY=PASS")
