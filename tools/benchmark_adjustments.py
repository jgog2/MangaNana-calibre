"""Calibre A/B: neutral vs modest Pillow adjustments through real final jobs.

Use a disposable repo-local CALIBRE_CONFIG_DIRECTORY. Synthetic input creation,
backend validation and warm-up are excluded; timed work includes encode/serial ZIP.
"""
from io import BytesIO
from pathlib import Path
import os
import statistics
import sys
import tempfile
from time import perf_counter
import types
import zipfile
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
assert Path(os.environ['CALIBRE_CONFIG_DIRECTORY']).resolve().parent==root
package=types.ModuleType('calibre_plugins.manganana'); package.__path__=[str(root)]
sys.modules['calibre_plugins.manganana']=package
from PIL import Image, ImageEnhance
from calibre_plugins.manganana import image_processing
from calibre_plugins.manganana.main import output_page_jobs, render_output_page
from calibre_plugins.manganana.image_processing import ProcessingSettings
from calibre_plugins.manganana.page_rendering import ordered_render, final_workers
from calibre_plugins.manganana import native_dithering

settings={
    'A':ProcessingSettings(output_depth=8,dithering='atkinson'),
    'B':ProcessingSettings(brightness=1.25,sharpness=1.5,output_depth=8,dithering='atkinson'),
}
assert native_dithering.get_backend() is not None
base=bytes((i*37+i//1680*13)%256 for i in range(1680*1264*3))
records=[]
for page in range(12):
    im=Image.frombytes('RGB',(1680,1264),base)
    im.putpixel((page,page),(page*19,83,137))
    out=BytesIO(); im.save(out,'PNG')
    records.append({'blob':out.getvalue(),'size':im.size,'ext':'.png'})
jobs,_=output_page_jobs(records,'original_pages','rtl')
for config in settings.values(): render_output_page(jobs[0],config)
durations={'A':[],'B':[]}
with tempfile.TemporaryDirectory(dir=os.environ['CALIBRE_CONFIG_DIRECTORY'],prefix='benchmark-') as temporary:
    for label in ('A','B','B','A','A','B'):
        config=settings[label]; workers=final_workers(config); metrics={}
        target=Path(temporary)/f'{label}.cbz'; started=perf_counter()
        iterator=ordered_render(jobs,lambda job,check:render_output_page(job,config,check),workers,
                                metrics=metrics,fallback_active=lambda:native_dithering.backend_status()!='native')
        try:
            with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_STORED) as z:
                for index,(ext,blob,kind) in iterator: z.writestr(f'{index+1:05d}{ext}',blob)
        finally: iterator.close()
        duration=perf_counter()-started; durations[label].append(duration)
        with zipfile.ZipFile(target) as z:
            assert z.testzip() is None
            assert z.namelist()==[f'{i+1:05d}.png' for i in range(len(jobs))]
        print(f'{label}: brightness={config.brightness} sharpness={config.sharpness} '
              f'pages={len(jobs)} workers={workers} seconds={duration:.4f} '
              f'peak_outstanding={metrics["peak_outstanding"]}',flush=True)
a,b=(statistics.median(durations[label]) for label in ('A','B'))
print(f'Median A={a:.4f}s B={b:.4f}s change={(b/a-1)*100:.2f}%; ordered ZIP integrity=PASS')

# Diagnostic only: sums of per-page elapsed time (overlapping across workers),
# not additive wall-clock phase timings. Detect fallback/encoding vs filter cost.
for label,config in settings.items():
    stages={name:[] for name in ('transform','depth','brightness','sharpness')}
    def timed(name,fn):
        def call(*args,**kwargs):
            start=perf_counter()
            try: return fn(*args,**kwargs)
            finally: stages[name].append(perf_counter()-start)
        return call
    def enhancement(name,cls):
        def create(image):
            start=perf_counter(); enhancer=cls(image)
            def enhance(factor):
                try: return enhancer.enhance(factor)
                finally: stages[name].append(perf_counter()-start)
            return types.SimpleNamespace(enhance=enhance)
        return create
    with patch.object(image_processing,'apply_processing',timed('transform',image_processing.apply_processing)), \
         patch.object(image_processing,'quantize',timed('depth',image_processing.quantize)), \
         patch.object(ImageEnhance,'Brightness',enhancement('brightness',ImageEnhance.Brightness)), \
         patch.object(ImageEnhance,'Sharpness',enhancement('sharpness',ImageEnhance.Sharpness)):
        started=perf_counter()
        results=list(ordered_render(jobs,lambda job,check:render_output_page(job,config,check),final_workers(config)))
    assert native_dithering.backend_status()=='native'
    print(f'{label} diagnostic wall={perf_counter()-started:.4f}s encoded_bytes={sum(len(result[1][1]) for result in results)} '
          f'overlapping_stage_seconds={ {name:round(sum(values),4) for name,values in stages.items()} } '
          f'enhancement_calls={len(stages["brightness"])}/{len(stages["sharpness"])} backend=native')
