import unittest

from search_resolution import resolve_search_group
from source_adapter import SourceAdapter
from source_registry import SourceRegistry


class FakeSource(SourceAdapter):
    enabled_by_default = True
    capabilities = frozenset({'search', 'metadata', 'chapters'})

    def __init__(self, source_id, languages, chapters, plan_error='', adult=False):
        self.source_id = source_id
        self.display_name = {'mangadex': 'MangaDex', 'mangapill': 'MangaPill', 'weebcentral': 'WeebCentral'}[source_id]
        self.domains = (source_id + '.test',)
        self.languages = tuple(languages)
        self.chapters = {language: tuple(rows) for language, rows in chapters.items()}
        self.plan_error = plan_error
        self.adult = bool(adult)
        self.metadata_calls = 0
        self.plan_calls = 0
        self.chapter_calls = 0

    def parse_manga_ref(self, value):
        text = str(value or '')
        return text.rsplit('/', 1)[-1] if self.source_id in text else None

    def get_manga(self, value, preferred='en'):
        self.metadata_calls += 1
        return {'uuid': self.parse_manga_ref(value), 'title': 'Series',
                'available_languages': list(self.languages), 'source_url': value,
                'adult': self.adult}

    def search(self, query, **kwargs): return {'query': query, 'rows': []}

    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        self.plan_calls += 1
        if self.plan_error:
            raise RuntimeError(self.plan_error)
        rows = self.chapters.get(language, ())
        volumes = sorted({float(row['volume']) for row in rows if row.get('volume') is not None})
        return {'volumes': volumes}

    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        self.chapter_calls += 1
        return list(self.chapters.get(language, ()))

    def get_volume_covers(self, value): return {}
    def get_page_manifest(self, chapter_id, retry_callback=None): return {'full': [], 'data_saver': []}
    def fetch_binary(self, url, **kwargs): return b''
    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None): return b'', True


def chapters(source_id, start, end, volume=None):
    return [
        {'id': f'{source_id}-{number}', 'chapter': str(number), 'volume': volume}
        for number in range(start, end + 1)
    ]


def candidate(source_id):
    return {
        'source_id': source_id,
        'source_name': {'mangadex': 'MangaDex', 'mangapill': 'MangaPill', 'weebcentral': 'WeebCentral'}[source_id],
        'id': source_id + '-series',
        'url': f'https://{source_id}.test/series/{source_id}-series',
        'title': 'Series',
        'full_title': 'Series',
        'alternate_titles': [],
        'badge': '',
    }


class SearchResolutionTests(unittest.TestCase):
    def test_chapter_resolution_matches_direct_chapter_semantics_without_volume_plan(self):
        dex = FakeSource('mangadex', ('en',), {'en': chapters('dex', 1, 8)}, plan_error='aggregate unavailable')
        resolution = resolve_search_group(SourceRegistry((dex,)), (candidate('mangadex'),), 'en', 'chapter')
        self.assertTrue(resolution.usable)
        self.assertEqual(('mangadex',), resolution.expected_source_ids)
        self.assertEqual(0, dex.plan_calls)
        self.assertGreater(dex.chapter_calls, 0)

    def test_volume_mode_requires_native_readable_volume_inventory(self):
        dex = FakeSource('mangadex', ('en',), {'en': chapters('dex', 1, 4, volume=1)})
        pill = FakeSource('mangapill', ('en',), {'en': chapters('pill', 1, 20)})
        resolution = resolve_search_group(
            SourceRegistry((dex, pill)), (candidate('mangadex'), candidate('mangapill')),
            'en', 'volume',
        )
        self.assertTrue(resolution.usable)
        self.assertEqual(('mangadex',), resolution.expected_source_ids)

    def test_language_fallback_uses_an_actual_reported_language(self):
        dex = FakeSource('mangadex', ('ja',), {'ja': chapters('dex', 1, 3)})
        resolution = resolve_search_group(SourceRegistry((dex,)), (candidate('mangadex'),), 'en', 'chapter')
        self.assertTrue(resolution.usable)
        self.assertTrue(resolution.language_fallback)
        self.assertEqual('ja', resolution.language)

    def test_no_usable_selected_mode_inventory_is_rejected(self):
        pill = FakeSource('mangapill', ('en',), {'en': chapters('pill', 1, 10)})
        resolution = resolve_search_group(SourceRegistry((pill,)), (candidate('mangapill'),), 'en', 'volume')
        self.assertFalse(resolution.usable)
        self.assertEqual((), resolution.expected_source_ids)

    def test_safe_cross_source_gap_plan_orders_primary_then_filler(self):
        pill = FakeSource('mangapill', ('en',), {'en': chapters('pill', 1, 3)})
        weeb = FakeSource('weebcentral', ('en',), {'en': chapters('weeb', 4, 5)})
        resolution = resolve_search_group(
            SourceRegistry((pill, weeb)), (candidate('mangapill'), candidate('weebcentral')),
            'en', 'chapter',
        )
        self.assertTrue(resolution.usable)
        self.assertEqual(('mangapill', 'weebcentral'), resolution.expected_source_ids)
        self.assertTrue(resolution.fallback_plan.can_execute)
        self.assertEqual(1, pill.chapter_calls)
        self.assertEqual(1, weeb.chapter_calls)

    def test_title_level_adult_metadata_is_rejected_before_inventory(self):
        dex = FakeSource('mangadex', ('en',), {'en': chapters('dex', 1, 3)}, adult=True)
        resolution = resolve_search_group(
            SourceRegistry((dex,)), (candidate('mangadex'),), 'en', 'chapter',
            include_adult=False,
        )
        self.assertFalse(resolution.usable)
        self.assertIn('Adult title blocked', resolution.error)
        self.assertEqual(0, dex.chapter_calls)

    def test_inventory_cache_avoids_repeating_identical_resolution(self):
        dex = FakeSource('mangadex', ('en',), {'en': chapters('dex', 1, 3)})
        registry = SourceRegistry((dex,))
        metadata_cache = {}; inventory_cache = {}
        for _ in range(2):
            resolve_search_group(registry, (candidate('mangadex'),), 'en', 'chapter', metadata_cache, inventory_cache)
        self.assertEqual(1, dex.chapter_calls)

    def test_reported_search_languages_avoid_an_extra_metadata_request(self):
        dex = FakeSource('mangadex', ('en',), {'en': chapters('dex', 1, 3)})
        row = candidate('mangadex')
        row['available_languages'] = ['en']
        row['adult'] = False
        resolution = resolve_search_group(SourceRegistry((dex,)), (row,), 'en', 'chapter')
        self.assertTrue(resolution.usable)
        self.assertEqual(0, dex.metadata_calls)


if __name__ == '__main__':
    unittest.main()
