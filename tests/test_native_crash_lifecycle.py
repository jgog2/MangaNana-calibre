"""Run with Calibre Python: Qt construction/destruction and late completions."""
import gc,sys,types,weakref,unittest
from pathlib import Path
from qt.core import QApplication,QDialog,QWidget,QListWidget,QEvent,QCoreApplication
ROOT=Path(__file__).resolve().parents[1]
if 'calibre_plugins.manganana' not in sys.modules:
    package=types.ModuleType('calibre_plugins.manganana');package.__path__=[str(ROOT)]
    sys.modules['calibre_plugins.manganana']=package
from calibre_plugins.manganana.presentation.choose_manga_design import VolumeCarousel
from calibre_plugins.manganana.presentation.mangaanka_widgets import PageWheelFilter
from calibre_plugins.manganana.app.main import MangaNanaDialog
app=QApplication.instance() or QApplication([])

class NativeLifecycleTests(unittest.TestCase):
    def test_presentation_filter_is_removed_when_its_owner_closes(self):
        from calibre_plugins.manganana.presentation.mangaanka_presentation import PresentationScope
        seen=[];original=PresentationScope.eventFilter
        def observe(scope,watched,event):
            seen.append(int(event.type()))
            return original(scope,watched,event)
        PresentationScope.eventFilter=observe
        try:
            owner=QDialog();scope=PresentationScope(owner)
            owner.reject();seen.clear()
            unrelated=QDialog();unrelated.show();app.processEvents()
            self.assertEqual([],seen,'Closed presentation scope must receive no application events')
            unrelated.close();unrelated.deleteLater();owner.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        finally:PresentationScope.eventFilter=original

    def test_destroyed_popup_cannot_receive_deferred_presentation_fit(self):
        from calibre_plugins.manganana.presentation.mangaanka_presentation import PresentationScope
        errors=[];previous=sys.excepthook
        sys.excepthook=lambda kind,value,tb:errors.append(str(value))
        try:
            owner=QDialog();scope=PresentationScope(owner);popup=QDialog(owner)
            popup.show();popup.deleteLater()
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
            owner.reject();owner.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            self.assertEqual([],errors)
        finally:sys.excepthook=previous

    def test_full_choose_dialog_cycle_detaches_before_workflow_state_is_cleared(self):
        from qt.core import QIcon
        from calibre_plugins.manganana.presentation.choose_manga_ui import ChooseMangaDialog
        errors=[];previous=sys.excepthook
        def observe(kind,value,tb):errors.append(str(value))
        sys.excepthook=observe
        try:
            for _ in range(5):
                gui=QWidget();gui.current_db=types.SimpleNamespace(new_api=object(),library_path='C:/MangaNana-Dev/Test-Library',library_id='native-lifecycle-test')
                dialog=ChooseMangaDialog(gui,QIcon())
                ref=weakref.ref(dialog);filter_ref=weakref.ref(dialog.fidelity.carousel)
                dialog.reject();dialog.setParent(None)
                sys.excepthook=observe
                del dialog,gui
                # A queued constructor/layout callback may hold the wrapper
                # until its Qt turn completes. Drain posted work before the
                # final collection; do not retain the dialog in the test.
                for _turn in range(3):
                    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents();gc.collect()
                self.assertIsNone(ref());self.assertIsNone(filter_ref())
                self.assertEqual([],errors)
        finally:sys.excepthook=previous

    def test_closed_or_abandoned_cycles_unregister_before_gc_clears_state(self):
        errors=[];previous=sys.excepthook
        sys.excepthook=lambda kind,value,tb:errors.append(str(value))
        try:
            for close in (False,True)*5:
                d=QDialog();d.workflow_mode='volume';d.volume_list=QListWidget()
                host=QWidget(d);d.carousel=VolumeCarousel(d,host);d.wheel=PageWheelFilter(d,host)
                ref=weakref.ref(d.carousel)
                if close:
                    d.reject()
                    self.assertFalse(d.carousel._registered)
                    self.assertFalse(d.wheel._registered)
                del host,d
                gc.collect();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
                self.assertIsNone(ref())
            self.assertEqual([],errors)
        finally:sys.excepthook=previous

    def test_destroyed_dialog_search_completion_releases_worker_without_ui(self):
        worker=object()
        owner=types.SimpleNamespace(search_workers={'mangadex':worker},_closing=True)
        # No workflow/UI attributes: a completion after close must release its
        # slot without looking up presentation state or Qt widgets.
        MangaNanaDialog._search_worker_finished(owner,'mangadex',worker)
        self.assertEqual({},owner.search_workers)
        MangaNanaDialog._finish_coordinated_search(owner)
        MangaNanaDialog._on_search_ready(owner,None,{})
        MangaNanaDialog._on_search_failed(owner,{})
        MangaNanaDialog._on_enrichment_ready(owner,{})
        MangaNanaDialog._on_search_resolution(owner,{})

    def test_stale_worker_completion_cannot_remove_newer_worker(self):
        newer=object();old=object()
        owner=types.SimpleNamespace(search_workers={'mangadex':newer},_closing=True)
        MangaNanaDialog._search_worker_finished(owner,'mangadex',old)
        self.assertIs(newer,owner.search_workers['mangadex'])

    def test_terminal_selected_callbacks_do_not_even_read_absent_qt_state(self):
        # A closing owner deliberately has no widgets, selection, source, or
        # request fields. These are presentation callbacks, not cleanup hooks.
        owner=types.SimpleNamespace(_closing=True)
        MangaNanaDialog._dispatch_selected_result(owner,None,lambda _:self.fail('late dispatch'),{})
        MangaNanaDialog._on_manga_worker_ready(owner,{})
        MangaNanaDialog._on_manga_worker_failed(owner,{})
        MangaNanaDialog._apply_loaded_manga(owner,1,{})
        MangaNanaDialog._on_volume_plan_ready(owner,{})
        MangaNanaDialog._apply_volume_plan_data(owner,{})
        MangaNanaDialog._on_reference_lookup_ready(owner,{})
        MangaNanaDialog._load_volume_plan(owner)
        MangaNanaDialog._start_reference_lookup(owner)
        MangaNanaDialog.on_preview_ready(owner,{})
        MangaNanaDialog.on_progress(owner,50,'late')

    def test_finished_output_releases_native_handle_even_if_result_receiver_failed(self):
        from qt.core import QThread
        worker=QThread()
        owner=types.SimpleNamespace(worker=worker,_async_workers={worker})
        MangaNanaDialog._release_async_worker(owner,worker)
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        from PyQt6 import sip
        self.assertTrue(sip.isdeleted(worker))
        self.assertIsNone(owner.worker)
        self.assertEqual(set(),owner._async_workers)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeLifecycleTests))
    if not result.wasSuccessful():raise SystemExit(1)
