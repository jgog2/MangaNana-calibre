"""Dialog-owned asynchronous release checks and explicit, recoverable installation."""
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from qt.core import QObject, QThread, pyqtSignal, QTimer, QDesktopServices, QUrl
from calibre_plugins.manganana.presentation.non_modal_window import PluginMessageBox as QMessageBox
from calibre_plugins.manganana.app.settings.config import prefs
from calibre_plugins.manganana.version_info import SEMANTIC_VERSION
from calibre_plugins.manganana.app.updates.release_updates import (
    check_release,
    download_release,
    REPOSITORY,
    stable_version,
)

# Workers outlive closed dialogs until cooperative interruption completes.
_JOBS = set()


class ReleaseWorker(QThread):
    result = pyqtSignal(object)
    failure = pyqtSignal(str)

    def __init__(self, release=None):
        super().__init__()
        self.release = release

    def run(self):
        try:
            value = (download_release(self.release, self.isInterruptionRequested) if self.release
                else check_release(SEMANTIC_VERSION, self.isInterruptionRequested))
            if not self.isInterruptionRequested():
                self.result.emit(value)
        except InterruptedError:
            pass
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failure.emit(str(error)[:400])


def install_package(raw):
    """Use Calibre's installer, restoring its prior ZIP/config if it fails."""
    from calibre.customize import ui
    target = Path(ui.plugin_dir) / 'MangaNana.zip'
    previous = target.read_bytes() if target.exists() else None
    plugins = dict(ui.config['plugins'])
    with TemporaryDirectory(prefix='mangaanka-update-') as directory:
        incoming = Path(directory) / 'MangaNana.zip'
        incoming.write_bytes(raw)
        try:
            ui.add_plugin(str(incoming))
        except Exception:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous)
            ui.config['plugins'] = plugins
            ui.initialize_plugins()
            raise


class ReleaseUpdates(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.d = dialog
        self.active = True
        self.worker = None
        self.manual = False
        self.release = None
        self.status = 'Official stable releases only'
        self.refresh_indication()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.check)
        dialog.finished.connect(self.detach)
        dialog.destroyed.connect(self.detach)
        self.timer.start(0)

    def check(self, manual=False):
        if not self.active or self.worker is not None:
            return
        now = time.time()
        if not manual and (not prefs.get('update_auto_check', True) or
                now - float(prefs.get('update_last_attempt', 0)) < 3600 or
                now - float(prefs.get('update_last_success', 0)) < 86400):
            return
        prefs['update_last_attempt'] = now
        self.manual = manual
        self.d.check_updates_btn.setEnabled(False)
        self.d.check_updates_btn.setText('Checking…')
        self.start(ReleaseWorker(), self.checked)

    def start(self, worker, callback):
        self.worker = worker
        _JOBS.add(worker)
        if hasattr(self.d,'_retain_async_worker'): self.d._retain_async_worker(worker)
        worker.result.connect(callback)
        worker.failure.connect(self.failed)
        worker.finished.connect(self.settled)
        worker.finished.connect(lambda w=worker: (_JOBS.discard(w), w.deleteLater()))
        worker.start()

    def settled(self):
        if not self.active:
            return
        self.worker = None
        self.d.check_updates_btn.setEnabled(True)
        self.d.check_updates_btn.setText('Check for updates')
        self.refresh_indication()

    def refresh_indication(self, message=None):
        if not self.active:
            return
        available=self.release is not None
        self.d.settings_button.setProperty('updateAvailable',available)
        self.d.settings_button.setToolTip('MangaAnkā '+self.release['version']+' is available' if available else 'Settings')
        self.d.settings_button.style().unpolish(self.d.settings_button)
        self.d.settings_button.style().polish(self.d.settings_button)
        if message is not None:self.status=message
        self.d.update_status.setText(self.status)
        self.d.release_notes_btn.setVisible(available)

    def open_release_page(self):
        if self.active and self.release and stable_version(self.release.get('tag')):
            QDesktopServices.openUrl(QUrl('https://github.com/'+REPOSITORY+'/releases/tag/'+self.release['tag']))

    def checked(self, release):
        if not self.active:
            return
        prefs['update_last_success'] = time.time()
        self.release = release
        self.status='MangaAnkā '+release['version']+' is available' if release else 'No newer official stable release found'
        self.refresh_indication()
        if release is None:
            if self.manual:
                QMessageBox.information(self.d, 'MangaAnkā updates', 'No newer official stable release was found.')
            return
        if not self.manual and (not prefs.get('update_auto_check',True) or prefs.get('update_ignored_version') == release['version'] or
                time.time() < float(prefs.get('update_later_until', 0))):
            return
        # Let the checking worker settle before opening an installable prompt.
        QTimer.singleShot(0, self.offer)

    def offer(self):
        if not self.active or self.release is None:
            return
        if self.worker is not None:
            self.worker.finished.connect(self.offer)
            return
        session=getattr(self.d,'nonmodal_session',None)
        if session is not None and session.defer_notice(self.offer,'Update available'): return
        box = QMessageBox(self.d)
        box.setWindowTitle('MangaAnkā update available')
        box.setTextFormat(__import__('qt.core', fromlist=['Qt']).Qt.TextFormat.PlainText)
        box.setText('MangaAnkā ' + self.release['version'] + ' is available.\nInstalled: ' + SEMANTIC_VERSION)
        install = box.addButton('Install', QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton('Later', QMessageBox.ButtonRole.RejectRole)
        ignore = box.addButton('Don’t remind me', QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(later)
        busy = self.d._download_in_progress or self.d.workflow_state.stage != 'choose_manga'
        install.setEnabled(not busy)
        if busy:
            box.setInformativeText('Finish the current workflow before installing. Settings can check again at any time.')
        box.exec()
        if box.clickedButton() is ignore:
            prefs['update_ignored_version'] = self.release['version']
        elif box.clickedButton() is install and self.active:
            self.d.check_updates_btn.setEnabled(False)
            self.d.check_updates_btn.setText('Downloading update…')
            self.start(ReleaseWorker(dict(self.release)), self.downloaded)
        else:
            prefs['update_later_until'] = time.time() + 86400
        box.deleteLater()

    def downloaded(self, raw):
        if not self.active:
            return
        if self.d._download_in_progress or self.d.workflow_state.stage != 'choose_manga':
            self.failed('Finish the current workflow, then check for updates again.')
            return
        try:
            install_package(raw)
        except Exception as error:
            self.failed('Installation failed: ' + str(error)[:300])
            return
        QMessageBox.information(self.d, 'MangaAnkā update installed', 'Update installed. Restart calibre to finish.')

    def failed(self, message):
        if not self.active:
            return
        self.d.add_log('Official release update: ' + message)
        self.refresh_indication('Could not check for updates. Try again later.')
        if self.manual or self.release is not None:
            QMessageBox.warning(self.d, 'MangaAnkā updates', message)

    def detach(self, *_):
        self.active = False
        from PyQt6 import sip
        if not sip.isdeleted(self.timer):
            self.timer.stop()
        if self.worker is not None and not sip.isdeleted(self.worker):
            self.worker.requestInterruption()
