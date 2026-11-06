"""Counted offline qualification-cache recovery; no provider or image network."""
from pathlib import Path
import ast
from copy import deepcopy
from dataclasses import asdict, replace
import json
import subprocess
import sys
import time
import tempfile
import threading
import unittest
from unittest.mock import patch

from calibre_plugins.manganana.discovery.search_cache import INVENTORY_TTL, SearchMetadataCache
from calibre_plugins.manganana.discovery.search_resolution import inventory_cache_key, inventory_refresh_due, resolve_search_group, snapshot_inventory_refresh_due
from calibre_plugins.manganana.providers.source_adapter import SourceAdapter
from calibre_plugins.manganana.providers.source_registry import SourceRegistry
from tests.test_search_resolution import FakeSource, candidate, chapters


class RecoveringSource(FakeSource):
    def __init__(self):
        super().__init__('mangadex', ('en', 'ja'), {'en': chapters('dex', 1, 4, 1)})
        self.warning = 'partial feed'
        self.fail = False
        self.transport = []
        self.hook = None

    @SourceAdapter.capture_chapter_inventory
    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        self.transport.append((value, language))
        if self.hook:
            self.hook()
        if self.fail:
            raise RuntimeError('provider unavailable')
        return super().get_chapters(value, language, start_volume, end_volume)

    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        self.plan_calls += 1
        self.get_chapters(value, language)
        return dict(volumes=[1], feed_error=self.warning)

    def recover(self):
        self.warning = ''
        self.chapters['en'] = tuple(chapters('dex', 1, 20, 1))


class InventoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = [1_000_000.0]
        self.cache = SearchMetadataCache(Path(self.temp.name)/'cache.sqlite3', clock=lambda: self.now[0])
        self.source = RecoveringSource()
        self.row = dict(candidate('mangadex'), available_languages=['en', 'ja'], adult=False)
        self.registry = SourceRegistry((self.source,))

    def tearDown(self):
        self.cache.close()
        self.temp.cleanup()

    def resolve(self, cache=None, **kwargs):
        return resolve_search_group(self.registry, (self.row,), 'en', 'volume', {},
                                    self.cache if cache is None else cache, **kwargs)

    def test_partial_inventory_refreshes_after_one_minute(self):
        first = self.resolve()
        self.assertEqual((4, False, 'partial feed'),
                         (first.primary.chapter_count, first.primary.complete, first.primary.error))
        self.source.recover()
        self.now[0] += 61
        second = self.resolve()
        self.assertEqual(20, second.primary.chapter_count)
        self.assertTrue(second.primary.complete)
        self.assertEqual(2, len(self.source.transport))

    def test_memory_partial_inventory_also_recovers(self):
        cache = {}
        with patch('time.time', side_effect=lambda: self.now[0]):
            self.resolve(cache)
            self.source.recover()
            self.now[0] += 61
            self.assertEqual(20, self.resolve(cache).primary.chapter_count)

    def test_memory_failure_also_preserves_rows_and_enforces_cooldown(self):
        cache = {}
        with patch('time.time', side_effect=lambda: self.now[0]):
            self.resolve(cache)
            self.now[0] += 61
            self.source.fail = True
            self.assertEqual(4, self.resolve(cache).primary.chapter_count)
            self.source.fail = False
            self.source.recover()
            for _ in range(10):
                self.assertEqual(4, self.resolve(cache).primary.chapter_count)
            self.assertEqual(2, len(self.source.transport))
            self.now[0] += 300
            self.assertEqual(20, self.resolve(cache).primary.chapter_count)

    def key(self, row=None, language='en', source=None):
        return inventory_cache_key(source or self.source, row or self.row, language)

    def test_no_requests_before_partial_deadline_or_on_read_only_renders(self):
        self.resolve()
        for _ in range(20):
            self.assertFalse(inventory_refresh_due(self.cache, [self.key()]))
            self.assertEqual(4, self.resolve().primary.chapter_count)
        self.assertEqual(1, len(self.source.transport))
        self.now[0] += 60
        for _ in range(20):
            self.assertTrue(inventory_refresh_due(self.cache, [self.key()]))
        self.assertEqual(1, len(self.source.transport))

    def test_failed_refresh_retains_all_rows_and_cools_down_for_five_minutes(self):
        first = self.resolve().primary
        self.now[0] += 61
        self.source.fail = True
        failed = self.resolve().primary
        self.assertEqual(tuple(first.chapter_records), tuple(failed.chapter_records))
        self.assertEqual(first.error, failed.error)
        self.assertFalse(failed.complete)
        self.source.fail = False
        self.source.recover()
        for _ in range(20):
            self.assertEqual(4, self.resolve().primary.chapter_count)
        self.now[0] += 299
        self.assertEqual(4, self.resolve().primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))
        self.now[0] += 1
        self.assertEqual(20, self.resolve().primary.chapter_count)
        self.assertEqual(3, len(self.source.transport))

    def test_smaller_partial_refresh_does_not_erase_or_union_existing_chapters(self):
        first = self.resolve().primary
        self.source.chapters['en'] = tuple(chapters('changed-upload', 3, 5, 1))
        self.now[0] += 61
        refreshed = self.resolve().primary
        self.assertEqual(tuple(first.chapter_records), tuple(refreshed.chapter_records))
        self.assertEqual(4, refreshed.chapter_count)
        self.assertFalse(inventory_refresh_due(self.cache, [self.key()]))

    def test_larger_partial_snapshot_can_save_progress_without_becoming_complete(self):
        first = self.resolve().primary
        self.source.chapters['en'] = tuple(chapters('dex', 1, 20, 1))
        self.now[0] += 61
        refreshed = self.resolve().primary
        self.assertEqual(20, refreshed.chapter_count)
        self.assertFalse(refreshed.complete)
        self.assertEqual('partial feed', refreshed.error)
        self.assertEqual(tuple(first.chapter_records), tuple(refreshed.chapter_records[:4]))
        self.assertFalse(inventory_refresh_due(self.cache, [self.key()]))
        self.assertEqual(2, len(self.source.transport))

    def test_larger_conflicting_partial_snapshot_cannot_replace_cached_identities(self):
        first = self.resolve().primary
        self.source.chapters['en'] = tuple(chapters('different-id', 1, 20, 1))
        self.now[0] += 61
        refreshed = self.resolve().primary
        self.assertEqual(tuple(first.chapter_records), tuple(refreshed.chapter_records))
        self.assertEqual(4, refreshed.chapter_count)

    def test_partial_refresh_preserves_duplicate_multiplicity(self):
        self.source.chapters['en'] += (self.source.chapters['en'][0],)
        first = self.resolve().primary
        self.source.chapters['en'] = tuple(chapters('dex', 1, 20, 1))
        self.now[0] += 61
        refreshed = self.resolve().primary
        self.assertEqual(5, refreshed.chapter_count)
        self.assertEqual(tuple(first.chapter_records), tuple(refreshed.chapter_records))

    def test_complete_refresh_is_not_selected_by_larger_raw_count(self):
        self.resolve()
        self.source.warning = ''
        self.source.chapters['en'] = tuple(chapters('dex', 1, 3, 1))
        self.now[0] += 61
        refreshed = self.resolve().primary
        self.assertEqual(3, refreshed.chapter_count)
        self.assertTrue(refreshed.complete)

    def test_cold_waiter_can_cancel_without_cancelling_refresh_owner(self):
        self.source.recover()
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        def paused():
            entered.set()
            if not release.wait(5): raise RuntimeError('fixture timeout')
        def check():
            if cancelled.is_set(): raise InterruptedError('waiter cancelled')
        self.source.hook = paused
        owner, answers, owner_errors = self.start_resolve()
        self.assertTrue(entered.wait(5))
        waiter, waiter_answers, waiter_errors = self.start_resolve(check_cancel=check)
        try:
            cancelled.set()
            waiter.join(5)
            self.assertFalse(waiter.is_alive())
            self.assertFalse(waiter_answers)
            self.assertIsInstance(waiter_errors[0], InterruptedError)
        finally:
            release.set()
            owner.join(5)
        self.assertFalse(owner_errors)
        self.assertEqual(20, answers[0].primary.chapter_count)
        self.assertEqual(1, len(self.source.transport))

    def test_qt_worker_refresh_and_cancellation_use_existing_generation_guards(self):
        from qt.core import QCoreApplication, QEventLoop, QObject, QThread, QTimer, pyqtSignal, pyqtSlot
        app = QCoreApplication.instance() or QCoreApplication([])
        tree = ast.parse((Path(__file__).resolve().parents[1]/'app/main.py').read_text(encoding='utf-8'))
        worker = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SearchResolutionWorker')
        namespace = dict(__name__=__name__, QThread=QThread, pyqtSignal=pyqtSignal,
                         resolve_search_group=resolve_search_group)
        exec(compile(ast.Module(body=[worker], type_ignores=[]), 'app/main.py', 'exec'), namespace)
        callback = next(n for cls in tree.body if isinstance(cls, ast.ClassDef)
                        for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_on_search_resolution')
        exec(compile(ast.Module(body=[callback], type_ignores=[]), 'app/main.py', 'exec'), namespace)
        self.resolve()
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                self.now[0] += 61
                self.source.recover()
                entered, release = threading.Event(), threading.Event()
                transport_threads = []
                def paused():
                    transport_threads.append(threading.get_ident())
                    entered.set()
                    if not release.wait(5): raise RuntimeError('fixture timeout')
                self.source.hook = paused
                # Ensure both branches start with the same partial state.
                if cancel:
                    self.source.warning = 'partial feed'
                    self.source.chapters['en'] = tuple(chapters('dex', 1, 4, 1))
                    from dataclasses import replace
                    from calibre_plugins.manganana.discovery.search_resolution import _inventory_cache_put
                    previous = self.resolve().primary
                    _inventory_cache_put(self.cache, self.key(), replace(previous,
                        chapter_records=tuple(chapters('dex', 1, 4, 1)), chapter_count=4,
                        complete=False, error='partial feed'), created_at=self.now[0]-61)
                    self.source.recover()
                item = namespace['SearchResolutionWorker'](7, self.registry, [('group', (self.row,))],
                                                          'en', 'volume', {}, self.cache)
                class Receiver(QObject):
                    def __init__(self): super().__init__(); self.payloads=[]
                    @pyqtSlot(object)
                    def receive(self, value): self.payloads.append(value)
                receiver = Receiver()
                loop = QEventLoop()
                item.resolved.connect(receiver.receive)
                item.finished.connect(loop.quit)
                timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(5000)
                item.start()
                started = entered.wait(5)
                if cancel: item.requestInterruption()
                release.set()
                loop.exec(); timer.stop()
                self.assertTrue(item.wait(5000)); app.processEvents()
                self.assertTrue(started)
                self.assertTrue(all(t != threading.get_ident() for t in transport_threads))
                if cancel:
                    self.assertFalse(receiver.payloads)
                    self.assertEqual(4, self.cache.get_inventory(self.key()).value['chapter_count'])
                else:
                    self.assertEqual(20, receiver.payloads[0]['resolution'].primary.chapter_count)
                    context = type('Context', (), dict(_closing=False, _search_resolution_request_id=8,
                        workflow_mode='volume', _mode_generation=2, _search_resolutions={}))()
                    namespace['_on_search_resolution'](context, receiver.payloads[0], 'volume', 2)
                    context._search_resolution_request_id = 7
                    namespace['_on_search_resolution'](context, receiver.payloads[0], 'volume', 1)
                    self.assertFalse(context._search_resolutions)
                self.source.hook = None

    def test_complete_inventory_reuses_existing_three_hour_ttl(self):
        self.source.recover()
        first = self.resolve().primary
        for offset in (60, 300, INVENTORY_TTL):
            self.now[0] = 1_000_000 + offset
            self.assertEqual(tuple(first.chapter_records), tuple(self.resolve().primary.chapter_records))
        self.assertEqual(1, len(self.source.transport))
        self.now[0] += 1
        self.assertEqual(20, self.resolve().primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))

    def test_explicit_refresh_bypasses_both_partial_and_healthy_freshness(self):
        self.resolve()
        self.source.recover()
        self.assertEqual(20, self.resolve(refresh_inventory=True).primary.chapter_count)
        self.resolve(refresh_inventory=True)
        self.assertEqual(3, len(self.source.transport))

    def test_failed_explicit_refresh_of_healthy_result_keeps_rows_but_marks_partial(self):
        self.source.recover()
        first = self.resolve().primary
        self.source.fail = True
        failed = self.resolve(refresh_inventory=True).primary
        self.assertEqual(tuple(first.chapter_records), tuple(failed.chapter_records))
        self.assertFalse(failed.complete)
        self.assertIn('unavailable', failed.error)
        self.resolve()
        self.assertEqual(2, len(self.source.transport))

    def test_expired_partial_stays_usable_after_failed_refresh(self):
        first = self.resolve().primary
        self.now[0] += INVENTORY_TTL + 1
        self.assertIsNone(self.cache.get_inventory(self.key()))
        self.source.fail = True
        self.assertEqual(tuple(first.chapter_records), tuple(self.resolve().primary.chapter_records))
        self.assertEqual(4, self.resolve().primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))

    def test_cooldown_survives_restart_without_refreshing_acquisition_timestamp(self):
        self.resolve()
        self.now[0] += 61
        self.source.fail = True
        self.resolve()
        self.assertEqual(61, self.cache.get_inventory(self.key()).age_seconds)
        self.cache.close()
        self.cache = SearchMetadataCache(Path(self.temp.name)/'cache.sqlite3', clock=lambda: self.now[0])
        self.source.fail = False
        self.source.recover()
        self.assertEqual(4, self.resolve().primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))
        self.now[0] += 300
        self.assertEqual(20, self.resolve().primary.chapter_count)

    def test_legacy_flat_inventory_payload_is_eligible_for_recovery(self):
        from dataclasses import asdict
        first = self.resolve().primary
        self.cache.put('inventory', self.cache._inventory_storage_key(self.key()), asdict(first))
        self.now[0] += 61
        self.source.recover()
        self.assertEqual(20, self.resolve().primary.chapter_count)

    def start_resolve(self, **kwargs):
        answers, errors = [], []
        def run():
            try:
                answers.append(self.resolve(**kwargs))
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=run)
        thread.start()
        return thread, answers, errors

    def test_concurrent_refresh_consumers_keep_partial_rows_without_duplicate_requests(self):
        first = self.resolve().primary
        self.source.recover()
        self.now[0] += 61
        entered, release = threading.Event(), threading.Event()
        def paused():
            entered.set()
            if not release.wait(5): raise RuntimeError('fixture timeout')
        self.source.hook = paused
        thread, answers, errors = self.start_resolve()
        try:
            self.assertTrue(entered.wait(5))
            # Simulates reads on the caller/UI thread while transport is blocked.
            self.assertEqual(4, self.cache.get_inventory(self.key()).value['chapter_count'])
            # A different inventory key can acquire while this provider is paused.
            other = FakeSource('mangapill', ('en',), {'en': chapters('pill', 1, 8)})
            result = resolve_search_group(SourceRegistry((other,)), (candidate('mangapill'),),
                                          'en', 'volume', {}, self.cache)
            self.assertEqual(8, result.primary.chapter_count)
            self.assertEqual(1, other.chapter_calls)
            for _ in range(10):
                self.assertEqual(tuple(first.chapter_records), tuple(self.resolve().primary.chapter_records))
                self.assertFalse(inventory_refresh_due(self.cache, [self.key()]))
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
        self.assertEqual(20, answers[0].primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))

    def test_concurrent_cold_consumers_share_one_transport(self):
        self.source.recover()
        entered, release = threading.Event(), threading.Event()
        def paused():
            entered.set()
            if not release.wait(5): raise RuntimeError('fixture timeout')
        self.source.hook = paused
        first, a, errors_a = self.start_resolve()
        self.assertTrue(entered.wait(5))
        second, b, errors_b = self.start_resolve()
        release.set()
        first.join(5); second.join(5)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertFalse(errors_a + errors_b)
        self.assertEqual([20, 20], [a[0].primary.chapter_count, b[0].primary.chapter_count])
        self.assertEqual(1, len(self.source.transport))

    def test_cancelled_refresh_cannot_publish_or_cache_recovered_rows(self):
        self.resolve()
        self.now[0] += 61
        self.source.recover()
        cancelled = [False]
        def check():
            if cancelled[0]: raise InterruptedError('cancelled')
        self.source.hook = lambda: cancelled.__setitem__(0, True)
        with self.assertRaises(InterruptedError):
            self.resolve(check_cancel=check)
        self.assertEqual(4, self.cache.get_inventory(self.key()).value['chapter_count'])
        self.source.hook = None
        self.assertEqual(20, self.resolve().primary.chapter_count)

    def test_cancelled_before_inspection_makes_no_request(self):
        with self.assertRaises(InterruptedError):
            self.resolve(check_cancel=lambda: (_ for _ in ()).throw(InterruptedError('cancelled')))
        self.assertEqual([], self.source.transport)

    def test_language_edition_provider_title_and_contract_keys_are_isolated(self):
        self.resolve()
        self.source.recover()
        variants = [dict(self.row, badge='COLOR'),
                    dict(self.row, url='https://mangadex.test/series/different')]
        for row in variants:
            result = resolve_search_group(self.registry, (row,), 'en', 'volume', {}, self.cache)
            self.assertEqual(20, result.primary.chapter_count)
        self.source.chapters['ja'] = tuple(chapters('dex-ja', 1, 7, 1))
        result = resolve_search_group(self.registry, (self.row,), 'ja', 'volume', {}, self.cache)
        self.assertEqual(7, result.primary.chapter_count)
        self.source.inventory_contract = 'different-contract'
        self.assertEqual(20, self.resolve().primary.chapter_count)
        pill = FakeSource('mangapill', ('en',), {'en': chapters('pill', 1, 8)})
        other = resolve_search_group(SourceRegistry((pill,)), (candidate('mangapill'),), 'en', 'volume', {}, self.cache)
        self.assertEqual(8, other.primary.chapter_count)
        del self.source.inventory_contract
        self.assertEqual(4, self.resolve().primary.chapter_count)
        self.assertEqual(5, len(self.source.transport))

    def test_existing_native_volume_preference_is_unchanged(self):
        self.source.warning = ''
        pill = FakeSource('mangapill', ('en',), {'en': chapters('pill', 1, 20)})
        result = resolve_search_group(SourceRegistry((self.source, pill)),
            (self.row, candidate('mangapill')), 'en', 'volume', {}, self.cache)
        self.assertEqual('mangadex', result.primary.source_id)
        self.assertEqual(4, result.primary.chapter_count)

    def test_exhausted_budget_uses_saved_partial_and_does_not_consume_retry(self):
        self.resolve()
        self.now[0] += 61
        result = self.resolve(inspection_budget=[0])
        self.assertEqual(4, result.primary.chapter_count)
        self.assertTrue(inventory_refresh_due(self.cache, [self.key()]))
        self.assertEqual(1, len(self.source.transport))
        self.source.recover()
        budget = [1]
        self.assertEqual(20, self.resolve(inspection_budget=budget).primary.chapter_count)
        self.assertEqual([0], budget)

    def test_query_snapshot_gate_handles_exact_and_legacy_keys_without_network(self):
        self.resolve()
        snapshot = dict(inventory_keys=[list(self.key())], final_cards=[dict(provider_record=self.row)])
        legacy = dict(final_cards=snapshot['final_cards'])
        for value in (snapshot, legacy):
            self.assertFalse(snapshot_inventory_refresh_due(self.cache, self.registry, value, 'en'))
        self.now[0] += 61
        for value in (snapshot, legacy):
            self.assertTrue(snapshot_inventory_refresh_due(self.cache, self.registry, value, 'en'))
        self.assertFalse(snapshot_inventory_refresh_due(self.cache, self.registry,
            dict(inventory_keys=[list(self.key(dict(self.row, badge='COLOR')))]), 'en'))
        self.assertEqual(1, len(self.source.transport))

    def test_real_mangadex_transport_recovery_preserves_single_inventory_acquisition(self):
        from tests.test_single_inventory import source_fixture
        def warning(url, base):
            if '/aggregate?' in url: raise RuntimeError('aggregate unavailable')
        source, url, calls, base = source_fixture('MangaDex', warning)
        template = deepcopy(base.feed_pages[0]['data'][0])
        def feed(count):
            rows = []
            for number in range(1, count+1):
                row = deepcopy(template)
                row['id'] = 'opaque-' + str(number)
                row['attributes'].update(chapter=str(number), volume='1', pages=20)
                rows.append(row)
            base.feed_pages = {0:dict(data=rows)}
        feed(4)
        row = dict(self.row, url=url)
        registry = SourceRegistry((source,))
        first = resolve_search_group(registry, (row,), 'en', 'volume', {}, self.cache)
        self.assertEqual((4, False), (first.primary.chapter_count, first.primary.complete))
        self.assertEqual(2, len(calls))
        feed(20)
        # Disable the injected failure without replacing real provider parsing.
        base_transport = source._api_json
        def recovered(path, **kwargs):
            if '/aggregate?' in path:
                calls.append(path)
                return base(path, **kwargs)
            return base_transport(path, **kwargs)
        source._api_json = recovered
        self.now[0] += 61
        second = resolve_search_group(registry, (row,), 'en', 'volume', {}, self.cache)
        self.assertEqual((20, True), (second.primary.chapter_count, second.primary.complete))
        self.assertEqual(4, len(calls))


class InventorySnapshotSafetyTests(unittest.TestCase):
    setUp = InventoryRecoveryTests.setUp
    tearDown = InventoryRecoveryTests.tearDown
    resolve = InventoryRecoveryTests.resolve
    key = InventoryRecoveryTests.key
    start_resolve = InventoryRecoveryTests.start_resolve

    def newer_inventory(self, previous, count=20):
        return replace(previous, chapter_records=tuple(chapters('dex', 1, count, 1)),
                       chapter_count=count, complete=True, error='')

    def test_old_partial_cannot_overwrite_new_complete_from_another_handle(self):
        previous = self.resolve().primary
        self.now[0] += 61
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        try:
            self.source.hook = lambda: other.put_inventory(
                self.key(), asdict(self.newer_inventory(previous)), created_at=self.now[0]+1)
            result = self.resolve().primary
            self.assertEqual((20, True, ''), (result.chapter_count, result.complete, result.error))
            persisted = self.cache.get_inventory(self.key()).value
            self.assertEqual((20, True), (persisted['chapter_count'], persisted['complete']))
            self.assertNotIn('_inventory_retry_after', persisted)
        finally:
            other.close()

    def test_failed_old_refresh_does_not_mark_newer_complete_partial(self):
        previous = self.resolve().primary
        self.now[0] += 61
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        try:
            self.source.fail = True
            self.source.hook = lambda: other.put_inventory(self.key(), asdict(self.newer_inventory(previous)))
            self.assertTrue(self.resolve().primary.complete)
            self.assertEqual(20, self.cache.get_inventory(self.key()).value['chapter_count'])
            self.assertFalse(inventory_refresh_due(other, [self.key()]))
        finally:
            other.close()

    def test_cancelled_old_refresh_preserves_other_handles_complete_result(self):
        previous = self.resolve().primary
        self.now[0] += 61
        cancelled = [False]
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        def publish_and_cancel():
            other.put_inventory(self.key(), asdict(self.newer_inventory(previous)))
            cancelled[0] = True
        def check():
            if cancelled[0]: raise InterruptedError('cancelled')
        try:
            self.source.hook = publish_and_cancel
            with self.assertRaises(InterruptedError): self.resolve(check_cancel=check)
            self.assertEqual(20, self.cache.get_inventory(self.key()).value['chapter_count'])
            self.assertTrue(self.cache.get_inventory(self.key()).value['complete'])
            self.source.hook = None
            self.assertEqual(20, self.resolve().primary.chapter_count)
        finally:
            other.close()

    def test_older_complete_result_also_cannot_replace_a_changed_snapshot(self):
        previous = self.resolve().primary
        self.now[0] += 61
        self.source.recover()  # This older acquisition would return 20 complete rows.
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        try:
            self.source.hook = lambda: other.put_inventory(self.key(), asdict(self.newer_inventory(previous, 21)))
            self.assertEqual(21, self.resolve().primary.chapter_count)
            self.assertEqual(21, other.get_inventory(self.key()).value['chapter_count'])
        finally:
            other.close()

    def test_shared_database_handles_coalesce_without_blocking_other_databases_or_keys(self):
        self.resolve()
        self.now[0] += 61
        self.source.recover()
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        separate = SearchMetadataCache(Path(self.temp.name)/'other.sqlite3', clock=lambda: self.now[0])
        entered, release = threading.Event(), threading.Event()
        def pause():
            entered.set()
            if not release.wait(5): raise RuntimeError('fixture timeout')
        self.source.hook = pause
        owner, answers, errors = self.start_resolve()
        try:
            self.assertTrue(entered.wait(5))
            source = RecoveringSource(); source.recover()
            result = resolve_search_group(SourceRegistry((source,)), (self.row,), 'en', 'volume', {}, other)
            self.assertEqual(4, result.primary.chapter_count)
            self.assertEqual([], source.transport)
            self.assertFalse(inventory_refresh_due(other, [list(self.key())]))
            fresh = resolve_search_group(SourceRegistry((source,)), (self.row,), 'en', 'volume', {}, separate)
            self.assertEqual(20, fresh.primary.chapter_count)
            self.assertEqual(1, len(source.transport))
            different = dict(self.row, url='https://mangadex.test/series/different')
            fresh = resolve_search_group(SourceRegistry((source,)), (different,), 'en', 'volume', {}, other)
            self.assertEqual(20, fresh.primary.chapter_count)
            self.assertEqual(2, len(source.transport))
        finally:
            release.set(); owner.join(5)
            other.close(); separate.close()
        self.assertFalse(owner.is_alive())
        self.assertFalse(errors)
        self.assertEqual(20, answers[0].primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))

    def test_claim_identity_normalizes_path_and_key_but_isolates_memory_databases(self):
        alias_directory = Path(self.temp.name)/'alias'; alias_directory.mkdir()
        alias = SearchMetadataCache(alias_directory/'..'/self.cache.path.name)
        self.assertEqual(self.cache.inventory_claim_key(self.key()), alias.inventory_claim_key(list(self.key())))
        one, two = SearchMetadataCache(':memory:'), SearchMetadataCache(':memory:')
        self.assertNotEqual(one.inventory_claim_key(self.key()), two.inventory_claim_key(self.key()))

    def test_concurrent_first_writes_have_exactly_one_winner(self):
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        try:
            self.assertIsNone(self.cache.get_inventory_snapshot(self.key()))
            self.assertIsNone(other.get_inventory_snapshot(self.key()))
            barrier = threading.Barrier(2)
            outcomes, errors = [], []
            def write(cache, count):
                try:
                    barrier.wait(5)
                    saved = cache.compare_and_set_inventory(self.key(), dict(chapter_count=count), None)
                    outcomes.append((count, saved))
                except BaseException as exc:
                    errors.append(exc)
            workers = [threading.Thread(target=write, args=(cache, count))
                       for cache, count in ((self.cache, 4), (other, 20))]
            for worker in workers: worker.start()
            for worker in workers: worker.join(5)
            self.assertFalse(any(worker.is_alive() for worker in workers))
            self.assertFalse(errors)
            self.assertEqual([False, True], sorted(saved for _, saved in outcomes))
            winner = next(count for count, saved in outcomes if saved)
            self.assertEqual(winner, self.cache.get_inventory(self.key()).value['chapter_count'])
        finally:
            other.close()

    def test_payload_change_at_identical_timestamp_rejects_old_token(self):
        previous = self.resolve().primary
        token = self.cache.get_inventory_snapshot(self.key())
        self.cache.put_inventory(self.key(), asdict(self.newer_inventory(previous)), created_at=token[1])
        self.assertFalse(self.cache.compare_and_set_inventory(self.key(), asdict(previous), token))
        self.assertEqual(20, self.cache.get_inventory(self.key()).value['chapter_count'])

    def test_access_timestamp_changes_do_not_reject_valid_write(self):
        previous = self.resolve().primary
        token = self.cache.get_inventory_snapshot(self.key())
        self.now[0] += 1
        self.cache.get_inventory(self.key())
        self.assertTrue(self.cache.compare_and_set_inventory(self.key(), asdict(self.newer_inventory(previous)), token))
        self.assertEqual(20, self.resolve().primary.chapter_count)

    def test_identical_rewrite_at_same_timestamp_has_a_distinct_snapshot_revision(self):
        self.source.recover()
        previous = self.resolve().primary
        token = self.cache.get_inventory_snapshot(self.key())
        self.cache.put_inventory(self.key(), asdict(previous), created_at=token[1])
        newer = self.cache.get_inventory_snapshot(self.key())
        self.assertNotEqual(token, newer)
        self.assertEqual(token[1], newer[1])
        self.assertFalse(self.cache.compare_and_set_inventory(self.key(),
            asdict(replace(previous, complete=False, error='old failure')), token))
        self.assertEqual(newer, self.cache.get_inventory_snapshot(self.key()))
        self.assertTrue(self.cache.get_inventory(self.key()).value['complete'])
        self.assertNotIn('_inventory_snapshot_id', self.cache.get_inventory(self.key()).value)

    def test_deleted_entry_cannot_be_resurrected_by_an_old_refresh(self):
        previous = self.resolve().primary
        self.now[0] += 61
        self.source.hook = lambda: self.cache.delete('inventory', self.cache._inventory_storage_key(self.key()))
        with self.assertRaisesRegex(RuntimeError, 'refresh not published'):
            self.resolve()
        self.assertIsNone(self.cache.get_inventory_snapshot(self.key()))
        self.source.hook = None
        self.source.recover()
        self.assertEqual(20, self.resolve().primary.chapter_count)

    def test_malformed_snapshot_can_be_repaired_without_schema_changes(self):
        self.cache.put_inventory(self.key(), dict(bad_contract=True))
        self.source.recover()
        self.assertEqual(20, self.resolve().primary.chapter_count)
        db = self.cache._connect()
        self.assertEqual('4', db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone()[0])
        self.assertEqual(['cache_key', 'payload', 'created_at', 'accessed_at'],
                         [row[1] for row in db.execute('PRAGMA table_info(inventory)')])

    def test_sql_failure_rolls_back_and_releases_writer(self):
        previous = self.resolve().primary
        token = self.cache.get_inventory_snapshot(self.key())
        db = self.cache._connect()
        db.execute("CREATE TEMP TRIGGER reject_inventory BEFORE UPDATE OF payload ON inventory "
                   "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        db.commit()
        with self.assertRaisesRegex(Exception, 'injected failure'):
            self.cache.compare_and_set_inventory(self.key(), asdict(self.newer_inventory(previous)), token)
        self.assertFalse(db.in_transaction)
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        try:
            self.assertTrue(other.compare_and_set_inventory(self.key(), asdict(self.newer_inventory(previous)), token))
            self.assertEqual(20, self.cache.get_inventory(self.key()).value['chapter_count'])
        finally:
            other.close()

    def test_separate_process_preserves_newer_complete_for_warm_and_missing_keys(self):
        root = Path(__file__).resolve().parents[1]
        for warm in (True, False):
            with self.subTest(warm=warm):
                self.cache.clear()
                self.source.hook = None
                if warm: self.resolve()
                self.now[0] += 61
                entered, release = threading.Event(), threading.Event()
                def pause():
                    entered.set()
                    if not release.wait(30): raise RuntimeError('fixture timeout')
                self.source.hook = pause
                owner, answers, errors = self.start_resolve()
                try:
                    self.assertTrue(entered.wait(5))
                    script = Path(self.temp.name)/'independent_writer.py'
                    script.write_text(
                        'import sys, socket, json\n'
                        f'sys.path.insert(0, {str(root)!r})\n'
                        'from tools.source_bootstrap import ensure_source_package\n'
                        'ensure_source_package()\n'
                        'def blocked(*args, **kwargs): raise AssertionError("No network permitted")\n'
                        'socket.create_connection = blocked\nsocket.socket.connect = blocked\n'
                        'from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache\n'
                        'from calibre_plugins.manganana.discovery.search_resolution import resolve_search_group\n'
                        'from calibre_plugins.manganana.providers.source_registry import SourceRegistry\n'
                        'from tests.test_inventory_recovery import RecoveringSource\n'
                        f'cache = SearchMetadataCache({str(self.cache.path)!r}, clock=lambda: {self.now[0]+1!r})\n'
                        'source = RecoveringSource(); source.recover()\n'
                        f'row = {self.row!r}\n'
                        'try:\n'
                        '    result = resolve_search_group(SourceRegistry((source,)), (row,), "en", "volume", {}, cache)\n'
                        '    print(json.dumps(dict(chapters=result.primary.chapter_count, complete=result.primary.complete)))\n'
                        'finally: cache.close()\n', encoding='utf-8')
                    child = subprocess.run([sys.executable, '-e', str(root/'tools/run_qt_checks.py'), '--', str(script)],
                                           cwd=root, capture_output=True, text=True, timeout=20)
                    self.assertEqual(0, child.returncode, child.stdout + child.stderr)
                    self.assertEqual(dict(chapters=20, complete=True), json.loads(child.stdout.strip()))
                    self.assertEqual(20, self.cache.get_inventory(self.key()).value['chapter_count'])
                finally:
                    release.set(); owner.join(5)
                self.assertFalse(owner.is_alive())
                self.assertFalse(errors)
                self.assertEqual((20, True), (answers[0].primary.chapter_count, answers[0].primary.complete))
                self.assertEqual(20, self.cache.get_inventory(self.key()).value['chapter_count'])
                self.assertTrue(self.cache.get_inventory(self.key()).value['complete'])

    def competing_process_refresh(self, first_count, second_count, first_warning='',
                                  second_warning='', second_fail=False, first_finishes_first=False):
        """Release real independent-process acquisitions in a prescribed order."""
        root = Path(__file__).resolve().parents[1]
        self.resolve()  # Four usable partial rows at the shared acquisition start.
        self.now[0] += 61
        self.source.chapters['en'] = tuple(chapters('dex', 1, first_count, 1))
        self.source.warning = first_warning
        entered, release = threading.Event(), threading.Event()
        events = []
        def pause():
            events.append('A-start'); entered.set()
            if not release.wait(30): raise RuntimeError('fixture timeout')
        self.source.hook = pause
        owner, answers, errors = self.start_resolve()
        child = None
        try:
            self.assertTrue(entered.wait(5))
            started = Path(self.temp.name)/'B-started'
            script = Path(self.temp.name)/'competing_writer.py'
            script.write_text(
                'import sys, socket, json\n'
                f'sys.path.insert(0, {str(root)!r})\n'
                        'from tools.source_bootstrap import ensure_source_package\n'
                        'ensure_source_package()\n'
                'def blocked(*args, **kwargs): raise AssertionError("No network permitted")\n'
                'socket.create_connection = blocked\nsocket.socket.connect = blocked\n'
                'from pathlib import Path\n'
                'from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache\n'
                'from calibre_plugins.manganana.discovery.search_resolution import resolve_search_group\n'
                'from calibre_plugins.manganana.providers.source_registry import SourceRegistry\n'
                'from tests.test_inventory_recovery import RecoveringSource\n'
                'from tests.test_search_resolution import chapters\n'
                f'cache = SearchMetadataCache({str(self.cache.path)!r}, clock=lambda: {self.now[0]+1!r})\n'
                'source = RecoveringSource()\n'
                f'source.chapters["en"] = tuple(chapters("dex", 1, {second_count}, 1))\n'
                f'source.warning = {second_warning!r}\nsource.fail = {second_fail!r}\n'
                'def pause():\n'
                f'    Path({str(started)!r}).write_text("started")\n'
                '    if not sys.stdin.readline(): raise RuntimeError("release not received")\n'
                'source.hook = pause\n'
                f'row = {self.row!r}\n'
                'try:\n'
                '    result = resolve_search_group(SourceRegistry((source,)), (row,), "en", "volume", {}, cache)\n'
                f'    token = cache.get_inventory_snapshot({self.key()!r})\n'
                '    print(json.dumps(dict(chapters=result.primary.chapter_count, complete=result.primary.complete, '
                'requests=len(source.transport), snapshot=token)))\n'
                'finally: cache.close()\n', encoding='utf-8')
            child = subprocess.Popen([sys.executable, '-e', str(root/'tools/run_qt_checks.py'), '--', str(script)],
                                     cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic()+10
            while not started.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(started.exists(), 'Independent acquisition failed to start')
            events.append('B-start')
            if first_finishes_first:
                release.set(); owner.join(5)
                self.assertFalse(owner.is_alive()); self.assertFalse(errors)
                events.append('A-finish')
                winner = self.cache.get_inventory_snapshot(self.key())
            stdout, stderr = child.communicate(input='release\n', timeout=20)
            self.assertEqual(0, child.returncode, stdout+stderr)
            second = json.loads(stdout.strip())
            events.append('B-finish')
            if not first_finishes_first:
                winner = self.cache.get_inventory_snapshot(self.key())
                release.set(); owner.join(5)
                self.assertFalse(owner.is_alive()); self.assertFalse(errors)
                events.append('A-finish')
            self.assertEqual(winner, self.cache.get_inventory_snapshot(self.key()))
            self.assertEqual(list(winner), second['snapshot'])
            self.assertEqual(2, len(self.source.transport))
            self.assertEqual(1, second['requests'])
            print(json.dumps(dict(events=events, requests=dict(initial=1, A=1, B=1),
                                  final_chapters=json.loads(winner[0])['chapter_count'])))
            return answers[0].primary, second, winner, events
        finally:
            release.set(); owner.join(5)
            if child is not None and child.poll() is None:
                child.kill(); child.communicate(timeout=5)
            self.source.hook = None

    def test_a_start_b_start_b_finish_a_finish_preserves_complete_and_full_ttl(self):
        first, second, winner, events = self.competing_process_refresh(8, 20)
        self.assertEqual(['A-start', 'B-start', 'B-finish', 'A-finish'], events)
        self.assertEqual((20, True), (first.chapter_count, first.complete))
        self.assertEqual((20, True), (second['chapters'], second['complete']))
        self.assertNotIn('_inventory_retry_after', json.loads(winner[0]))
        self.now[0] = winner[1]+INVENTORY_TTL
        self.assertEqual(20, self.resolve().primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))
        self.now[0] += 1
        self.source.recover()
        self.resolve()
        self.assertEqual(3, len(self.source.transport))

    def test_both_partial_b_smaller_retains_old_rows_and_winner_cooldown(self):
        first, second, winner, events = self.competing_process_refresh(8, 2, 'A partial', 'B partial')
        self.assertEqual(['A-start', 'B-start', 'B-finish', 'A-finish'], events)
        self.assertEqual((4, False), (first.chapter_count, first.complete))
        self.assertEqual((4, False), (second['chapters'], second['complete']))
        value = json.loads(winner[0])
        self.assertEqual(1_000_000, winner[1])  # Retained rows keep their acquisition time.
        self.assertEqual(1_000_362, value['_inventory_retry_after'])
        self.now[0] = value['_inventory_retry_after']-1
        self.assertEqual(4, self.resolve().primary.chapter_count)
        self.assertEqual(2, len(self.source.transport))
        self.now[0] += 1
        self.source.recover()
        self.assertEqual(20, self.resolve().primary.chapter_count)
        self.assertEqual(3, len(self.source.transport))

    def test_both_partial_b_larger_progress_survives_older_completion(self):
        first, second, winner, _ = self.competing_process_refresh(4, 8, 'A partial', 'B partial')
        self.assertEqual((8, False), (first.chapter_count, first.complete))
        self.assertEqual((8, False), (second['chapters'], second['complete']))
        self.assertEqual(1_000_062, winner[1])
        self.assertEqual(1_000_362, json.loads(winner[0])['_inventory_retry_after'])

    def test_b_failure_after_a_success_cannot_downgrade_a(self):
        first, second, winner, events = self.competing_process_refresh(
            20, 4, second_fail=True, first_finishes_first=True)
        self.assertEqual(['A-start', 'B-start', 'A-finish', 'B-finish'], events)
        self.assertEqual((20, True), (first.chapter_count, first.complete))
        self.assertEqual((20, True), (second['chapters'], second['complete']))
        self.assertNotIn('_inventory_retry_after', json.loads(winner[0]))

    def test_cancel_before_persistence_does_not_issue_any_conditional_write(self):
        self.resolve()
        self.now[0] += 61
        token = self.cache.get_inventory_snapshot(self.key())
        cancelled = [False]
        def check():
            if cancelled[0]: raise InterruptedError('cancelled')
        self.source.recover()
        self.source.hook = lambda: cancelled.__setitem__(0, True)
        with patch.object(self.cache, 'compare_and_set_inventory', wraps=self.cache.compare_and_set_inventory) as write:
            with self.assertRaises(InterruptedError): self.resolve(check_cancel=check)
            write.assert_not_called()
        self.assertEqual(token, self.cache.get_inventory_snapshot(self.key()))

    def test_small_healthy_inventory_is_not_classified_partial_by_count(self):
        self.source.chapters['en'] = tuple(chapters('dex', 1, 2, 1))
        self.source.warning = ''
        self.assertEqual((2, True), (self.resolve().primary.chapter_count, self.resolve().primary.complete))
        for offset in (60, 300, INVENTORY_TTL):
            self.now[0] = 1_000_000+offset
            self.assertEqual(2, self.resolve().primary.chapter_count)
            self.assertFalse(inventory_refresh_due(self.cache, [self.key()]))
        self.assertEqual(1, len(self.source.transport))

    def test_cancellation_during_sql_write_rolls_back_before_commit(self):
        self.resolve()
        self.now[0] += 61
        token = self.cache.get_inventory_snapshot(self.key())
        cancelled = [False]
        def check():
            if cancelled[0]: raise InterruptedError('cancelled during write')
        db = self.cache._connect()
        db.create_function('cancel_refresh', 0, lambda: cancelled.__setitem__(0, True))
        db.execute('CREATE TEMP TRIGGER cancel_inventory AFTER UPDATE OF payload ON inventory '
                   'BEGIN SELECT cancel_refresh(); END')
        db.commit()
        self.source.recover()
        with self.assertRaisesRegex(InterruptedError, 'cancelled during write'):
            self.resolve(check_cancel=check)
        self.assertFalse(db.in_transaction)
        self.assertEqual(token, self.cache.get_inventory_snapshot(self.key()))
        db.execute('DROP TRIGGER cancel_inventory'); db.commit()
        cancelled[0] = False
        self.assertEqual(20, self.resolve(check_cancel=check).primary.chapter_count)

    def test_cold_failure_remains_uncached_and_retryable_without_a_save_error(self):
        self.source.fail = True
        result = self.resolve()
        self.assertIsNone(result.primary)
        self.assertIn('provider unavailable', result.inventories[0].error)
        self.assertIsNone(self.cache.get_inventory_snapshot(self.key()))
        self.assertEqual(2, len(self.source.transport))  # Existing en -> ja fallback.
        self.source.fail = False
        self.source.recover()
        self.assertEqual(20, self.resolve().primary.chapter_count)
        self.assertEqual(3, len(self.source.transport))

    def test_cold_failure_returns_concurrent_complete_instead_of_overwriting_it(self):
        previous = self.resolve().primary
        self.cache.clear()
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        try:
            self.source.fail = True
            self.source.hook = lambda: other.put_inventory(self.key(), asdict(self.newer_inventory(previous)))
            result = self.resolve().primary
            self.assertEqual((20, True), (result.chapter_count, result.complete))
            self.assertEqual(20, other.get_inventory(self.key()).value['chapter_count'])
        finally:
            other.close()

    def test_cold_handle_read_race_reuses_owner_that_finished_before_claim(self):
        self.source.recover()
        owner_entered, owner_release = threading.Event(), threading.Event()
        reader_entered, reader_release = threading.Event(), threading.Event()
        def pause_owner():
            owner_entered.set()
            if not owner_release.wait(5): raise RuntimeError('owner timeout')
        self.source.hook = pause_owner
        other = SearchMetadataCache(self.cache.path, clock=lambda: self.now[0])
        owner, answers, owner_errors = self.start_resolve()
        reader = None
        try:
            self.assertTrue(owner_entered.wait(5))
            read = other.get_inventory_snapshot
            held = [False]
            def pause_first_read(key):
                snapshot = read(key)
                if not held[0]:
                    held[0] = True
                    reader_entered.set()
                    if not reader_release.wait(5): raise RuntimeError('reader timeout')
                return snapshot
            with patch.object(other, 'get_inventory_snapshot', side_effect=pause_first_read):
                reader, other_answers, reader_errors = self.start_resolve(cache=other)
                self.assertTrue(reader_entered.wait(5))
                owner_release.set(); owner.join(5)
                self.assertFalse(owner.is_alive())
                reader_release.set(); reader.join(5)
                self.assertFalse(reader.is_alive())
            self.assertFalse(owner_errors+reader_errors)
            self.assertEqual([20, 20], [answers[0].primary.chapter_count, other_answers[0].primary.chapter_count])
            self.assertEqual(1, len(self.source.transport))
        finally:
            owner_release.set(); reader_release.set()
            owner.join(5)
            if reader is not None: reader.join(5)
            other.close()

    def test_cache_recovery_does_not_mutate_an_existing_volume_operation_snapshot(self):
        from calibre_plugins.manganana.providers.source_adapter import acquire_volume_inventory
        plan, rows = acquire_volume_inventory(self.source, self.row['url'], 'en')
        original = deepcopy((plan, rows))
        self.assertEqual(4, self.resolve().primary.chapter_count)
        self.now[0] += 61
        self.source.recover()
        self.assertEqual(20, self.resolve().primary.chapter_count)
        self.assertEqual(original, (plan, rows))
        self.assertEqual(4, len(rows))
        self.assertEqual(3, len(self.source.transport))


if __name__ == '__main__':
    unittest.main()
