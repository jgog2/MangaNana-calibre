import sqlite3
import tempfile
from pathlib import Path
import unittest

from search_cache import (
    IDENTITY_TTL, INVENTORY_TTL, QUERY_FRESH_SECONDS, QUERY_TTL,
    SCHEMA_VERSION, SearchMetadataCache, query_cache_key,
)


class SearchCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = [1_000_000.0]
        self.path = Path(self.temp.name) / 'cache.sqlite3'
        self.cache = SearchMetadataCache(self.path, clock=lambda: self.now[0])

    def tearDown(self):
        self.cache.close(); self.temp.cleanup()

    def test_cold_fresh_stale_while_revalidate_and_expired_query(self):
        self.assertIsNone(self.cache.get_query_snapshot('q'))
        self.cache.put_query_snapshot('q', {'offsets': {'mangadex': 24}, 'final_result_count': 1})
        self.assertTrue(self.cache.get_query_snapshot('q').fresh)
        self.now[0] += QUERY_FRESH_SECONDS + 1
        stale = self.cache.get_query_snapshot('q')
        self.assertFalse(stale.fresh)
        self.assertEqual(24, stale.value['offsets']['mangadex'])
        self.now[0] += QUERY_TTL
        self.assertIsNone(self.cache.get_query_snapshot('q'))

    def test_layer_ttls_are_distinct(self):
        self.cache.put('inventory', 'i', {'usable': True})
        self.cache.put('external_identity', 'x', {'title': 'Series'})
        self.now[0] += INVENTORY_TTL + 1
        self.assertIsNone(self.cache.get('inventory', 'i'))
        self.assertIsNotNone(self.cache.get('external_identity', 'x'))
        self.now[0] += IDENTITY_TTL
        self.assertIsNone(self.cache.get('external_identity', 'x'))

    def test_query_keys_include_every_material_search_state(self):
        base = query_cache_key('Series', 'chapter', 'en', False, ('mangadex',), False, True)
        variants = {
            query_cache_key('Series', 'volume', 'en', False, ('mangadex',), False, True),
            query_cache_key('Series', 'chapter', 'ja', False, ('mangadex',), False, True),
            query_cache_key('Series', 'chapter', 'en', True, ('mangadex',), False, True),
            query_cache_key('Series', 'chapter', 'en', False, ('mangadex','mangapill'), False, True),
            query_cache_key('Series', 'chapter', 'en', False, ('mangadex',), True, True),
            query_cache_key('Series', 'chapter', 'en', False, ('mangadex',), False, False),
        }
        self.assertNotIn(base, variants)
        self.assertEqual(6, len(variants))

    def test_clear_only_removes_cache_layers(self):
        for table in self.cache.TABLES:
            self.cache.put(table, table, {'value': table})
        self.cache.clear()
        self.assertTrue(all(self.cache.get(table, table, allow_stale=True) is None for table in self.cache.TABLES))
        self.assertGreaterEqual(self.cache.size_bytes(), 0)

    def test_binary_page_or_image_payload_cannot_be_stored(self):
        self.cache.put_query_snapshot('raw', {
            'rows': [{'title': 'Series', 'cover_url': 'https://example.invalid/c.jpg'}],
            'page_bytes': b'not allowed', 'raw_payload': {'huge': True}, 'final_result_count': 1,
        })
        value = self.cache.get_query_snapshot('raw').value
        self.assertNotIn('page_bytes', value)
        self.assertNotIn('raw_payload', value)
        self.assertNotIn('cover_url', value['rows'][0])
        with self.assertRaises(TypeError):
            self.cache.put('external_identity', 'binary', {'blob': b'not allowed'})

    def test_corrupted_database_fails_safe(self):
        self.cache.close()
        self.path.write_bytes(b'not a sqlite database')
        replacement = SearchMetadataCache(self.path, clock=lambda: self.now[0])
        replacement.put_query_snapshot('q', {'rows': [1], 'final_result_count': 1})
        self.assertIsNotNone(replacement.get_query_snapshot('q'))
        replacement.close()

    def test_schema_version_mismatch_invalidates_only_cache_records(self):
        self.cache.put_query_snapshot('q', {'rows': [1], 'final_result_count': 1})
        self.cache.close()
        db = sqlite3.connect(self.path)
        db.execute("UPDATE cache_meta SET value='999' WHERE key='schema_version'")
        db.commit(); db.close()
        replacement = SearchMetadataCache(self.path, clock=lambda: self.now[0])
        self.assertIsNone(replacement.get_query_snapshot('q'))
        db = replacement._connect()
        self.assertEqual(str(SCHEMA_VERSION), db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone()[0])
        replacement.close()

    def test_eviction_priority_keeps_stable_identities_last(self):
        self.assertEqual(
            ('inventory','query_snapshot','external_metrics','provider_mapping','external_identity'),
            self.cache.TABLES,
        )

    def test_zero_final_results_are_never_reusable_but_lower_layers_survive(self):
        self.cache.put('inventory','usable',{'chapter_count':12})
        stored=self.cache.put_query_snapshot('empty',{'content_results':[{'title':'noise'}],'final_result_count':0})
        self.assertFalse(stored)
        self.assertIsNone(self.cache.get_query_snapshot('empty'))
        self.assertEqual(12,self.cache.get('inventory','usable').value['chapter_count'])

    def test_old_provider_inventory_contract_is_ignored_without_clearing_other_layers(self):
        key=('chapter','weebcentral','series-id','en')
        self.cache.put('inventory',repr(key),{'chapter_count':0,'usable':False})
        self.cache.put('provider_mapping','stable',{'work_family_id':'work'})
        self.assertIsNone(self.cache.get_inventory(key))
        self.cache.put_inventory(key,{'chapter_count':162,'usable':True})
        self.assertEqual(162,self.cache.get_inventory(key).value['chapter_count'])
        self.assertEqual('work',self.cache.get('provider_mapping','stable').value['work_family_id'])

    def test_pre_v2_empty_snapshot_is_removed_on_read(self):
        self.cache.put('query_snapshot','old-empty',{'content_results':[]})
        self.assertIsNone(self.cache.get_query_snapshot('old-empty'))
        self.assertIsNone(self.cache.get('query_snapshot','old-empty'))

    def test_size_enforcement_evicts_query_before_stable_identity(self):
        self.cache.close()
        bounded = SearchMetadataCache(
            self.path, clock=lambda: self.now[0],
            hard_limit=600 * 1024, eviction_target=350 * 1024,
        )
        try:
            bounded.put('external_identity', 'identity', {'title': 'A' * 60000})
            bounded.put('query_snapshot', 'query', {'rows': ['B' * 650000]})
            self.assertIsNotNone(bounded.get('external_identity', 'identity'))
            self.assertIsNone(bounded.get('query_snapshot', 'query'))
            self.assertLessEqual(bounded.size_bytes(), bounded.hard_limit)
        finally:
            bounded.close()


if __name__ == '__main__':
    unittest.main()
