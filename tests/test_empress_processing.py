"""Deterministic processing contracts; no Calibre, network, or timing waits."""
from io import BytesIO
import unittest
from unittest.mock import patch
from PIL import Image, ImageEnhance, ImageStat

from image_processing import ProcessingSettings, apply_processing, process_page_blob
import image_processing
from preview_render_state import RenderOwnership
from window_geometry import DEFAULT_WINDOW_FRAME, choose_window_size


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (3, 1))
        self.image.putdata([(45, 60, 75), (100, 125, 150), (175, 190, 205)])

    def test_neutral_is_identity_including_bytes(self):
        self.assertIs(self.image, apply_processing(self.image, ProcessingSettings()))
        for fmt, ext in [('JPEG', '.jpg'), ('PNG', '.png'), ('WEBP', '.webp')]:
            out = BytesIO(); self.image.save(out, fmt)
            blob = out.getvalue()
            self.assertIs(blob, process_page_blob(blob, ext, ProcessingSettings()))

    def test_contrast_spread(self):
        def variance(factor):
            return sum(ImageStat.Stat(apply_processing(self.image, ProcessingSettings(contrast=factor))).var)
        self.assertLess(variance(.5), variance(1))
        self.assertGreater(variance(1.5), variance(1))

    def test_saturation_chroma(self):
        def chroma(factor):
            im = apply_processing(self.image, ProcessingSettings(saturation=factor))
            return sum(max(p)-min(p) for p in im.getdata())
        self.assertLess(chroma(.2), chroma(1))
        self.assertGreater(chroma(3), chroma(1))

    def test_saturation_supported_boundaries(self):
        for factor in (.2, 1., 2., 2.5, 3.):
            self.assertEqual(factor, ProcessingSettings(saturation=factor).saturation)
        with self.assertRaises(ValueError):
            ProcessingSettings(saturation=3.01)

    def test_reciprocal_gamma_slider_right_brightens(self):
        im = Image.new('L', (1, 1), 128)
        self.assertEqual(apply_processing(im, ProcessingSettings(gamma=.5)).getpixel((0, 0)), 64)
        self.assertEqual(apply_processing(im, ProcessingSettings()).getpixel((0, 0)), 128)
        self.assertEqual(apply_processing(im, ProcessingSettings(gamma=2)).getpixel((0, 0)), 181)

    def test_order_is_gamma_contrast_saturation(self):
        settings = ProcessingSettings(1.3, .65, .8)
        lut = [round(255*(i/255)**(1/.8)) for i in range(256)]
        expected = ImageEnhance.Color(ImageEnhance.Contrast(self.image.point(lut*3)).enhance(1.3)).enhance(.65)
        self.assertEqual(expected.tobytes(), apply_processing(self.image, settings).tobytes())

    def test_alpha_and_modes(self):
        for mode in ('RGB', 'RGBA', 'L', 'LA', 'P'):
            im = self.image.convert(mode)
            if mode in ('RGBA', 'LA'): im.putalpha(87)
            if mode == 'P': im.info['transparency'] = 0
            before = im.tobytes()
            result = apply_processing(im, ProcessingSettings(1.2, .5, .8))
            self.assertEqual(im.size, result.size)
            self.assertEqual(before, im.tobytes())
            if mode in ('RGBA', 'LA'):
                self.assertEqual(im.getchannel('A').tobytes(), result.getchannel('A').tobytes())
            if mode == 'P': self.assertEqual(result.mode, 'RGBA')

    def test_processed_encodings_are_valid_and_keep_format(self):
        for fmt, ext in [('JPEG', '.jpg'), ('PNG', '.png'), ('WEBP', '.webp')]:
            source = BytesIO(); self.image.save(source, fmt)
            result = process_page_blob(source.getvalue(), ext, ProcessingSettings(gamma=.5))
            with Image.open(BytesIO(result)) as im:
                self.assertEqual(fmt, im.format)
                self.assertEqual(self.image.size, im.size)

    def test_settings_reject_invalid_ranges(self):
        self.assertEqual(3, ProcessingSettings(saturation=3).saturation)
        for kwargs in ({'contrast':0}, {'saturation':0}, {'saturation':3.01},
                       {'gamma':float('nan')}, {'gamma':3}):
            with self.assertRaises(ValueError): ProcessingSettings(**kwargs)

    def test_grayscale_off_identity_on_equal_channels_and_ignores_saturation(self):
        self.assertIs(self.image,apply_processing(self.image,ProcessingSettings(grayscale=False)))
        gray=apply_processing(self.image,ProcessingSettings(saturation=2,grayscale=True))
        self.assertEqual(self.image.convert('L').tobytes(),gray.tobytes())
        self.assertTrue(all(r==g==b for r,g,b in gray.convert('RGB').getdata()))

    def test_brightness_multiplicative_black_clipping_and_modes(self):
        for mode in ('L','RGB'):
            im=Image.new('L',(4,1)); im.putdata([0,64,128,240]); im=im.convert(mode)
            for factor,expected in ((.25,[0,16,32,60]),(.5,[0,32,64,120]),
                                    (1,[0,64,128,240]),(1.5,[0,96,192,255]),(2,[0,128,255,255])):
                result=apply_processing(im,ProcessingSettings(brightness=factor))
                self.assertEqual(expected,list(result.convert('L').getdata()))
                self.assertEqual(ImageEnhance.Brightness(im).enhance(factor).tobytes(),result.tobytes())
                if factor==1: self.assertIs(im,result)

    def test_sharpness_softens_sharpens_and_is_deterministic(self):
        for mode in ('L','RGB'):
            im=Image.new('L',(7,7),80); im.putpixel((3,3),160); im=im.convert(mode)
            for factor in (0,1,2):
                settings=ProcessingSettings(sharpness=factor)
                result=apply_processing(im,settings)
                self.assertEqual(ImageEnhance.Sharpness(im).enhance(factor).tobytes(),result.tobytes())
                self.assertEqual(result.tobytes(),apply_processing(im,settings).tobytes())
                center=result.convert('L').getpixel((3,3))
                if factor==0: self.assertLess(center,160)
                elif factor==2: self.assertGreater(center,160)
                else: self.assertIs(im,result)

    def test_neutral_enhancements_are_skipped_even_with_other_processing(self):
        with patch.object(ImageEnhance,'Brightness',side_effect=AssertionError('unnecessary brightness')), \
             patch.object(ImageEnhance,'Sharpness',side_effect=AssertionError('unnecessary sharpness')):
            apply_processing(self.image,ProcessingSettings())
            apply_processing(self.image,ProcessingSettings(gamma=2,output_depth=4))
            apply_processing(self.image,ProcessingSettings(),working_ceiling=(2,2))

    def test_adjustments_validate_and_are_immutable_signature_fields(self):
        from dataclasses import FrozenInstanceError
        for name,low in (('brightness',.25),('sharpness',0)):
            for value in (low-.01,2.01,float('nan'),float('inf')):
                with self.assertRaises(ValueError): ProcessingSettings(**{name:value})
            settings=ProcessingSettings(**{name:low})
            self.assertNotEqual(settings,ProcessingSettings()); self.assertFalse(settings.neutral)
            with self.assertRaises(FrozenInstanceError): setattr(settings,name,1)
        self.assertNotIn('resolution',ProcessingSettings.__dataclass_fields__)
        with self.assertRaises(TypeError): ProcessingSettings(resolution=.75)

    def test_shared_order_before_depth_and_diffusion(self):
        im=Image.new('RGB',(40,20)); im.putdata([(i%256,(i*3)%256,(i*7)%256) for i in range(800)])
        for grayscale in (False,True):
            settings=ProcessingSettings(1.3,.65,.8,grayscale,brightness=1.5,sharpness=2,
                                        output_depth=4,dithering='atkinson')
            expected=im.convert('L' if grayscale else 'RGB')
            expected=ImageEnhance.Brightness(expected).enhance(1.5)
            expected=expected.point([round(255*(i/255)**(1/.8)) for i in range(256)]*len(expected.getbands()))
            expected=ImageEnhance.Contrast(expected).enhance(1.3)
            if not grayscale: expected=ImageEnhance.Color(expected).enhance(.65)
            expected=ImageEnhance.Sharpness(expected).enhance(2)
            quantize=image_processing.quantize
            with patch.object(image_processing,'quantize',wraps=quantize) as depth:
                actual=apply_processing(im,settings)
            self.assertEqual(expected.tobytes(),depth.call_args.args[0].tobytes())
            self.assertEqual((4,'atkinson',1.),depth.call_args.args[1:])
            self.assertEqual(quantize(expected,4,'atkinson',1).tobytes(),actual.tobytes())

    def test_adjusted_grayscale_alpha_and_encodings_preserve_dimensions(self):
        rgba=self.image.resize((20,10)).convert('RGBA'); rgba.putalpha(87)
        result=apply_processing(rgba,ProcessingSettings(grayscale=True,brightness=1.5,sharpness=2))
        self.assertEqual('LA',result.mode); self.assertEqual((20,10),result.size)
        self.assertEqual({87},set(result.getchannel('A').getdata()))
        for fmt,ext in (('JPEG','.jpg'),('PNG','.png'),('WEBP','.webp')):
            blob=BytesIO(); self.image.resize((20,10)).save(blob,fmt)
            result=process_page_blob(blob.getvalue(),ext,ProcessingSettings(grayscale=True,brightness=1.5,sharpness=2))
            with Image.open(BytesIO(result)) as im:
                self.assertEqual(fmt,im.format); self.assertEqual((20,10),im.size)


class RenderOwnershipTests(unittest.TestCase):
    def test_latest_only_and_sample_invalidation(self):
        state = RenderOwnership()
        a = state.advance()
        b = state.advance()
        self.assertFalse(state.accepts(a))
        self.assertTrue(state.accepts(b))
        state.advance()  # sample replacement, layout change, or closure
        self.assertFalse(state.accepts(b))


class WindowSizeTests(unittest.TestCase):
    def test_fresh_target_subtracts_actual_frame_margins(self):
        self.assertEqual((1780, 1107), DEFAULT_WINDOW_FRAME)
        self.assertEqual((1764, 1068), choose_window_size(None, (2400, 1400), (16, 39)))

    def test_saved_client_dimensions_preserved(self):
        self.assertEqual((1450, 850), choose_window_size((1450, 850), (2400, 1400), (16, 39)))

    def test_small_desktop_fits_and_preserves_frame_ratio(self):
        w, h = choose_window_size(None, (1024, 700), (16, 39))
        self.assertLessEqual(w+16, 1024)
        self.assertLessEqual(h+39, 700)
        self.assertAlmostEqual((w+16)/(h+39), 1780/1107, delta=.003)

    def test_invalid_saved_size_uses_default(self):
        self.assertEqual(choose_window_size(None, (2000, 1400)), choose_window_size(('bad', -5), (2000, 1400)))
