"""Detail uses the selected processed page, not an enlarged thumbnail."""
from unittest.mock import patch
from types import SimpleNamespace
import unittest
from PIL import Image

from image_processing import ProcessingSettings, apply_processing
from preview_detail import DETAIL_MAX_BYTES, detail_rgba, zoom_dimensions
from tests import test_empress_pipeline as pipeline


class DetailGeometryTests(unittest.TestCase):
    def test_100_percent_is_exact_image_pixel_size(self):
        self.assertEqual((1260,948),zoom_dimensions((1260,948),(400,300),1.0))

    def test_fit_contains_without_upscaling(self):
        self.assertEqual((400,300),zoom_dimensions((1600,1200),(400,300)))
        self.assertEqual((100,50),zoom_dimensions((100,50),(400,300)))
        size=zoom_dimensions((1260,948),(510,370))
        self.assertLessEqual(size[0],510); self.assertLessEqual(size[1],370)
        self.assertAlmostEqual(size[0]/size[1],1260/948,delta=.005)

    def test_zoom_factors(self):
        for factor in (.25,.5,.75,1.,1.25,1.5,2.):
            self.assertEqual((round(800*factor),round(600*factor)),zoom_dimensions((800,600),(400,300),factor))

    def test_fit_has_no_simulator_specific_cap(self):
        self.assertEqual((1200, 903), zoom_dimensions((1680, 1264), (1200, 1000)))
        self.assertEqual((752, 1000), zoom_dimensions((1264, 1680), (1200, 1000)))
        self.assertEqual((900, 677), zoom_dimensions((1680, 1264), (900, 700)))

    def test_explicit_zoom_is_framebuffer_relative(self):
        for factor in (.25, .5, .75, 1., 1.25, 1.5, 2.):
            self.assertEqual(
                (round(1680 * factor), round(1264 * factor)),
                zoom_dimensions((1680, 1264), (200, 200), factor),
            )

    def test_detail_has_strict_preallocation_memory_limit(self):
        class TooLarge:
            width=DETAIL_MAX_BYTES//4+1; height=1
            def convert(self,*_args): raise AssertionError('Must reject before allocation')
        with self.assertRaisesRegex(ValueError,'64 MiB'): detail_rgba(TooLarge())


class DetailPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): pipeline.PipelineTests.setUpClass()
    @classmethod
    def tearDownClass(cls): pipeline.PipelineTests.tearDownClass()
    def setUp(self):
        self.fixture=pipeline.PipelineTests(); self.fixture.setUp()

    def test_reports_normal_dimensions_for_both_layouts_and_adjustments(self):
        for layout in ('original_pages','paired_landscape'):
            source,sample=self.fixture.acquire(layout)
            for settings in (ProcessingSettings(),ProcessingSettings(brightness=.25,sharpness=0),
                             ProcessingSettings(brightness=1.5,sharpness=2)):
                worker=self.fixture.ns['ProcessingPreviewWorker'](sample,'rtl',settings)
                worker.run(); self.assertFalse(worker.failed.calls)
                result=worker.ready.calls[0][0]
                expected=(1680,1264) if layout=='paired_landscape' else (40,60)
                self.assertTrue(all(size==expected for size in result['dimensions'].values()))
                self.assertIsNone(result['detail_image'])
            self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_selected_page_is_full_processed_source_not_thumbnail(self):
        source,sample=self.fixture.acquire()
        sample['records'][0]['image']=Image.new('RGB',(600,800),(50,70,90))
        sample['records'][1]['image']=Image.new('RGB',(600,800),(150,170,190))
        settings=ProcessingSettings(gamma=2,grayscale=True,brightness=.5,sharpness=2)
        worker=self.fixture.ns['ProcessingPreviewWorker'](sample,'rtl',settings,detail_page=2)
        worker.run(); self.assertFalse(worker.failed.calls)
        result=worker.ready.calls[0][0]; detail=result['detail_image']
        self.assertEqual(2,result['detail_page'])
        self.assertEqual((600,800),(detail.width(),detail.height()))
        self.assertEqual(detail_rgba(apply_processing(sample['records'][1]['image'],settings)),detail.raw)
        self.assertNotEqual(detail_rgba(apply_processing(sample['records'][0]['image'],settings)),detail.raw)
        self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_kobo_is_detail_only_and_overview_pixels_are_unchanged(self):
        source,sample=self.fixture.acquire()
        off=self.fixture.ns['ProcessingPreviewWorker'](sample,'rtl',ProcessingSettings())
        armed=self.fixture.ns['ProcessingPreviewWorker'](
            sample,'rtl',ProcessingSettings(),screen_emulation_id='kobo_libra_colour')
        off.run(); armed.run()
        normal=off.ready.calls[0][0]; kobo=armed.ready.calls[0][0]
        self.assertEqual(normal['thumbs'],kobo['thumbs'])
        self.assertEqual({k:v.raw for k,v in normal['provisional_images'].items()},
                         {k:v.raw for k,v in kobo['provisional_images'].items()})
        self.assertIsNone(kobo['emulation_metadata'])
        self.assertEqual('',kobo['emulation_error'])
        self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_kobo_detail_uses_output_layout_and_native_framebuffer_only(self):
        source,sample=self.fixture.acquire('paired_landscape')
        worker=self.fixture.ns['ProcessingPreviewWorker'](
            sample,'rtl',ProcessingSettings(),detail_page=1,
            screen_emulation_id='kobo_libra_colour')
        worker.run(); self.assertFalse(worker.failed.calls)
        result=worker.ready.calls[0][0]
        self.assertEqual((1680,1264),result['emulation_metadata']['screen_size'])
        self.assertNotIn('composite_size', result['emulation_metadata'])
        self.assertEqual((1680,1264),(result['detail_image'].width(),result['detail_image'].height()))
        self.assertEqual([],result['thumbs'])
        self.assertGreater(result['emulation_seconds'],0)
        self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_emulation_failure_returns_normal_detail_and_error(self):
        _source,sample=self.fixture.acquire()
        worker=self.fixture.ns['ProcessingPreviewWorker'](
            sample,'rtl',ProcessingSettings(),detail_page=1,
            screen_emulation_id='kobo_libra_colour')
        with patch.dict(self.fixture.ns, render_emulated_detail=lambda *_a, **_k: (_ for _ in ()).throw(
                ValueError('Synthetic emulator failure'))):
            worker.run()
        self.assertFalse(worker.failed.calls)
        result=worker.ready.calls[0][0]
        self.assertIsNone(result['emulation_metadata'])
        self.assertTrue(result['emulation_error'])
        self.assertEqual((40,60),(result['detail_image'].width(),result['detail_image'].height()))

    def test_landscape_detail_matches_shared_processed_canvas(self):
        source,sample=self.fixture.acquire('paired_landscape')
        settings=ProcessingSettings(1.2,.8,2,True,brightness=1.5,sharpness=2)
        worker=self.fixture.ns['ProcessingPreviewWorker'](sample,'rtl',settings,detail_page=2)
        worker.run(); self.assertFalse(worker.failed.calls)
        pages,_=self.fixture.ns['build_landscape_pages'](sample['records'],'rtl',processing=settings,in_memory=True,detailed=True)
        self.assertEqual(detail_rgba(pages[1][1]),worker.ready.calls[0][0]['detail_image'].raw)
        self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_switching_and_processing_only_newest_detail_can_win(self):
        source,sample=self.fixture.acquire(); c=self.fixture.controls(sample)
        c._processed_page_count=3
        c._select_detail_page(1); first=c._processing_worker; token=c._render_ownership.generation
        c._select_detail_page(2)
        c._processing_controls['gamma'][0].setValue(200); c._processing_changed(); c._flush_processing_render()
        self.assertEqual(1,len(c.started))
        first.finished.emit(); c._processing_worker.run()
        latest=c._processing_worker.ready.calls[0][0]
        self.assertEqual(2,latest['detail_page']); self.assertEqual(2,latest['processing'].gamma)
        c._on_processing_ready({'detail_page':1},token,'sample')
        self.assertEqual([],c.displayed)  # Detail must not regenerate hidden overview.
        self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_detail_limit_does_not_break_thumbnail_preview(self):
        _source,sample=self.fixture.acquire()
        worker=self.fixture.ns['ProcessingPreviewWorker'](sample,'rtl',ProcessingSettings(),detail_page=1)
        with patch.dict(self.fixture.ns,detail_rgba=lambda _im:(_ for _ in ()).throw(ValueError('64 MiB limit'))):
            worker.run()
        result=worker.ready.calls[0][0]
        self.assertEqual([],result['thumbs']); self.assertIsNone(result['detail_image'])
        self.assertIn('64 MiB',result['detail_error'])
        self.assertIsNone(worker.sample)

    def test_context_clear_releases_selected_detail(self):
        _source,sample=self.fixture.acquire(); c=self.fixture.controls(sample)
        closed=[]
        c._detail_viewer=SimpleNamespace(surface=SimpleNamespace(image=object()), deleteLater=lambda:closed.append(True))
        c.live_preview_stack=SimpleNamespace(setCurrentIndex=lambda _v:None,removeWidget=lambda _v:None)
        c._detail_page=2; c._processed_page_count=3
        c._clear_detail_preview()
        self.assertEqual([True],closed)
        self.assertIsNone(c._detail_viewer); self.assertIsNone(c._detail_page)
        self.assertEqual(0,c._processed_page_count)
