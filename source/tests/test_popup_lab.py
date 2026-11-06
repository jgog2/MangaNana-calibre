"""Laboratory boundaries, state conservation and controlled service contracts."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

from calibre_plugins.manganana.tools.popup_lab import popup_test_state as state


class ResetTests(unittest.TestCase):
    def test_reset_is_narrow_and_backs_up_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = state.ensure_profile(directory)
            path = root / 'plugins/manganana.json'; path.parent.mkdir()
            values = dict(ask_virtual_library=False, popup_test_google_invited=True, update_auto_check=False,
                update_last_attempt=123, update_last_success=124, update_ignored_version='0.14.1', update_later_until=999,
                saved_provider='weebcentral', duplicate_policy='replace', completion_sounds=False, arbitrary='retain')
            path.write_text(json.dumps(values, indent=4), encoding='utf-8'); before = path.read_bytes()
            key = root / 'plugins/private-key-fixture'; key.write_bytes(b'not-a-real-credential')
            favorites = root / 'plugins/favorites-fixture'; favorites.write_bytes(b'preserve-favorite-records')
            backup = state.reset_prompts(root)
            self.assertEqual(backup.read_bytes(), before)
            actual = json.loads(path.read_text())
            self.assertEqual({k: actual[k] for k in state.RESET_VALUES}, state.RESET_VALUES)
            self.assertEqual({k: v for k, v in actual.items() if k not in state.RESET_VALUES},
                             {k: v for k, v in values.items() if k not in state.RESET_VALUES})
            self.assertEqual(key.read_bytes(), b'not-a-real-credential')
            self.assertEqual(favorites.read_bytes(), b'preserve-favorite-records')

    def test_unmarked_or_existing_profile_cannot_be_reset_or_adopted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); (path / 'sentinel').write_text('retain')
            with self.assertRaises(ValueError): state.reset_prompts(path)
            with self.assertRaises(ValueError): state.ensure_profile(path)
            self.assertEqual((path / 'sentinel').read_text(), 'retain')

    def test_normal_profile_is_rejected_even_with_existing_opt_in(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(state, 'normal_locations', return_value={Path(directory).resolve()}):
            with self.assertRaises(ValueError): state.ensure_profile(directory, existing=True)

    def test_live_profile_lock_prevents_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = state.ensure_profile(directory)
            with state.lock_profile(root):
                with self.assertRaises(ValueError): state.reset_prompts(root)
            state.reset_prompts(root)

    def test_invalid_marker_does_not_change_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / state.MARKER).write_text('{"kind":"wrong"}')
            with self.assertRaises(ValueError): state.reset_prompts(root)
            self.assertFalse((root / 'plugins').exists())


ARCHIVE = Path(os.environ.get('MANGAANKA_TEST_ZIP', Path(__file__).resolve().parents[1] /
    'dist/MangaAnka-v0.14.0-cross-platform-popup-test.zip'))


@unittest.skipUnless(ARCHIVE.is_file(), 'Requires separately built popup test ZIP')
class PackagedBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from calibre.customize.zipplugin import loader
        loader.load(str(ARCHIVE))
        from calibre_plugins.manganana.tools.popup_lab import popup_test_support
        cls.lab = popup_test_support

    def test_older_release_is_not_an_upgrade_from_development_build(self):
        lab = self.lab
        with patch.dict(lab.prefs, popup_test_update_scenario='older'):
            raw = lab.release_response(lab.release_updates.API_URL, 10000)
            self.assertIsNone(lab.release_updates.select_release(json.loads(raw), '0.14.0-dev'))

    def test_newer_release_uses_real_release_selector_but_never_downloads(self):
        lab = self.lab
        with patch.dict(lab.prefs, popup_test_update_scenario='newer'):
            release = lab.release_updates.select_release(json.loads(lab.release_response(lab.release_updates.API_URL, 10000)), '0.14.0-dev')
            self.assertEqual(release['version'], '0.14.1')
            with self.assertRaises(RuntimeError): lab.release_response(release['url'], 10000)

    def test_google_success_accepts_only_explicit_dummy_input(self):
        lab = self.lab
        with patch.dict(lab.prefs, popup_test_google_scenario='success'):
            with lab.google_response(urllib.request.Request('https://www.googleapis.com/books/v1/volumes?key=popup-test-valid')) as response:
                self.assertEqual(json.loads(response.read())['kind'], 'books#volumes')
            with self.assertRaises(urllib.error.HTTPError):
                lab.google_response(urllib.request.Request('https://www.googleapis.com/books/v1/volumes?key=accidental-real-input'))

    def test_services_honor_controlled_errors_and_cancellation(self):
        lab = self.lab
        for scenario in ('offline', 'rate-limit'):
            with patch.dict(lab.prefs, popup_test_update_scenario=scenario):
                with self.assertRaises(urllib.error.URLError): lab.release_response(lab.release_updates.API_URL, 10000)
        with self.assertRaises(InterruptedError): lab.release_response(lab.release_updates.API_URL, 10000, lambda: True)

    def test_diagnostics_are_bounded_and_contain_no_key(self):
        lab = self.lab
        for _ in range(230): lab.record('unit', 'controlled')
        self.assertEqual(len(lab.EVENTS), 200)
        self.assertTrue(all(set(row) == {'kind', 'scenario', 'thread'} for row in lab.EVENTS))

    def test_standard_manifest_excludes_lab_and_package_contains_no_preferences(self):
        from tools import build_plugin
        self.assertNotIn('tools/popup_lab/popup_test_support.py', build_plugin.PYTHON_FILES)
        self.assertNotIn('tools/popup_lab/popup_test_state.py', build_plugin.PYTHON_FILES)
        with zipfile.ZipFile(ARCHIVE) as archive:
            self.assertIn('popup-test-build.json', archive.namelist())
            self.assertFalse(any(n.endswith(('google_books_api_key.json', 'manganana.json')) for n in archive.namelist()))
            self.assertIn(b'd.popup_test = attach(d)', archive.read('ui.py'))
        self.assertNotIn('d.popup_test = attach(d)', (Path(__file__).resolve().parents[1] / 'ui.py').read_text())
