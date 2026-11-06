"""Narrow native Qt checks; run with calibre-debug and an isolated config."""

import ast
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

try:
    from qt.core import QApplication, QDialog, QLineEdit, QPushButton, QMessageBox
    from calibre_plugins.manganana.app.settings import google_books_key_dialog as ui
except ImportError:
    ui = None

from calibre_plugins.manganana.app.settings import google_books_credentials as credentials
from tests.test_google_books_credentials import accepted


@unittest.skipIf(ui is None, 'Requires Calibre Qt runtime')
class GoogleBooksKeyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = self.folder.name

    def save(self, key, config_directory=None, **kwargs):
        credentials.save_api_key(key, config_directory or self.root, opener=accepted, **kwargs)

    def wait_worker(self, dialog):
        deadline = time.monotonic() + 10
        while dialog._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertIsNone(dialog._worker)

    def test_mask_toggle_and_official_links(self):
        dialog = ui.GoogleBooksKeyDialog(config_directory=self.root)
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.key_input.echoMode())
        dialog.show_btn.click()
        self.assertEqual(QLineEdit.EchoMode.Normal, dialog.key_input.echoMode())
        dialog.show_btn.click()
        self.assertEqual(QLineEdit.EchoMode.Password, dialog.key_input.echoMode())
        links = []
        with patch.object(ui.QDesktopServices, 'openUrl', side_effect=lambda url: links.append(url.toString())):
            dialog.get_key_btn.click(); dialog.guide_btn.click()
        self.assertEqual([credentials.CREDENTIALS_URL, credentials.GUIDE_URL], links)
        dialog.reject()

    def test_save_worker_empty_failure_and_success(self):
        dialog = ui.GoogleBooksKeyDialog(config_directory=self.root)
        dialog.save_btn.click()
        self.assertIn('Enter a Google Books', dialog.status.text())
        with patch.object(ui, 'save_api_key', side_effect=credentials.CredentialError('Invalid Google Books API key. The key was not saved.')):
            dialog.key_input.setText('synthetic-invalid-key'); dialog.save_btn.click()
            self.wait_worker(dialog)
        self.assertFalse(credentials.has_api_key(self.root))
        self.assertIn('Invalid', dialog.status.text())
        self.assertEqual('', dialog.key_input.text())
        with patch.object(ui, 'save_api_key', side_effect=self.save):
            dialog.key_input.setText('synthetic-verified-key'); dialog.save_btn.click()
            self.wait_worker(dialog)
        self.assertEqual(QDialog.DialogCode.Accepted, dialog.result())
        self.assertTrue(credentials.has_api_key(self.root))

    def test_preferences_connected_replace_and_confirmed_remove(self):
        settings = ui.GoogleBooksSettings(config_directory=self.root)
        self.assertIn('Not configured', settings.status.text())
        self.assertFalse(settings.remove_btn.isEnabled())
        self.save('synthetic-first-key'); settings.refresh()
        self.assertEqual('Status: Connected', settings.status.text())
        self.assertEqual('Replace Key', settings.replace_btn.text())
        signals = []; settings.changed.connect(lambda: signals.append(True))
        def replacement(dialog):
            self.assertEqual('', dialog.key_input.text())
            self.save('synthetic-replacement-key')
            return QDialog.DialogCode.Accepted
        with patch.object(ui.GoogleBooksKeyDialog, 'exec', replacement):
            settings.replace_btn.click()
        self.assertEqual('synthetic-replacement-key', credentials.load_google_books_api_key(self.root).api_key)
        with patch.object(ui.QMessageBox, 'question', return_value=QMessageBox.StandardButton.No):
            settings.remove_btn.click()
        self.assertTrue(credentials.has_api_key(self.root))
        with patch.object(ui.QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
            settings.remove_btn.click()
        self.assertFalse(credentials.has_api_key(self.root))
        self.assertIn('Not configured', settings.status.text())
        self.assertEqual(2, len(signals))

    def test_main_button_visibility_uses_verified_state(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'app/main.py').read_text(encoding='utf-8')
        tree = ast.parse(text)
        dialog = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MangaNanaDialog')
        refresh = next(n for n in dialog.body if isinstance(n, ast.FunctionDef) and n.name == '_refresh_google_books_key_button')
        namespace = {'has_api_key': lambda: credentials.has_api_key(self.root)}
        exec(compile(ast.Module(body=[refresh], type_ignores=[]), 'main key visibility', 'exec'), namespace)
        host = types.SimpleNamespace(google_books_key_btn=QPushButton())
        update = lambda: namespace[refresh.name](host)
        update(); self.assertFalse(host.google_books_key_btn.isHidden())
        self.save('synthetic-verified-key')
        update(); self.assertTrue(host.google_books_key_btn.isHidden())
        credentials.clear_api_key(self.root)
        with patch.dict(os.environ, {'MANGANANA_GOOGLE_BOOKS_API_KEY': 'synthetic-ignored'}):
            update(); self.assertFalse(host.google_books_key_btn.isHidden())
        host.google_books_key_btn.close()
        self.assertIn('d.google_books_settings.changed.connect(self._refresh_google_books_key_button)', text)


if __name__ == '__main__':
    unittest.main()
