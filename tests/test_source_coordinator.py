import unittest

from source_adapter import SourceAdapter
from source_coordinator import SourceCoordinator, SourceSearchError, count_chapter_pages, format_page_count
from source_registry import SourceRegistry


class FakeSource(SourceAdapter):
    enabled_by_default = True
    capabilities = frozenset({'search', 'metadata', 'chapters'})

    def __init__(self, source_id, display_name, domain, rows=(), failure=''):
        self.source_id = source_id
        self.display_name = display_name
        self.domains = (domain,)
        self.rows = list(rows)
        self.failure = failure

    def parse_manga_ref(self, value):
        prefix = f'https://{self.domains[0]}/title/'
        return value[len(prefix):] if isinstance(value, str) and value.startswith(prefix) else None

    def search(self, query, **kwargs):
        if self.failure:
            raise RuntimeError(self.failure)
        return {'query': query, 'rows': list(self.rows), 'has_more': False}

    def get_manga(self, value, preferred='en'):
        return {'uuid': self.parse_manga_ref(value), 'title': 'Title'}

    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        return {'volumes': [1.0]} if self.source_id == 'mangadex' else {'volumes': [], 'bonus_chapters': 2}

    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        volume = 1.0 if self.source_id == 'mangadex' else None
        return [{'id': 'chapter', 'volume': volume, 'chapter': '1', 'pages': 1}]

    def get_volume_covers(self, value): return {}
    def get_page_manifest(self, chapter_id, retry_callback=None): return {'full': [], 'data_saver': []}
    def fetch_binary(self, url, **kwargs): return b''
    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None): return b'', True


class SourceCoordinatorTests(unittest.TestCase):
    def make_coordinator(self, dex_failure='', pill_failure=''):
        dex = FakeSource('mangadex', 'MangaDex', 'mangadex.test',
                         [{'id': 'same', 'title': 'Edition'}], dex_failure)
        pill = FakeSource('mangapill', 'MangaPill', 'mangapill.test',
                          [{'id': 'same', 'title': 'Edition'}], pill_failure)
        return SourceCoordinator(SourceRegistry((dex, pill))), dex, pill

    def test_combined_search_attributes_results_and_keeps_duplicate_editions(self):
        coordinator, _dex, _pill = self.make_coordinator()
        result = coordinator.search('Edition')
        self.assertEqual(['mangadex', 'mangapill'], [row['source_id'] for row in result['rows']])
        self.assertEqual(['MangaDex', 'MangaPill'], [row['source_name'] for row in result['rows']])
        self.assertEqual(2, len(result['rows']))

    def test_one_provider_failure_does_not_hide_success(self):
        coordinator, _dex, _pill = self.make_coordinator(dex_failure='offline')
        result = coordinator.search('Edition')
        self.assertEqual(['mangapill'], [row['source_id'] for row in result['rows']])
        states = {state['source_id']: state for state in result['providers']}
        self.assertEqual('failed', states['mangadex']['status'])
        self.assertEqual('complete', states['mangapill']['status'])

    def test_all_provider_failure_has_combined_error(self):
        coordinator, _dex, _pill = self.make_coordinator('dex down', 'pill down')
        with self.assertRaises(SourceSearchError) as raised:
            coordinator.search('Edition')
        self.assertIn('MangaDex: dex down', str(raised.exception))
        self.assertIn('MangaPill: pill down', str(raised.exception))

    def test_direct_urls_route_through_registry(self):
        coordinator, dex, pill = self.make_coordinator()
        self.assertIs(dex, coordinator.identify('https://mangadex.test/title/abc').source)
        self.assertIs(pill, coordinator.identify('https://mangapill.test/title/xyz').source)

    def test_selected_result_retains_provider_and_workflow_model(self):
        coordinator, dex, pill = self.make_coordinator()
        rows = coordinator.search('Edition')['rows']
        self.assertIs(dex, coordinator.source_for_result(rows[0]))
        self.assertIs(pill, coordinator.source_for_result(rows[1]))
        self.assertEqual([1.0], dex.get_download_plan('', 'en')['volumes'])
        self.assertEqual([], pill.get_download_plan('', 'en')['volumes'])
        self.assertIsNone(pill.get_chapters('', 'en')[0]['volume'])

    def test_provider_order_is_registration_order(self):
        coordinator, _dex, _pill = self.make_coordinator()
        self.assertEqual(('mangadex', 'mangapill'),
                         tuple(state['source_id'] for state in coordinator.snapshot()['providers']))

    def test_mangadex_known_page_counts_are_summed_without_manifest_requests(self):
        coordinator, dex, _pill = self.make_coordinator()
        del coordinator
        dex.get_page_manifest = lambda *_args, **_kwargs: self.fail('manifest should not be requested')
        self.assertEqual(12, count_chapter_pages(dex, [
            {'id': 'a', 'pages': 5}, {'id': 'b', 'pages': 7},
        ]))

    def test_unknown_count_remains_unknown_when_manifest_is_unavailable(self):
        coordinator, _dex, pill = self.make_coordinator()
        del coordinator
        pill.get_page_manifest = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('unavailable'))
        self.assertIsNone(count_chapter_pages(pill, [{'id': 'a', 'pages': None}]))

    def test_unknown_review_page_count_is_not_rendered_as_zero(self):
        self.assertEqual('Unknown', format_page_count(None))
        self.assertEqual('12', format_page_count(12))


if __name__ == '__main__':
    unittest.main()
