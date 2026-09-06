"""Lab-derived independent full-buffer oracle vs production rolling kernels."""
from array import array
from io import BytesIO
import math
import random
import unittest
from unittest.mock import patch

from PIL import Image
import dithering
from image_processing import ProcessingSettings, apply_processing, process_page_blob
from tests import test_empress_pipeline as pipeline


def lab_oracle(image, levels, algorithm, strength, serpentine=True):
    # Independent full-image implementation of the supplied lab. Deliberate
    # correction: round the output palette instead of truncating the uint8 cast.
    kernels = {
        'floyd-steinberg': [(1,0,7/16),(-1,1,3/16),(0,1,5/16),(1,1,1/16)],
        'atkinson': [(1,0,1/8),(2,0,1/8),(-1,1,1/8),(0,1,1/8),(1,1,1/8),(0,2,1/8)],
        'sierra-lite': [(1,0,.5),(-1,1,.25),(0,1,.25)],
    }
    w,h=image.size; c=len(image.getbands())
    # array(bytes) interprets binary floats; populate numeric channel values.
    work=array('f',list(image.tobytes())); output=bytearray(w*h*c); step=255/(levels-1)
    for y in range(h):
        direction=-1 if serpentine and y%2 else 1
        for x in (range(w) if direction==1 else range(w-1,-1,-1)):
            for ch in range(c):
                i=(y*w+x)*c+ch; old=min(255,max(0,float(work[i])))
                new=math.floor(old/step+.5)*step; output[i]=round(new)
                error=(old-new)*strength
                for dx,dy,weight in kernels[algorithm]:
                    nx,ny=x+dx*direction,y+dy
                    if 0<=nx<w and ny<h:
                        j=(ny*w+nx)*c+ch; work[j]+=error*weight
    return bytes(output)


def fixture(mode='RGB', size=(19,21)):
    rng=random.Random(710)
    return Image.frombytes(mode,size,bytes(rng.randrange(256) for _ in range(size[0]*size[1]*(3 if mode=='RGB' else 1))))


class DepthTests(unittest.TestCase):
    def test_original_identity(self):
        im=fixture(); self.assertIs(im,dithering.quantize(im,0,'atkinson',2))
        self.assertIs(im,apply_processing(im,ProcessingSettings()))

    def test_grayscale_palettes(self):
        im=Image.frombytes('L',(256,1),bytes(range(256)))
        for levels in (16,8,4,2):
            self.assertEqual(set(dithering.palette(levels)),set(dithering.quantize(im,levels).getdata()))

    def test_rgb_independent_palettes(self):
        im=Image.frombytes('RGB',(256,1),bytes(v for i in range(256) for v in (i,255-i,(i+83)%256)))
        for levels in (16,8,4):
            for channel in dithering.quantize(im,levels).split():
                self.assertEqual(set(dithering.palette(levels)),set(channel.getdata()))

    def test_diffusion_uses_same_rounded_palette(self):
        for mode in ('L','RGB'):
            for levels in (2,4,8,16):
                for algo in dithering.KERNELS:
                    out=dithering.quantize(fixture(mode),levels,algo,backend='python')
                    self.assertLessEqual(set(out.tobytes()),set(dithering.palette(levels)))

    def test_alpha_and_source_unchanged(self):
        im=fixture().convert('RGBA'); im.putalpha(71); before=im.tobytes()
        result=apply_processing(im,ProcessingSettings(output_depth=8,dithering='atkinson'))
        self.assertEqual(before,im.tobytes()); self.assertEqual({71},set(result.getchannel('A').getdata()))

    def test_png_encoding_unchanged_policy_and_shared_pixels(self):
        im=fixture(); blob=BytesIO(); im.save(blob,'PNG')
        settings=ProcessingSettings(output_depth=8,dithering='sierra-lite')
        result=Image.open(BytesIO(process_page_blob(blob.getvalue(),'.png',settings)))
        self.assertEqual('PNG',result.format)
        self.assertEqual(apply_processing(im,settings).tobytes(),result.tobytes())

    def test_jpeg_not_replaced_by_png(self):
        blob=BytesIO(); fixture().save(blob,'JPEG')
        result=Image.open(BytesIO(process_page_blob(blob.getvalue(),'.jpg',ProcessingSettings(output_depth=4))))
        self.assertEqual('JPEG',result.format)

    def test_settings_validation(self):
        for kwargs in ({'output_depth':2},{'output_depth':3},{'dithering':'random'},{'dither_strength':2.01},{'dither_strength':float('nan')}):
            with self.assertRaises(ValueError): ProcessingSettings(**kwargs)


class DiffusionTests(unittest.TestCase):
    def assert_kernel(self, algorithm):
        for mode in ('L','RGB'):
            for levels in (2,4,8,16):
                for strength in (.05,1.,2.):
                    im=fixture(mode)
                    actual=dithering.quantize(im,levels,algorithm,strength,backend='python').tobytes()
                    self.assertEqual(lab_oracle(im,levels,algorithm,strength),actual)

    def test_floyd_steinberg_lab_kernel(self): self.assert_kernel('floyd-steinberg')
    def test_atkinson_lab_kernel(self): self.assert_kernel('atkinson')
    def test_sierra_lite_lab_kernel(self): self.assert_kernel('sierra-lite')

    def test_atkinson_distributes_six_eighths(self):
        self.assertEqual(.75,sum(v[2] for v in dithering.KERNELS['atkinson']))

    def test_zero_strength_is_exact_hard_quantization(self):
        for mode in ('L','RGB'):
            for levels in (2,4,8,16):
                for algo in dithering.KERNELS:
                    im=fixture(mode)
                    self.assertEqual(dithering.quantize(im,levels).tobytes(),dithering.quantize(im,levels,algo,0).tobytes())

    def test_serpentine_not_unidirectional(self):
        im=fixture('L')
        for algo in dithering.KERNELS:
            actual=dithering.quantize(im,4,algo,backend='python').tobytes()
            self.assertNotEqual(actual,lab_oracle(im,4,algo,1,False))

    def test_double_strength_not_clamped(self):
        im=Image.frombytes('L',(2,1),bytes((80,65)))
        self.assertEqual(bytes((0,0)),dithering.quantize(im,2,'sierra-lite',1,backend='python').tobytes())
        self.assertEqual(bytes((0,255)),dithering.quantize(im,2,'sierra-lite',2,backend='python').tobytes())

    def test_degenerate_edges_and_row_chunk_boundaries(self):
        for size in ((1,1),(1,35),(35,1),(2,35)):
            im=fixture('L',size)
            for algo in dithering.KERNELS:
                self.assertEqual(lab_oracle(im,8,algo,2),dithering.quantize(im,8,algo,2,backend='python').tobytes())

    def test_optional_numba_exact_integer_parity(self):
        if dithering._get_accelerator() is None: self.skipTest('Numba unavailable')
        for mode in ('L','RGB'):
            for levels in (2,4,8,16):
                for algo in dithering.KERNELS:
                    for strength in (.05,1.,2.):
                        im=fixture(mode)
                        actual=dithering.quantize(im,levels,algo,strength,backend='numba').tobytes()
                        self.assertEqual(lab_oracle(im,levels,algo,strength),actual)

    def test_fallback_without_acceleration(self):
        im=fixture()
        with patch.object(dithering.native_dithering,'get_backend',return_value=None), patch.object(dithering,'_get_accelerator',side_effect=AssertionError('Portable fallback must not import Numba')):
            self.assertEqual(lab_oracle(im,8,'atkinson',1),dithering.quantize(im,8,'atkinson').tobytes())

    def test_explicit_numba_failure_leaves_original_for_portable_retry(self):
        try: import numpy as np
        except ImportError: self.skipTest('Optional NumPy unavailable')
        def broken(*args): args[1][0]=255; raise RuntimeError('optional runtime failure')
        im=fixture()
        before=im.tobytes()
        with patch.object(dithering,'_accelerator',None), patch.object(dithering,'_get_accelerator',return_value=(np,broken)):
            with self.assertRaises(RuntimeError): dithering.quantize(im,8,'atkinson',backend='numba')
        self.assertEqual(before,im.tobytes())
        self.assertEqual(lab_oracle(im,8,'atkinson',1),dithering.quantize(im,8,'atkinson',backend='python').tobytes())

    def test_cooperative_cancel_between_scanline_chunks(self):
        calls=[]
        def cancel():
            calls.append(True)
            if len(calls)==2: raise InterruptedError()
        with self.assertRaises(InterruptedError):
            dithering.quantize(fixture('L',(30,50)),4,'atkinson',backend='python',check_cancel=cancel)
        self.assertEqual(2,len(calls))

    def test_final_download_runtime_cancel_does_not_disable_accelerator(self):
        accelerator=dithering._get_accelerator()
        if accelerator is None: self.skipTest('Numba unavailable')
        def cancel(): raise RuntimeError('Download cancelled.')
        with self.assertRaisesRegex(RuntimeError,'Download cancelled'):
            dithering.quantize(fixture(),4,'atkinson',backend='numba',check_cancel=cancel)
        self.assertIs(accelerator,dithering._accelerator)

    def test_missing_numba_import_is_portable(self):
        import builtins
        original=builtins.__import__
        def unavailable(name,*args,**kwargs):
            if name in ('numba','numpy'): raise ImportError('Not installed')
            return original(name,*args,**kwargs)
        with patch.object(dithering.native_dithering,'get_backend',return_value=None), patch.object(dithering,'_attempted',False), patch.object(dithering,'_accelerator',None), patch('builtins.__import__',side_effect=unavailable):
            self.assertEqual(lab_oracle(fixture(),8,'atkinson',1),dithering.quantize(fixture(),8,'atkinson').tobytes())


class DepthControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): pipeline.PipelineTests.setUpClass()
    @classmethod
    def tearDownClass(cls): pipeline.PipelineTests.tearDownClass()
    def setUp(self):
        self.fixture=pipeline.PipelineTests(); self.fixture.setUp()

    def test_choices_dependencies_and_saturation_preservation(self):
        c=self.fixture.controls(); c._processing_changed()
        self.assertEqual(['Original','4096 Colors','512 Colors','64 Colors'],[v[0] for v in c.output_depth.items])
        self.assertFalse(c.dithering.enabled); self.assertFalse(c.dither_strength.enabled)
        c.output_depth.setCurrentIndex(2); c._processing_changed()
        self.assertTrue(c.dithering.enabled); self.assertFalse(c.dither_strength.enabled)
        c.dithering.setCurrentIndex(2); c.dither_strength.setValue(200); c._processing_changed()
        self.assertTrue(c.dither_strength.enabled); self.assertEqual(2,c.processing.dither_strength)
        c._processing_controls['saturation'][0].setValue(155); c._choose_grayscale(True)
        self.assertEqual(['Original','16 Gray Levels','8 Gray Levels','4 Gray Levels','2 Gray Levels'],[v[0] for v in c.output_depth.items])
        self.assertEqual(8,c.processing.output_depth)
        c.output_depth.setCurrentIndex(4); c._processing_changed(); c._choose_grayscale(False)
        self.assertEqual(0,c.processing.output_depth)  # No 2/channel color target.
        self.assertEqual(155,c._processing_controls['saturation'][0].value())

    def test_reset_atomic_and_network_isolation_with_stale_finalization(self):
        source,sample=self.fixture.acquire(); c=self.fixture.controls(sample)
        c.output_depth.setCurrentIndex(2); c.dithering.setCurrentIndex(3); c.dither_strength.setValue(200)
        c._processing_changed(); self.assertTrue(c.workflow_state.finalization_stale)
        c._flush_processing_render(); c._processing_worker.run(); c._processing_worker.finished.emit()
        before=c.transitions
        c._reset_processing()
        self.assertEqual(before+1,c.transitions); self.assertEqual(ProcessingSettings(),c.processing)
        c._flush_processing_render(); c._processing_worker.run()
        self.assertEqual((1,3),(source.manifests,source.fetches))

    def test_preview_and_final_landscape_shared_quantization(self):
        source,sample=self.fixture.acquire('paired_landscape')
        settings=ProcessingSettings(brightness=1.5,sharpness=2,output_depth=4)
        worker=self.fixture.ns['ProcessingPreviewWorker'](sample,'rtl',settings,detail_page=1)
        worker.run(); self.assertFalse(worker.failed.calls)
        pages,_=self.fixture.ns['build_landscape_pages'](sample['records'],'rtl',processing=settings,in_memory=True)
        self.assertEqual(pages[0][1].convert('RGBA').tobytes(),worker.ready.calls[0][0]['detail_image'].raw)
        self.assertEqual((1,3),(source.manifests,source.fetches))
