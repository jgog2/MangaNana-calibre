"""Static UI contracts for asynchronous search and cover-loading feedback."""

from pathlib import Path
import unittest


MAIN = (Path(__file__).resolve().parent.parent / 'main.py').read_text(encoding='utf-8')


class LoadingFeedbackContractTests(unittest.TestCase):
    def test_progress_bar_uses_standard_solid_qprogressbar_rendering(self):
        self.assertIn('class MangaNanaProgressBar(QProgressBar):', MAIN)
        self.assertIn('QProgressBar::chunk {{ background:{ORANGE};', MAIN)
        self.assertNotIn('StripedProgressBar', MAIN)
        self.assertNotIn('_stripe_offset', MAIN)
        self.assertNotIn('marquee', MAIN.casefold())
        self.assertNotIn('drawLine(x, fill.bottom()', MAIN)

    def test_provider_search_is_determinate_by_settled_provider_count(self):
        self.assertIn('self._search_provider_ids=tuple(', MAIN)
        self.assertIn('self.search_progress.setRange(0,max(1,len(participating_sources)))', MAIN)
        self.assertIn('settled,total=settled_provider_progress(', MAIN)
        self.assertIn('self.search_progress.setValue(settled if total else 0)', MAIN)
        search_section = MAIN[MAIN.index('def search_mangadex('):MAIN.index('def _visible_row_range(')]
        self.assertNotIn('setIndeterminate(True)', search_section)
        self.assertNotIn('self.progress.', search_section)
        self.assertNotIn('self.progress_text.', search_section)

    def test_search_and_work_progress_surfaces_have_separate_ownership(self):
        self.assertIn("self.search_progress_text=QLabel('Search ready')", MAIN)
        self.assertIn('self.search_progress=MangaNanaProgressBar()', MAIN)
        self.assertIn('self.work_progress_widget=QWidget()', MAIN)
        self.assertIn('self.work_progress_widget.setVisible(False)', MAIN)
        selection_section = MAIN[MAIN.index('def use_search_result('):MAIN.index('def _start_inventory_comparison(')]
        self.assertNotIn('self.search_progress.', selection_section)
        self.assertNotIn('self.search_progress_text.', selection_section)

    def test_review_progress_remains_determinate_and_separate(self):
        self.assertIn('def setDeterminateValue(self, value):', MAIN)
        self.assertIn('self.progress.setDeterminateValue(percent)', MAIN)
        self.assertIn('self.progress.setDeterminateValue(100)', MAIN)
        self.assertIn('self.setRange(0, 100)', MAIN)

    def test_review_cancellation_is_cooperative_and_stale_safe(self):
        self.assertIn('cancelled_ok = pyqtSignal()', MAIN)
        self.assertIn('self._check_cancel()', MAIN)
        self.assertIn('self.preview_worker.requestInterruption()', MAIN)
        self.assertIn('Review preparation cancelled.', MAIN)
        self.assertIn('self._review_cancel_requested', MAIN)
        self.assertIn('def _on_preview_worker_finished', MAIN)

    def test_search_cancellation_is_separate_and_preserves_completed_results(self):
        self.assertIn('self.search_coordinator.cancel_remaining()', MAIN)
        self.assertIn('worker.requestInterruption()', MAIN)
        self.assertIn('providers settled; completed results preserved', MAIN)
        self.assertIn('request_id != self._search_request_id', MAIN)

    def test_source_confidence_is_bounded_inline_and_removes_dead_ends(self):
        self.assertIn('SEARCH_RESOLUTION_LIMIT = 8', MAIN)
        self.assertIn("unresolved = QLabel('Checking sources…')", MAIN)
        self.assertIn('row.set_source_state(confirmed,note)', MAIN)
        self.assertIn('self.search_results.takeItem(index)', MAIN)
        self.assertIn("info['resolution_state']='resolved'", MAIN)

    def test_source_resolution_rejects_stale_search_mode_and_direct_load_work(self):
        self.assertIn("payload.get('request_id') != self._search_resolution_request_id", MAIN)
        self.assertIn('mode != self.workflow_mode or generation != self._mode_generation', MAIN)
        load_start = MAIN.index('def load_metadata(')
        direct_start = MAIN.index("if discovery_kind == 'direct':", load_start)
        direct_section = MAIN[direct_start:MAIN.index('self._manga_request_id += 1', direct_start)]
        self.assertIn('self._search_resolution_request_id += 1', direct_section)
        self.assertIn('self._search_resolution_worker.requestInterruption()', direct_section)

    def test_title_level_adult_metadata_is_enforced_before_inventory(self):
        self.assertIn("if md.get('adult') and not prefs['show_adult_search_results']:", MAIN)
        self.assertIn('Adult title blocked by the current search preference.', MAIN)

    def test_mode_switch_replays_the_last_direct_or_search_discovery(self):
        self.assertIn('self._last_discovery_kind', MAIN)
        self.assertIn('should_reload_direct=bool', MAIN)
        self.assertIn("value, discovery_kind='direct', prompt_disabled=False", MAIN)
        self.assertIn('discovery_kind, discovery_value=self._manga_discovery_kinds.pop', MAIN)

    def test_cover_spinner_has_explicit_loading_and_failure_transitions(self):
        self.assertIn('class CoverLoadingLabel(QLabel):', MAIN)
        self.assertIn('self._spinner_timer.timeout.connect(self._spin)', MAIN)
        self.assertIn('painter.drawEllipse', MAIN)
        self.assertIn("def set_loading(self, loading=True, style='spinner'):", MAIN)
        self.assertIn("def set_failed(self, text='No Cover'):", MAIN)
        self.assertIn("style='pulse'", MAIN)
        self.assertIn('image_failed = pyqtSignal(object)', MAIN)

    def test_all_async_cover_surfaces_handle_permanent_failures(self):
        self.assertIn("cover_loading=bool(primary.get('cover_url'))", MAIN)
        self.assertIn('cover_loading=bool(self._main_cover_url)', MAIN)
        self.assertIn('worker.image_failed.connect(self._on_search_thumb_failed)', MAIN)
        self.assertIn('worker.image_failed.connect(self._on_volume_thumb_failed)', MAIN)

    def test_cover_requests_are_bounded_and_stale_callbacks_are_rejected(self):
        self.assertIn('COVER_BATCH_LIMIT = 8', MAIN)
        self.assertIn('worker.requestInterruption()', MAIN)
        self.assertIn('generation != self._cover_generation', MAIN)
        self.assertIn('self._cover_pulse_timer', MAIN)


if __name__ == '__main__':
    unittest.main()
