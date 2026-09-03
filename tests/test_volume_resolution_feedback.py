from pathlib import Path
import unittest

from workflow_state import HighPriestessState


ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def selected_state():
    state = HighPriestessState(mode='volume')
    generation = state.select_provider({'source_id':'mangapill','id':'work'})
    return state, generation


class VolumeResolutionStateTests(unittest.TestCase):
    def test_chapter_only_inventory_is_resolving_until_publication_terminal(self):
        state, generation = selected_state()
        self.assertTrue(state.begin_publication_resolution(generation))
        self.assertTrue(state.begin_volume_preparation(generation, 7))
        self.assertEqual('loading_acquisition', state.volume_presentation_state)
        self.assertTrue(state.settle_volume_acquisition(generation, 7, 0, 1207))
        self.assertEqual('resolving_publication', state.volume_presentation_state)

    def test_derived_ready_and_final_standalone_are_distinct(self):
        state, generation = selected_state()
        state.begin_publication_resolution(generation)
        state.begin_volume_preparation(generation, 8)
        state.settle_volume_acquisition(generation, 8, 0, 1207)
        state.settle_publication_resolution(generation)
        self.assertEqual('building_groups', state.volume_presentation_state)
        state.finalize_volume_inventory(generation, 8, 0, 115, 12)
        self.assertEqual('ready', state.volume_presentation_state)

        state.begin_volume_preparation(generation, 9)
        state.settle_volume_acquisition(generation, 9, 0, 40)
        state.finalize_volume_inventory(generation, 9, 0, 0, 40)
        self.assertEqual('final_standalone', state.volume_presentation_state)

    def test_native_only_never_blocks_on_reference(self):
        state, generation = selected_state()
        state.begin_publication_resolution(generation)
        state.begin_volume_preparation(generation, 10)
        state.settle_volume_acquisition(generation, 10, 24, 0)
        self.assertEqual('ready', state.volume_presentation_state)

    def test_mixed_inventory_keeps_native_count_during_supplementation(self):
        state, generation = selected_state()
        state.begin_publication_resolution(generation)
        state.begin_volume_preparation(generation, 11)
        state.settle_volume_acquisition(generation, 11, 106, 33)
        self.assertEqual('resolving_publication', state.volume_presentation_state)
        self.assertEqual((106, 33), (state.volume_native_count, state.volume_standalone_count))
        state.settle_publication_resolution(generation)
        state.finalize_volume_inventory(generation, 11, 106, 2, 12)
        self.assertEqual((106, 2, 12), (state.volume_native_count,
                                       state.volume_derived_count,
                                       state.volume_standalone_count))

    def test_warm_terminal_publication_skips_cold_resolution_state(self):
        state, generation = selected_state()
        state.settle_publication_resolution(generation)
        state.begin_volume_preparation(generation, 12)
        state.settle_volume_acquisition(generation, 12, 0, 698)
        self.assertEqual('building_groups', state.volume_presentation_state)
        self.assertNotEqual('resolving_publication', state.volume_presentation_state)

    def test_stale_work_and_mode_generations_cannot_mutate_state(self):
        state, first = selected_state()
        state.begin_publication_resolution(first)
        state.begin_volume_preparation(first, 13)
        second = state.select_provider({'source_id':'mangapill','id':'new-work'})
        self.assertNotEqual(first, second)
        self.assertFalse(state.settle_publication_resolution(first))
        self.assertFalse(state.settle_volume_acquisition(first, 13, 0, 1207))
        self.assertEqual('idle', state.volume_presentation_state)

        state.begin_publication_resolution(second)
        state.begin_volume_preparation(second, 14)
        state.change_mode('chapter')
        self.assertFalse(state.finalize_volume_inventory(second, 14, 0, 115, 12))
        self.assertEqual('idle', state.volume_presentation_state)


class VolumeResolutionPresentationTests(unittest.TestCase):
    def test_in_pane_loader_and_nonblocking_mixed_copy_are_owned_by_volume_browser(self):
        full = MAIN[MAIN.index('def _show_volume_acquisition_loading('):
                    MAIN.index('def _finalize_pending_volume_fallback(')]
        self.assertIn("'Resolving volumes…'", full)
        self.assertIn("'Matching downloadable chapters to published volumes'", full)
        self.assertIn("'Finding additional volumes…'", full)
        self.assertIn('class VolumeResolutionRowWidget', MAIN)
        self.assertNotIn("'Standalone Chapters", full)

    def test_provisional_full_pane_disables_final_inventory_controls(self):
        pending = MAIN[MAIN.index('def _show_pending_volume_resolution('):
                       MAIN.index('def _finalize_pending_volume_fallback(')]
        self.assertIn('self.select_all_btn.setEnabled(False)', pending)
        self.assertIn('self.clear_volume_btn.setEnabled(False)', pending)
        self.assertIn('self.preview_btn.setEnabled(False)', pending)
        self.assertIn("self.selected_inventory_summary.setText('Resolving volumes…')", pending)

    def test_finalization_and_validation_are_gated_by_owned_resolution_state(self):
        self.assertGreaterEqual(MAIN.count('self._volume_resolution_pending()'), 4)
        self.assertIn('not self._volume_resolution_pending()', MAIN)
        self.assertIn('still matching downloadable chapters to published volumes', MAIN)

    def test_no_artificial_delay_or_new_resolution_request_exists(self):
        widget = MAIN[MAIN.index('class VolumeResolutionRowWidget('):
                      MAIN.index('class FocusClearingFrame(')]
        self.assertNotIn('sleep(', widget)
        self.assertNotIn('singleShot', widget)
        self.assertNotIn('ReferenceLookupWorker', widget)


if __name__ == '__main__':
    unittest.main()
