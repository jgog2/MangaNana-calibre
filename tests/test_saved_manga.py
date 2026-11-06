"""Exact bookmark identity, bounded storage and atomic restart contracts."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if 'calibre_plugins.manganana' not in sys.modules:
    package = types.ModuleType('calibre_plugins.manganana')
    package.__path__ = [str(ROOT)]
    sys.modules['calibre_plugins.manganana'] = package
from calibre_plugins.manganana.discovery.saved_manga import FavoritesStore, favorite_key, clean_record, MAX_BYTES
from calibre_plugins.manganana.discovery import saved_manga as storage


def listing(**extra):
    return dict(dict(source_id='mangapill', source_name='MangaPill', id='1',
        url='https://mangapill.com/manga/1/berserk', title='Berserk', language='en',
        canonical_work_id='anilist:30002|kitsu:8', edition='original'), **extra)


class SavedMangaTests(unittest.TestCase):
    def setUp(self):
        directory=ROOT/'build/saved-manga-favorites/unit-temp'
        directory.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.store = FavoritesStore(self.temp.name)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_case_only_display_changes_do_not_duplicate(self):
        self.assertEqual(favorite_key(listing()), favorite_key(listing(title='BERSERK')))
        self.store.toggle(listing())
        self.assertTrue(self.store.contains(listing(title='berserk')))
        self.store.toggle(listing(title='BERSERK'))
        self.assertFalse(self.store.records)

    def test_provider_editions_layout_languages_are_separate(self):
        rows = [listing(), listing(source_id='weebcentral'), listing(edition='official_color'),
            listing(publication_layout='webcomic'), listing(language='ja'), listing(id='2')]
        self.assertEqual(len(rows), len({favorite_key(r) for r in rows}))

    def test_url_slug_changes_do_not_duplicate_provider_id(self):
        self.assertEqual(favorite_key(listing()), favorite_key(listing(url='https://mangapill.com/manga/1/berserk-new-title')))

    def test_atomic_coalesced_write_and_restart(self):
        for i in range(100):
            self.store.toggle(listing(id=str(i)))
        self.assertTrue(self.store.close())
        recovered = FavoritesStore(self.temp.name)
        self.addCleanup(recovered.close)
        self.assertEqual(self.store.records, recovered.records)
        document = json.loads(self.store.path.read_bytes())
        self.assertEqual(2, document['version'])
        self.assertFalse(list(self.store.path.parent.glob('.manganana-favorites-*')))

    def test_only_explicit_toggle_creates_entries(self):
        self.assertFalse(self.store.path.exists())
        self.store.contains(listing())
        self.store.close()
        self.assertFalse(self.store.path.exists())

    def test_payload_credentials_and_chapters_not_retained(self):
        row = clean_record(listing(chapters=[{'id':'secret'}], token='secret', password='secret',
            cover_url='https://cdn.example/image.jpg?token=secret', resolution=object(),
            external_ids={'anilist_id':'30002', 'password':'secret'}))
        self.assertFalse({'chapters','token','password','resolution'} & row.keys())
        self.assertNotIn('secret', json.dumps(row))
        self.assertEqual({'anilist_id':'30002'}, row['external_ids'])
        self.assertIsNone(clean_record(listing(url='https://user:secret@mangapill.com/manga/1')))

    def test_invalid_records_are_skipped_without_blocking_valid_entries(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text(json.dumps(dict(version=2, records=[
            dict(key=favorite_key(listing()), listing=listing()), None,
            dict(key='wrong-key', listing=listing(id='2')),
            dict(key='invalid-provider',listing=listing(source_id=[]))])))
        restored = FavoritesStore(self.temp.name)
        self.addCleanup(restored.close)
        self.assertEqual(1, len(restored.records))
        self.assertFalse(restored.read_only)
        self.assertIn('Skipped 3', restored.warning)

    def test_future_and_corrupt_documents_are_preserved(self):
        self.store.path.parent.mkdir(parents=True)
        for data in ('{broken', '{"version":99,"records":[]}'):
            self.store.path.write_text(data)
            restored = FavoritesStore(self.temp.name)
            self.assertTrue(restored.read_only)
            with self.assertRaises(ValueError):restored.toggle(listing())
            restored.close()
            self.assertEqual(data, self.store.path.read_text())

    def test_v1_migration_keeps_identity(self):
        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text(json.dumps(dict(version=1, records=[listing(), listing(title='BERSERK')])))
        restored = FavoritesStore(self.temp.name)
        self.assertEqual(1, len(restored.records))
        restored.toggle(listing(id='2'))
        self.assertTrue(restored.close())
        self.assertEqual(2, json.loads(restored.path.read_text())['version'])

    def test_file_and_record_limits_fail_without_losing_existing_state(self):
        self.store.toggle(listing())
        with patch.object(storage,'MAX_RECORDS', 1):
            with self.assertRaises(ValueError):self.store.toggle(listing(id='2'))
        self.assertTrue(self.store.contains(listing()))
        self.store.close()
        self.store.path.write_bytes(b' ' * (MAX_BYTES+1))
        restored=FavoritesStore(self.temp.name)
        self.assertTrue(restored.read_only)
        restored.close()

    def test_atomic_failure_preserves_previous_file(self):
        self.store.toggle(listing());self.store.close()
        previous = self.store.path.read_bytes()
        restored = FavoritesStore(self.temp.name)
        with patch.object(storage.os,'replace', side_effect=OSError('controlled disk failure')):
            restored.toggle(listing(id='2'))
            self.assertFalse(restored.close())
        self.assertEqual(previous, self.store.path.read_bytes())
        recovery = list(self.store.path.parent.glob('.manganana-favorites-*'))
        self.assertEqual(1, len(recovery))
        self.assertEqual(2, len(json.loads(recovery[0].read_text())['records']))
        self.assertIn(str(recovery[0]), restored.error)
        retry = FavoritesStore(self.temp.name)
        self.assertTrue(retry.close())
        self.assertFalse(recovery[0].exists())


if __name__ == '__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SavedMangaTests))
    if not result.wasSuccessful():raise SystemExit(1)
