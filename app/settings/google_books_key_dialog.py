"""Small Google Books-only setup and Preferences controls."""

from qt.core import (
    QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QThread, QVBoxLayout, QDesktopServices, QUrl,
    QScrollArea, QWidget, pyqtSignal, QFormLayout, QToolButton,
)
from calibre_plugins.manganana.presentation.non_modal_window import (
    PluginDialog as QDialog,
    PluginMessageBox as QMessageBox,
    plugin_window,
)

_JOBS = set()

from calibre_plugins.manganana.app.settings.google_books_credentials import (
    CREDENTIALS_URL,
    GUIDE_URL,
    CredentialError,
    has_api_key,
    save_api_key,
    clear_api_key,
)


class GoogleBooksKeyWorker(QThread):
    def __init__(self, key, config_directory=None, parent=None):
        super().__init__(parent)
        self._key = key
        self._config_directory = config_directory
        self.error = ''

    def run(self):
        try:
            save_api_key(self._key, self._config_directory, cancelled=self.isInterruptionRequested)
        except InterruptedError:
            pass
        except CredentialError as exc:
            self.error = str(exc)
        except Exception:
            self.error = 'Google Books setup could not be completed. The key was not saved.'
        finally:
            self._key = ''


class GoogleBooksKeyDialog(QDialog):
    def __init__(self, parent=None, config_directory=None):
        super().__init__(parent)
        self._config_directory = config_directory
        self._worker = None
        self._active = True
        self.finished.connect(self._detach)
        self.setWindowTitle('MangaAnkā · Google Books')
        self.resize(570, 430)
        self.setStyleSheet('''QDialog,QWidget {background:#191d20;color:#edf0f0;font-size:13px;}
            QLabel {background:transparent;} QGroupBox {background:#23292c;border:1px solid #343c3f;border-radius:8px;margin-top:18px;padding:14px;}
            QLineEdit,QPushButton,QToolButton {background:#2c3337;color:#edf0f0;border:1px solid #41494c;border-radius:6px;padding:7px;}
            QPushButton#primaryAction {background:#66B7A8;color:#102421;border-color:#66B7A8;}
        ''')
        root = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); content = QVBoxLayout(body)
        heading = QLabel('Optional metadata & volume artwork')
        heading.setStyleSheet('font-size:20px;font-weight:600;');heading.setWordWrap(True)
        content.addWidget(heading)
        intro = QLabel('Connect your Google Books API key for an additional source of publication metadata and volume covers. Search, downloads and other reference sources work without it.')
        intro.setWordWrap(True);content.addWidget(intro)
        instructions = QWidget();instruction_layout=QVBoxLayout(instructions)
        self.setup_details = QToolButton();self.setup_details.setText('How to get a key & privacy')
        self.setup_details.setCheckable(True)
        self.setup_details.toggled.connect(instructions.setVisible)
        content.addWidget(self.setup_details)
        for text in (
            'In Google Cloud, select a project, enable the Books API, then create an API key under Credentials. Use “Get API Key” or the setup guide below.',
            'Requests use your Google Cloud project quota. Restrict the key to the Books API.',
            'Your API key is stored locally in MangaAnkā’s private configuration area on this '
            'computer. It is only used for requests sent to Google Books. It is not included in '
            'MangaAnkā logs, diagnostics, exported settings, plugin builds, Git files, or requests '
            'sent to manga providers. Local storage is not encrypted and is not protection against '
            'someone who already has access to your computer account.',
        ):
            label = QLabel(text); label.setWordWrap(True);instruction_layout.addWidget(label)
        content.addWidget(instructions);instructions.hide();content.addStretch(1)
        scroll.setWidget(body); root.addWidget(scroll, 1)
        root.addWidget(QLabel('API Key'))
        row = QHBoxLayout()
        self.key_input = QLineEdit(); self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setAccessibleName('Google Books API key')
        self.show_btn = QPushButton('Show'); self.show_btn.clicked.connect(self._toggle_visibility)
        row.addWidget(self.key_input, 1); row.addWidget(self.show_btn); root.addLayout(row)
        self.status = QLabel(''); self.status.setWordWrap(True); root.addWidget(self.status)
        actions = QHBoxLayout()
        self.get_key_btn = QPushButton('Get API Key')
        self.get_key_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CREDENTIALS_URL)))
        self.save_btn = QPushButton('Save & Test'); self.save_btn.setObjectName('primaryAction')
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(self.get_key_btn); actions.addStretch(1); actions.addWidget(self.save_btn)
        root.addLayout(actions)
        self.guide_btn = QPushButton('Google Books setup guide'); self.guide_btn.setFlat(True)
        self.guide_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GUIDE_URL)))
        root.addWidget(self.guide_btn)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Not now')
        self.buttons.rejected.connect(self.reject); root.addWidget(self.buttons)

    def _toggle_visibility(self):
        show = self.key_input.echoMode() == QLineEdit.EchoMode.Password
        self.key_input.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password)
        self.show_btn.setText('Hide' if show else 'Show')

    def _save(self):
        if self._worker is not None:
            return
        key = self.key_input.text().strip()
        if not key:
            self.status.setText('Enter a Google Books API key.')
            return
        self._worker = GoogleBooksKeyWorker(key, self._config_directory)
        worker=self._worker;_JOBS.add(worker)
        owner=plugin_window(self)
        if owner is not None: owner._retain_async_worker(worker)
        self.key_input.clear()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password); self.show_btn.setText('Show')
        for widget in (self.key_input, self.show_btn, self.save_btn):
            widget.setEnabled(False)
        self.status.setText('Testing Google Books access…')
        self._worker.finished.connect(self._finished)
        self._worker.finished.connect(lambda w=worker: (_JOBS.discard(w),w.deleteLater()))
        self._worker.start()

    def _finished(self):
        error = self._worker.error
        self._worker = None
        if not self._active:return
        for widget in (self.key_input, self.show_btn, self.save_btn, self.buttons):
            widget.setEnabled(True)
        if error:
            self.status.setText(error)
        else:
            self.accept()

    def reject(self):
        self.key_input.clear()
        super().reject()

    def _detach(self, *_):
        self._active=False
        if self._worker is not None:self._worker.requestInterruption()

    def closeEvent(self, event):
        self._detach()
        self.key_input.clear()
        super().closeEvent(event)


class GoogleBooksSettings(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, parent=None, config_directory=None):
        super().__init__('Google Books API', parent)
        self._config_directory = config_directory
        layout = QFormLayout(self)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addRow('',self.status)
        row = QHBoxLayout()
        self.replace_btn = QPushButton(); self.replace_btn.clicked.connect(self._replace)
        self.remove_btn = QPushButton('Remove Key'); self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.replace_btn); row.addWidget(self.remove_btn); row.addStretch(1)
        layout.addRow('',row); self.refresh()

    def refresh(self):
        connected = has_api_key(self._config_directory)
        self.status.setText('Status: Connected' if connected else 'Status: Not configured (optional)')
        self.replace_btn.setText('Replace Key' if connected else 'Set Up Key')
        self.remove_btn.setEnabled(connected)

    def _replace(self):
        dialog = GoogleBooksKeyDialog(self, self._config_directory)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(); self.changed.emit()

    def _remove(self):
        answer = QMessageBox.question(self, 'Remove Google Books API Key',
            'Remove the stored key? Google Books will be disabled. Other reference sources remain available.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            clear_api_key(self._config_directory)
        except CredentialError as exc:
            QMessageBox.warning(self, 'Google Books API Key', str(exc))
            return
        self.refresh(); self.changed.emit()
