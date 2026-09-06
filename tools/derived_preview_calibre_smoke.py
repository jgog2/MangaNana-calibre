"""Real Qt worker acquisition -> Finalization -> CBZ with synthetic title cases.

No network/library access. Set MANGANANA_INTEGRITY_PACKAGED=1 after installing
the final ZIP in an isolated config to exercise packaged modules instead.
"""
from io import BytesIO
from pathlib import Path
import os
import sys
import tempfile
import time
import types
import urllib.request
import zipfile

root=Path(__file__).resolve().parents[1]
config=Path(os.environ['CALIBRE_CONFIG_DIRECTORY']).resolve()
assert config.parent==root and config.name.startswith('.empress-')
if os.environ.get('MANGANANA_INTEGRITY_PACKAGED')=='1':
    from calibre.customize.ui import initialized_plugins
    assert any(p.name=='MangaNana' for p in initialized_plugins())
else:
    package=types.ModuleType('calibre_plugins.manganana'); package.__path__=[str(root)]
    sys.modules['calibre_plugins.manganana']=package
from calibre_plugins.manganana import main
from calibre_plugins.manganana.image_processing import ProcessingSettings
from calibre_plugins.manganana.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.unified_volume import build_unified_volume_plan, selected_unified_volume_groups
from qt.core import QApplication, QEventLoop, QTimer
from PIL import Image

if os.environ.get('MANGANANA_INTEGRITY_PACKAGED')=='1': assert '.zip' in main.__file__.lower()
app=QApplication([])
def forbidden(*args,**kwargs): raise AssertionError('No external network in integrity smoke')
urllib.request.urlopen=forbidden
buffer=BytesIO(); Image.new('RGB',(40,60),(80,120,160)).save(buffer,'PNG'); blob=buffer.getvalue()

def run_worker(worker):
    ready=[]; errors=[]; loop=QEventLoop(); timeout=QTimer(); timeout.setSingleShot(True)
    worker.ready.connect(ready.append); worker.failed.connect(errors.append)
    worker.finished.connect(loop.quit); timeout.timeout.connect(loop.quit)
    timeout.start(60000); worker.start(); loop.exec()
    if not timeout.isActive():
        worker.requestInterruption(); worker.wait(); raise AssertionError('Worker timed out')
    timeout.stop(); worker.wait(); app.processEvents()
    assert not errors,errors
    assert len(ready)==1
    return ready[0]

for title,provider,native in (('Attack on Titan','weebcentral',False),
                              ('Chainsaw Man','mangapill',False),
                              ('Chainsaw Man','weebcentral',False),
                              ('Steel Ball Run','mangadex',True)):
    rows=tuple({'id':f'{provider}-{i}','chapter':str(i),'volume':1. if native else None,
                '_source_id':provider,'pages':1} for i in range(1,4))
    class Source:
        display_name=title; source_id=provider; capabilities=()
        def __init__(self): self.lookups=0; self.manifests=[]
        def get_chapters(self,url,language,start,end):
            assert native, 'Derived volume must not query native range'
            assert (start,end)==(1.,1.)
            self.lookups+=1; return rows
        def get_page_manifest(self,chapter,**kwargs):
            self.manifests.append(chapter); return {'full':['page.png']}
        def fetch_preview_page(self,*args,**kwargs): return blob,False
        def fetch_binary(self,*args,**kwargs): return blob
    source=Source(); main.SOURCE_REGISTRY=types.SimpleNamespace(get=lambda key:source if key==provider else None)
    if native:
        plan={'volumes':[1.]}  # legacy native plan deliberately has no groups
        groups=None
    else:
        manifest=PublicationManifestBuilder({'title':title}).apply_wikipedia({
            'status':'valid_with_data','chapters':[{'chapter':str(i),'volume':'1'} for i in range(1,4)]}).build()
        plan=build_unified_volume_plan({},rows,build_publication_projection(rows,manifest,provider,provider),provider,provider)
        groups=selected_unified_volume_groups(plan,(1.,),False)
    selection=types.SimpleNamespace(_has_volume_selection=lambda:True,loaded_metadata={'title':title},
        workflow_mode='volume',_selected_volumes={1.},_standalone_selected=False,_current_plan=plan)
    target=main.MangaNanaDialog._preview_sample_target(selection)
    preview=run_worker(main.PairingPreviewWorker(source,'url','en',target['volume'],'rtl',target['chapters'],layout='original_pages'))
    assert preview['source_pages']==3 and source.manifests==[r['id'] for r in rows]
    final=run_worker(main.PreviewWorker(source,'url',title,'Author',title,'en',1.,1.,True,(),chapter_output_plan=groups))
    selected=rows if native else final['rows'][0]['group']['chapters']
    if not native: assert [r['id'] for r in target['chapters']]==[r['id'] for r in selected]
    settings=ProcessingSettings(brightness=1.5,sharpness=2)
    worker=main.DownloadWorker(source,'url',title,'Author',title,'en',1,1,True,True,(),processing=settings)
    state={'bytes':0,'pages_done':0,'pages_total':3,'volume_done':0,'started':time.time()}
    with tempfile.TemporaryDirectory(dir=config,prefix='derived-smoke-') as directory:
        output=Path(directory)/'fixture.cbz'
        cover=worker._download_group(selected,output,title,1.,'cover.png',state,1,1,3)
        assert Path(cover).read_bytes()==blob
        main._validate_cbz_output(output,'original_pages',settings)
        with zipfile.ZipFile(output) as z:
            assert z.testzip() is None
            assert z.namelist()==['00001.png','00002.png','00003.png','ComicInfo.xml']
    assert source.lookups==(2 if native else 0)
    print(f'{title}/{provider}: Preview -> Finalization -> ordered CBZ PASS; native lookups={source.lookups}')
print('DERIVED_NATIVE_QT_WORKERS_AND_COVER_ISOLATION=PASS; EXTERNAL_NETWORK_CALLS=0')
