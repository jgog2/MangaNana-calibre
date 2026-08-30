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

    def test_mode_switch_researches_only_after_an_existing_search(self):
        self.assertIn("should_research=bool(previous_mode and replay_kind == 'search'", MAIN)
        self.assertIn("should_reload_direct=bool(previous_mode and replay_kind == 'direct'", MAIN)
        self.assertIn("self.search_mangadex(True, generation)", MAIN)

    def test_selecting_a_search_result_preserves_the_search_replay_query(self):
        self.assertIn("self._last_discovery_kind='search'; self._last_discovery_value=query", MAIN)
        apply_section = MAIN[MAIN.index('def _apply_loaded_manga('):MAIN.index('def _download_language_changed(')]
        self.assertIn("if discovery_kind == 'direct' and discovery_value:", apply_section)
        self.assertNotIn("if discovery_kind == 'search'", apply_section)

    def test_selected_card_owns_a_content_derived_minimum_height(self):
        self.assertIn("selected_top_l.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)", MAIN)
        self.assertNotIn("selected_top.setMinimumHeight(228)", MAIN)


if __name__ == '__main__':
    unittest.main()
