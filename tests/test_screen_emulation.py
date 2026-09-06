from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import time
import unittest

from PIL import Image, ImageDraw

import screen_emulation as se
from image_processing import ProcessingSettings


ROOT = Path(__file__).resolve().parents[1]
def synthetic(size=(1680, 1264)):
    image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, min(300, size[0] - 1), min(300, size[1] - 1)), fill=(255, 0, 0))
    draw.rectangle((size[0] // 3, 0, (size[0] * 2) // 3, min(300, size[1] - 1)), fill=(0, 168, 107))
    draw.line((0, size[1] - 1, size[0] - 1, 0), fill=(0, 0, 255), width=3)
    return image


class ScreenEmulationTests(unittest.TestCase):
    def test_frozen_kobo_profile(self):
        p = se.KOBO_LIBRA_COLOUR
        self.assertEqual('kobo_libra_colour', p.profile_id)
        self.assertEqual('Kobo Libra Colour', p.display_name)
        self.assertEqual((1264, 1680), p.native_portrait)
        self.assertEqual((1680, 1264), p.native_landscape)
        self.assertEqual((300, 150, 100, 0),
                         (p.bw_ppi, p.color_ppi, p.frontlight_percent, p.comfortlight_warmth))
        self.assertEqual((62, 232, 1.05), (p.black_floor, p.white_ceiling, p.gamma))
        self.assertEqual((.22, 1.03, 1., .92),
                         (p.saturation, p.red_gain, p.green_gain, p.blue_gain))
        self.assertEqual(.10, se.KOBO_PANEL_SOFTNESS_RADIUS)
        self.assertEqual((50, .10, False, 25.),
                         (p.chroma_resolution_percent, p.softness_radius,
                          p.hue_corrections_enabled, p.hue_saturation_gate_percent))
        self.assertEqual(tuple((hue, 0., 0.) for hue in (0, 30, 60, 120, 180, 240, 270, 300)),
                         tuple((a.hue_degrees, a.lightness_percent, a.saturation_percent)
                               for a in p.hue_anchors))
        self.assertEqual((True, .10, True, True, 1.),
                         (p.cfa_enabled, p.cfa_strength, p.mirror_cfa_horizontal,
                          p.micro_grain_enabled, p.grain_strength))

    def test_final_profile_matches_authoritative_lab_json(self):
        payload = json.loads((ROOT / 'tools' / 'Kobo-Emulation-Lab-v2' /
                              'final_kobo_libra_colour_tuned_v2.json').read_text(encoding='utf-8'))
        p = se.KOBO_LIBRA_COLOUR
        self.assertFalse(payload['provisional'])
        self.assertEqual(tuple(payload['native_portrait']), p.native_portrait)
        self.assertEqual(tuple(payload['native_landscape']), p.native_landscape)
        self.assertEqual((payload['bw_ppi'], payload['color_ppi']), (p.bw_ppi, p.color_ppi))
        self.assertEqual((payload['tone']['black_floor'], payload['tone']['white_ceiling'],
                          payload['tone']['gamma']), (p.black_floor, p.white_ceiling, p.gamma))
        self.assertEqual((payload['color']['saturation'], payload['color']['red_gain'],
                          payload['color']['green_gain'], payload['color']['blue_gain']),
                         (p.saturation, p.red_gain, p.green_gain, p.blue_gain))
        self.assertEqual((payload['spatial']['chroma_resolution_percent'],
                          payload['spatial']['softness_radius']),
                         (p.chroma_resolution_percent, p.softness_radius))
        surface = payload['kaleido_surface']
        self.assertEqual((surface['cfa_enabled'], surface['cfa_strength'],
                          surface['mirror_cfa_horizontal'], surface['micro_grain_enabled'],
                          surface['grain_strength']),
                         (p.cfa_enabled, p.cfa_strength, p.mirror_cfa_horizontal,
                          p.micro_grain_enabled, p.grain_strength))

    def test_cfa_layout_mirrored_handedness_and_rotation(self):
        expected = ((0, 1, 2), (2, 0, 1), (1, 2, 0))
        self.assertEqual(expected, tuple(tuple(se.cfa_index(
            x, y, se.PORTRAIT_LAYOUT, mirror_horizontal=False) for x in range(3))
            for y in range(3)))
        for x, y in ((0, 0), (1, 2), (631, 839), (1263, 1679)):
            self.assertEqual(
                se.cfa_index(1263 - x, y, se.PORTRAIT_LAYOUT, mirror_horizontal=False),
                se.cfa_index(x, y, se.PORTRAIT_LAYOUT),
            )
        for x, y in ((0, 0), (1, 2), (839, 631), (1679, 1263)):
            self.assertEqual(
                se.cfa_index(y, 1679 - x, se.PORTRAIT_LAYOUT),
                se.cfa_index(x, y, se.LANDSCAPE_LAYOUT),
            )
        self.assertEqual(se.cfa_index(20, 20, se.LANDSCAPE_LAYOUT),
                         se.cfa_index(21, 21, se.LANDSCAPE_LAYOUT))

    def test_cfa_mean_phase_and_grain_are_deterministic(self):
        p = replace(se.KOBO_LIBRA_COLOUR, cfa_strength=.2, micro_grain_enabled=False)
        source = Image.new('RGB', (3, 3), (30, 60, 90))
        result = se.apply_cfa_modulation(source, p, se.PORTRAIT_LAYOUT)
        pixels = tuple(result.get_flattened_data())
        self.assertEqual((30., 60., 90.), tuple(
            sum(pixel[channel] for pixel in pixels) / 9 for channel in range(3)))
        pages = (Image.new('RGB', (12, 9), (40, 40, 40)),
                 Image.new('RGB', (12, 9), (80, 80, 80)))
        outputs = [se.apply_cfa_modulation(page, p, se.PORTRAIT_LAYOUT) for page in pages]
        for y in range(9):
            for x in range(12):
                classes = [image.getpixel((x, y)).index(max(image.getpixel((x, y))))
                           for image in outputs]
                self.assertEqual([se.cfa_index(x, y, se.PORTRAIT_LAYOUT)] * 2, classes)
        grain_profile = replace(p, cfa_enabled=False, micro_grain_enabled=True, grain_strength=1.)
        gray = Image.new('RGB', (97, 83), (128, 128, 128))
        first = se.apply_micro_grain(gray, grain_profile, se.LANDSCAPE_LAYOUT)
        second = se.apply_micro_grain(gray, grain_profile, se.LANDSCAPE_LAYOUT)
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertTrue(all(r == g == b for r, g, b in first.get_flattened_data()))

    def test_production_surface_is_pixel_identical_to_accepted_lab_algorithm(self):
        path = ROOT / 'tools' / 'Kobo-Emulation-Lab-v2' / 'kaleido_surface.py'
        spec = importlib.util.spec_from_file_location('accepted_kaleido_surface', path)
        lab = importlib.util.module_from_spec(spec); spec.loader.exec_module(lab)
        source = synthetic((117, 83))
        p = se.KOBO_LIBRA_COLOUR
        production = se.apply_micro_grain(
            se.apply_cfa_modulation(source, p, se.LANDSCAPE_LAYOUT),
            p, se.LANDSCAPE_LAYOUT)
        accepted = lab.apply_kaleido_surface(
            source, {
                'cfa_enabled': True, 'cfa_strength': .10,
                'mirror_cfa_horizontal': True,
                'micro_grain_enabled': True, 'grain_strength': 1.,
            }, lab.LANDSCAPE, portrait_height=1680, portrait_width=1264)
        self.assertEqual(accepted.tobytes(), production.tobytes())

    def test_layout_not_source_aspect_controls_orientation(self):
        landscape_source = synthetic((900, 500))
        portrait = se.render_emulated_detail(
            landscape_source, se.KOBO_LIBRA_COLOUR_PROFILE_ID,
            se.PORTRAIT_LAYOUT)
        self.assertEqual((1264, 1680), portrait.screen_size)
        self.assertEqual((1264, 1680), portrait.image.size)
        portrait_source = synthetic((500, 900))
        landscape = se.render_emulated_detail(
            portrait_source, se.KOBO_LIBRA_COLOUR_PROFILE_ID,
            se.LANDSCAPE_LAYOUT)
        self.assertEqual((1680, 1264), landscape.screen_size)
        self.assertEqual((1680, 1264), landscape.image.size)

    def test_render_modes_source_immutability_and_native_geometry(self):
        source = synthetic()
        before = source.tobytes()
        result = se.render_emulated_detail(
            source, se.KOBO_LIBRA_COLOUR_PROFILE_ID,
            se.LANDSCAPE_LAYOUT)
        self.assertEqual(before, source.tobytes())
        self.assertEqual('RGB', result.image.mode)
        self.assertEqual((1680, 1264), result.screen_size)
        screen = se.emulate_screen(source, se.KOBO_LIBRA_COLOUR, se.LANDSCAPE_LAYOUT)
        self.assertEqual(('RGB', (1680, 1264)), (screen.mode, screen.size))

    def test_higher_resolution_source_is_collapsed_to_final_framebuffer(self):
        source = synthetic((2200, 1800))
        result = se.render_emulated_detail(
            source, se.KOBO_LIBRA_COLOUR_PROFILE_ID, se.LANDSCAPE_LAYOUT)
        self.assertEqual((1680, 1264), result.image.size)
        self.assertEqual(result.screen_size, result.image.size)
        self.assertFalse(hasattr(result, 'source_image'))
        self.assertFalse(hasattr(result, 'composite_size'))

    def test_contain_preserves_arbitrary_page_without_crop(self):
        page = Image.new('RGB', (600, 1800), (10, 20, 30))
        contained = se.contain_on_canvas(page, (1264, 1680))
        self.assertEqual((1264, 1680), contained.size)
        bbox = Image.eval(contained, lambda value: 255 - value).getbbox()
        self.assertIsNotNone(bbox)
        self.assertLessEqual(bbox[2] - bbox[0], 560)
        self.assertEqual(1680, bbox[3] - bbox[1])

    def test_cancellation_checked_between_transform_phases(self):
        calls = []
        with self.assertRaises(InterruptedError):
            se.render_emulated_detail(
                synthetic((120, 90)), se.KOBO_LIBRA_COLOUR_PROFILE_ID,
                se.LANDSCAPE_LAYOUT,
                check_cancel=lambda: (calls.append(True),
                                      (_ for _ in ()).throw(InterruptedError()))[1]
                if len(calls) >= 3 else calls.append(True),
            )
        self.assertGreaterEqual(len(calls), 3)

    def test_unknown_profile_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, 'Unknown screen emulation profile'):
            se.profile_for('not-a-profile')

    def test_selected_page_timing_and_processing_firewall(self):
        source = synthetic()
        started = time.perf_counter()
        result = se.render_emulated_detail(
            source, se.KOBO_LIBRA_COLOUR_PROFILE_ID,
            se.LANDSCAPE_LAYOUT)
        elapsed = time.perf_counter() - started
        self.assertEqual((1680, 1264), result.image.size)
        self.assertGreater(elapsed, 0)
        self.assertNotIn('screen', ProcessingSettings.__dataclass_fields__)
        self.assertNotIn('emulation', ProcessingSettings.__dataclass_fields__)
        print(f'SCREEN_EMULATION_SELECTED_PAGE_SECONDS={elapsed:.3f}')

    def test_signature_preset_output_and_package_firewalls(self):
        main=(ROOT/'main.py').read_text(encoding='utf-8')
        current=main[main.index('def current_signature(self):'):main.index('def _clear_preview_state(')]
        live=main[main.index('def _live_preview_signature_value(self):'):main.index('def _reset_live_preview(')]
        download=main[main.index('class DownloadWorker(QThread):'):main.index('class PreviewWorker(QThread):')]
        presets=(ROOT/'processing_presets.py').read_text(encoding='utf-8')
        self.assertNotIn('screen_emulation',current)
        self.assertNotIn('screen_emulation',live)
        self.assertNotIn('screen_emulation',download)
        self.assertNotIn('screen_emulation',presets)
        build=(ROOT/'tools'/'build_plugin.py').read_text(encoding='utf-8')
        self.assertIn('"screen_emulation.py"',build)
        self.assertNotIn('kobo-libra-colour-frame',build)
        self.assertNotIn('kobo-libra-colour-frame',main)
        self.assertFalse((ROOT/'images'/'kobo-libra-colour-frame.png').exists())


if __name__ == '__main__':
    unittest.main()
