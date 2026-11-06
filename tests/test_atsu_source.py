"""Offline Atsu contracts using whitelisted public fields from supplied captures."""

import json
from pathlib import Path
import unittest
import urllib.error
import urllib.parse

from calibre_plugins.manganana.providers.atsu_source import AtsuSource
from calibre_plugins.manganana.providers.source_registry import SourceRegistry
from calibre_plugins.manganana.providers.source_policy import enabled_sources
from calibre_plugins.manganana.publication.inventory_comparison import inspect_source_inventory, compare_inventories
from tools.build_plugin import files_to_package


ROOT = Path(__file__).resolve().parent.parent
TITLE = 'https://atsu.moe/manga/Xqitk'
READER = 'https://atsu.moe/read/Xqitk/hI3sCUwE'


class Fetcher:
    def __init__(self):
        self.calls = []
        self.data = {n: json.loads((ROOT / 'tests' / 'fixtures' / ('atsu_' + n + '.json')).read_text(encoding='utf-8'))
                     for n in ('search', 'title', 'chapters', 'reader')}

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = urllib.parse.urlparse(url).path
        routes = {'/collections/manga/documents/search': 'search', '/api/manga/page': 'title',
                  '/api/manga/allChapters': 'chapters', '/api/read/chapter': 'reader'}
        if path not in routes: raise AssertionError('Unexpected request: ' + url)
        return json.dumps(self.data[routes[path]])


class AtsuTests(unittest.TestCase):
    def setUp(self):
        self.fetch = Fetcher(); self.binary_calls = []
        self.source = AtsuSource(self.fetch, lambda u, **kw: self.binary_calls.append((u, kw)) or b'image', sleeper=lambda s: None)

    def test_registration_direct_refs_policy_and_package(self):
        registry = SourceRegistry((self.source,))
        for url in (TITLE, READER):
            self.assertEqual('Xqitk', registry.identify(url).reference)
        for url in ('https://atsu.moe.evil.test/manga/Xqitk', 'ftp://atsu.moe/manga/Xqitk',
                    'https://user@atsu.moe/manga/Xqitk', 'https://atsu.moe/read/Xqitk', 'Xqitk'):
            self.assertIsNone(self.source.parse_manga_ref(url))
        self.assertEqual([], self.fetch.calls)
        self.assertIn('volumes', self.source.capabilities)
        self.assertEqual(('en',), self.source.content_languages)
        self.assertEqual((), enabled_sources(registry, {'source_enabled': {'atsu': False}}))
        self.assertIsNotNone(registry.identify(READER))
        self.assertIn('providers/atsu_source.py', {p for _, p in files_to_package(ROOT)})
        self.assertIn('ATSU_SOURCE = AtsuSource()', (ROOT / 'app/main.py').read_text(encoding='utf-8'))

    def test_search_captured_query_and_normalization(self):
        data = self.source.search('One Piece')
        row = next(r for r in data['rows'] if r['id'] == 'Xqitk')
        self.assertEqual(('One Piece (Color)', TITLE, 'ODA Eiichiro'), (row['title'], row['url'], row['author']))
        self.assertTrue(row['cover_url'].startswith('https://cdn.atsu.moe/static/posters/'))
        self.source.search('One Piece', offset=12)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.fetch.calls[-1][0]).query)
        self.assertEqual(['2'], query['page'])
        self.assertEqual(['title,englishTitle,otherNames,authors,acronyms'], query['query_by'])
        self.assertEqual(['isAdult:=false && views:>0 && hidden:!=true'], query['filter_by'])
        self.source.search('One Piece', include_adult=True)
        self.assertNotIn('isAdult', urllib.parse.parse_qs(urllib.parse.urlparse(self.fetch.calls[-1][0]).query)['filter_by'][0])

    def test_metadata_parent_and_cover(self):
        md = self.source.get_manga(READER)
        self.assertEqual(('Xqitk', 'One Piece (Color)', TITLE), (md['uuid'], md['title'], md['source_url']))
        self.assertEqual('Eiichirou Oda', md['author'])
        self.assertTrue(md['alternate_titles']); self.assertTrue(md['year'])
        self.assertEqual('https://cdn.atsu.moe/static/posters/SXfnXIG79jc1uhCY.jpg', md['main_cover_url'])
        self.assertEqual({None: md['main_cover_url']}, self.source.get_volume_covers(TITLE))

    def test_complete_inventory_and_fresh_adapter_manifest(self):
        rows = self.source.get_chapters(TITLE, 'en')
        self.assertEqual(1076, len(rows))
        self.assertEqual(('1', READER, 56), (rows[0]['chapter'], rows[0]['id'], rows[0]['pages']))
        self.assertTrue(all(r['volume'] is None for r in rows))
        manifest = AtsuSource(self.fetch).get_page_manifest(rows[0]['id'])
        self.assertEqual(56, len(manifest['full']))
        self.assertEqual([f'https://cdn.atsu.moe/static/pages/Xqitk/hI3sCUwE/{i}.webp' for i in range(56)], manifest['full'])
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.fetch.calls[-1][0]).query)
        self.assertEqual({'mangaId': ['Xqitk'], 'chapterId': ['hI3sCUwE']}, query)
        plan = self.source.get_download_plan(TITLE, 'en')
        self.assertEqual(([], 1076), (plan['volumes'], plan['bonus_chapters']))
        self.assertEqual([], self.source.get_chapters(TITLE, 'ja'))
        self.assertEqual([], self.source.get_chapters(TITLE, 'en', 1, 2))

    def test_decimals_zero_and_specials(self):
        self.fetch.data['chapters']['chapters'] = [
            {'id': str(i), 'number': n, 'title': 'Special' if n is None else 'Chapter ' + str(n), 'pageCount': 1}
            for i, n in enumerate((2, 1.2, 0, 1.1, 1, None))]
        self.assertEqual(['0', '1', '1.1', '1.2', '2', 'Special'], [r['chapter'] for r in self.source.get_chapters(TITLE, 'en')])

    def test_page_order_and_missing_pages(self):
        pages = self.fetch.data['reader']['readChapter']['pages']
        pages.reverse()
        self.assertTrue(self.source.get_page_manifest(READER)['full'][0].endswith('/0.webp'))
        pages.pop()
        with self.assertRaisesRegex(RuntimeError, 'missing or duplicate'):
            self.source.get_page_manifest(READER)

    def test_malformed_empty_and_wrong_identity_fail(self):
        self.fetch.data['title']['mangaPage']['id'] = 'wrong'
        with self.assertRaisesRegex(RuntimeError, 'metadata'): self.source.get_manga(TITLE)
        self.fetch.data['reader']['readChapter']['pages'] = []
        with self.assertRaisesRegex(RuntimeError, 'readable pages'): self.source.get_page_manifest(READER)
        self.fetch.data['chapters'] = {}
        with self.assertRaisesRegex(RuntimeError, 'incomplete'): self.source.get_chapters(TITLE, 'en')
        with self.assertRaisesRegex(RuntimeError, 'malformed JSON'):
            AtsuSource(lambda u, **kw: '<html>503</html>').search('x')

    def test_binary_preview_referer_and_cancel(self):
        url = self.source.get_page_manifest(READER)['full'][0]
        self.assertEqual((b'image', True), self.source.fetch_preview_page('', url, 1))
        self.assertEqual('https://atsu.moe/', self.binary_calls[-1][1]['headers']['Referer'])
        self.assertEqual(b'image', self.source.fetch_binary(self.source.get_manga(TITLE)['main_cover_url']))
        def cancel(): raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError): self.source.with_cancel_check(cancel).fetch_binary(url)

    def test_retry_transient_then_success_and_permanent_failure(self):
        calls = []
        def transient(url, **kw):
            calls.append(url)
            if len(calls) < 3: raise urllib.error.HTTPError(url, 503, 'temporary', {}, None)
            return self.fetch(url, **kw)
        self.assertEqual('Xqitk', AtsuSource(transient, sleeper=lambda s: None).get_manga(TITLE)['uuid'])
        self.assertEqual(3, len(calls))
        def blocked(url, **kw): raise urllib.error.HTTPError(url, 403, 'blocked', {}, None)
        with self.assertRaisesRegex(RuntimeError, 'access blocked by site protection'):
            AtsuSource(blocked).search('x')

    def test_inventory_qualifies_for_both_workflows(self):
        inv = inspect_source_inventory(self.source, {'url': TITLE, 'title': 'One Piece (Color)'}, 'en')
        self.assertEqual(0, inv.native_volumes)
        self.assertEqual(1076, inv.standalone_chapters)
        for mode in ('volume', 'chapter'):
            self.assertIs(inv, compare_inventories((inv,), expected_edition=inv.edition, workflow=mode).selected)


if __name__ == '__main__':
    unittest.main()
