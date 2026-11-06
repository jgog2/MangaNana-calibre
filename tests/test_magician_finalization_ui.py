from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / 'app/main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'app/settings/config.py').read_text(encoding='utf-8')


class MagicianFinalizationUiTests(unittest.TestCase):
    def test_removed_browse_widget_has_zero_production_dependencies(self):
        self.assertNotIn('browse_mangadex_btn', MAIN)
        lock = MAIN[MAIN.index('def _set_download_ui_locked('):MAIN.index('def _check_download_disk_space(')]
        self.assertIn('self.search_box, self.prefer_colored, self.search_btn', lock)

    def test_prefer_colored_is_persistent_and_local_only(self):
        self.assertIn("prefs.defaults['prefer_colored'] = False", CONFIG)
        self.assertIn("self.prefer_colored = MangaSelectionCheckBox('Prefer Colored')", MAIN)
        self.assertIn("prefs['prefer_colored'] = bool(checked)", MAIN)
        prefer=MAIN[MAIN.index('def _prefer_colored_changed('):MAIN.index('def _search_score(')]
        self.assertIn('_render_provider_search_results()',prefer)
        self.assertNotIn('search_mangadex(',prefer)

    def test_enrichment_preferences_are_separate_from_manga_sources(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self, 'enrichment_preferences_are_separate_from_manga_sources')

    def test_unresolved_source_state_is_a_neutral_pill(self):
        self.assertIn("unresolved_text='Searching sources…'", MAIN)
        self.assertIn("'kind':'neutral'", MAIN)
        self.assertIn("'icon_path':''", MAIN)

    def test_stale_cache_refresh_does_not_restore_provider_offsets(self):
        search = MAIN[MAIN.index('def search_mangadex('):MAIN.index('def _on_search_ready(')]
        zero = search.index("self._search_offsets={source.source_id:0")
        fresh = search.index("if hit is not None and hit.fresh and snapshot.get('final'):")
        restore = search.index("self._search_offsets.update")
        self.assertLess(zero, fresh)
        self.assertGreater(restore, fresh)
        stale_branch = search[fresh:restore]
        self.assertNotIn('self._search_offsets.update', stale_branch)

    def test_mode_buttons_use_content_derived_minimum_widths(self):
        self.assertIn('button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)', MAIN)
        self.assertIn('button.setMinimumWidth(button.sizeHint().width() + 12)', MAIN)

    def test_calibre_import_count_preserves_confirmed_duplicate_and_anomaly_truth(self):
        section = MAIN[MAIN.index('def on_downloaded('):]
        import tempfile
        from calibre_plugins.manganana.books.imports.output_import import OutputReconciliation
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'controlled.cbz';path.write_bytes(b'controlled import accounting')
            statuses=('imported','skipped','conflicted','failed')
            requests=[{'output_identity':status,'title':status} for status in statuses]
            files=[dict(row,path=str(path),format='cbz') for row in requests]
            class Importer:
                def import_one(self,item,*_):return {'status':item['output_identity']}
            run=OutputReconciliation(requests,files,Importer(),lambda _:None,'skip')
            while not run.done:run.step()
            ledger=run.result()
            self.assertEqual([row['status'] for row in ledger['outputs']],list(statuses))
            self.assertEqual({status:ledger['counts'][status] for status in statuses},{status:1 for status in statuses})
        self.assertIn("counts=ledger['counts']", section)
        self.assertIn('conflicted', section)
        self.assertIn('failed', section)
        importer=(ROOT/'books/imports/output_import.py').read_text(encoding='utf8')
        self.assertIn('self.verify(bid, mi, item)',importer)
        self.assertIn("add_duplicates=bool(matches)",importer)

    def test_clicked_provider_local_record_is_authoritative(self):
        self.assertIn("prefs.defaults['ask_equivalent_sources'] = False", CONFIG)
        sources = MAIN[MAIN.index('class MangaSourcesDialog('):MAIN.index('class SearchResultRowWidget(')]
        self.assertIn('Ask when multiple equivalent sources are available', sources)
        click = MAIN[MAIN.index('def use_search_result('):MAIN.index('def _start_inventory_comparison(')]
        self.assertIn("info.get('resolution_state') in ('provider_local','cached_final')", click)
        self.assertIn('self._begin_search_result(info)',click)

    def test_chapter_output_controls_and_grouped_download_contracts_exist(self):
        from tests.rc_ui_behavior import assert_contract
        assert_contract(self,'chapter_output_mode_controls_are_explicit')

    def test_cover_is_cleared_before_new_result_and_author_reaches_import(self):
        begin=MAIN[MAIN.index('def _begin_search_result('):MAIN.index('def _load_debounced_search_result(')]
        self.assertLess(begin.index('self.selected_cover.clear()'),begin.index('self._pending_result_token += 1'))
        loaded=MAIN[MAIN.index('def _apply_loaded_manga('):MAIN.index('def _download_language_changed(')]
        self.assertIn("pending.get('external_authors')",loaded)
        imported=MAIN[MAIN.index('def _output_import_metadata('):MAIN.index('def _ask_output_duplicate(')]
        self.assertIn('self._applied_metadata_values()',imported)
        self.assertIn("item.get('author',author)",imported)
        self.assertIn("item.get('series',series)",imported)
        self.assertIn('mi.series_index = planned_series_index(item)',imported)

    def test_zero_result_snapshot_is_removed_after_provider_barrier(self):
        finished=MAIN[MAIN.index('def _finish_coordinated_search('):MAIN.index('def _find_search_item(')]
        self.assertIn('self._search_resolution_complete=True',finished)
        self.assertIn("delete('query_snapshot'",finished)
        self.assertIn('self._store_query_snapshot()',finished)

    def test_search_display_barrier_prevents_provisional_cards(self):
        ready=MAIN[MAIN.index('def _on_search_ready('):MAIN.index('def _apply_search_page(')]
        self.assertIn("settle(source_id,'success',data)",ready)
        self.assertNotIn('_apply_search_page',ready)
        enrichment=MAIN[MAIN.index('def _on_enrichment_ready('):MAIN.index('def _enrichment_finished(')]
        self.assertNotIn('_render_canonical_search_results',enrichment)
        finish=MAIN[MAIN.index('def _finish_coordinated_search('):MAIN.index('def _find_search_item(')]
        self.assertIn('ordered_successes()',finish)
        self.assertIn('_rebuild_enriched_results(render=False)',finish)

    def test_stale_cache_is_not_displayed_but_fresh_final_cache_is(self):
        search=MAIN[MAIN.index('def search_mangadex('):MAIN.index('def _on_search_ready(')]
        self.assertIn("if hit is not None and hit.fresh and snapshot.get('final'):",search)
        self.assertIn('self._render_provider_search_results()',search)
        self.assertNotIn('Showing cached results while sources refresh',search)


if __name__ == '__main__':
    unittest.main()
