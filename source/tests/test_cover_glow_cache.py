"""Pixel parity against the previous full-canvas title/glow compositor."""
from unittest.mock import patch
import unittest
from PIL import Image,ImageFilter,ImageChops
from calibre_plugins.manganana.books.imaging import cover_rendering as c

def full_canvas_title(canvas,text):
    raster=c._title_raster(text);layer=Image.new('RGBA',c.CANVAS_SIZE)
    if raster:
        ink=Image.frombytes('RGBA',raster[0],raster[1])
        position=(round((c.TITLE_BOX[0]+c.TITLE_BOX[2]-ink.width)/2),round((c.TITLE_BOX[1]+c.TITLE_BOX[3]-ink.height)/2))
        layer.alpha_composite(ink,position)
    glow=Image.new('RGBA',c.CANVAS_SIZE,c.PALETTE['deep_ocean'])
    glow.putalpha(layer.getchannel('A').filter(ImageFilter.GaussianBlur(4)).point(lambda a:a//5))
    canvas.alpha_composite(glow);canvas.alpha_composite(layer)

class GlowCacheTests(unittest.TestCase):
    def test_equal_pixels_for_title_lengths_numbering_and_unicode(self):
        for title in ('Berserk','A long complicated title '*10,'UnbrokenTitle'*60,'進撃の巨人','', 'é É & Ω'):
            for kind,index in (('volume',67.5),('chapter',0)):
                options=dict(mode='generate',title=title,output_kind=kind,series_index=index)
                actual=c.render_cover_image(**options)
                with patch.object(c,'_draw_title',full_canvas_title):expected=c.render_cover_image(**options)
                self.assertIsNone(ImageChops.difference(expected,actual).getbbox(),(title,kind))

    def test_identical_title_reuses_blur_with_bounded_immutable_storage(self):
        c._title_glow_raster.cache_clear()
        for number in range(8):c.render_cover_image(mode='generate',title='Shared title',volume=number)
        info=c._title_glow_raster.cache_info()
        self.assertEqual((1,7),(info.misses,info.hits))
        value=c._title_glow_raster('Shared title')
        self.assertIsInstance(value[2],bytes)
        for title in ('A','B','C','D','E'):c.render_cover_image(mode='generate',title=title)
        self.assertEqual(4,c._title_glow_raster.cache_info().currsize)
