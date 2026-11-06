"""Dialog-owned, nonblocking playback of the bundled completion MP3."""
from qt.core import QObject, QThread, QUrl, pyqtSignal
from calibre_plugins.manganana.app.notifications.completion_policy import successful_batch
from calibre_plugins.manganana.presentation.choose_manga_resources import asset_root
from calibre_plugins.manganana.app.settings.config import prefs

SOUND_FILE = 'assets/audio/mangaanka_complete.mp3'


class CompletionAudio(QObject):
    active = False
    started = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, dialog):
        super().__init__(dialog)
        self.active = True
        self.player = self.output = None
        self.last_batch = None
        self.last_error = ''
        self._releasing = False
        dialog.finished.connect(self.detach)
        dialog.destroyed.connect(self.detach)
        self.failed.connect(dialog._completion_sound_failed)

    def completed(self, ledger):
        if not self.active or not prefs.get('completion_sounds', True) or not successful_batch(ledger):
            return False
        # Repeated delivery of one terminal ledger cannot ring twice. Actual
        # subsequent batches receive their own reconciliation timestamp.
        token = ledger.get('timestamp')
        if token is None or token == self.last_batch:
            return False
        self.last_batch = token
        return self.play('completion')

    def play(self, reason='preview'):
        if not self.active:
            return False
        if QThread.currentThread() != self.thread():
            raise RuntimeError('Completion audio must be requested on the GUI thread')
        try:
            if self.player is None:
                from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
                self.output = QAudioOutput(self)
                self.output.setVolume(0.5)
                self.player = QMediaPlayer(self)
                self.player.setAudioOutput(self.output)
                self.player.mediaStatusChanged.connect(self._media_status)
                self.player.errorOccurred.connect(self._error)
            self.stop()
            path = asset_root() / SOUND_FILE
            if not path.is_file():
                raise FileNotFoundError('The built-in completion sound is unavailable.')
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.play()
            self.started.emit(reason)
            return True
        except Exception as error:
            self._error(None, str(error))
            return False

    def _media_status(self, status):
        from PyQt6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop()

    def _error(self, _code, message):
        self.stop()
        message = str(message)[:250]
        if self.active and message != self.last_error:
            self.last_error = message
            self.failed.emit(message)

    def stop(self):
        if self.player is None or self._releasing:
            return
        self._releasing = True
        try:
            self.player.stop()
            self.player.setSource(QUrl())
        finally:
            self._releasing = False

    def detach(self, *_):
        if not self.active:
            return
        self.active = False
        self.stop()
