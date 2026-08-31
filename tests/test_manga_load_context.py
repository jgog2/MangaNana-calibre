from pathlib import Path
import unittest

from manga_load_context import MangaLoadContext, take_manga_load_context


MAIN=(Path(__file__).resolve().parent.parent/'main.py').read_text(encoding='utf-8')


class MangaLoadContextTests(unittest.TestCase):
    def test_search_and_direct_contexts_are_explicit_and_consumed_once(self):
        contexts={
            1:MangaLoadContext('search','https://mangapill.com/manga/3262/one-punch-man','en'),
            2:MangaLoadContext('direct','https://mangadex.org/title/example',''),
        }
        search=take_manga_load_context(contexts,1)
        direct=take_manga_load_context(contexts,2)
        self.assertEqual(('search','en'),(search.discovery_kind,search.requested_language))
        self.assertEqual('direct',direct.discovery_kind)
        with self.assertRaisesRegex(RuntimeError,'Missing manga load context'):
            take_manga_load_context(contexts,1)

    def test_invalid_discovery_kind_is_rejected_at_creation(self):
        with self.assertRaisesRegex(ValueError,'Unsupported manga discovery kind'):
            MangaLoadContext('', 'value')

    def test_apply_loaded_manga_retrieves_context_before_any_read(self):
        section=MAIN[MAIN.index('def _apply_loaded_manga('):MAIN.index('def _download_language_changed(')]
        take=section.index('load_context=take_manga_load_context')
        pending=section.index("pending=dict(self._pending_search_result")
        self.assertLess(take,pending)
        self.assertIn('discovery_kind=load_context.discovery_kind',section)
        self.assertNotIn('_manga_discovery_kinds',section)

    def test_cache_and_worker_callbacks_share_the_same_context_backed_apply_path(self):
        load=MAIN[MAIN.index('def load_metadata('):MAIN.index('def _on_manga_worker_failed(')]
        self.assertLess(load.index('self._manga_load_contexts[request_id]=MangaLoadContext('),
                        load.index('cached=self._manga_cache.get(cache_key)'))
        self.assertIn('self._apply_loaded_manga(r,d)',load)
        self.assertIn('self._apply_loaded_manga(data.get(\'request_id\'),data)',load)

    def test_alias_retry_keeps_actual_query_and_first_pass_pagination(self):
        retry=MAIN[MAIN.index('def _on_alias_search_ready('):MAIN.index('def _store_query_snapshot(')]
        apply=MAIN[MAIN.index('def _apply_search_page('):MAIN.index('def _rebuild_enriched_results(')]
        self.assertIn("page['request_query']=str(page.get('query') or '')",retry)
        self.assertIn("page['context_query']=self._search_query",retry)
        self.assertIn('preserve_existing=True',retry)
        self.assertIn('def _on_alias_search_failed(',retry)
        self.assertIn('Alias retry “{alias}” failed:',retry)
        self.assertIn('if not alias_retry:',apply)
        self.assertIn('Alias retry “{request_query}” returned',apply)


if __name__ == '__main__':
    unittest.main()
