"""Calibre serial-native vs bounded-parallel-native processing/encoding/ZIP."""
from io import BytesIO
from pathlib import Path
import hashlib
import os
import sys
import tempfile
from time import perf_counter
import types
import zipfile

root=Path(__file__).resolve().parents[1]
assert Path(os.environ['CALIBRE_CONFIG_DIRECTORY']).resolve().parent==root
package=types.ModuleType('calibre_plugins.manganana'); package.__path__=[str(root)]
sys.modules['calibre_plugins.manganana']=package
from PIL import Image
from calibre_plugins.manganana.main import output_page_jobs, render_output_page
from calibre_plugins.manganana.image_processing import ProcessingSettings
from calibre_plugins.manganana.page_rendering import ordered_render, final_workers
from calibre_plugins.manganana import native_dithering

settings=ProcessingSettings(output_depth=8,dithering='atkinson')
assert native_dithering.get_backend() is not None
workers=final_workers(settings)
base=bytes((i*37+i//1680*13)%256 for i in range(1680*1264*3))
records=[]
for page in range(12):
    im=Image.frombytes('RGB',(1680,1264),base)
    im.putpixel((page,page),(page*19,83,137))
    out=BytesIO(); im.save(out,'PNG')
    records.append({'blob':out.getvalue(),'size':im.size,'ext':'.png'})
jobs,_=output_page_jobs(records,'original_pages','rtl')
digests=[]; durations=[]
with tempfile.TemporaryDirectory(dir=os.environ['CALIBRE_CONFIG_DIRECTORY'],prefix='benchmark-') as temporary:
    for count in (1,workers):
        metrics={}; target=Path(temporary)/f'{count}.cbz'; started=perf_counter()
        iterator=ordered_render(jobs,lambda job,check:render_output_page(job,settings,check),count,
                                metrics=metrics,fallback_active=lambda:native_dithering.backend_status()!='native')
        try:
            with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_STORED) as z:
                for index,(ext,blob,kind) in iterator: z.writestr(f'{index+1:05d}{ext}',blob)
        finally: iterator.close()
        duration=perf_counter()-started; durations.append(duration)
        with zipfile.ZipFile(target) as z:
            assert z.testzip() is None
            digests.append([(name,hashlib.sha256(z.read(name)).hexdigest()) for name in z.namelist()])
        print(f'Pages={len(jobs)} workers={count} wall_seconds={duration:.4f} peak_outstanding={metrics["peak_outstanding"]}',flush=True)
assert digests[0]==digests[1]
print(f'Speedup={durations[0]/durations[1]:.3f}x; ordered encoded output parity=exact')
