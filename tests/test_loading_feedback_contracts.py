"""Static UI contracts for asynchronous search and cover-loading feedback."""

from pathlib import Path
import textwrap
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
        self.assertIn('self.progress_card.setVisible(search_visible or work_visible)', MAIN)
        self.assertIn('def _set_search_progress_visible(self, visible):', MAIN)
        self.assertIn('def _set_work_progress_visible(self, visible):', MAIN)
        selection_section = MAIN[MAIN.index('def use_search_result('):MAIN.index('def _start_inventory_comparison(')]
        self.assertNotIn('self.search_progress.', selection_section)
        self.assertNotIn('self.search_progress_text.', selection_section)

    def test_finalization_progress_remains_determinate_and_separate(self):
        self.assertIn('def setDeterminateValue(self, value):', MAIN)
        self.assertIn('self.progress.setDeterminateValue(percent)', MAIN)
        self.assertIn('self.progress.setDeterminateValue(100)', MAIN)
        self.assertIn('self.setRange(0, 100)', MAIN)

    def test_finalization_cancellation_is_cooperative_and_stale_safe(self):
        self.assertIn('cancelled_ok = pyqtSignal()', MAIN)
        self.assertIn('self._check_cancel()', MAIN)
        self.assertIn('self.preview_worker.requestInterruption()', MAIN)
        self.assertIn('Finalization preparation cancelled.', MAIN)
        self.assertIn('self._review_cancel_requested', MAIN)
        self.assertIn('def _on_preview_worker_finished', MAIN)

    def test_search_cancellation_is_separate_and_preserves_completed_results(self):
        self.assertIn('self.search_coordinator.cancel_remaining()', MAIN)
        self.assertIn('worker.requestInterruption()', MAIN)
        self.assertIn('providers settled; completed results preserved', MAIN)
        self.assertIn('request_id != self._search_request_id', MAIN)

    def test_provider_local_cards_render_without_inventory_admission_gate(self):
        render=MAIN[MAIN.index('def _render_provider_search_results('):MAIN.index('def _render_canonical_search_results(')]
        self.assertIn("primary['resolution_state']='provider_local'",render)
        self.assertIn('ranked_provider_results',MAIN)
        self.assertNotIn('resolution.usable',render)

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

    def test_mode_switch_preserves_query_but_never_replays_discovery(self):
        mode=MAIN[MAIN.index('def _set_workflow_mode('):MAIN.index('def _choose_layout(')]
        self.assertIn('self.workflow_state.change_mode(mode)',mode)
        self.assertNotIn('search_mangadex(',mode)
        self.assertNotIn('load_metadata(',mode)
        self.assertIn('load_context=take_manga_load_context(self._manga_load_contexts,request_id)', MAIN)

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
        self.assertIn('cover_loading=bool(cover_url)', MAIN)
        self.assertIn('def _chapter_inventory_cover_url(self, chapter):', MAIN)
        self.assertIn('worker.image_failed.connect(self._on_search_thumb_failed)', MAIN)
        self.assertIn('worker.image_failed.connect(self._on_volume_thumb_failed)', MAIN)

    def test_cover_requests_are_bounded_and_stale_callbacks_are_rejected(self):
        self.assertIn('COVER_BATCH_LIMIT = 8', MAIN)
        self.assertIn('worker.requestInterruption()', MAIN)
        self.assertIn('generation != self._cover_generation', MAIN)
        self.assertIn('self._cover_pulse_timer', MAIN)

    def test_browsing_workers_are_owned_until_qthread_finished(self):
        self.assertIn('self._async_workers = set()', MAIN)
        self.assertIn('def _retain_async_worker(self, worker):', MAIN)
        self.assertIn('worker.finished.connect(lambda w=worker:self._release_async_worker(w))', MAIN)
        self.assertIn('self._async_workers.discard(worker)', MAIN)
        self.assertIn('worker.deleteLater()', MAIN)
        self.assertIn('worker.finished.connect(lambda w=worker:self._on_search_thumb_finished(w))', MAIN)
        self.assertIn('worker.finished.connect(lambda w=worker:self._on_volume_thumb_finished(w))', MAIN)
        self.assertNotIn('worker.batch_done.connect(self._on_search_thumb_batch_done)', MAIN)
        self.assertNotIn('worker.batch_done.connect(self._on_volume_thumb_batch_done)', MAIN)

    def test_image_byte_storage_terminates_and_invalidates_only_derived_pixmaps(self):
        start=MAIN.index('def _store_image_bytes(self, url, raw):')
        end=MAIN.index('def _load_visible_search_thumbs(self):',start)
        namespace={}
        exec(textwrap.dedent(MAIN[start:end]),namespace)

        class CacheOwner:
            def __init__(self):
                self._image_cache={}
                self._failed_image_urls={'https://example.test/cover'}
                self._scaled_pixmap_cache={
                    ('https://example.test/cover',42,58):'stale',
                    ('https://example.test/other',42,58):'keep',
                }

        owner=CacheOwner()
        namespace['_store_image_bytes'](owner,'https://example.test/cover',b'image-bytes')
        self.assertEqual(b'image-bytes',owner._image_cache['https://example.test/cover'])
        self.assertNotIn('https://example.test/cover',owner._failed_image_urls)
        self.assertNotIn(('https://example.test/cover',42,58),owner._scaled_pixmap_cache)
        self.assertEqual('keep',owner._scaled_pixmap_cache[('https://example.test/other',42,58)])

        callback=MAIN[MAIN.index('def _on_volume_thumb_ready(self, data):'):MAIN.index('def _on_volume_thumb_failed(self, data):')]
        self.assertIn('self._store_image_bytes(url,raw)',callback)


if __name__ == '__main__':
    unittest.main()
