"""Standalone classifier characterization and shared grayscale-inversion regressions."""
from dataclasses import replace
from io import BytesIO
import unittest
from unittest.mock import patch
from PIL import Image, ImageOps
from calibre_plugins.manganana.books.imaging.bw_dark_mode import monochrome, invert_composed
from calibre_plugins.manganana.books.imaging.image_processing import ProcessingSettings, apply_processing
from calibre_plugins.manganana.books.imaging.processing_presets import BUILTIN_PRESETS, settings_to_payload, settings_from_payload, save_user_preset, load_user_presets, user_presets_payload
from tests import test_empress_pipeline as pipeline


def blob(image, fmt='PNG'):
    out=BytesIO(); image.save(out,fmt); return out.getvalue()


class ClassifierTests(unittest.TestCase):
    def test_monochrome_variants(self):
        gray=Image.linear_gradient('L').resize((256,256))
        noise=gray.convert('RGB')
        noise.putdata([(min(255,v+2),v,max(0,v-2)) for v in gray.getdata()])
        for source in (gray,gray.convert('RGB'),blob(gray.convert('RGB'),'JPEG'),noise,
                       Image.new('RGB',(256,256),(245,241,236)),Image.new('RGB',(16,16),'black')):
            with self.subTest(source=type(source)): self.assertTrue(monochrome(source))

    def test_color_and_uncertain_tint_preserved(self):
        for color in ((190,160,115),(245,220,220),(90,190,55),(250,233,235),(16,0,0)):
            with self.subTest(color=color): self.assertFalse(monochrome(Image.new('RGB',(256,256),color)))
        for color in ('red','blue','green'):
            page=Image.new('RGB',(256,256),'white'); page.paste(color,(100,100,108,108))
            self.assertFalse(monochrome(page))

    def test_invalid_uncertain_input_and_cancellation(self):
        self.assertFalse(monochrome(b'invalid'))
        def cancel(): raise InterruptedError()
        with self.assertRaises(InterruptedError): monochrome(Image.new('L',(256,256)),cancel)
        with self.assertRaises(InterruptedError): invert_composed(Image.new('L',(2,2)),cancel)

    def test_true_inversion_values(self):
        image=Image.new('L',(5,1)); image.putdata([0,32,128,224,255])
        self.assertEqual([255,223,127,31,0],list(invert_composed(image).getdata()))

    def test_transparency_uses_visible_white_page_background(self):
        image=Image.new('RGBA',(32,32),(255,0,0,0))
        self.assertTrue(monochrome(image))
        self.assertEqual((0,0,0),invert_composed(image).getpixel((0,0)))


class DarkRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.ns = pipeline.production_namespace()

    def test_shared_renderer_inverts_color_and_gray_after_layout(self):
        for source in (Image.new('RGB', (60, 90), 'red'), Image.new('L', (60, 90), 224)):
            for kind in ('INDIVIDUAL', 'PAIRED', 'ISOLATED', 'ORIGINAL SPREAD'):
                record = {'blob': blob(source), 'size': source.size, 'ext': '.png'}
                job = {'kind': kind, 'records': (record, record) if kind == 'PAIRED' else (record,)}
                render = self.ns['render_output_page']
                for overview in (False, True):
                    for framing in (0, -40, 100):
                        options = dict(in_memory=True, overview=overview, framing=framing, gutter_px=16)
                        normal = render(job, ProcessingSettings(grayscale=True), **options)[1]
                        dark = render(job, ProcessingSettings(grayscale=True, dark_mode=True), **options)[1]
                        self.assertEqual(ImageOps.invert(normal).tobytes(), dark.tobytes())
                encoded = render(job, ProcessingSettings(grayscale=True, dark_mode=True))[1]
                detail = render(job, ProcessingSettings(grayscale=True, dark_mode=True), in_memory=True)[1]
                with Image.open(BytesIO(encoded)) as final:
                    self.assertEqual(final.size, detail.size)
                    self.assertLessEqual(abs(final.convert('L').getpixel((20, 20)) - detail.convert('L').getpixel((20, 20))), 3)
                self.assertNotIn('_bw_dark_eligible', record)

    def test_inversion_requires_explicit_grayscale(self):
        source = Image.new('RGB', (20, 30), 'red')
        self.assertEqual(source.tobytes(), apply_processing(source, ProcessingSettings(dark_mode=True)).tobytes())
        self.assertEqual(179, apply_processing(source, ProcessingSettings(grayscale=True, dark_mode=True)).getpixel((0, 0)))
        self.assertEqual(31, apply_processing(Image.new('L', (2, 2), 224), ProcessingSettings(grayscale=True, dark_mode=True)).getpixel((0, 0)))

    def test_adjustments_and_depth_follow_grayscale_inversion(self):
        source = Image.new('RGB', (32, 48)); source.putdata([(i % 256, i * 3 % 256, i * 7 % 256) for i in range(32 * 48)])
        for algorithm in ('off', 'floyd-steinberg', 'atkinson', 'sierra-lite'):
            settings = ProcessingSettings(grayscale=True, dark_mode=True, brightness=.8, contrast=1.2, gamma=.8,
                                          saturation=2, sharpness=1.1, output_depth=4, dithering=algorithm)
            expected = apply_processing(ImageOps.invert(source.convert('L')), replace(settings, dark_mode=False))
            self.assertEqual(expected.tobytes(), apply_processing(source, settings).tobytes())

    def test_preset_migrates_old_inversion_intent(self):
        payload = settings_to_payload(ProcessingSettings(dark_mode=True, saturation=1.7))
        settings = settings_from_payload(payload)
        self.assertTrue(settings.grayscale and settings.dark_mode)
        self.assertEqual(1.7, settings.saturation)
        for preset in BUILTIN_PRESETS:
            old = settings_to_payload(preset.settings); del old['dark_mode']
            self.assertEqual(preset.settings, settings_from_payload(old))

    def test_preview_simulation_receives_inverted_grayscale(self):
        from types import SimpleNamespace
        for color in ((224, 224, 224), (255, 0, 0)):
            image = Image.new('RGB', (80, 120), color)
            sample = {'layout': 'original_pages', 'records': ({'image': image, 'size': image.size, 'ext': '.png'},)}
            seen = []
            def simulate(page, profile, layout, **kwargs):
                seen.append(page.getpixel((0, 0)))
                return SimpleNamespace(image=page, profile_id=profile, display_name='Test', screen_size=page.size, layout=layout)
            with patch.dict(self.ns, render_emulated_detail=simulate):
                worker = self.ns['ProcessingPreviewWorker'](sample, 'rtl', ProcessingSettings(grayscale=True, dark_mode=True),
                                                           detail_page=1, screen_emulation_id='test')
                worker.run()
            self.assertFalse(worker.failed.calls)
            self.assertIn('inversion applied', worker.ready.calls[0][0]['dark_status'])
            self.assertEqual([255 - image.convert('L').getpixel((0, 0))], seen)
