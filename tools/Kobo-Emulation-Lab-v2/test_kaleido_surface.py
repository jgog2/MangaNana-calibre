import json
import hashlib
from pathlib import Path
import sys
import time
import unittest

from PIL import Image


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from kaleido_surface import (  # noqa: E402
    LANDSCAPE, PORTRAIT, apply_cfa_modulation, apply_kaleido_surface,
    apply_micro_grain, cfa_index, diagnostic_image, merge_lab_profile,
    normalized_surface,
)


class KaleidoSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defaults = json.loads(
            (HERE / "kobo_libra_colour_lab_profile.json").read_text(encoding="utf-8"))

    def test_exact_canonical_portrait_3x3_layout(self):
        self.assertEqual(
            ((0, 1, 2), (2, 0, 1), (1, 2, 0)),
            tuple(tuple(cfa_index(x, y, PORTRAIT) for x in range(3)) for y in range(3)),
        )

    def test_mirror_disabled_preserves_existing_handedness(self):
        for y in range(12):
            for x in range(12):
                self.assertEqual((x - y) % 3,
                                 cfa_index(x, y, PORTRAIT, mirror_cfa_horizontal=False))
        for x, y in ((0, 0), (1, 0), (45, 78), (1679, 1263)):
            expected = (y - (1679 - x)) % 3
            self.assertEqual(expected, cfa_index(
                x, y, LANDSCAPE, 1680, mirror_cfa_horizontal=False))
        source = Image.frombytes(
            "RGB", (17, 13), bytes((index * 37 + 11) % 256 for index in range(17 * 13 * 3)))
        pixels = apply_cfa_modulation(source, .18, LANDSCAPE).tobytes()
        self.assertEqual("1179ba45a1387aafc94b18ecadd6ca9671bffeadd03dbf95cdf95bd6c83cc2bf",
                         hashlib.sha256(pixels).hexdigest())

    def test_mirrored_portrait_is_horizontal_panel_reflection(self):
        width = 1264
        for x, y in ((0, 0), (1, 2), (631, 839), (1263, 1679)):
            self.assertEqual(
                cfa_index(width - 1 - x, y, PORTRAIT),
                cfa_index(x, y, PORTRAIT, 1680, True, width),
            )

    def test_mirrored_landscape_rotates_and_reverses_diagonal(self):
        width, height = 1264, 1680
        for x, y in ((0, 0), (1, 2), (839, 631), (1679, 1263)):
            self.assertEqual(
                cfa_index(y, height - 1 - x, PORTRAIT, height, True, width),
                cfa_index(x, y, LANDSCAPE, height, True, width),
            )
        # Current landscape is constant along /; mirrored is constant along \.
        self.assertEqual(cfa_index(20, 20, LANDSCAPE),
                         cfa_index(21, 19, LANDSCAPE))
        self.assertEqual(cfa_index(20, 20, LANDSCAPE, 1680, True),
                         cfa_index(21, 21, LANDSCAPE, 1680, True))
        self.assertNotEqual(cfa_index(20, 20, LANDSCAPE),
                            cfa_index(21, 21, LANDSCAPE))

    def test_complete_tile_is_mean_preserving_per_channel(self):
        source = Image.new("RGB", (3, 3), (30, 60, 90))
        result = apply_cfa_modulation(source, 0.20, PORTRAIT)
        pixels = tuple(result.get_flattened_data())
        means = tuple(sum(pixel[channel] for pixel in pixels) / 9
                      for channel in range(3))
        self.assertEqual((30.0, 60.0, 90.0), means)

    def test_disabled_surface_and_zero_strength_are_exact_noops(self):
        source = Image.new("RGB", (12, 9), (40, 80, 120))
        self.assertIs(source, apply_kaleido_surface(source, {}, PORTRAIT))
        self.assertIs(source, apply_cfa_modulation(source, 0.0, PORTRAIT))
        self.assertIs(source, apply_micro_grain(source, 0.0, PORTRAIT))
        self.assertEqual(source.tobytes(), apply_kaleido_surface(
            source, {"cfa_enabled": False, "cfa_strength": .2,
                     "micro_grain_enabled": False, "grain_strength": 3},
            PORTRAIT).tobytes())

    def test_cfa_and_grain_are_deterministic(self):
        source = Image.new("RGB", (73, 61), (90, 110, 130))
        settings = {"cfa_enabled": True, "cfa_strength": .16,
                    "micro_grain_enabled": True, "grain_strength": 2.0}
        first = apply_kaleido_surface(source, settings, PORTRAIT)
        second = apply_kaleido_surface(source, settings, PORTRAIT)
        self.assertEqual(first.tobytes(), second.tobytes())

    def test_source_page_does_not_change_cfa_phase(self):
        first = apply_cfa_modulation(Image.new("RGB", (9, 9), (40, 40, 40)), .2, PORTRAIT)
        second = apply_cfa_modulation(Image.new("RGB", (9, 9), (80, 80, 80)), .2, PORTRAIT)
        for y in range(9):
            for x in range(9):
                self.assertEqual(first.getpixel((x, y)).index(max(first.getpixel((x, y)))),
                                 second.getpixel((x, y)).index(max(second.getpixel((x, y)))))
                self.assertEqual(cfa_index(x, y, PORTRAIT),
                                 first.getpixel((x, y)).index(max(first.getpixel((x, y)))))

    def test_landscape_is_canonical_panel_rotated_clockwise(self):
        portrait_height = 1680
        for x, y in ((0, 0), (1, 0), (45, 78), (1679, 1263)):
            self.assertEqual(
                cfa_index(y, portrait_height - 1 - x, PORTRAIT, portrait_height),
                cfa_index(x, y, LANDSCAPE, portrait_height),
            )
        self.assertNotEqual(
            tuple(cfa_index(x, 0, PORTRAIT) for x in range(3)),
            tuple(cfa_index(x, 0, LANDSCAPE, portrait_height) for x in range(3)),
        )

    def test_micro_grain_is_achromatic_and_deterministic(self):
        source = Image.new("RGB", (97, 83), (128, 128, 128))
        first = apply_micro_grain(source, 3.0, LANDSCAPE)
        second = apply_micro_grain(source, 3.0, LANDSCAPE)
        self.assertEqual(first.tobytes(), second.tobytes())
        pixels = tuple(first.get_flattened_data())
        self.assertTrue(all(r == g == b for r, g, b in pixels))
        self.assertGreater(len(set(pixels)), 1)

    def test_handedness_setting_does_not_change_grain(self):
        source = Image.new("RGB", (97, 83), (128, 128, 128))
        base = {"cfa_enabled": False, "micro_grain_enabled": True, "grain_strength": 3.0}
        current = apply_kaleido_surface(source, dict(base, mirror_cfa_horizontal=False), LANDSCAPE)
        mirrored = apply_kaleido_surface(source, dict(base, mirror_cfa_horizontal=True), LANDSCAPE)
        self.assertEqual(current.tobytes(), mirrored.tobytes())

    def test_old_json_loads_disabled_and_preserves_softness(self):
        old = json.loads((HERE / "baseline_tuned_profile.json").read_text(encoding="utf-8"))
        merged = merge_lab_profile(old, self.defaults)
        self.assertEqual(0.41000000000000003, merged["spatial"]["softness_radius"])
        self.assertEqual({"cfa_enabled": False, "cfa_strength": 0.0,
                          "mirror_cfa_horizontal": False,
                          "micro_grain_enabled": False, "grain_strength": 0.0},
                         normalized_surface(merged))
        self.assertIn("frame", merged)
        self.assertIn("hue_corrections", merged)

    def test_new_json_round_trips_experimental_values(self):
        profile = json.loads(json.dumps(self.defaults))
        expected = {"cfa_enabled": True, "cfa_strength": .25,
                    "mirror_cfa_horizontal": True,
                    "micro_grain_enabled": True, "grain_strength": 2.7}
        profile["kaleido_surface"] = expected
        loaded = merge_lab_profile(json.loads(json.dumps(profile)), self.defaults)
        self.assertEqual(expected, normalized_surface(loaded))

    def test_schema_three_without_handedness_defaults_current(self):
        profile = json.loads(json.dumps(self.defaults))
        profile["kaleido_surface"].pop("mirror_cfa_horizontal")
        self.assertFalse(normalized_surface(profile)["mirror_cfa_horizontal"])

    def test_source_is_never_mutated(self):
        source = diagnostic_image((180, 240))
        before = source.tobytes()
        apply_kaleido_surface(
            source, {"cfa_enabled": True, "cfa_strength": .25,
                     "micro_grain_enabled": True, "grain_strength": 3.0},
            PORTRAIT)
        self.assertEqual(before, source.tobytes())

    def test_full_landscape_framebuffer_performance(self):
        source = Image.new("RGB", (1680, 1264), (120, 140, 160))
        started = time.perf_counter()
        result = apply_kaleido_surface(
            source, {"cfa_enabled": True, "cfa_strength": .16,
                     "micro_grain_enabled": True, "grain_strength": 2.0},
            LANDSCAPE)
        elapsed = time.perf_counter() - started
        self.assertEqual(source.size, result.size)
        started = time.perf_counter()
        warm = apply_kaleido_surface(
            source, {"cfa_enabled": True, "cfa_strength": .16,
                     "micro_grain_enabled": True, "grain_strength": 2.0},
            LANDSCAPE)
        warm_elapsed = time.perf_counter() - started
        self.assertEqual(result.tobytes(), warm.tobytes())
        print(f"KALEIDO_SURFACE_LANDSCAPE_SECONDS={elapsed:.3f}")
        print(f"KALEIDO_SURFACE_LANDSCAPE_WARM_SECONDS={warm_elapsed:.3f}")


if __name__ == "__main__":
    unittest.main()
