"""Offline MangaK contracts using whitelisted public fields from supplied captures."""

import json
from pathlib import Path
import unittest
import urllib.error
import urllib.parse

from calibre_plugins.manganana.providers.mangak_source import MangaKSource
from calibre_plugins.manganana.publication.inventory_comparison import inspect_source_inventory, compare_inventories
from calibre_plugins.manganana.providers.source_registry import SourceRegistry
from calibre_plugins.manganana.providers.source_policy import enabled_sources
from calibre_plugins.manganana.providers.source_coordinator import SourceCoordinator, count_chapter_pages
from tools.build_plugin import files_to_package


ROOT = Path(__file__).resolve().parent.parent
TITLE = 'https://mangak.io/one-piece'
READER = TITLE + '/chapter-1-romance-dawn'


def fixture(name):
    return json.loads((ROOT / 'tests' / 'fixtures' / ('mangak_' + name + '.json')).read_text(encoding='utf-8'))


class Fetcher:
    def __init__(self):
        self.calls = []
        self.build = 'fixture-build'
        self.data = {name: fixture(name) for name in ('search', 'title', 'chapters', 'reader')}

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        path = urllib.parse.urlparse(url).path
        if path == '/home':
            return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({'buildId': self.build}) + '</script>'
        routes = {'/titles/search': 'search', '/titles/98vndE8d/chapters': 'chapters',
                  f'/_next/data/{self.build}/one-piece.json': 'title',
                  f'/_next/data/{self.build}/one-piece/chapter-1-romance-dawn.json': 'reader'}
        if path not in routes:
            raise AssertionError('Unexpected request: ' + url)
        return json.dumps(self.data[routes[path]])


class MangaKTests(unittest.TestCase):
    def setUp(self):
        self.fetch = Fetcher()
        self.binary_calls = []
        self.source = MangaKSource(self.fetch, lambda u, **kw: self.binary_calls.append((u, kw)) or b'image', sleeper=lambda s: None)

    def test_registration_identity_and_package(self):
        registry = SourceRegistry((self.source,))
        self.assertIs(registry.identify(TITLE).source, self.source)
        self.assertEqual('one-piece', registry.identify(READER).reference)
        self.assertEqual(('en',), self.source.content_languages)
        self.assertNotIn('volumes', self.source.capabilities)
        self.assertEqual((), enabled_sources(registry, {'source_enabled': {'mangak': False}}))
        self.assertIsNotNone(registry.identify(TITLE))
        packaged = {name for _, name in files_to_package(ROOT)}
        self.assertIn('providers/mangak_source.py', packaged)
        main = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        self.assertIn('MANGAK_SOURCE = MangaKSource()', main)
        self.assertIn('MANGAK_SOURCE, ATSU_SOURCE', main)

    def test_foreign_reserved_and_non_web_references_rejected_without_fetch(self):
        for value in ('https://mangak.io.evil.test/one-piece', 'https://mangak.io/home',
                      'ftp://mangak.io/one-piece', 'https://user@mangak.io/one-piece',
                      'https://mangak.io/search', 'https://mangak.io/one-piece/other'):
            self.assertIsNone(self.source.parse_manga_ref(value))
        self.assertEqual([], self.fetch.calls)

    def test_search_normalization_and_pagination(self):
        data = self.source.search('One Piece', limit=7)
        self.assertEqual('98vndE8d', data['rows'][0]['id'])
        self.assertEqual(TITLE, data['rows'][0]['url'])
        self.assertEqual(1000, data['rows'][0]['score'])
        self.assertTrue(data['has_more'])
        self.assertEqual(7, data['next_offset'])
        self.fetch.data['search']['data']['items'][0]['is_adult'] = True
        self.assertNotIn('98vndE8d', [r['id'] for r in self.source.search('One Piece')['rows']])
        self.assertIn('98vndE8d', [r['id'] for r in self.source.search('One Piece', include_adult=True)['rows']])
        self.source.search('One Piece', offset=14, limit=7)
        self.assertEqual(['3'], urllib.parse.parse_qs(urllib.parse.urlparse(self.fetch.calls[-1][0]).query)['page'])

    def test_metadata_and_direct_reader_parent(self):
        md = self.source.get_manga(READER)
        self.assertEqual(('98vndE8d', 'One Piece', TITLE), (md['uuid'], md['title'], md['source_url']))
        self.assertTrue(md['author']); self.assertTrue(md['alternate_titles'])
        self.assertEqual({None: md['main_cover_url']}, self.source.get_volume_covers(TITLE))

    def test_complete_chapters_use_display_number_not_internal_index(self):
        rows = self.source.get_chapters(TITLE, 'en')
        self.assertEqual(1307, len(rows))
        numbers = [r['chapter'] for r in rows]
        self.assertEqual(['0', '1', '1.1', '1.2', '2'], numbers[:5])
        self.assertIn('1192', numbers); self.assertNotIn('1307', numbers)
        volume_label = next(r for r in rows if '/vol-96-chapter-976-' in r['id'])
        self.assertEqual('976', volume_label['chapter'])
        self.assertIsNone(volume_label['volume'])
        self.assertTrue(all(r['volume'] is None and r['pages'] is None for r in rows))
        plan = self.source.get_download_plan(TITLE, 'en')
        self.assertEqual(([], 1307), (plan['volumes'], plan['bonus_chapters']))
        self.assertEqual([], self.source.get_chapters(TITLE, 'fr'))
        self.assertEqual([], self.source.get_chapters(TITLE, 'en', 1, 2))

    def test_alternate_versions_are_not_collapsed_into_numeric_identity(self):
        self.fetch.data['chapters']['data']['chapters'] = [
            {'id': 'alt', 'url': '/one-piece/chapter-1-v2', 'name': 'Chapter 1 V2', 'number': 999}]
        self.assertEqual('1 V2', self.source.get_chapters(TITLE, 'en')[0]['chapter'])

    def test_full_reader_order_and_review_without_binary(self):
        manifest = self.source.get_page_manifest(READER)
        self.assertEqual(54, len(manifest['full']))
        self.assertEqual(fixture('reader')['pageProps']['initialChapter']['images'], manifest['full'])
        self.assertEqual([], manifest['data_saver'])
        self.assertEqual(54, count_chapter_pages(self.source, [{'id': READER, 'pages': None}]))
        self.assertEqual([], self.binary_calls)
        self.assertFalse(any('/images' in u for u, _ in self.fetch.calls))

    def test_binary_preview_cover_headers_and_cancel(self):
        url = self.source.get_manga(TITLE)['main_cover_url']
        self.assertEqual((b'image', True), self.source.fetch_preview_page('', url, 1))
        self.assertEqual('https://mangak.io/', self.binary_calls[-1][1]['headers']['Referer'])
        def cancel(): raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            self.source.with_cancel_check(cancel).fetch_binary(url)
        with self.assertRaises(InterruptedError):
            self.source.fetch_preview_page('', url, 1, check_cancel=cancel)

    def test_dynamic_build_refresh_after_deployment(self):
        self.source._build_id = 'stale'
        original = self.source._text_transport
        def transport(url, **kwargs):
            if '/stale/' in url:
                raise urllib.error.HTTPError(url, 404, 'old build', {}, None)
            return original(url, **kwargs)
        self.source._text_transport = transport
        self.assertEqual('One Piece', self.source.get_manga(TITLE)['title'])
        self.assertEqual('fixture-build', self.source._build_id)

    def test_malformed_metadata_and_truncated_reader_fail(self):
        self.fetch.data['title'] = {'pageProps': {}}
        with self.assertRaisesRegex(RuntimeError, 'metadata'):
            self.source.get_manga(TITLE)
        self.fetch.data['reader']['pageProps']['initialChapter']['images'] = ['https://cdn.test/one.jpg']
        with self.assertRaisesRegex(RuntimeError, 'inconsistent'):
            self.source.get_page_manifest(READER)
        with self.assertRaisesRegex(RuntimeError, 'malformed JSON'):
            MangaKSource(lambda u, **kw: '<html>blocked</html>').search('x')

    def test_retries_bounded_and_cancel_backoff(self):
        calls = []
        def fail(url, **kwargs):
            calls.append(url)
            raise urllib.error.HTTPError(url, 503, 'unavailable', {}, None)
        source = MangaKSource(fail, sleeper=lambda s: None)
        with self.assertRaisesRegex(RuntimeError, '3 attempts'): source.search('x')
        self.assertEqual(3, len(calls))
        def cancel():
            if len(calls) > 3: raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError): source.with_cancel_check(cancel).search('x')
        self.assertEqual(4, len(calls))

    def test_chapter_inventory_qualifies_both_workflows_and_failure_isolated(self):
        result = {'url': TITLE, 'title': 'One Piece'}
        inv = inspect_source_inventory(self.source, result, 'en')
        for mode in ('chapter', 'volume'):
            self.assertIs(inv, compare_inventories((inv,), workflow=mode).selected)
        from calibre_plugins.manganana.providers.atsu_source import AtsuSource
        def blocked(url, **kwargs): raise urllib.error.HTTPError(url, 403, 'blocked', {}, None)
        other = AtsuSource(blocked)
        snap = SourceCoordinator(SourceRegistry((self.source, other))).search('One Piece')
        self.assertFalse(snap['all_failed'])
        self.assertTrue(snap['rows'])
        self.assertEqual('failed', snap['providers'][1]['status'])


if __name__ == '__main__':
    unittest.main()
