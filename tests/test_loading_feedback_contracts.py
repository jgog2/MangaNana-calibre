"""Static UI contracts for asynchronous search and cover-loading feedback."""

from pathlib import Path
import unittest


MAIN = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")


class LoadingFeedbackContractTests(unittest.TestCase):
    def test_determinate_fill_geometry_is_accumulated_and_phase_independent(self):
        self.assertIn("def determinate_fill_width(track_width, completed, total):", MAIN)
        self.assertIn("fill_w = determinate_fill_width(track.width(), self._value - self._minimum, span)", MAIN)
        self.assertIn("QColor(ORANGE))", MAIN)
        self.assertIn("if self._indeterminate:\n                painter.setPen", MAIN)
        self.assertIn("if self._indeterminate:\n            if not self._timer.isActive():", MAIN)

    def test_provider_search_uses_indeterminate_activity_until_a_final_state(self):
        self.assertIn("def setIndeterminate(self, active):", MAIN)
        self.assertIn("self.progress.setIndeterminate(True)", MAIN)
        self.assertIn("provider_search_progress_text(snap,time.monotonic()-self._search_started_at)", MAIN)
        self.assertIn("self.progress.setIndeterminate(False)", MAIN)
        self.assertIn("self.progress.setValue(100)", MAIN)
        self.assertIn("track = outer.adjusted(1, 1, -1, -1)", MAIN)
        self.assertIn("left=track.left() - chunk", MAIN)
        self.assertIn("painter.setClipRect(track if self._indeterminate else fill)", MAIN)
        self.assertNotIn("intersected(inner)", MAIN)
        self.assertIn("def setDeterminateValue(self, value):", MAIN)
        self.assertIn("self.progress.setDeterminateValue(percent)", MAIN)
        self.assertIn("fill = QRect(track.left(), track.top(), min(fill_w, track.width()), track.height())", MAIN)

    def test_review_cancellation_is_cooperative_and_stale_safe(self):
        self.assertIn("cancelled_ok = pyqtSignal()", MAIN)
        self.assertIn("self._check_cancel()", MAIN)
        self.assertIn("self.preview_worker.requestInterruption()", MAIN)
        self.assertIn("Review preparation cancelled.", MAIN)
        self.assertIn("self._review_cancel_requested", MAIN)
        self.assertIn("def _on_preview_worker_finished", MAIN)

    def test_search_cancellation_is_separate_and_preserves_completed_results(self):
        self.assertIn("self.search_coordinator.cancel_remaining()",MAIN)
        self.assertIn("worker.requestInterruption()",MAIN)
        self.assertIn("completed results preserved",MAIN)
        self.assertIn("request_id != self._search_request_id",MAIN)

    def test_title_level_adult_metadata_is_enforced_before_inventory(self):
        self.assertIn("if md.get('adult') and not prefs['show_adult_search_results']:",MAIN)
        self.assertIn("Adult title blocked by the current search preference.",MAIN)

    def test_mode_switch_replays_the_last_direct_or_search_discovery(self):
        self.assertIn("self._last_discovery_kind", MAIN)
        self.assertIn("should_reload_direct=bool", MAIN)
        self.assertIn("self.load_metadata(value, discovery_kind='direct')", MAIN)
        self.assertIn("discovery_kind, discovery_value=self._manga_discovery_kinds.pop", MAIN)

    def test_cover_spinner_has_explicit_loading_and_failure_transitions(self):
        self.assertIn("class CoverLoadingLabel(QLabel):", MAIN)
        self.assertIn("self._spinner_timer.timeout.connect(self._spin)", MAIN)
        self.assertIn("painter.drawEllipse", MAIN)
        self.assertIn("def set_loading(self, loading=True, style='spinner'):", MAIN)
        self.assertIn("def set_failed(self, text='No Cover'):", MAIN)
        self.assertIn("style='pulse'", MAIN)
        self.assertIn("image_failed = pyqtSignal(object)", MAIN)

    def test_all_async_cover_surfaces_handle_permanent_failures(self):
        self.assertIn("cover_loading=bool(primary.get('cover_url'))", MAIN)
        self.assertIn("cover_loading=bool(self._main_cover_url)", MAIN)
        self.assertIn("worker.image_failed.connect(self._on_search_thumb_failed)", MAIN)
        self.assertIn("worker.image_failed.connect(self._on_volume_thumb_failed)", MAIN)

    def test_cover_requests_are_bounded_and_stale_callbacks_are_rejected(self):
        self.assertIn("COVER_BATCH_LIMIT = 8", MAIN)
        self.assertIn("worker.requestInterruption()", MAIN)
        self.assertIn("generation != self._cover_generation", MAIN)
        self.assertIn("self._cover_pulse_timer", MAIN)


if __name__ == "__main__":
    unittest.main()
