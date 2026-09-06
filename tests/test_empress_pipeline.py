"""Execute production workers and slider handlers with deterministic fake Qt/I/O."""
import ast
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import os
import time
import unittest
import zipfile

from PIL import Image
import image_processing
import native_dithering
from page_rendering import final_workers, ordered_render
from image_processing import ProcessingSettings, apply_processing, process_page_blob
from processing_presets import BUILTIN_PRESETS_BY_ID, matching_preset
from preview_render_state import RenderOwnership
from preview_detail import detail_rgba, zoom_dimensions
from screen_emulation import (
    NONE_PROFILE_ID, native_screen_size, profile_for,
    render_emulated_detail,
)
from workflow_state import HighPriestessState
from cover_rendering import render_cover
from tests.test_image_regressions import load_image_helpers


class Signal:
    def __init__(self, *_args): self.calls = []; self.callbacks = []
    def connect(self, callback): self.callbacks.append(callback)
    def emit(self, *args):
        self.calls.append(args)
        for callback in self.callbacks: callback(*args)


class Thread:
    def __init__(self):
        self.interrupted = False
        for name in ('ready', 'failed', 'progress', 'log', 'cancelled_ok', 'finished', 'stats'):
            setattr(self, name, Signal())
    def requestInterruption(self): self.interrupted = True
    def isInterruptionRequested(self): return self.interrupted
    def start(self): pass  # scheduling controlled explicitly, never sleeps


class DetailImage:
    Format=SimpleNamespace(Format_RGBA8888=1)
    def __init__(self, raw, width, height, *_args): self.raw=raw; self.w=width; self.h=height
    def copy(self): return self
    def isNull(self): return False
    def setDevicePixelRatio(self, value): self.dpr=value
    def width(self): return self.w
    def height(self): return self.h


class Timer:
    def __init__(self): self.active = False; self.starts = 0
    def start(self): self.active = True; self.starts += 1
    def stop(self): self.active = False
    def isActive(self): return self.active


class Control:
    def __init__(self, value=100): self.v=value; self.blocked=False; self.text=''; self.enabled=True; self.checked=False
    def value(self): return self.v
    def setValue(self, value): self.v=value
    def blockSignals(self, value): old=self.blocked; self.blocked=value; return old
    def setText(self, value): self.text=value
    def currentData(self): return 'rtl'
    def setEnabled(self, value): self.enabled=value
    def isChecked(self): return self.checked
    def setChecked(self, value): self.checked=value
    def setCurrentIndex(self, value): self.v=value


class Combo(Control):
    def __init__(self, items):
        super().__init__(0)
        self.items=list(items)
    def currentData(self): return self.items[self.v][1] if self.items else None
    def clear(self): self.items=[]; self.v=0
    def addItem(self, label, value): self.items.append((label,value))
    def findData(self, value):
        return next((i for i, item in enumerate(self.items) if item[1]==value),-1)


def production_namespace():
    from book_export import write_book, validate_pdf
    ns=load_image_helpers('_image_size', '_normalize_exif_orientation', '_exif_orientation_value',
                          '_select_verified_preview_source', '_to_rgb', '_save_jpeg',
                          '_landscape_safe_area', '_kobo_landscape_canvas', '_landscape_canvas_for_single',
                          '_fit_page_to_slot', '_paired_canvas', '_spread_with_margin', 'build_landscape_pages', '_validate_cbz_output',
                          'output_page_jobs', 'output_job_size', 'load_page_record', 'render_output_page')
    ns.update(QThread=Thread, pyqtSignal=Signal, time=time, os=os, ProcessingSettings=ProcessingSettings,
              native_dithering=native_dithering,final_workers=final_workers,ordered_render=ordered_render,
              render_cover=render_cover, write_book=write_book, validate_pdf=validate_pdf,
              BUILTIN_PRESETS_BY_ID=BUILTIN_PRESETS_BY_ID,matching_preset=matching_preset,
              QImage=DetailImage, detail_rgba=detail_rgba,
              NONE_PROFILE_ID=NONE_PROFILE_ID,
              native_screen_size=native_screen_size, profile_for=profile_for,
              render_emulated_detail=render_emulated_detail,
              apply_processing=apply_processing, process_page_blob=process_page_blob,
              SOURCE_REGISTRY=SimpleNamespace(get=lambda _key:None), image_extension=lambda _url:'.png',
              format_speed=lambda _v:'speed', format_eta=lambda _v:'eta', USER_AGENT='test')
    tree=ast.parse(Path('main.py').read_text(encoding='utf-8'))
    workers=[n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in
             ('DownloadWorker', 'PairingPreviewWorker', 'ProcessingPreviewWorker')]
    exec(compile(ast.Module(body=workers, type_ignores=[]), 'main.py', 'exec'), ns)
    dialog=next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='MangaNanaDialog')
    methods=[n for n in dialog.body if isinstance(n, ast.FunctionDef) and n.name in (
        '_update_processing_labels', '_processing_changed', '_reset_processing', '_apply_processing_preset',
        '_sync_processing_preset','current_processing_settings','_all_processing_presets','_invalidate_processing_render',
        '_schedule_processing_render', '_flush_processing_render', '_start_processing_render',
        '_processing_result_current', '_on_processing_ready', '_on_processing_failed', '_processing_finished',
        'current_signature', 'invalidate_preview', '_choose_grayscale', '_select_detail_page', '_clear_detail_preview', '_update_depth_choices')]
    harness=ast.ClassDef(name='Controls', bases=[], keywords=[], body=methods, decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[])), 'main.py', 'exec'), ns)
    return ns


class Source:
    display_name='Synthetic'; source_id='synthetic'; capabilities=()
    def __init__(self):
        im=Image.new('RGB', (40, 60), (80, 110, 140))
        out=BytesIO(); im.save(out, 'PNG'); self.blob=out.getvalue()
        self.manifests=0; self.fetches=0
    def get_page_manifest(self, *_args, **_kwargs):
        self.manifests+=1
        return {'full':['page.png']*3}
    def fetch_preview_page(self, *_args, **_kwargs):
        self.fetches+=1; return self.blob, False
    def fetch_binary(self, *_args, **_kwargs): self.fetches+=1; return self.blob


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_pillow=not hasattr(Image,'Resampling')
        if cls.old_pillow: Image.Resampling=SimpleNamespace(LANCZOS=Image.LANCZOS)

    @classmethod
    def tearDownClass(cls):
        if cls.old_pillow: del Image.Resampling

    def setUp(self): self.ns=production_namespace()

    def acquire(self, layout='original_pages'):
        source=Source()
        worker=self.ns['PairingPreviewWorker'](source, 'url', 'en', 1, 'rtl',
                                               [{'id':'chapter', 'chapter':'1', 'pages':3}], layout=layout)
        worker.run()
        self.assertFalse(worker.failed.calls)
        return source, worker.ready.calls[0][0]

    def controls(self, sample=None):
        c=self.ns['Controls']()
        c.processing=ProcessingSettings(); c._render_ownership=RenderOwnership()
        c._user_processing_presets=()
        c._processing_worker=None; c._processing_pending=False; c._processing_timer=Timer()
        c._detail_viewer=None; c._detail_page=None; c._processed_page_count=0
        c._screen_emulation_id=NONE_PROFILE_ID
        c._overview_images={}; c._overview_dimensions={}; c._overview_dirty=False
        c._closing=False; c._live_preview_stale=False
        c._active_preview_sample_key='sample' if sample else None
        c._live_preview_samples={'sample':sample} if sample else {}
        c._live_preview_signature_value=lambda:'sample'
        c.live_preview_status=Control(); c.progress_text=Control(); c.reading_direction=Control()
        c._processing_controls={name:(Control(), Control()) for name in ('brightness','contrast','gamma','saturation','sharpness')}
        c.grayscale_off=Control(); c.grayscale_off.checked=True; c.grayscale_on=Control()
        c.output_depth=Combo([]); c._depth_grayscale=None; c._update_depth_choices()
        c.dithering=Combo([(name,name) for name in ('off','floyd-steinberg','atkinson','sierra-lite')])
        c.dither_strength=Control(); c.dither_strength_value=Control()
        c._download_in_progress=False
        c.workflow_state=HighPriestessState(); c.workflow_state.preview_state='ready' if sample else 'off'
        c.workflow_state.set_finalization_plan(('output',))
        c.workflow_mode='volume'; c.current_source_id='synthetic'; c.current_manga_url='url'
        c._applied_metadata_values=lambda:('Title','Author','Series')
        c.language=Control(); c.page_layout=Control()
        c.start=c.end=SimpleNamespace(text=lambda:'')
        c._selected_volumes={1}; c._selected_chapter_ids=set()
        c._standalone_selected=c._using_entire_series=False
        c._chapter_output_mode=SimpleNamespace(value='volume'); c._manual_volume_assignments={}
        c.covers=c.pad=SimpleNamespace(isChecked=lambda:True)
        c._preview_build_signature=None; c.download_btn=SimpleNamespace(setEnabled=lambda _v:None)
        c._update_preview_button_for_volume_selection=lambda:None
        c.transitions=0
        actual_invalidate=c.invalidate_preview
        def invalidate(): c.transitions+=1; actual_invalidate()
        c.invalidate_preview=invalidate
        c.displayed=[]; c.logs=[]; c.started=[]
        c._render_live_preview=c.displayed.append; c.add_log=c.logs.append
        c._update_live_preview_action=lambda:None
        c._retain_async_worker=c.started.append
        return c

    def test_acquisition_is_bounded_and_reused_without_http(self):
        source, sample=self.acquire()
        self.assertEqual((1,3), (source.manifests,source.fetches))
        self.assertEqual(3, len(sample['records']))
        self.assertTrue(all('image' in r and 'blob' not in r for r in sample['records']))
        original=[r['image'].tobytes() for r in sample['records']]
        c=self.controls(sample)
        for value in range(50,201,5):
            c._processing_controls['contrast'][0].setValue(value); c._processing_changed()
        self.assertEqual([], c.started)
        c._flush_processing_render()
        self.assertEqual(1, len(c.started))
        c._processing_worker.run()
        self.assertEqual(2, c.displayed[-1]['processing'].contrast)
        self.assertEqual((1,3), (source.manifests,source.fetches))
        self.assertEqual(original, [r['image'].tobytes() for r in sample['records']])

    def test_actual_ui_gamma_slider_right_brightens(self):
        c=self.controls()
        midpoint=Image.new('L',(1,1),128)
        for tick, gamma, expected in ((50,.5,64),(100,1.,128),(200,2.,181)):
            c._processing_controls['gamma'][0].setValue(tick)
            c._processing_changed()  # actual production label and settings path
            self.assertEqual(gamma,c.processing.gamma)
            self.assertEqual(f'{gamma:.2f}',c._processing_controls['gamma'][1].text)
            self.assertEqual(expected,apply_processing(midpoint,c.processing).getpixel((0,0)))

    def test_actual_ui_saturation_accepts_300_percent_without_network(self):
        source, sample = self.acquire()
        c = self.controls(sample)
        c.workflow_state.set_finalization_plan(('output',))
        signature = c.current_signature()
        c._processing_controls['saturation'][0].setValue(300)
        c._processing_changed()
        self.assertEqual(3.0, c.processing.saturation)
        self.assertEqual('300%', c._processing_controls['saturation'][1].text)
        self.assertNotEqual(signature, c.current_signature())
        self.assertTrue(c.workflow_state.finalization_stale)
        c._flush_processing_render(); c._processing_worker.run()
        self.assertEqual((1, 3), (source.manifests, source.fetches))

    def test_off_retains_output_settings_without_enabling_or_network(self):
        c=self.controls()
        for name in c._processing_controls:
            c._processing_controls[name][0].setValue(125); c._processing_changed()
        self.assertEqual(ProcessingSettings(1.25,1.25,1.25,brightness=1.25,sharpness=1.25),c.processing)
        self.assertEqual('off',c.workflow_state.preview_state)
        self.assertFalse(c._processing_pending)
        self.assertEqual([],c.started)

    def test_running_job_coalesces_and_late_result_cannot_win(self):
        _source,sample=self.acquire(); c=self.controls(sample)
        c._schedule_processing_render(immediate=True); first=c._processing_worker
        first_token=c._render_ownership.generation
        for v in range(105,200,5):
            c._processing_controls['gamma'][0].setValue(v); c._processing_changed(); c._flush_processing_render()
        self.assertEqual(1,len(c.started))
        self.assertTrue(first.interrupted)
        first.finished.emit()
        self.assertEqual(2,len(c.started))
        c._processing_worker.run()
        latest=c.displayed[-1]
        c._on_processing_ready({'processing':ProcessingSettings()},first_token,'sample')
        self.assertIs(latest,c.displayed[-1])
        self.assertEqual(1.95,latest['processing'].gamma)

    def test_reset_is_atomic_one_render_and_finalization_stales(self):
        source,sample=self.acquire(); c=self.controls(sample)
        signature=c.current_signature()
        for slider,_label in c._processing_controls.values(): slider.setValue(150)
        c.grayscale_on.setChecked(True)
        c._processing_changed()
        self.assertNotEqual(signature,c.current_signature())
        c._reset_processing()
        self.assertEqual(signature,c.current_signature())
        self.assertEqual(2,c.transitions)
        self.assertEqual(ProcessingSettings(),c.processing)
        self.assertTrue(c.workflow_state.finalization_stale)
        self.assertEqual((),c.workflow_state.finalization_plan)
        c._flush_processing_render()
        self.assertEqual(1,len(c.started))
        self.assertEqual((1,3),(source.manifests,source.fetches))
        self.assertEqual(['100%','100%','1.00','100%','100%'],[label.text for _slider,label in c._processing_controls.values()])
        self.assertFalse(c.grayscale_on.isChecked()); self.assertTrue(c.grayscale_off.isChecked())
        self.assertFalse(hasattr(c,'resolution'))
        self.assertTrue(c._processing_controls['saturation'][0].enabled)

    def test_sample_change_and_closure_reject_old_renders(self):
        _source,sample=self.acquire(); c=self.controls(sample)
        c._schedule_processing_render(immediate=True); token=c._render_ownership.generation
        c._invalidate_processing_render(); c._live_preview_samples.clear()
        c._on_processing_ready({},token,'sample'); self.assertEqual([],c.displayed)
        c._closing=True
        c._on_processing_ready({},c._render_ownership.generation,'sample')
        self.assertEqual([],c.displayed)

    def test_preview_final_shared_pixels_and_cover_isolation_both_layouts(self):
        for layout in ('original_pages','paired_landscape'):
            for settings in (ProcessingSettings(),ProcessingSettings(1.2,.8,.65),
                             ProcessingSettings(saturation=3),
                             ProcessingSettings(grayscale=True),
                             ProcessingSettings(output_depth=8),
                             ProcessingSettings(grayscale=True,brightness=1.25,sharpness=1.5,output_depth=4,dithering='atkinson',dither_strength=2),
                             ProcessingSettings(brightness=1.5),ProcessingSettings(sharpness=2),
                             ProcessingSettings(1.2,.8,.65,True,brightness=.5,sharpness=0)):
                with self.subTest(layout=layout,settings=settings):
                    source,sample=self.acquire(layout)
                    seen=[]
                    def transform(image, config, **kwargs):
                        result=apply_processing(image, config, **kwargs)
                        seen.append((result.size,result.tobytes()))
                        return result
                    self.ns['apply_processing']=transform
                    for page in range(1,sample['output_pages']+1):
                        preview=self.ns['ProcessingPreviewWorker'](sample,'rtl',settings,detail_page=page)
                        preview.run(); self.assertFalse(preview.failed.calls)
                    expected=seen[:]; seen.clear()
                    worker=self.ns['DownloadWorker'](source,'url','Title','Author','Series','en',1,1,True,True,(),processing=settings,page_layout=layout)
                    state={'bytes':0,'pages_done':0,'pages_total':3,'volume_done':0,'started':time.time()}
                    with tempfile.TemporaryDirectory() as directory:
                        output=Path(directory)/'test.cbz'
                        with patch.object(image_processing,'apply_processing',transform):
                            cover=worker._download_group([{'id':'chapter','chapter':'1','pages':3}],output,'Title',1,'cover.png',state,1,1,3)
                        self.assertEqual(source.blob,Path(cover).read_bytes())
                        self.ns['_validate_cbz_output'](output,layout,settings)
                        with zipfile.ZipFile(output) as z:
                            self.assertIsNone(z.testzip())
                            self.assertIn(b'<Series>Series</Series>',z.read('ComicInfo.xml'))
                            self.assertFalse(any('cover' in n for n in z.namelist()))
                            with Image.open(BytesIO(z.read('00001.png' if layout=='original_pages' else '00001.jpg'))) as im:
                                self.assertEqual((40,60) if layout=='original_pages' else (1680,1264),im.size)
                            if layout=='original_pages' and settings.neutral:
                                self.assertEqual(source.blob,z.read('00001.png'))
                                self.assertEqual([],seen)  # byte-preserving fast path
                            else: self.assertEqual(sorted(expected),sorted(seen))

    def test_final_cbz_entries_are_identical_with_simulator_armed_or_off(self):
        settings=ProcessingSettings(contrast=1.2,sharpness=1.1)
        archives=[]
        for _simulator_id in ('none','kobo_libra_colour'):
            source=Source()
            worker=self.ns['DownloadWorker'](
                source,'url','Title','Author','Series','en',1,1,True,True,(),
                processing=settings,page_layout='original_pages')
            state={'bytes':0,'pages_done':0,'pages_total':3,'volume_done':0,'started':time.time()}
            with tempfile.TemporaryDirectory() as directory:
                output=Path(directory)/'test.cbz'
                worker._download_group([{'id':'chapter','chapter':'1','pages':3}],output,
                                       'Title',1,'cover.png',state,1,1,3)
                with zipfile.ZipFile(output) as archive:
                    archives.append({name:archive.read(name) for name in archive.namelist()})
        self.assertEqual(archives[0],archives[1])

    def test_landscape_neutral_encoding_matches_existing_default(self):
        _source,sample=self.acquire('paired_landscape')
        build=self.ns['build_landscape_pages']
        legacy,stats=build(sample['records'],'rtl')
        neutral,other_stats=build(sample['records'],'rtl',processing=ProcessingSettings())
        self.assertEqual(legacy,neutral); self.assertEqual(stats,other_stats)

    def test_large_inventory_retains_only_bounded_sample(self):
        source=Source()
        source.get_page_manifest=lambda *_a,**_k:{'full':['page.png']*100}
        worker=self.ns['PairingPreviewWorker'](source,'url','en',1,'rtl',[{'id':'one'}],layout='paired_landscape')
        worker.run(); self.assertFalse(worker.failed.calls)
        self.assertEqual(12,len(worker.ready.calls[0][0]['records']))
        self.assertEqual(12,source.fetches)

    def test_decoded_memory_ceiling_fails_preview_without_large_allocation(self):
        source=Source()
        self.ns['_normalize_exif_orientation']=lambda blob,ext:(blob,(10000,10000),False,1)
        worker=self.ns['PairingPreviewWorker'](source,'url','en',1,'rtl',[{'id':'one'}])
        worker.run()
        self.assertEqual([],worker.ready.calls)
        self.assertIn('128 MiB',worker.failed.calls[0][0])

    def test_local_worker_cancellation_produces_no_callback(self):
        _source,sample=self.acquire()
        worker=self.ns['ProcessingPreviewWorker'](sample,'rtl',ProcessingSettings(gamma=.8))
        worker.requestInterruption(); worker.run()
        self.assertEqual([],worker.ready.calls); self.assertEqual([],worker.failed.calls)
        self.assertIsNone(worker.sample)

    def test_grayscale_retains_saturation_and_rerenders_without_network(self):
        source,sample=self.acquire(); c=self.controls(sample)
        saturation=c._processing_controls['saturation'][0]
        saturation.setValue(160); c._processing_changed()
        signature=c.current_signature()
        c.workflow_state.set_finalization_plan(('output',))
        c._choose_grayscale(True)
        self.assertFalse(saturation.enabled); self.assertEqual(1.6,c.processing.saturation)
        self.assertNotEqual(signature,c.current_signature()); self.assertTrue(c.workflow_state.finalization_stale)
        c._choose_grayscale(False)
        self.assertTrue(saturation.enabled); self.assertEqual(160,saturation.value())
        self.assertEqual(1.6,c.processing.saturation)
        c._flush_processing_render(); c._processing_worker.run()
        self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_adjustment_mapping_invalidates_finalization_and_is_local(self):
        source,sample=self.acquire(); c=self.controls(sample)
        for name,ticks in (('brightness',(25,50,100,150,200)),('sharpness',(0,100,200))):
            for tick in ticks:
                c.workflow_state.set_finalization_plan(('output',))
                signature=c.current_signature()
                c._processing_controls[name][0].setValue(tick); c._processing_changed()
                self.assertEqual(tick/100,getattr(c.processing,name))
                self.assertEqual(f'{tick}%',c._processing_controls[name][1].text)
                self.assertNotEqual(signature,c.current_signature())
                self.assertTrue(c.workflow_state.finalization_stale)
        c._flush_processing_render(); c._processing_worker.run()
        self.assertEqual((1,3),(source.manifests,source.fetches))
        self.assertEqual(2,c.displayed[-1]['processing'].brightness)
        self.assertEqual(2,c.displayed[-1]['processing'].sharpness)

    def test_new_controls_off_do_not_enable_preview(self):
        c=self.controls(); c._choose_grayscale(True)
        c._processing_controls['brightness'][0].setValue(150)
        c._processing_controls['sharpness'][0].setValue(200); c._processing_changed()
        self.assertTrue(c.processing.grayscale); self.assertEqual(1.5,c.processing.brightness)
        self.assertEqual(2,c.processing.sharpness)
        self.assertEqual('off',c.workflow_state.preview_state); self.assertEqual([],c.started)

    def test_validator_rejects_wrong_landscape_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'wrong.cbz'; blob=BytesIO()
            Image.new('RGB',(1260,948)).save(blob,'JPEG')
            with zipfile.ZipFile(output,'w') as z: z.writestr('00001.jpg',blob.getvalue())
            with self.assertRaisesRegex(RuntimeError,'1680x1264'):
                self.ns['_validate_cbz_output'](output,'paired_landscape',ProcessingSettings(brightness=1.5))


if __name__=='__main__': unittest.main()
