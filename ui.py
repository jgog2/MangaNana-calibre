from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog


class MangaNanaAction(InterfaceAction):
    name = 'MangaNana'
    action_spec = (
        'MangaAnkā',
        'images/mangaanka-calibre-icon.png',
        'Prepare manga and add it to Calibre',
        None,
    )
    action_add_menu = False

    def genesis(self):
        self._mangaanka_window = None
        self._retiring_windows = set()
        self._stopping = False
        self._shutdown_had_nested_dialog = False
        self._late_book_display_timer_stopped = False
        # Load the icon through calibre's plugin resource loader. get_icons is
        # injected into plugin modules by calibre's ZIP plugin loader.
        try:
            icon = get_icons('images/mangaanka-calibre-icon.png', 'MangaNana')
            if icon is not None and not icon.isNull():
                self.qaction.setIcon(icon)
        except Exception:
            pass

        # Keep plugin startup deliberately lightweight. The full MangaNana UI
        # is imported only after the toolbar action is clicked, so a problem in
        # the downloader/dialog code cannot prevent the action from appearing
        # in calibre's toolbar customization list.
        self.qaction.triggered.connect(self.show_dialog)
        gui = getattr(self, 'gui', None)
        if gui is not None:
            gui.shutdown_started.connect(self.shutting_down)
            gui.shutdown_completed.connect(self._shutdown_completed)

    def initialization_complete(self):
        pass

    def library_changed(self, db):
        d = self._mangaanka_window
        if d is not None and not d._closing:
            d.nonmodal_session.library_changed()

    def library_about_to_change(self, olddb, newdb):
        d = self._mangaanka_window
        if d is not None and not d._closing:
            d.nonmodal_session.before_library_change()

    def location_selected(self, loc):
        pass

    def shutting_down(self):
        if self._stopping: return
        self._stopping = True
        windows = set(self._retiring_windows)
        if self._mangaanka_window is not None: windows.add(self._mangaanka_window)
        self._shutdown_had_nested_dialog = any(getattr(d,'_nested_dialog_depth',0) for d in windows)
        workers = set()
        import sys
        for name in ('calibre_plugins.manganana.app.updates.release_updates_ui','calibre_plugins.manganana.app.settings.google_books_key_dialog'):
            workers.update(getattr(sys.modules.get(name),'_JOBS',()))
        for d in windows:
            workers.update(d._owned_workers())
            d.reject()
        # Join actual cooperative work, not a sleep or a nested event loop.
        # This early shutdown hook runs before Calibre closes its database.
        from PyQt6 import sip
        for worker in workers:
            if not sip.isdeleted(worker) and worker.isRunning():
                worker.requestInterruption()
                worker.wait()
        self._drain_retired()

    def _shutdown_completed(self):
        # Calibre's DB cleanup/model notifications can restart its book-details
        # debounce after the initial shutdown stop. A plugin's nested decision
        # loop may otherwise deliver it after model.close() removed the DB.
        # Stop that obsolete presentation work at the supported final hook.
        if self._shutdown_had_nested_dialog:
            from PyQt6 import sip
            timer=getattr(self.gui.library_view,'connect_to_book_display_timer',None)
            if timer is not None and not sip.isdeleted(timer):
                self._late_book_display_timer_stopped=timer.isActive()
                timer.stop()

    def _window_finished(self, d, *_):
        if self._mangaanka_window is d: self._mangaanka_window = None
        self._retiring_windows.add(d)
        for worker in d._owned_workers():
            worker.finished.connect(self._drain_retired)
        self._drain_retired()

    def _drain_retired(self):
        from PyQt6 import sip
        for d in tuple(self._retiring_windows):
            if getattr(d,'_nested_dialog_depth',0): continue
            if getattr(d,'_import_reconciliation',None) is not None: continue
            if not any(not sip.isdeleted(w) and w.isRunning() for w in d._owned_workers()):
                self._retiring_windows.discard(d)
                d.deleteLater()

    def show_dialog(self):
        if self._stopping or getattr(self.gui, 'shutting_down', False): return
        try:
            from qt.core import Qt
            from functools import partial
            from PyQt6 import sip
            d = self._mangaanka_window
            if d is not None and not sip.isdeleted(d) and not d._closing:
                if d.isMinimized():
                    d.setWindowState(d.windowState() & ~Qt.WindowState.WindowMinimized)
                d.show(); d.raise_(); d.activateWindow()
                return
            from calibre_plugins.manganana.presentation.choose_manga_ui import ChooseMangaDialog
            d = ChooseMangaDialog(self.gui, self.qaction.icon())
            # A native independent top-level avoids parent-on-top behavior.
            # Python ownership belongs to this action until finished/worker drain.
            d.setParent(None, Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint |
                Qt.WindowType.WindowCloseButtonHint)
            d.setWindowModality(Qt.WindowModality.NonModal)
            self._mangaanka_window = d
            d.finished.connect(partial(self._window_finished, d))
            d.window_retirement_ready.connect(self._drain_retired)
            d.show()
        except Exception as e:
            import traceback
            error_dialog(
                self.gui,
                'MangaAnkā error',
                str(e),
                det_msg=traceback.format_exc(),
                show=True,
            )
