import unittest

from source_adapter import SourceAdapter
from source_coordinator import SourceCoordinator, settled_provider_progress
from source_policy import (
    enabled_sources,
    is_source_enabled,
    save_source_enabled_states,
    source_enabled_states,
)
from source_registry import SourceRegistry


class FakePreferences(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commits = 0

    def commit(self):
        self.commits += 1


class FakeSource(SourceAdapter):
    enabled_by_default = True
    capabilities = frozenset({'search', 'metadata', 'chapters'})

    def __init__(self, source_id):
        self.source_id = source_id
        self.display_name = source_id.title()
        self.domains = (source_id + '.test',)
        self.search_calls = 0
        self.metadata_calls = 0

    def parse_manga_ref(self, value):
        prefix = f'https://{self.domains[0]}/series/'
        return value[len(prefix):] if str(value or '').startswith(prefix) else None

    def search(self, query, **kwargs):
        self.search_calls += 1
        return {'query': query, 'rows': [], 'has_more': False}

    def get_manga(self, value, preferred='en'):
        self.metadata_calls += 1
        return {'uuid': self.parse_manga_ref(value), 'title': 'Direct title'}

    def get_download_plan(self, value, language, start_volume=None, end_volume=None): return {'volumes': []}
    def get_chapters(self, value, language, start_volume=None, end_volume=None): return []
    def get_volume_covers(self, value): return {}
    def get_page_manifest(self, chapter_id, retry_callback=None): return {'full': [], 'data_saver': []}
    def fetch_binary(self, url, **kwargs): return b''
    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None): return b'', True


class DefaultOffSource(FakeSource):
    enabled_by_default = False


class SourcePolicyTests(unittest.TestCase):
    def make_registry(self):
        sources = tuple(FakeSource(source_id) for source_id in ('mangadex', 'mangapill', 'weebcentral'))
        return SourceRegistry(sources), sources

    def test_all_registered_sources_default_enabled(self):
        registry, sources = self.make_registry()
        preferences = FakePreferences()
        self.assertTrue(all(is_source_enabled(preferences, source) for source in sources))
        self.assertEqual(sources, enabled_sources(registry, preferences))

    def test_state_persists_by_source_id_and_preserves_unknown_entries(self):
        preferences = FakePreferences({'source_enabled': {'future-source': False}})
        stored = save_source_enabled_states(preferences, {'mangapill': False})
        self.assertEqual({'future-source': False, 'mangapill': False}, stored)
        self.assertEqual(stored, source_enabled_states(preferences))
        self.assertEqual(1, preferences.commits)

    def test_disabled_source_gets_no_general_search_task_and_progress_uses_two(self):
        registry, (dex, pill, weeb) = self.make_registry()
        preferences = FakePreferences({'source_enabled': {'mangapill': False}})
        coordinator = SourceCoordinator(registry, enabled_sources(registry, preferences))
        result = coordinator.search('Series')
        self.assertEqual(1, dex.search_calls)
        self.assertEqual(0, pill.search_calls)
        self.assertEqual(1, weeb.search_calls)
        self.assertEqual(2, result['total'])
        self.assertEqual((2, 2), settled_provider_progress(result))

    def test_all_sources_disabled_produces_no_participants_or_requests(self):
        registry, sources = self.make_registry()
        preferences = FakePreferences({'source_enabled': {
            source.source_id: False for source in sources
        }})
        participating = enabled_sources(registry, preferences)
        self.assertEqual((), participating)
        coordinator = SourceCoordinator(registry, participating)
        self.assertEqual((), coordinator.sources)
        self.assertTrue(all(source.search_calls == 0 for source in sources))

    def test_disabled_direct_source_remains_registered_and_executable(self):
        registry, (_dex, _pill, weeb) = self.make_registry()
        preferences = FakePreferences({'source_enabled': {'weebcentral': False}})
        url = 'https://weebcentral.test/series/abc'
        self.assertFalse(is_source_enabled(preferences, weeb))
        match = registry.identify(url)
        self.assertIs(weeb, match.source)
        self.assertEqual('Direct title', match.source.get_manga(url)['title'])
        self.assertEqual(1, weeb.metadata_calls)

    def test_disabling_does_not_mutate_an_existing_search_coordinator(self):
        registry, sources = self.make_registry()
        preferences = FakePreferences()
        active = SourceCoordinator(registry, enabled_sources(registry, preferences))
        save_source_enabled_states(preferences, {'mangapill': False})
        self.assertEqual(sources, active.sources)
        future = SourceCoordinator(registry, enabled_sources(registry, preferences))
        self.assertEqual(('mangadex', 'weebcentral'), tuple(source.source_id for source in future.sources))

    def test_invalid_stored_values_fail_safe_to_source_default(self):
        registry, sources = self.make_registry()
        preferences = FakePreferences({'source_enabled': {'mangadex': 'false'}})
        self.assertNotIn('mangadex', source_enabled_states(preferences))
        self.assertTrue(is_source_enabled(preferences, sources[0]))
        self.assertEqual(3, len(enabled_sources(registry, preferences)))

    def test_future_provider_can_supply_a_safer_default(self):
        source = DefaultOffSource('future')
        preferences = FakePreferences()
        self.assertFalse(is_source_enabled(preferences, source))
        save_source_enabled_states(preferences, {'future': True})
        self.assertTrue(is_source_enabled(preferences, source))


if __name__ == '__main__':
    unittest.main()
