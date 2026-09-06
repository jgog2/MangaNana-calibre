"""Run against the installed ZIP in a disposable repo-local Calibre config."""
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.request
import zipfile

from calibre.constants import config_dir
from calibre.customize.ui import initialized_plugins

root=Path(__file__).resolve().parents[1]
assert Path(config_dir).resolve().parent==root and Path(config_dir).name.startswith('.empress-native-')
plugins=[p for p in initialized_plugins() if p.name=='MangaNana']
assert len(plugins)==1 and plugins[0].version==(0,12,0)
from calibre_plugins.manganana import main, native_dithering
from calibre_plugins.manganana.image_processing import ProcessingSettings, process_page_blob
from calibre_plugins.manganana.processing_presets import (
    BUILTIN_PRESETS_BY_ID, settings_from_payload, settings_to_payload,
)
from calibre_plugins.manganana.dithering import quantize
from PIL import Image

assert '.zip' in native_dithering.__file__.lower(), native_dithering.__file__
assert '.zip' in sys.modules['calibre_plugins.manganana.processing_presets'].__file__.lower()
assert settings_from_payload(settings_to_payload(BUILTIN_PRESETS_BY_ID['color_enhancement'].settings)) == BUILTIN_PRESETS_BY_ID['color_enhancement'].settings
assert callable(native_dithering.__dict__.get('get_resources')), 'Must use Calibre ZIP resources'
expected_backend=os.environ.get('MANGANANA_SMOKE_EXPECT_BACKEND','native')
if expected_backend=='portable':
    def missing(): raise FileNotFoundError('Synthetic missing packaged DLL')
    native_dithering._resource_bytes=missing

def forbidden(*args,**kwargs): raise AssertionError('No network allowed')
urllib.request.urlopen=forbidden
image=Image.frombytes('RGB',(40,60),bytes((i*37+i//40*13)%256 for i in range(40*60*3)))
buffer=BytesIO(); image.save(buffer,'PNG'); blob=buffer.getvalue()

class Source:
    display_name='Synthetic'; source_id='synthetic'; capabilities=()
    def get_page_manifest(self,*args,**kwargs): return {'full':['page.png']*3}
    def fetch_binary(self,*args,**kwargs): return blob

for layout in ('original_pages','paired_landscape'):
    settings=ProcessingSettings(grayscale=True,brightness=1.25,sharpness=1.5,output_depth=4,dithering='atkinson',dither_strength=1.5)
    worker=main.DownloadWorker(Source(),'url','Title','Author','Series','en',1,1,True,True,(),processing=settings,page_layout=layout)
    state={'bytes':0,'pages_done':0,'pages_total':3,'volume_done':0,'started':time.time()}
    with tempfile.TemporaryDirectory(dir=config_dir,prefix='output-') as temporary:
        output=Path(temporary)/'test.cbz'
        cover=worker._download_group([{'id':'chapter','chapter':'1','pages':3}],output,'Title',1,'cover.png',state,1,1,3)
        assert Path(cover).read_bytes()==blob, 'Cover must be untouched'
        main._validate_cbz_output(output,layout,settings)
        with zipfile.ZipFile(output) as z:
            assert z.testzip() is None
            extension,count=('.png',3) if layout=='original_pages' else ('.jpg',2)
            assert z.namelist()==[f'{i+1:05d}{extension}' for i in range(count)]+['ComicInfo.xml']
            if layout=='original_pages': assert z.read('00001.png')==process_page_blob(blob,'.png',settings)
assert process_page_blob(blob,'.png',ProcessingSettings())==blob
for algorithm in native_dithering.ALG_IDS:
    assert quantize(image,8,algorithm,2,backend='python').tobytes()==quantize(image,8,algorithm,2).tobytes()
assert native_dithering.backend_status().startswith(expected_backend),native_dithering.backend_status()
print('PACKAGED_CALIBRE_LOADER_AND_FINAL_CBZ=PASS')
print('BACKEND=',native_dithering.backend_status())
print('COVERS_NEUTRAL_ENCODING_AND_PARITY=PASS; NETWORK_CALLS=0')
if expected_backend=='native':
    backend=native_dithering.get_backend()
    print('EXTRACTED_LIBRARY=',backend.library._name)
