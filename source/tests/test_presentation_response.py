"""Exact measurement reuse and bounded, owner-validated table population."""
import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from calibre_plugins.manganana.books.imaging import cover_rendering as covers
from calibre_plugins.manganana.books.output.final_output_view import FinalOutputViewMixin


class PresentationResponseTests(unittest.TestCase):
    def progress_worker(self, clock):
        path = Path(__file__).resolve().parents[1] / 'app/main.py'
        tree = ast.parse(path.read_text(encoding='utf8'))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_report_review_progress')
        scope = {'time': SimpleNamespace(monotonic=clock),
                 'review_manifest_progress': lambda source, done, total: (source, done, total)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), scope)
        worker = SimpleNamespace(_review_progress_state=None, progress=SimpleNamespace(emit=Mock()))
        return worker, scope['_report_review_progress']

    def test_cached_1169_chapters_do_not_flood_the_gui_queue(self):
        worker, publish = self.progress_worker(lambda: 0)
        for done in range(1, 1170):publish(worker, done, 1169, 'MangaDex')
        events = worker.progress.emit.call_args_list
        self.assertEqual(2, len(events))
        self.assertEqual((100, ('MangaDex', 1169, 1169)), events[-1].args)
        self.assertEqual([0, 100], [event.args[0] for event in events])

    def test_slow_requests_update_counts_within_unchanged_percentage(self):
        now = [0]
        worker, publish = self.progress_worker(lambda: now[0])
        publish(worker, 1, 10000, 'Provider')
        now[0] = .02;publish(worker, 2, 10000, 'Provider')
        now[0] = .06;publish(worker, 3, 10000, 'Provider')
        self.assertEqual(2, worker.progress.emit.call_count)
        self.assertEqual((0, ('Provider', 3, 10000)), worker.progress.emit.call_args.args)

    def test_fast_percent_changes_are_sampled_without_delaying_completion(self):
        now = [0]
        worker, publish = self.progress_worker(lambda: now[0])
        for done in range(1, 1170):
            now[0] = done * .001
            publish(worker, done, 1169, 'Provider')
        self.assertLessEqual(worker.progress.emit.call_count, 25)
        self.assertEqual((100, ('Provider', 1169, 1169)), worker.progress.emit.call_args.args)

    def test_progress_state_is_owned_by_the_worker(self):
        first, publish = self.progress_worker(lambda: 0)
        second, _ = self.progress_worker(lambda: 0)
        publish(first, 1, 20, 'Provider');publish(second, 1, 20, 'Other')
        first.progress.emit.assert_called_once();second.progress.emit.assert_called_once()

    def test_exact_text_measurements_are_reused_across_related_titles(self):
        covers._title_widths.clear()
        original = covers.ImageDraw.ImageDraw.textbbox
        calls = []
        def measured(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)
        with patch.object(covers.ImageDraw.ImageDraw, 'textbbox', measured):
            first = covers.title_layout('Detective Conan Chapter One')
            initial = len(calls)
            second = covers.title_layout('Detective Conan Chapter One')
            repeated = len(calls) - initial
        self.assertEqual(first[0], second[0])
        self.assertEqual(first[2:], second[2:])
        self.assertLess(repeated, initial)
        self.assertLessEqual(covers._title_widths.bytes_used, 1024 * 1024)
        self.assertLessEqual(len(covers._title_widths), 4096)

    def test_width_cache_evicts_without_changing_fit(self):
        covers._title_widths.clear()
        expected = covers.title_layout('A bounded cache with exact glyph measurements')
        for index in range(4200):
            covers._title_widths[('test', index)] = (index, 512)
        self.assertLessEqual(covers._title_widths.bytes_used, 1024 * 1024)
        actual = covers.title_layout('A bounded cache with exact glyph measurements')
        self.assertEqual(expected[0], actual[0])
        self.assertEqual(expected[2:], actual[2:])
        covers._title_widths.clear()

    def test_obsolete_population_never_appends_or_finishes(self):
        data = {'rows': [object()]}
        for closing, cancelled, stage, request, owner, signature in (
                (True, False, 'finalization', 1, data, 'a'),
                (False, True, 'finalization', 1, data, 'a'),
                (False, False, 'choose_manga', 1, data, 'a'),
                (False, False, 'finalization', 2, data, 'a'),
                (False, False, 'finalization', 1, {}, 'a'),
                (False, False, 'finalization', 1, data, 'b')):
            d = SimpleNamespace(_review_population=dict(data=data, request=1, signature='a'),
                _closing=closing, _review_cancel_requested=cancelled,
                workflow_state=SimpleNamespace(stage=stage), _preview_request_id=request,
                preview_data=owner, current_signature=lambda: signature,
                _invalidate_inflight_preview=Mock(), _append_review_table_row=Mock(),
                _finish_review_presentation=Mock())
            FinalOutputViewMixin._populate_review_rows(d)
            d._invalidate_inflight_preview.assert_called_once()
            d._append_review_table_row.assert_not_called()
            d._finish_review_presentation.assert_not_called()

    def test_population_yields_and_does_not_publish_a_partial_plan(self):
        data = {'rows': ['one', 'two', 'three']}
        state = dict(data=data, request=1, signature='a', index=0, flags=())
        d = SimpleNamespace(_review_population=state, _closing=False, _review_cancel_requested=False,
            workflow_state=SimpleNamespace(stage='finalization'), _preview_request_id=1,
            preview_data=data, current_signature=lambda:'a', preview_table=Mock(),
            _append_review_table_row=Mock(), _finish_review_presentation=Mock(),
            _review_population_timer=Mock(), progress_text=Mock(), _cancel_review_population=Mock())
        with patch('calibre_plugins.manganana.books.output.final_output_view.perf_counter', side_effect=[0, .006]):
            FinalOutputViewMixin._populate_review_rows(d)
        self.assertEqual(1, state['index'])
        d._finish_review_presentation.assert_not_called()
        d._review_population_timer.start.assert_called_once_with(1)
        with patch('calibre_plugins.manganana.books.output.final_output_view.perf_counter', return_value=0):
            FinalOutputViewMixin._populate_review_rows(d)
        self.assertEqual(3, state['index'])
        self.assertEqual([((0, 'one', ()), {}), ((1, 'two', ()), {}), ((2, 'three', ()), {})],
                         d._append_review_table_row.call_args_list)
        d._cancel_review_population.assert_called_once_with(discard=False)
        d._finish_review_presentation.assert_called_once_with(data)
