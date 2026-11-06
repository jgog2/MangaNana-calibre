"""Offline Main/toolbar initialization, not a release qualification harness."""
import os,json,socket,hashlib,time,traceback
from pathlib import Path
OUT=Path(os.environ['SOURCE_SMOKE_OUT']);LIBRARY=Path(os.environ['SOURCE_SMOKE_LIBRARY']);PROFILE=Path(os.environ['CALIBRE_CONFIG_DIRECTORY'])
assert PROFILE.parent==OUT and not any(LIBRARY.iterdir()),'Fresh disposable paths required'
from calibre.constants import config_dir,__version__
assert Path(config_dir).resolve()==PROFILE.resolve()
from calibre.db.legacy import LibraryDatabase
db=LibraryDatabase(str(LIBRARY));db.close()
from calibre.gui2 import dynamic
dynamic.set('welcome_wizard_was_run',True)
import calibre.gui2.main as startup
from qt.core import QApplication,QTimer,Qt,QT_VERSION_STR,PYQT_VERSION_STR
report=dict(calibre=__version__,qt=QT_VERSION_STR,pyqt=PYQT_VERSION_STR,checks=[],errors=[],profile=str(PROFILE),library=str(LIBRARY),plugin_sha256=hashlib.sha256(Path(os.environ['SOURCE_SMOKE_PLUGIN']).read_bytes()).hexdigest())
state={};started=time.monotonic()
if os.environ.get('SOURCE_SMOKE_TRACE'):
    import faulthandler
    trace_file=(OUT/'thread-stack.log').open('w',encoding='utf8')
    faulthandler.enable(file=trace_file)
    faulthandler.dump_traceback_later(20,repeat=True,file=trace_file)
def check(value,name):
    report['checks'].append(dict(name=name,passed=bool(value)));assert value,name
def blocked(*a,**kw):raise RuntimeError('Offline source smoke cannot use live network')
socket.create_connection=blocked;socket.socket.connect=blocked
def poll():
    try:
        if os.environ.get('SOURCE_SMOKE_TRACE'):
            (OUT/'probe-progress.json').write_text(json.dumps(dict(elapsed_s=time.monotonic()-started,
                state=list(state),windows=[dict(kind=type(w).__name__,visible=w.isVisible(),
                    library_view=hasattr(w,'library_view')) for w in QApplication.topLevelWidgets()])),encoding='utf8')
        if 'gui' not in state:
            # Older Calibre pumps Qt events while constructing Main. The action
            # registry exists before its library view; exercise a usable toolbar.
            gui=next((w for w in QApplication.topLevelWidgets() if w.__class__.__name__=='Main'
                      and w.isVisible() and hasattr(w,'library_view')
                      and getattr(w,'iactions',{}).get('MangaNana')),None)
            if gui is None:
                assert time.monotonic()-started<40,'Main startup timed out';return
            state['gui']=gui
            from calibre_plugins.manganana.app.settings.config import prefs
            prefs['update_auto_check']=False;prefs['session_search']='';prefs['session_url']='';prefs['completion_sounds']=False
            if os.environ.get('SOURCE_SMOKE_TRACE'):
                import calibre_plugins.manganana.ui as action_module
                def capture_error(parent,title,message,**details):
                    raise RuntimeError(str(title)+': '+str(message)+'\n'+str(details.get('det_msg','')))
                action_module.error_dialog=capture_error
            action=gui.iactions['MangaNana'];action.qaction.trigger();d=action._mangaanka_window
            state.update(dialog=d,action=action,opened=time.monotonic());return
        if time.monotonic()-state['opened']<.6:return
        d=state['dialog'];gui=state['gui'];action=state['action'];timer.stop()
        check(d is not None and d.isVisible(),'Actual installed toolbar creates visible window')
        check(d.parentWidget() is None and d.windowModality()==Qt.WindowModality.NonModal,'Independent non-modal window')
        action.qaction.trigger();check(action._mangaanka_window is d,'One toolbar-owned instance')
        check(str(LIBRARY).casefold().replace('/','\\') in d.nonmodal_session.label.text().casefold().replace('/','\\'),'Persistent destination is actual disposable library')
        from calibre_plugins.manganana.app.main import SOURCE_REGISTRY
        check([s.source_id for s in SOURCE_REGISTRY.all()]==['mangadex','mangapill','weebcentral','mangak','atsu'],'Five packaged providers registered')
        from calibre_plugins.manganana.presentation import choose_manga_resources as resources
        root=resources.asset_root();check(all((root/n).is_file() for n in resources.UI_FILES),'Every UI resource extracted from plugin')
        check((root/'assets/audio/mangaanka_complete.mp3').stat().st_size==78576,'Built-in MP3 available')
        from calibre_plugins.manganana.build_info import BUILD_ID
        report['build_id']=BUILD_ID;report['passed']=True;d.reject();QTimer.singleShot(150,gui.close)
    except BaseException:
        report['errors'].append(traceback.format_exc());timer.stop();report['passed']=False
        (OUT/'failure-interim.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        if state.get('dialog') is not None:state['dialog'].reject()
        if state.get('gui') is not None:QTimer.singleShot(0,state['gui'].close)
        else:QApplication.instance().quit()
original=startup.init_qt
def init(args):
    global timer
    values=original(args);timer=QTimer(values[0]);timer.timeout.connect(poll);timer.start(100);return values
startup.init_qt=init;startup.singleinstance_name='MangaAnka-source-smoke-'+OUT.name
original_instance=startup.SingleInstance
startup.SingleInstance=lambda name:original_instance('MangaAnka-source-db-'+OUT.name if name=='db' else name)
startup.main(['calibre','--with-library',str(LIBRARY),'--no-update-check'])
report['event_loop_returned']=True;report['passed']=bool(report.get('passed') and not report['errors'])
(OUT/'native-results.json').write_text(json.dumps(report,indent=2),encoding='utf8')
if not report['passed']:raise SystemExit(1)
