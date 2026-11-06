"""Opt-in, bounded performance diagnostics. Arguments and user data are never logged.

Set MANGAANKA_PERF_DIR to a writable private diagnostic directory before launch.
Disabled launches install no wrappers, timers, hooks or watchdog threads.
"""
import collections
import ctypes
import faulthandler
import functools
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

_active = None


def memory():
    if os.name != 'nt':
        return {}
    class Counters(ctypes.Structure):
        _fields_ = [('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(n,ctypes.c_size_t) for n in
            ('peak_rss','rss','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    value=Counters();value.cb=ctypes.sizeof(value)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=ctypes.c_void_p
    psapi=ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(value),value.cb):
        return {'rss':value.rss,'peak_rss':value.peak_rss}
    return {}


def percentile(values, quantile):
    values=sorted(values)
    return values[min(len(values)-1,max(0,int((len(values)-1)*quantile+.5)))] if values else 0


class Recorder:
    def __init__(self,path,app):
        from qt.core import QTimer,Qt,qInstallMessageHandler
        self.path=Path(path);self.path.mkdir(parents=True,exist_ok=True)
        self.app=app;self.lock=threading.RLock();self.stages={};self.errors=collections.deque(maxlen=200)
        self.events=collections.deque(maxlen=20000);self.stalls=collections.deque(maxlen=20000)
        self.started=time.perf_counter();self.cpu_started=time.process_time();self.last_tick=self.started
        self.gui_thread=threading.get_ident();self.closed=threading.Event();self.workers=0
        self.wrappers=[]
        self.timer=QTimer(app);self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(10);self.timer.timeout.connect(self.tick);self.timer.start()
        self.old_qt=qInstallMessageHandler(self.qt_message)
        self.old_exception=sys.excepthook;sys.excepthook=self.exception
        self.old_thread_exception=threading.excepthook
        threading.excepthook=lambda a:self.exception(a.exc_type,a.exc_value,a.exc_traceback)
        self.fault_file=(self.path/'thread-stacks.log').open('w',encoding='utf-8')
        self.old_fault_enabled=faulthandler.is_enabled()
        faulthandler.enable(self.fault_file)
        faulthandler.dump_traceback_later(20,repeat=True,file=self.fault_file)
        self.watcher=threading.Thread(target=self.watch,name='MangaAnka diagnostic watchdog',daemon=True)
        self.watcher.start()

    def tick(self):
        now=time.perf_counter()
        with self.lock:
            self.stalls.append(max(0,(now-self.last_tick)*1000-10));self.last_tick=now

    def exception(self,kind,value,tb):
        frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(tb)]
        with self.lock:self.errors.append({'kind':'python_exception','type':kind.__name__,'frames':frames})
        # No exception value: it may embed a URL, credential or user title.

    def qt_message(self,kind,context,message):
        with self.lock:self.errors.append({'kind':'qt_diagnostic','type':int(kind.value),
            'file':Path(context.file or '').name,'line':context.line})

    def record(self,name,start,cpu,failed=False):
        elapsed=(time.perf_counter()-start)*1000
        with self.lock:
            row=self.stages.setdefault(name,{'calls':0,'elapsed_ms':0.,'cpu_ms':0.,'max_ms':0.,'gui_calls':0,'gui_ms':0.,'errors':0,'samples':collections.deque(maxlen=2048)})
            row['calls']+=1;row['elapsed_ms']+=elapsed;row['cpu_ms']+=(time.thread_time()-cpu)*1000
            row['max_ms']=max(row['max_ms'],elapsed);row['samples'].append(elapsed)
            gui=threading.get_ident()==self.gui_thread
            row['gui_calls']+=int(gui);row['gui_ms']+=elapsed if gui else 0;row['errors']+=int(failed)
            if elapsed>=20:self.events.append({'stage':name,'start_ms':(start-self.started)*1000,'elapsed_ms':elapsed,'gui':gui})

    def wrap(self,owner,name,label=None):
        original=getattr(owner,name,None)
        if not callable(original) or getattr(original,'_perf_wrapped',False):return
        @functools.wraps(original)
        def measured(*args,**kwargs):
            if self.closed.is_set():return original(*args,**kwargs)
            start=time.perf_counter();cpu=time.thread_time();failed=False
            try:return original(*args,**kwargs)
            except BaseException:
                failed=True;raise
            finally:self.record(label or name,start,cpu,failed)
        measured._perf_wrapped=True
        self.wrappers.append((owner,name,original,measured))
        setattr(owner,name,measured)

    def worker(self,worker):
        with self.lock:self.workers+=1
        worker.finished.connect(self.worker_finished)
        if hasattr(worker,'failed'):
            from qt.core import Qt
            worker.failed.connect(lambda *_:self.worker_failed(type(worker).__name__),Qt.ConnectionType.DirectConnection)

    def worker_failed(self,name):
        with self.lock:self.errors.append({'kind':'worker_failure','worker':name})

    def worker_finished(self):
        with self.lock:self.workers=max(0,self.workers-1)

    def watch(self):
        while not self.closed.wait(1):
            with self.lock:age=(time.perf_counter()-self.last_tick)*1000;workers=self.workers
            payload={'pid':os.getpid(),'gui_heartbeat_age_ms':age,'elapsed_s':time.perf_counter()-self.started,
                'cpu_s':time.process_time()-self.cpu_started,'workers':workers,**memory()}
            try:
                temporary=self.path/'heartbeat.tmp';temporary.write_text(json.dumps(payload),encoding='utf-8')
                os.replace(temporary,self.path/'heartbeat.json')
                (self.path/'profile-live.json').write_text(json.dumps(self.snapshot(),indent=2),encoding='utf-8')
            except OSError:pass

    def snapshot(self):
        with self.lock:
            stages={name:{**{k:v for k,v in row.items() if k!='samples'},'median_ms':percentile(row['samples'],.5),
                'p95_ms':percentile(row['samples'],.95)} for name,row in self.stages.items()}
            stalls=list(self.stalls);errors=list(self.errors);events=list(self.events)
        return {'elapsed_s':time.perf_counter()-self.started,'cpu_s':time.process_time()-self.cpu_started,
            **memory(),'stages':stages,'errors':errors,'events':events,'heartbeat':{'samples':len(stalls),
            'median_stall_ms':percentile(stalls,.5),'p95_stall_ms':percentile(stalls,.95),'worst_stall_ms':max(stalls,default=0),
            'over_100ms':sum(v>100 for v in stalls),'over_1000ms':sum(v>1000 for v in stalls)},'active_workers':self.workers}

    def close(self):
        from qt.core import qInstallMessageHandler
        if self.closed.is_set():return
        self.timer.stop();self.closed.set();self.watcher.join(2)
        for owner,name,original,measured in reversed(self.wrappers):
            if getattr(owner,name,None) is measured:setattr(owner,name,original)
        self.wrappers.clear()
        faulthandler.cancel_dump_traceback_later()
        if self.old_fault_enabled:faulthandler.enable()
        else:faulthandler.disable()
        self.fault_file.close()
        sys.excepthook=self.old_exception;threading.excepthook=self.old_thread_exception;qInstallMessageHandler(self.old_qt)
        (self.path/'profile.json').write_text(json.dumps(self.snapshot(),indent=2),encoding='utf-8')


def attach(main,dialog,path=None):
    global _active
    path=path or os.environ.get('MANGAANKA_PERF_DIR')
    if not path:return None
    if _active is not None and not _active.closed.is_set():return _active
    from qt.core import QApplication
    recorder=_active=Recorder(path,QApplication.instance())
    for cls in (main.MangaNanaDialog,type(dialog)):
        for name in ('search_mangadex','_apply_search_page','_rebuild_enriched_results','_apply_late_search_enrichment',
                '_search_presentations','_ranked_provider_results','_ranked_search_groups','_render_provider_search_results',
                '_render_fresh_cached_snapshot','_finish_coordinated_search','_search_resolution_finished',
                '_load_visible_search_thumbs','_on_search_thumb_ready','_pix_from_bytes','_pix_for_url','_refresh_search_rows',
                '_style_search_selection','use_search_result','_begin_search_result','_refresh_selected_details',
                '_apply_volume_plan_data','_rebuild_volume_list','_load_visible_volume_thumbs','_on_volume_thumb_ready',
                '_interrupt_async_workers','_clear_active_provider_selection'):
            if name in cls.__dict__:recorder.wrap(cls,name,cls.__name__+'.'+name)
    for name in ('rank_provider_results','rank_canonical_results','effective_search_rows','enrich_content_results','acquire_volume_inventory'):
        recorder.wrap(main,name)
    recorder.wrap(main.SourceCoordinator,'complete','normalize_provider_response')
    for cls in (main.SourceSearchWorker,main.EnrichmentSearchWorker,main.SearchResolutionWorker,main.MangaLoadWorker,
                main.VolumePlanWorker,main.ChapterPlanWorker,main.ImageBatchWorker,main.SelectedFallbackWorker):
        recorder.wrap(cls,'run',cls.__name__+'.run')
    for cls in (main.SearchResultRowWidget,main.VolumeRowWidget):recorder.wrap(cls,'__init__',cls.__name__+'.create')
    for source in main.SOURCE_REGISTRY.all():
        for name in ('search','get_manga','get_chapters','get_download_plan','get_volume_covers','fetch_binary',
                '_request','_request_text','_api_json','_json','_title_document'):
            # Class hooks also cover adapters cloned with a cancellation check.
            recorder.wrap(type(source),name,'adapter.'+source.source_id+'.'+name)
            recorder.wrap(source,name,'provider.'+source.source_id+'.'+name)
    recorder.wrap(main.ArtworkResolver,'resolve','artwork.fetch_validate')
    recorder.wrap(type(dialog.fidelity),'results','foreground.result_style')
    from calibre_plugins.manganana.presentation.choose_manga_background import ShaderPanel
    for name in ('paintGL','compile_program','cleanup'):recorder.wrap(ShaderPanel,name,'shader.'+name)
    original=dialog._retain_async_worker
    def retain(worker):recorder.worker(worker);return original(worker)
    dialog._retain_async_worker=retain
    recorder.wrappers.append((dialog,'_retain_async_worker',original,retain))
    dialog.finished.connect(lambda *_:recorder.close())
    return recorder
