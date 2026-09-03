import unittest

from workflow_state import HighPriestessState, volume_selection_hint


def result(source, identity):
    return {'source_id':source,'id':identity,'title':identity}


class HighPriestessStateTests(unittest.TestCase):
    def test_volume_selection_hint_uses_actual_unified_inventory(self):
        self.assertEqual('Select at least one volume to continue.',
                         volume_selection_hint(True,False))
        self.assertEqual('Select Standalone Chapters to continue.',
                         volume_selection_hint(False,True))
        self.assertEqual('Select at least one volume or Standalone Chapters to continue.',
                         volume_selection_hint(True,True))

    def test_pending_query_does_not_replace_executed_query(self):
        state=HighPriestessState(mode='volume')
        state.set_pending_query('One Piece')
        state.execute_search(('mangadex',))
        state.set_pending_query('JoJolion')
        self.assertEqual('One Piece',state.executed_query)
        self.assertEqual('JoJolion',state.pending_query_text)

    def test_results_publish_only_after_provider_barrier(self):
        state=HighPriestessState(mode='chapter',pending_query_text='JoJolion')
        generation=state.execute_search(('mangadex','mangapill'))
        state.settle_provider(generation,'mangadex','success')
        self.assertFalse(state.publish_search_results(generation,(result('mangadex','a'),)))
        state.settle_provider(generation,'mangapill','failure')
        self.assertTrue(state.publish_search_results(generation,(result('mangadex','a'),)))

    def test_mode_change_preserves_query_text_and_clears_discovery_without_replay(self):
        state=HighPriestessState(mode='volume',pending_query_text='Steel Ball Run')
        generation=state.execute_search(('mangadex',))
        state.settle_provider(generation,'mangadex','success')
        state.publish_search_results(generation,(result('mangadex','sbr'),))
        state.select_provider(result('mangadex','sbr'))
        self.assertTrue(state.change_mode('chapter'))
        self.assertEqual('Steel Ball Run',state.pending_query_text)
        self.assertEqual('',state.executed_query)
        self.assertEqual((),state.visible_provider_results)
        self.assertIsNone(state.selected_provider_record)

    def test_late_inventory_cannot_overwrite_newer_selection(self):
        state=HighPriestessState(mode='chapter')
        first=state.select_provider(result('mangadex','a'))
        second=state.select_provider(result('mangapill','b'))
        self.assertFalse(state.apply_inventory(first,({'id':'old'},)))
        self.assertTrue(state.apply_inventory(second,({'id':'new'},)))
        self.assertEqual('new',state.loaded_inventory[0]['id'])

    def test_publication_manifest_is_generation_guarded_and_selection_scoped(self):
        state=HighPriestessState(mode='chapter')
        first=state.select_provider(result('mangapill','a'))
        manifest=object()
        self.assertTrue(state.apply_publication_manifest(first,manifest))
        self.assertIs(manifest,state.publication_manifest)
        state.select_provider(result('mangadex','b'))
        self.assertIsNone(state.publication_manifest)
        self.assertFalse(state.apply_publication_manifest(first,manifest))

    def test_chapter_projection_waits_for_both_terminal_inputs(self):
        state=HighPriestessState(mode='chapter')
        generation=state.select_provider(result('mangadex','a'))
        self.assertTrue(state.begin_chapter_preparation(generation,10))
        self.assertTrue(state.settle_chapter_acquisition(generation,10,'ready',({'chapter':'1'},)))
        self.assertFalse(state.chapter_projection_ready)
        self.assertTrue(state.settle_publication_structure(generation,'valid'))
        self.assertTrue(state.chapter_projection_ready)

    def test_unsupported_and_failure_are_terminal_honest_release_states(self):
        for structure in ('unsupported','terminal_failure'):
            state=HighPriestessState(mode='chapter')
            generation=state.select_provider(result('mangapill',structure))
            state.begin_chapter_preparation(generation,1)
            state.settle_chapter_acquisition(generation,1,'ready',({'chapter':'1'},))
            state.settle_publication_structure(generation,structure)
            self.assertTrue(state.chapter_projection_ready)
        failed=HighPriestessState(mode='chapter')
        generation=failed.select_provider(result('mangapill','inventory-failure'))
        failed.begin_chapter_preparation(generation,4)
        failed.settle_chapter_acquisition(generation,4,'terminal_failure',())
        failed.settle_publication_structure(generation,'unsupported')
        self.assertTrue(failed.chapter_projection_ready)

    def test_warm_structure_has_no_delay_and_images_are_not_barrier_state(self):
        state=HighPriestessState(mode='chapter')
        generation=state.select_provider(result('mangadex','warm'))
        state.settle_publication_structure(generation,'valid_stale')
        state.begin_chapter_preparation(generation,2)
        state.settle_chapter_acquisition(generation,2,'ready',({'chapter':'1','cover_url':'pending'},))
        self.assertTrue(state.chapter_projection_ready)

    def test_projection_freeze_rejects_late_structure_and_stale_generation(self):
        state=HighPriestessState(mode='chapter')
        first=state.select_provider(result('mangadex','a'))
        state.begin_chapter_preparation(first,3)
        state.settle_chapter_acquisition(first,3,'ready',({'chapter':'1'},))
        state.settle_publication_structure(first,'valid')
        projection=object()
        self.assertTrue(state.freeze_chapter_projection(first,3,projection,({'chapter':'1','volume':'1'},)))
        self.assertTrue(state.chapter_presentation_frozen)
        self.assertFalse(state.settle_publication_structure(first,'terminal_failure'))
        second=state.select_provider(result('mangapill','b'))
        self.assertFalse(state.settle_chapter_acquisition(first,3,'ready',({'chapter':'stale'},)))
        self.assertNotEqual(first,second)

    def test_disabling_source_hides_locally_and_clears_its_selection(self):
        state=HighPriestessState(mode='volume',enabled_sources=('mangadex','mangapill'))
        state.visible_provider_results=(result('mangadex','a'),result('mangapill','b'))
        state.select_provider(result('mangadex','a'))
        state.apply_source_configuration(('mangapill',))
        self.assertEqual(('mangapill',),tuple(row['source_id'] for row in state.visible_provider_results))
        self.assertIsNone(state.selected_provider_record)

    def test_finalization_invalidation_preserves_upstream_selection(self):
        state=HighPriestessState(mode='volume')
        state.select_provider(result('mangadex','a'))
        generation=state.selected_record_load_generation
        state.apply_inventory(generation,({'id':'v1'},))
        state.set_inventory_selection(('v1',))
        state.set_finalization_plan(({'title':'Volume 1'},))
        self.assertFalse(state.finalization_stale)
        state.set_inventory_selection(('v1','v2'))
        self.assertTrue(state.finalization_stale)
        self.assertEqual((),state.finalization_plan)
        self.assertEqual('a',state.selected_provider_record['id'])

    def test_upstream_edits_never_navigate_or_prepare_finalization(self):
        state=HighPriestessState(mode='volume')
        state.go_to('finalization')
        state.set_finalization_plan(({'title':'Old'},))
        self.assertEqual(1,state.finalization_generation)
        state.go_to('book_customization')
        state.invalidate_downstream()
        state.invalidate_downstream()
        self.assertEqual('book_customization',state.stage)
        self.assertTrue(state.finalization_stale)
        self.assertEqual(1,state.finalization_generation)

    def test_explicit_forward_preparation_uses_newest_state_once(self):
        state=HighPriestessState(mode='chapter')
        state.set_inventory_selection(('c1',))
        state.go_to('book_customization')
        state.set_inventory_selection(('c1','c2'))
        self.assertEqual(0,state.finalization_generation)
        state.go_to('finalization')
        state.set_finalization_plan(({'chapter_ids':('c1','c2')},))
        self.assertEqual(1,state.finalization_generation)
        self.assertEqual(('c1','c2'),state.finalization_plan[0]['chapter_ids'])

    def test_stage_names_match_high_priestess_navigation(self):
        state=HighPriestessState()
        for stage in ('choose_manga','book_customization','finalization'):
            state.go_to(stage)
            self.assertEqual(stage,state.stage)
        with self.assertRaises(ValueError):
            state.go_to('review')


if __name__ == '__main__':
    unittest.main()
