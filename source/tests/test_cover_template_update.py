"""Cover-specific updated asset, glyph, bounds and legibility contracts."""
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image,ImageChops,ImageDraw
from calibre_plugins.manganana.books.imaging import cover_rendering as c

ROOT=Path(__file__).resolve().parents[1]
class UpdatedCoverTests(unittest.TestCase):
    def test_updated_assets_are_exact_supplied_files(self):
        import hashlib
        expected={'background.png':'b8f77743d3d095d7e6fb90db66ddf3a5ee004fe2233dd21c8d1a119a12535ea2',
            'stamp.png':'ad453178f6b2b3dffeb2c35a359783239179ef6835aa3316f41a5562ae7e6688',
            'BebasNeue-Regular.ttf':'8c6b9d4587002e47891b0d7dd66e37b5ecb6c61d0d571144d9e7dce03b6661f2',
            'anchor.png':'673328bd389f629286c63d46d731be45d60ed1fa9cdba88fa6d5fdabf0ade660',
            'OFL.txt':'72082f6cb4d04be2ecf7cc7d9e1e7d73787f0af8a5a278a47cade70c16b78341'}
        for name,digest in expected.items():
            self.assertEqual(digest,hashlib.sha256((ROOT/'assets/covers'/name).read_bytes()).hexdigest())

    def test_no_anchor_resource_is_read(self):
        original=c._art;calls=[]
        def art(name):
            calls.append(name)
            self.assertNotEqual('anchor.png',name)
            return original(name)
        with patch.object(c,'_art',art):c.render_cover(mode='generate',title='Berserk',volume=1)
        self.assertEqual(['background.png','stamp.png'],calls)
        self.assertTrue((ROOT/'assets/covers/anchor.png').exists())

    def test_full_stamp_reaches_right_edge_without_clipping(self):
        result=Image.open(BytesIO(c.render_cover(mode='generate',title='Berserk'))).convert('RGB')
        self.assertEqual(880,c.STRIP_X+c.STAMP_SIZE[0])
        expected=c._art('stamp.png').convert('RGB')
        self.assertIsNone(ImageChops.difference(expected,result.crop((c.STRIP_X,0,880,1200))).getbbox())

    def test_title_bounds_centering_and_script_coverage(self):
        for text in ('Berserk','One Piece',"JoJo's Bizarre Adventure: Part 7 - Steel Ball Run (Official Colored Edition)",
                'A long title '*60,'UnbrokenTitle'*60,''):
            with self.subTest(title=ascii(text[:50])):
                block,font,spacing,bbox=c.title_layout(c.cover_title(text))
                self.assertGreaterEqual(font.size,38)
                self.assertLessEqual(bbox[2]-bbox[0],c.TITLE_BOX[2]-c.TITLE_BOX[0]-8)
                self.assertLessEqual(bbox[3]-bbox[1],c.TITLE_BOX[3]-c.TITLE_BOX[1]-8)
                self.assertTrue(c._has_title_glyphs(font,block))
                if 'long title' in text or 'Unbroken' in text:self.assertTrue(block.endswith('...'))
                transparent=Image.new('RGBA',c.CANVAS_SIZE)
                c._draw_title(transparent,c.cover_title(text))
                # Solid text/outline pixels, excluding the faint shadow.
                pixels=transparent.getchannel('A').point(lambda a:255 if a>200 else 0)
                bounds=pixels.getbbox();self.assertIsNotNone(bounds)
                self.assertAlmostEqual((bounds[0]+bounds[2])/2,(c.TITLE_BOX[0]+c.TITLE_BOX[2])/2,delta=2)
                self.assertAlmostEqual((bounds[1]+bounds[3])/2,(c.TITLE_BOX[1]+c.TITLE_BOX[3])/2,delta=2)
                self.assertGreaterEqual(bounds[0],c.TITLE_BOX[0]);self.assertLessEqual(bounds[2],c.TITLE_BOX[2])
                self.assertGreaterEqual(bounds[1],c.TITLE_BOX[1]);self.assertLessEqual(bounds[3],c.TITLE_BOX[3])

    def test_japanese_fallback_when_a_compatible_font_is_installed(self):
        for text in ('\u9032\u6483\u306e\u5de8\u4eba', '\u30d9\u30eb\u30bb\u30eb\u30af Berserk'):
            block,font,_,bounds=c.title_layout(text)
            if not c._has_title_glyphs(font,block):
                self.skipTest('No compatible Japanese system font is installed')
            self.assertTrue(c._title_font_path(text))
            self.assertLessEqual(bounds[2]-bounds[0],592)
            self.assertLessEqual(bounds[3]-bounds[1],237)

    def test_background_unchanged_below_title(self):
        blob=c.render_cover(mode='generate',title='A long title '*30)
        result=Image.open(BytesIO(blob)).convert('RGB')
        bg=c._art('background.png').convert('RGB')
        region=(0,460,c.STRIP_X,1200)
        self.assertIsNone(ImageChops.difference(result.crop(region),bg.crop(region)).getbbox())

    def test_oversized_title_only_probes_ceiling_and_floor(self):
        with patch.object(c, '_font', wraps=c._font) as font:
            block, selected, _, _ = c.title_layout('UnbrokenTitle' * 60)
        self.assertEqual([114, 38], [call.args[0] for call in font.call_args_list if call.args[0] >= 38])
        self.assertEqual(38, selected.size)
        self.assertTrue(block.endswith('...'))

    def test_invalid_asset_geometry_is_explicit(self):
        original=c._art
        for name in ('background.png','stamp.png'):
            def art(n):return Image.new('RGBA',(1,1)) if n==name else original(n)
            with patch.object(c,'_art',art),self.assertRaises(ValueError):c.render_cover(mode='generate',title='Berserk')

    def test_large_title_and_outline_contrast(self):
        def linear(v):
            v=v/255
            return v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4
        def lum(color):return sum(w*linear(v) for w,v in zip((.2126,.7152,.0722),color))
        from PIL import ImageColor
        fg=lum(ImageColor.getrgb(c.PALETTE['off_white']))
        bg=c._art('background.png').convert('RGB').crop(c.TITLE_BOX)
        ratios=[(fg+.05)/(lum(pixel)+.05) for pixel in (bg.get_flattened_data() if hasattr(bg,'get_flattened_data') else bg.getdata())]
        self.assertGreaterEqual(min(ratios),3)
        outline=lum(ImageColor.getrgb(c.PALETTE['deep_ocean']))
        self.assertGreaterEqual((fg+.05)/(outline+.05),12)

if __name__=='__main__':unittest.main(verbosity=2)
