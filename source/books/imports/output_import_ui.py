"""Yield between Calibre commits; all database/Qt work stays on the GUI thread."""
import weakref
from qt.core import QObject,QTimer,pyqtSignal,QThread
from calibre_plugins.manganana.books.imports.calibre_destination import DestinationUnavailable, RejectedImporter
from calibre_plugins.manganana.books.output.batch_progress import import_percent


class ImportReconciliation(QObject):
    finished=pyqtSignal(object)

    def __init__(self,dialog,reconciliation):
        super().__init__(dialog)
        if QThread.currentThread()!=dialog.thread():raise RuntimeError('Import coordination requires the GUI thread.')
        self._dialog=weakref.ref(dialog);self.run=reconciliation
        self.in_step=False;self.active=True;self.blocked_reason=None
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(self.step)

    def start(self):self.timer.start(0)

    def cancel(self):
        if not self.active:return
        self.run.cancel_requested=True;self.timer.stop()
        if not self.in_step:
            while not self.run.done:self.run.step()
            self.finish()

    def step(self):
        if not self.active:return
        d=self._dialog()
        if d is None or d._closing:self.cancel();return
        self.in_step=True
        try:
            if not self.blocked_reason:
                try:
                    d.destination.api()
                    refresh=getattr(self.run.importer,'refresh_owners',None)
                    if refresh is not None:refresh()
                except DestinationUnavailable as exc:self.blocked_reason=str(exc)
                except Exception as exc:self.blocked_reason='Calibre ownership validation failed; prepared files retained: '+str(exc)
            if self.blocked_reason:self.run.importer=RejectedImporter(self.blocked_reason)
            self.run.step()
            if not d._closing:
                d.progress.setValue(import_percent(self.run.position,len(self.run.requests)))
                d.progress_text.setText(f'Importing books… {self.run.position} of {len(self.run.requests)} accounted for.')
        finally:self.in_step=False
        if self.run.cancel_requested or d._closing:self.cancel()
        elif self.run.done:self.finish()
        else:self.timer.start(0)

    def finish(self):
        if not self.active:return
        self.active=False;self.timer.stop();self.finished.emit(self.run.result())
        self.deleteLater()
