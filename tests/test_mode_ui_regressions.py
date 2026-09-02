"""Static contracts for UI regressions that require a running Calibre Qt host."""

from pathlib import Path
import unittest


MAIN = (Path(__file__).resolve().parent.parent / 'main.py').read_text(encoding='utf-8')


class ModeUiRegressionTests(unittest.TestCase):
    def test_mode_buttons_cannot_be_dialog_default_actions(self):
        self.assertIn("button.setAutoDefault(False); button.setDefault(False)", MAIN)

    def test_mode_painting_is_separate_from_user_click_connections(self):
        self.assertIn("self.volume_mode_btn.clicked.connect(lambda: self._set_workflow_mode('volume'))", MAIN)
        self.assertIn("self.chapter_mode_btn.clicked.connect(lambda: self._set_workflow_mode('chapter'))", MAIN)
        self.assertIn("self.volume_mode_btn.setChecked(mode == 'volume'); self.chapter_mode_btn.setChecked(mode == 'chapter')", MAIN)

    def test_mode_switch_clears_discovery_without_replaying_network_work(self):
        section=MAIN[MAIN.index('def _set_workflow_mode('):MAIN.index('def _choose_layout(')]
        self.assertIn('self.workflow_state.change_mode(mode)',section)
        self.assertIn('self._search_content_results=[]',section)
        self.assertNotIn('search_mangadex(',section)
        self.assertNotIn('load_metadata(',section)

    def test_selecting_a_search_result_does_not_replace_executed_query(self):
        self.assertIn("self._last_discovery_kind='search'; self._last_discovery_value=query", MAIN)
        self.assertIn('self.workflow_state.set_pending_query(query)',MAIN)
        apply_section = MAIN[MAIN.index('def _apply_loaded_manga('):MAIN.index('def _download_language_changed(')]
        self.assertIn("if discovery_kind == 'direct' and discovery_value:", apply_section)
        self.assertNotIn("if discovery_kind == 'search'", apply_section)

    def test_selected_card_owns_a_content_derived_stable_height(self):
        self.assertIn("selected_top_l.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)", MAIN)
        sync=MAIN[MAIN.index('def _sync_discovery_top_heights('):MAIN.index('def _add_glow(')]
        self.assertIn('panel.setFixedHeight(target)',sync)
        self.assertNotIn("selected_top.setMinimumHeight(228)", MAIN)


if __name__ == '__main__':
    unittest.main()
