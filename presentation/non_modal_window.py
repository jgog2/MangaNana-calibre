"""Plugin-local window modality and visible pinned-library integration."""
import weakref
from copy import deepcopy
from qt.core import (QDialog as QtDialog, QMessageBox as QtMessageBox,
    QFileDialog as QtFileDialog, QInputDialog as QtInputDialog, QLineEdit,
    Qt, QObject, QWidget, QHBoxLayout, QLabel, QPushButton, QApplication)


def plugin_window(widget):
    while widget is not None:
        if widget.property('mangaankaWindow'):
            return widget
        widget = widget.parentWidget()
    return None


def scope_dialog(dialog):
    if plugin_window(dialog.parentWidget()) is not None:
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
    return dialog


def scoped_exec(dialog, run):
    owner = plugin_window(dialog.parentWidget())
    if owner is not None: owner._nested_dialog_depth = getattr(owner,'_nested_dialog_depth',0)+1
    try: return run()
    finally:
        if owner is not None:
            owner._nested_dialog_depth -= 1
            signal = getattr(owner,'window_retirement_ready',None)
            if signal is not None: signal.emit()


class ScopedExec:
    def exec(self):
        return scoped_exec(self,super().exec)


class PluginDialog(ScopedExec,QtDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        scope_dialog(self)


class PluginMessageBox(ScopedExec,QtMessageBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        scope_dialog(self)

    @classmethod
    def _message(cls, icon, parent, title, text, buttons=None, default=None):
        box = cls(parent); box.setWindowTitle(title); box.setText(text); box.setIcon(icon)
        box.setStandardButtons(buttons or cls.StandardButton.Ok)
        if default is not None: box.setDefaultButton(default)
        answer = box.exec(); box.deleteLater()
        return cls.StandardButton(answer)

    @classmethod
    def information(cls, parent, title, text, buttons=None, defaultButton=None):
        return cls._message(cls.Icon.Information, parent, title, text, buttons, defaultButton)

    @classmethod
    def warning(cls, parent, title, text, buttons=None, defaultButton=None):
        return cls._message(cls.Icon.Warning, parent, title, text, buttons, defaultButton)

    @classmethod
    def question(cls, parent, title, text, buttons=None, defaultButton=None):
        return cls._message(cls.Icon.Question, parent, title, text,
            buttons or (cls.StandardButton.Yes | cls.StandardButton.No), defaultButton)


class PluginFileDialog(ScopedExec,QtFileDialog):
    @classmethod
    def _files(cls, parent, caption, directory, filters, mode, save=False, native=False):
        dialog = cls(parent, caption, directory, filters); scope_dialog(dialog)
        # Keep the same owned-dialog lifetime for either platform presentation.
        dialog.setProperty('mangaankaNativeFileDialog',bool(native))
        dialog.setOption(cls.Option.DontUseNativeDialog, not native)
        dialog.setFileMode(mode)
        if save: dialog.setAcceptMode(cls.AcceptMode.AcceptSave)
        ok = dialog.exec() == cls.DialogCode.Accepted
        paths = dialog.selectedFiles() if ok else []; selected = dialog.selectedNameFilter()
        dialog.deleteLater()
        return paths, selected

    @classmethod
    def getOpenFileNames(cls, parent=None, caption='', directory='', filter='', native=False, **_):
        return cls._files(parent, caption, directory, filter, cls.FileMode.ExistingFiles, native=native)

    @classmethod
    def getSaveFileName(cls, parent=None, caption='', directory='', filter='', **_):
        paths, selected = cls._files(parent, caption, directory, filter, cls.FileMode.AnyFile, True)
        return (paths[0] if paths else ''), selected


class PluginInputDialog(ScopedExec,QtInputDialog):
    @classmethod
    def getText(cls, parent, title, label, echo=QLineEdit.EchoMode.Normal, text='', **_):
        dialog = cls(parent); scope_dialog(dialog); dialog.setWindowTitle(title)
        dialog.setLabelText(label); dialog.setTextEchoMode(echo); dialog.setTextValue(text)
        accepted = dialog.exec() == cls.DialogCode.Accepted; value = dialog.textValue()
        dialog.deleteLater(); return value, accepted


def _calibre_message(kind, parent, *args, **kwargs):
    from calibre import gui2
    show = kwargs.pop('show', False)
    dialog = getattr(gui2, kind)(parent, *args, show=False, **kwargs)
    scope_dialog(dialog)
    if show:
        root = plugin_window(parent)
        session = getattr(root,'nonmodal_session',None)
        callback = lambda:scoped_exec(dialog,dialog.exec)
        if session is None or not session.defer_notice(callback,'View message'): callback()
    return dialog


def error_dialog(parent, *args, **kwargs):
    return _calibre_message('error_dialog', parent, *args, **kwargs)


def info_dialog(parent, *args, **kwargs):
    return _calibre_message('info_dialog', parent, *args, **kwargs)


class NonModalSession(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = weakref.ref(dialog)
        self.notices = []
        self.showing_notice = False
        self.pending = None
        self.active = True
        bar = QWidget(); bar.setObjectName('destinationLibraryBar')
        row = QHBoxLayout(bar); row.setContentsMargins(0, 0, 0, 6)
        self.label = QLabel(); self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setStyleSheet('font-size:12px;color:#b6d6d0;')
        row.addWidget(self.label, 1)
        self.resume = QPushButton('Resume import'); self.resume.clicked.connect(self.resume_import)
        self.keep_files = QPushButton('Keep files & continue'); self.keep_files.clicked.connect(self.release_pending)
        self.results = QPushButton('View results'); self.results.clicked.connect(self.show_notice)
        row.addWidget(self.resume); row.addWidget(self.keep_files); row.addWidget(self.results)
        dialog.footer.stack.insertWidget(0, bar)
        self.refresh()

    def refresh(self):
        d = self._dialog()
        if not self.active or d is None or d._closing: return
        available = d.destination.available()
        path = d.destination.identity.path
        text = 'Destination library: '+path
        if not available: text += '\nCalibre is using another library. Return to this destination to import.'
        elif self.pending: text += '\nPrepared books are waiting. Retry their import when ready.'
        self.label.setText(text); self.label.setToolTip(path)
        self.resume.setVisible(self.pending is not None); self.resume.setEnabled(available)
        self.keep_files.setVisible(self.pending is not None)
        self.results.setVisible(bool(self.notices))
        self.results.setText(self.notices[0][0] if len(self.notices)==1 else 'Notifications ('+str(len(self.notices))+')')

    def before_library_change(self):
        d = self._dialog()
        if not self.active or d is None: return
        d.destination.switching = True
        # A pending decision was based on the old library. Reject it before
        # Calibre detaches that DB; the importer revalidates after nested exec.
        for popup in d.findChildren(QtDialog):
            if popup.isVisible(): popup.reject()
        self.refresh()

    def library_changed(self):
        d = self._dialog()
        if not self.active or d is None: return
        d.destination.switching = False; self.refresh()

    def hold_import(self, result, ledger=None):
        d = self._dialog()
        if d is None or d._closing: return
        from calibre_plugins.manganana.books.imports.output_import import prepared_retry
        subset = prepared_retry(d._active_output_requests, result, ledger) if ledger is not None else None
        if ledger is not None and subset is None:
            self.pending = None; self.refresh(); return
        requests, result = subset if subset is not None else (d._active_output_requests, result)
        result = dict(result, retry_of=getattr(d,'_last_output_ledger_path',None))
        self.pending = dict(result=deepcopy(result), requests=deepcopy(requests),
            indices=deepcopy(d._active_series_indices), replace=getattr(d,'_active_replace_existing',False),
            tags=getattr(d,'_active_import_tags',()))
        self.resume.setText('Retry prepared imports')
        self.refresh()

    def resume_import(self):
        d = self._dialog()
        if (not self.active or d is None or d._closing or not self.pending or
                d._download_in_progress or not d.destination.available()): return
        job = self.pending; self.pending = None
        d._active_output_requests = job['requests']; d._active_series_indices = job['indices']
        d._active_replace_existing = job['replace']; d._active_import_tags = job['tags']
        d.on_downloaded(job['result']); self.refresh()

    def release_pending(self):
        d = self._dialog()
        if not self.active or d is None or d._closing or d._download_in_progress or not self.pending:return
        path = self.pending['result'].get('workdir')
        self.pending = None
        d.add_log('Prepared import set aside; files and output accounting retained: '+str(path))
        self.refresh()

    def defer_notice(self, callback, label='View results'):
        d = self._dialog()
        if not self.active or d is None or d._closing: return True
        if self.showing_notice or d.isActiveWindow() or plugin_window(QApplication.activeWindow()) is d: return False
        if not any(existing==callback for _,existing in self.notices): self.notices.append((label,callback))
        self.refresh(); return True

    def show_notice(self):
        if not self.active or not self.notices: return
        _,callback = self.notices.pop(0); self.showing_notice = True
        try: callback()
        finally: self.showing_notice = False; self.refresh()

    def detach(self):
        self.active = False; self.notices.clear(); self.pending = None
        d=self._dialog()
        if d is not None:
            for popup in d.findChildren(QtDialog):
                if popup.isVisible(): popup.reject()
