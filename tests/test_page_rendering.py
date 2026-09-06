from io import BytesIO
from pathlib import Path
from threading import Event, Lock, Barrier, get_ident
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image
import page_rendering as rendering
from image_processing import ProcessingSettings, apply_processing, process_page_blob
from tests import test_empress_pipeline as pipeline


class PoolTests(unittest.TestCase):
    def test_worker_rule(self):
        for cpu,expected in ((12,4),(8,4),(4,2),(2,1),(1,1),(0,1)):
            self.assertEqual(expected,rendering.worker_count(cpu))
        with patch.object(rendering.os,'cpu_count',return_value=None): self.assertEqual(1,rendering.worker_count())

    def test_native_active_diffusion_only(self):
        with patch.object(rendering.native_dithering,'get_backend',return_value=object()),patch.object(rendering.os,'cpu_count',return_value=12):
            self.assertEqual(4,rendering.final_workers(ProcessingSettings(output_depth=8,dithering='atkinson')))
            for settings in (ProcessingSettings(),ProcessingSettings(output_depth=8),ProcessingSettings(output_depth=8,dithering='atkinson',dither_strength=0)):
                self.assertEqual(1,rendering.final_workers(settings))
        with patch.object(rendering.native_dithering,'get_backend',return_value=None):
            self.assertEqual(1,rendering.final_workers(ProcessingSettings(output_depth=8,dithering='atkinson')))

    def test_out_of_order_completion_ordered_results_and_bound(self):
        second=Event(); completion=[]; progress=[]; metrics={}; owner=get_ident()
        def render(index,check):
            check()
            if index==0: self.assertTrue(second.wait(3))
            completion.append(index)
            if index==1: second.set()
            return str(index).encode()
        def completed(count): self.assertEqual(owner,get_ident()); progress.append(count)
        result=list(rendering.ordered_render(range(300),render,4,completed=completed,metrics=metrics))
        self.assertLess(completion.index(1),completion.index(0))
        self.assertEqual([(i,str(i).encode()) for i in range(300)],result)
        self.assertEqual(list(range(1,301)),progress)
        self.assertLessEqual(metrics['peak_outstanding'],8); self.assertEqual(300,metrics['completed'])
        self.assertGreaterEqual(metrics['render_seconds'],0)

    def test_portable_serial_runs_on_owner_thread(self):
        owner=get_ident(); calls=[]
        def render(job,check): check(); calls.append(get_ident()); return job
        list(rendering.ordered_render(range(20),render,1))
        self.assertEqual([owner]*20,calls)

    def test_exception_stops_new_work_and_propagates(self):
        submitted=[]
        def render(job,check):
            submitted.append(job)
            if job==1: raise ValueError('broken page')
            check(); return job
        with self.assertRaisesRegex(ValueError,'broken page'):
            list(rendering.ordered_render(range(300),render,4))
        self.assertLessEqual(len(submitted),8)

    def test_cancellation_stops_pending_batch(self):
        cancelled=Event(); started=[]
        def check():
            if cancelled.is_set(): raise RuntimeError('Download cancelled')
        def render(job,check): started.append(job); check(); return job
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            list(rendering.ordered_render(range(300),render,4,check,lambda n:cancelled.set() if n==2 else None))
        self.assertLessEqual(len(started),8)

    def test_runtime_fallback_gate_serializes_portable_work(self):
        barrier=Barrier(4); switched=Event(); lock=Lock(); active=[0,0]
        def render(job,check):
            barrier.wait(timeout=3); switched.set(); check()
            with lock: active[0]+=1; active[1]=max(active)
            Event().wait(.002)
            with lock: active[0]-=1
            return job
        list(rendering.ordered_render(range(4),render,4,fallback_active=switched.is_set))
        self.assertEqual(1,active[1])

    def test_consumer_close_drains_running_jobs(self):
        active=[]
        def render(job,check):
            active.append(job)
            try: check(); return job
            finally: active.remove(job)
        iterator=rendering.ordered_render(range(50),render,4)
        next(iterator); iterator.close()
        self.assertEqual([],active)


class OrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): pipeline.PipelineTests.setUpClass()
    @classmethod
    def tearDownClass(cls): pipeline.PipelineTests.tearDownClass()
    def setUp(self):
        self.fixture=pipeline.PipelineTests(); self.fixture.setUp(); self.ns=self.fixture.ns

    def test_overview_working_pixels_bounded_and_representative(self):
        source,sample=self.fixture.acquire()
        sample['records'][0]['image']=Image.new('RGB',(1600,2400),(80,120,160))
        seen=[]; original=self.ns['apply_processing']
        def transform(image,settings,**kwargs):
            result=original(image,settings,**kwargs); seen.append(result.size); return result
        self.ns['apply_processing']=transform
        settings=ProcessingSettings(grayscale=True,brightness=1.5,sharpness=2,output_depth=4,dithering='atkinson')
        worker=self.ns['ProcessingPreviewWorker'](sample,'rtl',settings); worker.run()
        self.assertFalse(worker.failed.calls); result=worker.ready.calls[0][0]
        self.assertEqual((360,540),seen[0]); self.assertEqual((40,60),seen[1])
        self.assertEqual((1600,2400),result['dimensions'][1])
        self.assertEqual(3,len(result['provisional_images']))
        self.assertEqual((1,3),(source.manifests,source.fetches))
        image=Image.frombytes('RGBA',(result['provisional_images'][1].width(),result['provisional_images'][1].height()),result['provisional_images'][1].raw)
        self.assertTrue(all(r==g==b for r,g,b,a in image.getdata()))

    def test_selected_detail_renders_exactly_one_job(self):
        for layout in ('original_pages','paired_landscape'):
            source,sample=self.fixture.acquire(layout); seen=[]; original=self.ns['render_output_page']
            def render(job,*args,**kwargs): seen.append(job); return original(job,*args,**kwargs)
            with patch.dict(self.ns,render_output_page=render):
                worker=self.ns['ProcessingPreviewWorker'](sample,'rtl',ProcessingSettings(brightness=1.5,sharpness=2),detail_page=2); worker.run()
            self.assertFalse(worker.failed.calls); data=worker.ready.calls[0][0]
            self.assertEqual(1,len(seen)); self.assertEqual([],data['thumbs']); self.assertEqual({},data['provisional_images'])
            self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_plan_only_never_builds_canvas_and_matches_legacy_pixels(self):
        _source,sample=self.fixture.acquire('paired_landscape')
        with patch.dict(self.ns,_paired_canvas=lambda *a,**k: self.fail('Planning must not composite')):
            jobs,stats=self.ns['output_page_jobs'](sample['records'],'paired_landscape','rtl')
        settings=ProcessingSettings(grayscale=True,output_depth=4,dithering='atkinson')
        for direction in ('rtl','ltr'):
            legacy,_=self.ns['build_landscape_pages'](sample['records'],direction,processing=settings)
            jobs,_=self.ns['output_page_jobs'](sample['records'],'paired_landscape',direction)
            actual=[self.ns['render_output_page'](job,settings)[:2] for job in jobs]
            self.assertEqual([blob for ext,blob in legacy],[blob for ext,blob in actual])

    def test_layout_plan_preserves_spreads_extras_and_reading_direction(self):
        records=[]
        for i,size in enumerate(((100,180),(100,180),(240,170),(100,180),(30,90),(100,180),(100,180))):
            image=Image.new('RGB',size,(i*30,100,180)); encoded=BytesIO(); image.save(encoded,'PNG')
            records.append({'blob':encoded.getvalue(),'size':size,'ext':'.png','page_in_chapter':1,'chapter_pages':1 if i==4 else 9})
        for direction in ('rtl','ltr'):
            expected,stats=self.ns['build_landscape_pages'](records,direction,detailed=True)
            jobs,actual_stats=self.ns['output_page_jobs'](records,'paired_landscape',direction)
            actual=[self.ns['render_output_page'](job,ProcessingSettings()) for job in jobs]
            self.assertEqual(stats,actual_stats)
            self.assertEqual([(blob,kind) for ext,blob,kind in expected],[(blob,kind) for ext,blob,kind in actual])

    def test_detail_change_marks_overview_dirty_without_hidden_render(self):
        _source,sample=self.fixture.acquire(); c=self.fixture.controls(sample)
        c._processed_page_count=3; c._detail_page=2
        c._processing_controls['brightness'][0].setValue(150)
        c._processing_controls['sharpness'][0].setValue(200); c._processing_changed(); c._flush_processing_render()
        c._processing_worker.run()
        self.assertTrue(c._overview_dirty); self.assertEqual([],c.displayed)
        self.assertEqual(2,c._processing_worker.ready.calls[0][0]['detail_page'])

    def test_final_progress_timings_cover_isolation_and_serial_zip_writes(self):
        source=pipeline.Source(); owner=get_ident(); writes=[]
        blobs={}
        for i in range(1,4):
            buffer=BytesIO(); Image.new('RGB',(40,60),(i*55,80,140)).save(buffer,'PNG'); blobs[f'page{i}.png']=buffer.getvalue()
        source.get_page_manifest=lambda *a,**k:{'full':list(blobs)}
        source.fetch_binary=lambda url,**kwargs:source.blob if url=='cover.png' else blobs[url]
        original=zipfile.ZipFile.writestr
        def write(z,*args,**kwargs): writes.append(get_ident()); return original(z,*args,**kwargs)
        worker=self.ns['DownloadWorker'](source,'url','Title','Author','Series','en',1,1,True,True,(),
                         processing=ProcessingSettings(brightness=1.5,sharpness=2,output_depth=8,dithering='atkinson'))
        state={'bytes':0,'pages_done':0,'pages_total':3,'volume_done':0,'started':pipeline.time.time()}
        with tempfile.TemporaryDirectory() as directory,patch.object(zipfile.ZipFile,'writestr',write):
            output=Path(directory)/'test.cbz'
            cover=worker._download_group([{'id':'chapter','chapter':'1','pages':3}],output,'Title',1,'cover.png',state,1,1,3)
            self.assertEqual(source.blob,Path(cover).read_bytes())
            with zipfile.ZipFile(output) as z:
                self.assertEqual(['00001.png','00002.png','00003.png','ComicInfo.xml'],z.namelist())
                self.assertIsNone(z.testzip())
                for i in range(1,4):
                    self.assertEqual(process_page_blob(blobs[f'page{i}.png'],'.png',worker.processing),z.read(f'{i:05d}.png'))
        self.assertEqual([owner]*4,writes)
        messages=[args[1] for args in worker.progress.calls]
        self.assertIn('Processing 0 / 3',messages[0]); self.assertIn('Processing 3 / 3',messages[-2])
        self.assertIn('Writing CBZ',messages[-1])
        logs=[args[0] for args in worker.log.calls]
        self.assertEqual(3,len([line for line in logs if line.startswith('Processing:')]))
        for key in ('acquisition_seconds','render_seconds','write_seconds'):
            self.assertGreaterEqual(state['phase_timings'][0][key],0)

    def test_render_failure_never_publishes_partial_cbz(self):
        source=pipeline.Source()
        worker=self.ns['DownloadWorker'](source,'url','Title','Author','Series','en',1,1,False,True,())
        state={'bytes':0,'pages_done':0,'pages_total':3,'volume_done':0,'started':pipeline.time.time()}
        def fail(*args,**kwargs): raise ValueError('encoding failed')
        with tempfile.TemporaryDirectory() as directory,patch.dict(self.ns,render_output_page=fail):
            output=Path(directory)/'test.cbz'
            with self.assertRaisesRegex(ValueError,'encoding failed'):
                worker._download_group([{'id':'chapter','pages':3}],output,'Title',1,None,state,1,1,3)
            self.assertFalse(output.exists()); self.assertFalse(Path(str(output)+'.part').exists())

    def test_small_processed_overview_never_upscales(self):
        image=Image.new('RGB',(100,50),(90,120,150))
        for ceiling,size in (((720,540),(100,50)),((50,50),(50,25))):
            result=apply_processing(image,ProcessingSettings(brightness=1.5,sharpness=2),working_ceiling=ceiling)
            self.assertEqual(size,result.size)
