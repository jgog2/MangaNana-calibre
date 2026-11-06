"""Framing geometry and production renderer regressions, without network access."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
import zipfile
from PIL import Image, ImageChops

from calibre_plugins.manganana.books.imaging.page_framing import framing_rectangle, portrait_framing, framing_label, framing_snapshot, framing_from_snapshot, save_framing_preset, delete_framing_preset, load_framing_presets
from calibre_plugins.manganana.books.imaging.image_processing import ProcessingSettings
from tests import test_empress_pipeline as pipeline


def png(image):
    stream = BytesIO(); image.save(stream, 'PNG'); return stream.getvalue()


class FramingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.ns = pipeline.production_namespace()

    def render(self, kind, images, framing=0, memory=True, overview=False, gutter=0):
        records = tuple({'image': image, 'blob': png(image), 'ext': '.png', 'size': image.size} for image in images)
        return self.ns['render_output_page']({'kind': kind, 'records': records}, ProcessingSettings(),
                                           in_memory=memory, overview=overview, framing=framing, gutter_px=gutter)[1]

    def test_current_is_exact_legacy_calibration_and_positions(self):
        self.assertEqual((1680,1264,30,38,1620,1188), self.ns['_landscape_safe_area']())
        left = Image.new('RGB', (500,900), 'red'); right = Image.new('RGB',(700,1000),'blue')
        expected = Image.new('RGB',(1680,1264),'white')
        # Independent copy of the established pre-framing fit and placement math.
        for image, origin in ((left,30),(right,840)):
            scale = min(810/image.width,1188/image.height)
            size = tuple(max(1,round(axis*scale)) for axis in image.size)
            expected.paste(image.resize(size,Image.Resampling.LANCZOS),
                           (origin+(810-size[0])//2,38+(1188-size[1])//2))
        actual = self.render('PAIRED',(left,right))
        self.assertEqual(expected.tobytes(), actual.tobytes())
        self.assertEqual(self.ns['_save_jpeg'](expected), self.render('PAIRED',(left,right),memory=False))
        for kind, source in (('ORIGINAL SPREAD',Image.new('RGB',(1700,1200),'red')),
                             ('ISOLATED',left)):
            art = source
            if kind == 'ISOLATED':
                art=Image.new('RGB',(source.width*2,source.height),'white'); art.paste(source,(source.width,0))
            scale=min(1620/art.width,1188/art.height)
            size=tuple(round(axis*scale) for axis in art.size)
            expected=Image.new('RGB',(1680,1264),'white')
            expected.paste(art.resize(size,Image.Resampling.LANCZOS),((1680-size[0])//2,(1264-size[1])//2))
            self.assertEqual(expected.tobytes(),self.render(kind,(source,)).tobytes())
            self.assertEqual(self.ns['_save_jpeg'](expected),self.render(kind,(source,),memory=False))

    def test_portrait_default_preserves_source_bytes(self):
        image=Image.new('RGB',(123,201),(12,67,99)); blob=png(image)
        record={'blob':blob,'ext':'.png','size':image.size}
        result=self.ns['render_output_page']({'kind':'INDIVIDUAL','records':(record,)},ProcessingSettings(),framing=0)
        self.assertIs(blob,result[1])
        self.assertIs(image,portrait_framing(image,0))

    def test_bounds_all_ticks_and_no_margin_landscape(self):
        for value in range(-100,101):
            x,y,w,h=framing_rectangle((1680,1264),(1620,1188),value)
            self.assertGreater(min(w,h),0)
            self.assertLessEqual(w,round(1680*1.05)); self.assertLessEqual(h,round(1264*1.05))
            self.assertLessEqual(abs(2*x+w-1680),1); self.assertLessEqual(abs(2*y+h-1264),1)
        self.assertEqual((0,0,1680,1264),framing_rectangle((1680,1264),(1620,1188),70))
        self.assertEqual((-42,-32,1764,1327),framing_rectangle((1680,1264),(1620,1188),100))
        for size in ((1,1),(1,17),(17,1)):
            for value in (-100,0,100): self.assertEqual(size,portrait_framing(Image.new('RGB',size),value).size)

    def test_landscape_pairs_spreads_and_isolated_keep_canvas_and_symmetry(self):
        left=Image.new('RGB',(810,1188),'red'); right=Image.new('RGB',(810,1188),'blue')
        areas=[]
        for value in (-100,0,35,70,100):
            pair=self.render('PAIRED',(left,right),value)
            self.assertEqual((1680,1264),pair.size)
            red=pair.getchannel('R').point(lambda p:255-p); blue=pair.getchannel('B').point(lambda p:255-p)
            self.assertLessEqual(abs(sum(red.histogram()[1:])-sum(blue.histogram()[1:])),1264)
            bbox=ImageChops.difference(pair,Image.new('RGB',pair.size,'white')).getbbox()
            areas.append((bbox[2]-bbox[0])*(bbox[3]-bbox[1]))
            isolated=self.render('ISOLATED',(left,),value)
            # LANCZOS can blend a few pixels across the existing white/art seam.
            self.assertIsNone(ImageChops.difference(isolated.crop((0,0,835,1264)),Image.new('RGB',(835,1264),'white')).getbbox())
            spread=self.render('ORIGINAL SPREAD',(Image.new('RGB',(1680,1264),'black'),),value)
            box=ImageChops.difference(spread,Image.new('RGB',spread.size,'white')).getbbox()
            self.assertLessEqual(abs(box[0]-(1680-box[2])),1)
            self.assertLessEqual(abs(box[1]-(1264-box[3])),1)
        self.assertEqual(sorted(areas),areas)

    def test_portrait_centered_border_crop_and_preview_final_equivalence(self):
        image=Image.new('RGB',(200,300),'black')
        for value in (-100,-35,0,50,100):
            preview=self.render('INDIVIDUAL',(image,),value)
            final=self.render('INDIVIDUAL',(image,),value,memory=False)
            with Image.open(BytesIO(final)) as output:
                self.assertEqual(image.size,output.size)
                self.assertEqual(preview.tobytes(),output.tobytes())
            if value<0:
                bbox=ImageChops.difference(preview,Image.new('RGB',preview.size,'white')).getbbox()
                self.assertLessEqual(abs(bbox[0]-(200-bbox[2])),1)
                self.assertLessEqual(abs(bbox[1]-(300-bbox[3])),1)
                self.assertEqual((255,255,255),preview.getpixel((0,0)))
        # Colored edge is lost equally at both sides when center-zooming.
        image.paste('red',(0,0,3,300)); image.paste('red',(197,0,200,300))
        zoom=self.render('INDIVIDUAL',(image,),100)
        self.assertLessEqual(max(zoom.getpixel((0,150))),3)
        self.assertLessEqual(max(zoom.getpixel((199,150))),3)

    def test_cbz_and_pdf_derived_records_share_renderer(self):
        from calibre_plugins.manganana.books.imports.local_import import inspect_book, staged_pages
        image=Image.new('RGB',(80,120),'black')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.cbz'
            with zipfile.ZipFile(path,'w') as archive: archive.writestr('1.png',png(image))
            with staged_pages(inspect_book(path)) as records:
                job=self.ns['output_page_jobs'](records,'original_pages','rtl')[0][0]
                self.assertEqual(png(image),self.ns['render_output_page'](job,ProcessingSettings(),framing=0)[1])
                cbz=self.ns['render_output_page'](job,ProcessingSettings(),in_memory=True,framing=100)[1]
            raster=Path(folder)/'pdf-page.png'; raster.write_bytes(png(image))
            # PDF rasterizer output uses the same disk-backed record contract.
            record={'local_path':str(raster),'ext':'.png','size':image.size}
            self.assertEqual(raster.read_bytes(),self.ns['render_output_page'](
                {'kind':'INDIVIDUAL','records':(record,)},ProcessingSettings(),framing=0)[1])
            pdf=self.ns['render_output_page']({'kind':'INDIVIDUAL','records':(record,)},ProcessingSettings(),in_memory=True,framing=100)[1]
            self.assertEqual(cbz.tobytes(),pdf.tobytes())

    def test_preview_workers_forward_framing_for_overview_and_detail(self):
        from unittest.mock import patch
        image=Image.new('RGB',(80,120),'black')
        sample={'layout':'original_pages','records':({'image':image,'size':image.size,'ext':'.png'},)}
        for detail in (None,1):
            worker=self.ns['ProcessingPreviewWorker'](sample,'rtl',ProcessingSettings(),detail_page=detail,framing=100,gutter_px=16)
            renderer=self.ns['render_output_page']
            with patch.dict(self.ns,render_output_page=lambda *a,**kw: (
                    self.assertEqual((100,16),(kw['framing'],kw['gutter_px'])) or renderer(*a,**kw))):
                worker.run()
            self.assertFalse(worker.failed.calls)
            self.assertTrue(worker.ready.calls)

    def test_landscape_preview_final_geometry_matches_at_all_boundaries(self):
        portrait=Image.new('RGB',(810,1188),'black')
        spread=Image.new('RGB',(1680,1264),'black')
        for kind,images in (('PAIRED',(portrait,portrait)),('ISOLATED',(portrait,)),
                            ('ORIGINAL SPREAD',(spread,))):
            for value in (-100,70,0,100):
                overview=self.render(kind,images,value,overview=True)
                detail=self.render(kind,images,value)
                def bounds(image):
                    return image.convert('L').point(lambda p: 255 if p<128 else 0).getbbox()
                # Overview deliberately uses a bounded raster, Detail uses final size.
                projected=detail.resize(overview.size,Image.Resampling.LANCZOS)
                for actual,expected in zip(bounds(overview),bounds(projected)):
                    self.assertLessEqual(abs(actual-expected),1)
                with Image.open(BytesIO(self.render(kind,images,value,memory=False))) as final:
                    self.assertEqual(bounds(detail),bounds(final))

    def test_framing_is_independent_of_preset_reset_and_reuses_acquisition(self):
        pipeline.PipelineTests.setUpClass()
        try:
            fixture=pipeline.PipelineTests(); fixture.setUp(); source,sample=fixture.acquire()
            control=fixture.controls(sample); counts=(source.manifests,source.fetches)
            control.page_framing.setValue(100); control._framing_changed()
            control.page_gutter.setValue(16); control._framing_changed()
            self.assertTrue(control._processing_timer.isActive())
            control._reset_processing()
            self.assertEqual(100,control.page_framing.value())
            self.assertEqual(counts,(source.manifests,source.fetches))
        finally: pipeline.PipelineTests.tearDownClass()

    def test_pixel_status_uses_renderer_baseline_and_never_negative_margins(self):
        w,h,x,y,sw,sh=self.ns['_landscape_safe_area']()
        self.assertEqual('Outer Margin: 30 px H × 38 px V · Gutter: 0 px',
                         framing_label(0,True,(w,h),(sw,sh)))
        self.assertEqual('Outer Margin: 0 px · Gutter: 0 px',framing_label(70,True,(w,h),(sw,sh)))
        self.assertIn('Zoom: +2.5%',framing_label(85,True,(w,h),(sw,sh),16))
        self.assertNotIn('-1',framing_label(100,True,(w,h),(sw,sh)))
        self.assertEqual('Outer Margin: 15 px H × 22 px V',framing_label(-100,False,(200,300)))
        self.assertEqual('Outer Margin: 0 px · Zoom: +5.0%',framing_label(100,False,(200,300)))

    def test_no_margin_contains_complete_source_without_crop(self):
        source=Image.new('RGB',(1680,1264),'black')
        source.paste('red',(0,0,1,1264)); source.paste('blue',(1679,0,1680,1264))
        self.assertEqual(source.tobytes(),self.render('ORIGINAL SPREAD',(source,),70).tobytes())
        portrait=Image.new('RGB',(840,1264),'red')
        pair=self.render('PAIRED',(portrait,portrait),70)
        self.assertEqual(Image.new('RGB',(1680,1264),'red').tobytes(),pair.tobytes())

    def test_gutter_is_symmetric_and_only_changes_pairs(self):
        page=Image.new('RGB',(810,1188),'black')
        for framing in (-100,0,70,100):
            for gutter in (0,16,80):
                pair=self.render('PAIRED',(page,page),framing,gutter=gutter)
                self.assertEqual((1680,1264),pair.size)
                bounds=[]
                for region in ((0,0,840,1264),(840,0,1680,1264)):
                    bounds.append(ImageChops.difference(pair.crop(region),Image.new('RGB',(840,1264),'white')).getbbox())
                self.assertLessEqual(abs(bounds[0][0]-(840-bounds[1][2])),1)
                if gutter:
                    self.assertEqual((255,255,255),pair.getpixel((839,632)))
                    self.assertEqual((255,255,255),pair.getpixel((840,632)))
                for kind in ('ORIGINAL SPREAD','ISOLATED'):
                    self.assertEqual(self.render(kind,(page,),framing).tobytes(),
                                     self.render(kind,(page,),framing,gutter=gutter).tobytes())
        # Slot-filling pages make the intentional gap measurable independently of aspect-fit whitespace.
        for gutter in (0,16,80):
            page=Image.new('RGB',((1620-gutter)//2,1188),'black')
            pair=self.render('PAIRED',(page,page),gutter=gutter)
            row=[pair.getpixel((x,632)) == (255,255,255) for x in range(30,1650)]
            self.assertEqual(gutter,sum(row))

    def test_gutter_preview_final_including_inner_edges(self):
        page=Image.new('RGB',(810,1188),'black')
        def boxes(image):
            middle=image.width//2
            return [image.crop(box).convert('L').point(lambda p:255 if p<128 else 0).getbbox()
                    for box in ((0,0,middle,image.height),(middle,0,image.width,image.height))]
        for framing in (-100,0,70,100):
            for gutter in (0,16,80):
                detail=self.render('PAIRED',(page,page),framing,gutter=gutter)
                overview=self.render('PAIRED',(page,page),framing,overview=True,gutter=gutter)
                projected=detail.resize(overview.size,Image.Resampling.LANCZOS)
                for a,b in zip(boxes(overview),boxes(projected)):
                    self.assertTrue(all(abs(x-y)<=1 for x,y in zip(a,b)))
                with Image.open(BytesIO(self.render('PAIRED',(page,page),framing,memory=False,gutter=gutter))) as final:
                    self.assertEqual(boxes(detail),boxes(final))

    def test_preset_storage_roundtrip_immutable_builtins_and_explicit_updates(self):
        import json
        for value in range(-100,101):
            payload=framing_snapshot(value,16)
            self.assertEqual((value,16),framing_from_snapshot(json.loads(json.dumps(payload))))
        presets=save_framing_preset({},'Kobo',framing_snapshot(-40,16))
        self.assertEqual((-40,16),framing_from_snapshot(load_framing_presets(presets)['Kobo']))
        changed=framing_snapshot(85,80)
        self.assertNotEqual(changed,presets['Kobo'])
        with self.assertRaises(ValueError): save_framing_preset(presets,'Kobo',changed)
        updated=save_framing_preset(presets,'Kobo',changed,'Kobo')
        renamed=save_framing_preset(updated,'Boox',updated['Kobo'],'Kobo')
        self.assertEqual({},delete_framing_preset(renamed,'Boox'))
        for name in ('Default','No Margin'):
            with self.assertRaises(ValueError): save_framing_preset({},name,changed)
            with self.assertRaises(ValueError): delete_framing_preset({},name)
        self.assertEqual({},load_framing_presets({'Broken':{'version':1}}))


if __name__ == '__main__': unittest.main()
