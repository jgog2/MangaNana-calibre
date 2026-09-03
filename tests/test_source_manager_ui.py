"""Static contracts for source-manager and disabled-direct behavior in Calibre UI."""

from pathlib import Path
import unittest

from tools.build_plugin import files_to_package


ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')


class SourceManagerUiTests(unittest.TestCase):
    def test_main_actions_replace_close_with_sources_in_requested_order(self):
        self.assertIn("self.sources_btn=QPushButton('Manga Sources')", MAIN)
        self.assertIn('actions.addWidget(self.preferences_btn); actions.addWidget(self.sources_btn); actions.addWidget(self.about_btn)', MAIN)
        self.assertNotIn("self.close_btn=QPushButton('Close')", MAIN)

    def test_dialog_is_registry_driven_and_reuses_provider_branding(self):
        section = MAIN[MAIN.index('class MangaSourcesDialog('):MAIN.index('class SearchResultRowWidget(')]
        self.assertIn('for source in registry.all():', section)
        self.assertIn('provider_badge_spec(source.source_id, source.display_name)', section)
        self.assertIn("_provider_icon_pixmap(spec.get('icon_path'))", section)
        self.assertIn('self.checkboxes[source.source_id] = checkbox', section)
        for forbidden in ("'mangadex'", "'mangapill'", "'weebcentral'"):
            self.assertNotIn(forbidden, section)

    def test_dialog_persists_stable_ids_and_build_packages_policy(self):
        self.assertIn("prefs.defaults['source_enabled'] = {}", CONFIG)
        packaged = {archive_path for _source, archive_path in files_to_package(ROOT)}
        self.assertIn('source_policy.py', packaged)
        self.assertIn('{source_id: checkbox.isChecked()', MAIN)

    def test_general_search_filters_before_workers_and_handles_zero_sources(self):
        section = MAIN[MAIN.index('def search_mangadex('):MAIN.index('def _on_search_ready(')]
        policy_index = section.index('participating = enabled_sources(SOURCE_REGISTRY, prefs)')
        worker_index = section.index('worker=self._retain_async_worker(SourceSearchWorker(')
        self.assertLess(policy_index, worker_index)
        self.assertIn('SourceCoordinator(SOURCE_REGISTRY, participating)', section)
        self.assertIn('No manga sources are enabled.', section)
        self.assertIn('Open Manga Sources to enable at least one source.', section)

    def test_disabled_direct_prompt_never_cancels_the_load(self):
        prompt = MAIN[MAIN.index('def _offer_enable_direct_source('):MAIN.index('def load_metadata(')]
        self.assertIn("box.addButton('Enable'", prompt)
        self.assertIn("box.addButton('Not now'", prompt)
        self.assertIn('save_source_enabled_states(prefs, {source.source_id: True}', prompt)
        self.assertNotIn('return False', prompt)
        load = MAIN[MAIN.index('def load_metadata('):MAIN.index('def _on_manga_worker_ready(')]
        self.assertLess(load.index('SOURCE_REGISTRY.identify(url)'), load.index('not is_source_enabled(prefs, source)'))
        self.assertIn('self._offer_enable_direct_source(source)', load)
        self.assertIn('worker=MangaLoadWorker(', load)

    def test_mode_change_does_not_replay_direct_or_query_discovery(self):
        mode = MAIN[MAIN.index('def _set_workflow_mode('):MAIN.index('def _choose_layout(')]
        self.assertNotIn('load_metadata(',mode)
        self.assertNotIn('search_mangadex(',mode)
        self.assertIn('participating = enabled_sources(SOURCE_REGISTRY, prefs)', MAIN)

    def test_manager_changes_filter_disabled_results_locally_without_networking(self):
        section = MAIN[MAIN.index('def open_manga_sources('):MAIN.index('def choose_alternate_title(')]
        self.assertIn('MangaSourcesDialog(SOURCE_REGISTRY, prefs, self)', section)
        self.assertIn('_render_provider_search_results()',section)
        self.assertIn('Sources changed. Search again',section)
        for forbidden in ('requestInterruption', 'cancel_remaining', 'search_mangadex('):
            self.assertNotIn(forbidden, section)


if __name__ == '__main__':
    unittest.main()
