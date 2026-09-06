"""Handoff byte hashes, strict native/Python parity and safe loader failures."""
import ctypes
import hashlib
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import dithering
import native_dithering as native

FIXTURES = Path(__file__).parent/'fixtures/native_dithering'
DLL = Path(__file__).resolve().parents[1]/native.RESOURCE


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.patches=[patch.object(native,'_attempted',False),patch.object(native,'_backend',None),
                      patch.object(native,'_status','not attempted'),patch.object(native,'_logged',set())]
        for p in self.patches: p.start(); self.addCleanup(p.stop)

    def rejected(self, **kwargs):
        with patch.object(native,'supported',return_value=True), patch.object(native,'_resource_bytes',return_value=b'dll'), \
                patch.object(native,'extract_library',return_value=DLL), patch.object(native.ctypes,'CDLL',**kwargs) as load, \
                patch.object(native,'_notice') as log:
            self.assertIsNone(native.get_backend()); self.assertIsNone(native.get_backend())
            self.assertEqual(1,load.call_count); self.assertEqual(1,log.call_count)
            self.assertIn('portable',native.backend_status())

    @staticmethod
    def fake_library(abi=1, rc=0):
        def version(): return abi
        def transform(*args): return rc
        return SimpleNamespace(manganana_dither_abi_version=version,manganana_dither_u8=transform)

    def test_wrong_abi_rejected(self): self.rejected(return_value=self.fake_library(2))
    def test_missing_symbol_rejected(self): self.rejected(return_value=object())
    def test_load_error_rejected(self): self.rejected(side_effect=OSError('load failed'))
    def test_bad_pixels_validation_rejected(self): self.rejected(return_value=self.fake_library())
    def test_nonzero_native_error_rejected(self): self.rejected(return_value=self.fake_library(rc=-5))

    def test_missing_library_falls_back_once(self):
        with patch.object(native,'supported',return_value=True), patch.object(native,'_resource_bytes',side_effect=FileNotFoundError('missing')) as read, patch.object(native,'_notice') as log:
            im=Image.new('L',(9,9),128)
            self.assertEqual(dithering.quantize(im,4,'atkinson',backend='python').tobytes(),dithering.quantize(im,4,'atkinson').tobytes())
            native.get_backend(); self.assertEqual(1,read.call_count); self.assertEqual(1,log.call_count)

    def test_unsupported_platform_never_reads_or_loads_dll(self):
        with patch.object(native,'supported',return_value=False),patch.object(native,'_resource_bytes') as read:
            self.assertIsNone(native.get_backend()); read.assert_not_called()

    def test_architecture_guard(self):
        for os_name,machine,size,expected in [('win32','AMD64',8,True),('win32','ARM64',8,False),('win32','AMD64',4,False),('linux','x86_64',8,False)]:
            with patch.object(native.sys,'platform',os_name),patch.object(native.platform,'machine',return_value=machine),patch.object(native.ctypes,'sizeof',return_value=size):
                self.assertEqual(expected,native.supported())

    def test_content_addressed_extraction_and_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            first=native.extract_library(b'first',directory); stamp=first.stat().st_mtime_ns
            self.assertEqual(first,native.extract_library(b'first',directory))
            self.assertEqual(stamp,first.stat().st_mtime_ns)
            second=native.extract_library(b'second',directory)
            self.assertNotEqual(first,second); self.assertEqual(b'first',first.read_bytes())
            self.assertIn(hashlib.sha256(b'second').hexdigest(),str(second))

    def test_corrupt_cached_dll_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target=native.extract_library(b'first',directory)
            with patch.object(Path,'read_bytes',return_value=b'corrupt'):
                with self.assertRaisesRegex(ValueError,'hash mismatch'): native.extract_library(b'first',directory)

    def test_packaged_resource_callback_used(self):
        with patch.dict(native.__dict__,{'get_resources':lambda name:b'packaged' if name==native.RESOURCE else None}):
            self.assertEqual(b'packaged',native._resource_bytes())

    def test_native_runtime_failure_restarts_portable_and_disables(self):
        def fail(*args): raise RuntimeError('native failure')
        native._attempted=True; native._backend=SimpleNamespace(transform=fail)
        im=Image.new('RGB',(9,9),(70,120,190))
        expected=dithering.quantize(im,8,'atkinson',backend='python')
        with patch.object(dithering,'_get_accelerator',side_effect=AssertionError('Auto must not require Numba')):
            result=dithering.quantize(im,8,'atkinson')
        self.assertEqual(expected.tobytes(),result.tobytes()); self.assertIsNone(native.get_backend())

    def test_native_cancellation_before_and_after_is_not_backend_failure(self):
        im=Image.new('L',(2,2),128)
        backend=SimpleNamespace(transform=lambda *args: bytes((85,170,85,170)))
        for when in (1,2):
            calls=[]
            def cancel():
                calls.append(True)
                if len(calls)==when: raise InterruptedError()
            with patch.object(native,'get_backend',return_value=backend),patch.object(native,'disable_backend') as disable:
                with self.assertRaises(InterruptedError): dithering.quantize(im,4,'atkinson',check_cancel=cancel)
                disable.assert_not_called()

    def test_neutral_hard_and_zero_do_not_load_native(self):
        im=Image.new('L',(2,2),128)
        with patch.object(native,'get_backend',side_effect=AssertionError('No DLL needed')):
            self.assertIs(im,dithering.quantize(im,0))
            self.assertEqual(dithering.quantize(im,4).tobytes(),dithering.quantize(im,4,'atkinson',0).tobytes())


@unittest.skipUnless(native.supported() and DLL.is_file(),'Windows x64 native build required')
class NativeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.backend=native.NativeBackend(ctypes.CDLL(str(DLL),winmode=0x1100))

    def test_valid_library_loads_and_is_selected(self):
        im=Image.new('RGB',(10,10),(60,120,180))
        with patch.object(native,'get_backend',return_value=self.backend),patch.object(dithering,'_diffuse_rows',side_effect=AssertionError('Native expected')):
            dithering.quantize(im,8,'atkinson')

    def test_all_supplied_fixture_hashes_and_python_oracle(self):
        vectors=json.loads((FIXTURES/'expected_sha256.json').read_text())
        count=0
        for name,spec in vectors.items():
            with Image.open(FIXTURES/f'{name}_input.png') as im:
                self.assertEqual(spec['source_sha256'],hashlib.sha256(im.tobytes()).hexdigest().upper())
                for key,expected in spec['cases'].items():
                    args=dict(v.split('=') for v in key.split(';'))
                    levels=int(args['levels']); strength=float(args['strength']); algorithm=args['algorithm']
                    with self.subTest(fixture=name,case=key):
                        portable=dithering.quantize(im,levels,algorithm,strength,backend='python').tobytes()
                        self.assertEqual(expected,hashlib.sha256(portable).hexdigest().upper())
                        if algorithm=='off':
                            actual=dithering.quantize(im,levels,algorithm,strength,backend='native').tobytes()
                        else: actual=self.backend.transform(im.tobytes(),im.width,im.height,len(im.getbands()),levels,strength,algorithm)
                        self.assertEqual(portable,actual)
                    count+=1
        self.assertEqual(112,count)

    def test_all_strength_ticks_edges_and_random_pixels(self):
        rng=random.Random(23)
        for mode,channels in [('L',1),('RGB',3)]:
            for width,height in [(1,1),(1,35),(35,1),(13,17)]:
                source=bytes(rng.randrange(256) for _ in range(width*height*channels))
                im=Image.frombytes(mode,(width,height),source)
                for levels in ((2,4,8,16) if mode=='L' else (4,8,16)):
                    for algorithm in native.ALG_IDS:
                        for tick in range(41):
                            strength=tick/20
                            self.assertEqual(dithering.quantize(im,levels,algorithm,strength,backend='python').tobytes(),
                                             self.backend.transform(source,width,height,channels,levels,strength,algorithm))

    def test_abi_invalid_inputs_return_errors(self):
        buf=(ctypes.c_uint8*3)(1,2,3)
        for w,h,c,levels,strength,algo in [(0,1,1,4,1,1),(1,1,2,4,1,1),(1,1,1,3,1,1),(1,1,1,4,float('nan'),1),(1,1,1,4,2.1,1),(1,1,1,4,1,9),(2147483647,1,1,4,1,1)]:
            self.assertLess(self.backend.function(buf,buf,w,h,c,levels,strength,algo),0)

    def test_wrapper_rejects_short_buffer(self):
        with self.assertRaises(ValueError): self.backend.transform(b'abc',20,20,3,8,1,'atkinson')
