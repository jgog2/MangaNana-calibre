"""Focused simulation isolation, official routing and requested copy contracts."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=Path(os.environ.get('MANGAANKA_TEST_ZIP',ROOT/'dist/MangaAnka-v0.14.0-cross-platform-popup-r3-test.zip'))


@unittest.skipUnless(ARCHIVE.is_file(),'Requires the separately packaged popup follow-up ZIP')
class FollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from calibre.customize.zipplugin import loader
        loader.load(str(ARCHIVE))
        from calibre_plugins.manganana.tools.popup_lab import popup_test_support as lab
        cls.lab=lab

    def test_official_checks_delegate_to_the_saved_official_transport(self):
        lab=self.lab;cancelled=lambda:False
        with patch.dict(lab.prefs,popup_test_update_scenario='official'),patch.object(lab,'_OFFICIAL_FETCH',return_value=b'[]') as fetch:
            self.assertEqual(lab.release_response(lab.release_updates.API_URL,10000,cancelled),b'[]')
            fetch.assert_called_once_with('https://api.github.com/repos/jgog2/MangaNana-calibre/releases?per_page=50',10000,cancelled)

    def test_explicit_simulation_is_marked_and_does_not_reconfigure_real_checks(self):
        lab=self.lab
        with patch.dict(lab.prefs,popup_test_update_scenario='official'),patch.object(lab,'_OFFICIAL_FETCH') as fetch:
            release=lab.simulated_release()
            self.assertTrue(release['_popup_simulated']);self.assertEqual(release['version'],'0.14.1')
            self.assertEqual(lab.prefs['popup_test_update_scenario'],'official');fetch.assert_not_called()

    def test_simulation_cannot_download_or_install_even_if_called_directly(self):
        lab=self.lab;release=lab.simulated_release()
        with patch.object(lab,'_OFFICIAL_DOWNLOAD') as download:
            with self.assertRaises(RuntimeError):lab.download_release(release)
            download.assert_not_called()
        controller=SimpleNamespace(release=release,failed=Mock())
        with patch.object(lab,'_DOWNLOADED') as install:
            lab.downloaded(controller,b'fake')
            install.assert_not_called();controller.failed.assert_called_once()

    def test_lab_never_installs_an_actual_release_while_real_checks_stay_available(self):
        lab=self.lab;release=dict(version='0.14.1');cancelled=lambda:False
        with patch.object(lab,'_OFFICIAL_DOWNLOAD',return_value=b'controlled') as download:
            with self.assertRaises(RuntimeError):lab.download_release(release,cancelled)
            download.assert_not_called()

    def test_closed_owner_cannot_start_or_queue_simulation(self):
        lab=self.lab;updates=Mock()
        for active,closing in ((False,False),(True,True)):
            owner=SimpleNamespace(active=active,d=SimpleNamespace(_closing=closing,release_updates=updates))
            lab.PopupLaboratory.simulate_update(owner)
        updates.assert_not_called();updates.checked.assert_not_called()

    def test_repeated_pending_simulation_connects_once_without_arbitrary_delay(self):
        lab=self.lab;worker=SimpleNamespace(finished=Mock())
        owner=SimpleNamespace(active=True,d=SimpleNamespace(_closing=False,release_updates=SimpleNamespace(worker=worker)),
            _simulate_pending=False,_simulate_settled=Mock())
        lab.PopupLaboratory.simulate_update(owner);lab.PopupLaboratory.simulate_update(owner)
        self.assertTrue(owner._simulate_pending);worker.finished.connect.assert_called_once_with(owner._simulate_settled)

    def test_full_setup_and_production_update_rules_are_byte_identical(self):
        with zipfile.ZipFile(ARCHIVE) as current,zipfile.ZipFile(ROOT/'dist/MangaAnka-v0.14.0-cross-platform-popup-test.zip') as old:
            for name in ('app/settings/google_books_key_dialog.py','app/settings/google_books_credentials.py','app/updates/release_updates.py','app/updates/release_updates_ui.py','presentation/non_modal_window.py','books/imports/calibre_destination.py'):
                self.assertEqual(current.read(name),old.read(name),name)
            self.assertIn('Keep MangaAnkā downloads separate from other books in your Calibre view.'.encode(),current.read('app/main.py'))
            support=current.read('tools/popup_lab/popup_test_support.py').decode()
            for phrase in ('Google Books Integration','MangaAnkā can use Google Books to find additional manga metadata',
                           'and volume covers. This feature is optional.','You can set it up anytime under Settings → Google Books.',
                           "addButton('Set Up'","addButton('Not Now'",'Simulate Update Available'):
                self.assertIn(phrase,support)
