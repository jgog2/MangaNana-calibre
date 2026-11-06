"""Operation-local Volume inventory reuse, using existing offline transports."""
import ast
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from calibre_plugins.manganana.providers.source_adapter import SourceAdapter, acquire_volume_inventory, _volume_inventory_capture
from calibre_plugins.manganana.publication.inventory_comparison import inspect_source_inventory
from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
from calibre_plugins.manganana.providers.mangapill_source import MangaPillSource
from calibre_plugins.manganana.providers.weebcentral_source import WeebCentralSource
from calibre_plugins.manganana.providers.mangak_source import MangaKSource
from calibre_plugins.manganana.providers.atsu_source import AtsuSource
from tests import test_mangadex_characterization as dex
from tests import test_mangapill_source as pill
from tests import test_weebcentral_source as weeb
from tests import test_mangak_source as mk
from tests import test_atsu_source as atsu
from tests import test_patch1b_search as packaged

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {'MangaDex': 3, 'MangaPill': 1, 'WeebCentral': 1, 'MangaK': 3,
           'Atsu': 1, 'Atsu packaged': 1, 'Atsu groups': 2}


def source_fixture(name, hook=None):
    calls = []
    if name == 'MangaDex':
        base = dex.FixtureAPI(aggregate=dex.load_fixture('aggregate_plan.json'),
            feed_pages={0: dex.load_fixture('chapter_feed_page_1.json'),
                        500: dex.load_fixture('chapter_feed_page_2.json')}, covers={'data': []})
        cls, url = MangaDexSource, dex.MANGA_URL
    elif name == 'MangaPill':
        base, cls, url = pill.FixtureHTML(), MangaPillSource, pill.MANGA_URL
    elif name == 'WeebCentral':
        base, cls = weeb.Fetcher(), WeebCentralSource
        url = 'https://weebcentral.com/series/01J76XY7KWP8KX5RFGVZY5TR95/Shingeki-No-Kyojin'
    elif name == 'MangaK':
        base, cls, url = mk.Fetcher(), MangaKSource, mk.TITLE
    else:
        base, cls, url = atsu.Fetcher(), AtsuSource, atsu.TITLE
        if name == 'Atsu packaged':
            base.data['chapters'] = deepcopy(packaged.FIX['banana_chapters'])
            url = 'https://atsu.moe/manga/W6oyN'
        elif name == 'Atsu groups':
            base.data['chapters'] = {'chapters': [dict(id=g+str(n), number=n,
                title='Chapter '+str(n), pageCount=1, scanlationMangaId=g)
                for g, numbers in [('a', [1, 3]), ('b', [1, 2])] for n in numbers]}
            base.data['title'] = {'mangaPage': dict(id='fixture', title='Series',
                scanlators=[dict(id='a', name='Alpha'), dict(id='b', name='Delta')])}
            url = 'https://atsu.moe/manga/fixture'
    def transport(value, **kwargs):
        calls.append(value)
        if hook:
            hook(value, base)
        return base(value, **kwargs)
    source = (cls(transport) if cls in (MangaDexSource, MangaPillSource)
              else cls(fetch_text=transport, sleeper=lambda _: None))
    return source, url, calls, base


def worker_class():
    from qt.core import QThread, pyqtSignal
    from calibre_plugins.manganana.common.session_retention import measured_payload
    tree = ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VolumePlanWorker')
    ns = dict(__name__=__name__, QThread=QThread, pyqtSignal=pyqtSignal,
              acquire_volume_inventory=acquire_volume_inventory, measured_payload=measured_payload)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT/'app/main.py'), 'exec'), ns)
    return ns['VolumePlanWorker']


def run_worker(source, url, cancelled=None):
    item = worker_class()(7, source, url, 'en')
    ready, failed = [], []
    item.ready = SimpleNamespace(emit=ready.append)
    item.failed = SimpleNamespace(emit=failed.append)
    if cancelled is not None:
        item.isInterruptionRequested = lambda: cancelled[0]
    item.run()
    return ready, failed


class SingleInventoryTests(unittest.TestCase):
    def tearDown(self):
        self.assertIsNone(_volume_inventory_capture.get())

    def test_all_provider_rows_plans_and_transport_targets(self):
        for name, target in TARGETS.items():
            with self.subTest(provider=name):
                old, url, _, _ = source_fixture(name)
                expected_plan = old.get_download_plan(url, 'en')
                expected_rows = old.get_chapters(url, 'en')
                source, url, calls, _ = source_fixture(name)
                with patch.object(source, 'get_chapters', wraps=source.get_chapters) as enumeration:
                    plan, rows = acquire_volume_inventory(source, url, 'en')
                self.assertEqual(1, enumeration.call_count)
                self.assertEqual(target, len(calls))
                self.assertEqual(expected_plan, plan)
                self.assertEqual(expected_rows, rows)  # all fields, ordering and envelopes

    def test_actual_volume_worker_preserves_full_payload_for_every_provider(self):
        for name, target in TARGETS.items():
            with self.subTest(provider=name):
                old, url, _, _ = source_fixture(name)
                plan = old.get_download_plan(url, 'en')
                rows = old.get_chapters(url, 'en')
                counts = {}
                for row in rows:
                    if row['volume'] is not None:
                        volume = float(row['volume'])
                        counts[volume] = counts.get(volume, 0)+1
                plan.update(volumes=sorted(counts), chapters_by_volume=counts,
                            bonus_chapters=sum(r['volume'] is None for r in rows))
                cover_error = ''
                try:
                    covers = old.get_volume_covers(url)
                except Exception as exc:
                    covers = {}
                    cover_error = str(exc)
                source, url, calls, _ = source_fixture(name)
                ready, failed = run_worker(source, url)
                self.assertEqual([], failed)
                self.assertGreater(ready[0].pop('_cache_bytes'),0)
                self.assertEqual([dict(request_id=7, url=url, language='en', source_id=source.source_id,
                    plan=plan, covers=covers, cover_error=cover_error, chapters=rows)], ready)
                self.assertEqual(target+(name not in ('WeebCentral','MangaPill')), len(calls))

    def test_inspector_preserves_context_and_readable_counts(self):
        for name in TARGETS:
            with self.subTest(provider=name):
                source, url, calls, _ = source_fixture(name)
                result = dict(url=url, title='Explicit fan colored edition', source_id=source.source_id)
                inventory = inspect_source_inventory(source, result, 'en', 'volume')
                self.assertEqual(TARGETS[name], len(calls))
                self.assertEqual(result, inventory.result)
                self.assertEqual('en', inventory.language)
                self.assertEqual('fan_color', inventory.edition)
                self.assertEqual(len(inventory.chapter_records), inventory.chapter_count)
                self.assertTrue(inventory.usable)

    def test_page_two_persistent_failure_never_promotes_a_prefix(self):
        def fail(url, base):
            if '/feed?' in url and 'offset=500' in url:
                raise RuntimeError('page two unavailable')
        source, url, calls, _ = source_fixture('MangaDex', fail)
        inventory = inspect_source_inventory(source, dict(url=url), 'en', 'volume')
        self.assertFalse(inventory.usable)
        self.assertFalse(inventory.complete)
        self.assertEqual((), inventory.chapter_records)
        self.assertIn('page two', inventory.error)
        self.assertEqual(5, len(calls))  # both independent attempts retained
        source, url, calls, _ = source_fixture('MangaDex', fail)
        ready, failed = run_worker(source, url)
        self.assertFalse(ready)
        self.assertIn('page two', failed[0]['error'])

    def test_failed_plan_feed_recovers_independently_without_losing_warning(self):
        failures = [1]
        def fail_once(url, base):
            if '/feed?' in url and 'offset=500' in url and failures[0]:
                failures[0] -= 1
                raise RuntimeError('first page two failure')
        source, url, calls, _ = source_fixture('MangaDex', fail_once)
        inventory = inspect_source_inventory(source, dict(url=url), 'en', 'volume')
        self.assertTrue(inventory.usable)
        self.assertFalse(inventory.complete)
        self.assertEqual(5, inventory.chapter_count)
        self.assertIn('first page two failure', inventory.error)
        self.assertEqual(5, len(calls))
        failures[0] = 1
        source, url, calls, _ = source_fixture('MangaDex', fail_once)
        ready, failed = run_worker(source, url)
        self.assertFalse(failed)
        self.assertEqual(5, len(ready[0]['chapters']))
        self.assertIn('first page two failure', ready[0]['plan']['feed_error'])

    def test_aggregate_failure_retains_warning_with_single_usable_feed(self):
        def fail(url, base):
            if '/aggregate?' in url:
                raise RuntimeError('aggregate unavailable')
        source, url, calls, _ = source_fixture('MangaDex', fail)
        inventory = inspect_source_inventory(source, dict(url=url), 'en', 'volume')
        self.assertTrue(inventory.usable)
        self.assertFalse(inventory.complete)
        self.assertIn('aggregate unavailable', inventory.error)
        self.assertEqual(3, len(calls))

    def test_empty_success_is_reused(self):
        source, url, calls, base = source_fixture('MangaDex')
        base.feed_pages = {0: {'data': []}}
        plan, rows = acquire_volume_inventory(source, url, 'en')
        self.assertEqual([], rows)
        self.assertTrue(plan['volumes'])  # advisory aggregate remains distinct
        self.assertEqual(2, len(calls))

    def test_whole_plan_failure_still_fails_and_releases_capture(self):
        source, url, calls, _ = source_fixture('MangaPill')
        with patch.object(source, 'get_download_plan', side_effect=RuntimeError('plan failed')):
            inventory = inspect_source_inventory(source, dict(url=url), 'en', 'volume')
        self.assertFalse(inventory.usable)
        self.assertEqual('plan failed', inventory.error)
        self.assertEqual([], calls)
        self.assertIsNone(_volume_inventory_capture.get())
        self.assertEqual(3, len(source.get_chapters(url, 'en')))

    def test_later_inspections_and_direct_download_enumeration_are_fresh(self):
        for name, target in TARGETS.items():
            with self.subTest(provider=name):
                source, url, calls, base = source_fixture(name)
                _, first = acquire_volume_inventory(source, url, 'en')
                calls.clear()
                if name == 'MangaDex':
                    base.feed_pages[500]['data'].append(dict(id='new', attributes=dict(chapter='999', pages=1)))
                _, second = acquire_volume_inventory(source, url, 'en')
                self.assertEqual(target-(name == 'MangaK'), len(calls))
                if name == 'MangaDex': self.assertEqual(len(first)+1, len(second))
                calls.clear()
                source.get_chapters(url, 'en')
                self.assertTrue(calls)  # no inventory reused by download-time callers

    def test_chapter_mode_and_public_plan_stay_independent(self):
        for name, target in TARGETS.items():
            with self.subTest(provider=name):
                source, url, calls, _ = source_fixture(name)
                with patch.object(source, 'get_download_plan', side_effect=AssertionError('Chapter mode called plan')):
                    inventory = inspect_source_inventory(source, dict(url=url), 'en', 'chapter')
                self.assertTrue(inventory.usable)
                self.assertEqual(target-(name == 'MangaDex'), len(calls))
                self.assertIsNone(_volume_inventory_capture.get())

    def test_cancellation_never_emits_a_ready_snapshot(self):
        for name in ('MangaDex','MangaPill','WeebCentral','MangaK','Atsu'):
            with self.subTest(provider=name):
                cancelled = [False]
                def cancel(url, base): cancelled[0] = True
                source, url, calls, _ = source_fixture(name, cancel)
                ready, failed = run_worker(source, url, cancelled)
                self.assertEqual([], ready)
                self.assertEqual('Selection changed', failed[0]['error'])

    def test_atsu_missing_recommendation_retains_complete_union(self):
        def fail(url, base):
            if '/api/manga/page' in url: raise RuntimeError('recommendation unavailable')
        source, url, calls, _ = source_fixture('Atsu groups', fail)
        plan, rows = acquire_volume_inventory(source, url, 'en')
        self.assertEqual(4, len(rows))
        self.assertEqual(2, len(calls))
        self.assertEqual(4, plan['bonus_chapters'])

    def test_unknown_adapter_keeps_legacy_fallback(self):
        calls=[]
        source=SimpleNamespace(get_download_plan=lambda *args: calls.append('plan') or {'diagnostic':'keep'},
                               get_chapters=lambda *args: calls.append('rows') or [{'id':'opaque'}])
        plan, rows=acquire_volume_inventory(source,'title','en')
        self.assertEqual(['plan','rows'],calls)
        self.assertEqual({'diagnostic':'keep'},plan)
        self.assertEqual([{'id':'opaque'}],rows)

    def test_capture_is_exact_source_title_language_and_range_scoped(self):
        source, url, calls, _ = source_fixture('MangaPill')
        other, _, _, _ = source_fixture('MangaPill')
        for wrong in (lambda: other.get_chapters(url,'en'),
                      lambda: source.get_chapters(url,'fr'),
                      lambda: source.get_chapters(url,'en',1,2),
                      lambda: source.get_chapters('https://mangapill.com/manga/5675/different','en')):
            with self.subTest(enumeration=wrong):
                with patch.object(source,'get_download_plan',side_effect=lambda *a: wrong() and {}):
                    with patch.object(source,'get_chapters',wraps=source.get_chapters) as enumeration:
                        acquire_volume_inventory(source,url,'en')
                    self.assertTrue(any(call.args==(url,'en') for call in enumeration.call_args_list))

    def test_concurrent_operations_on_same_adapter_do_not_share_capture(self):
        barrier = threading.Barrier(2)
        local = threading.local()
        class Source:
            @SourceAdapter.capture_chapter_inventory
            def get_chapters(self, value, language, start_volume=None, end_volume=None):
                return [{'id': str(local.identifier), 'chapter': str(local.identifier)}]
            def get_download_plan(self, value, language):
                rows = self.get_chapters(value, language)
                barrier.wait(timeout=5)
                return {'id': rows[0]['id']}
        source = Source()
        answers, errors = {}, []
        def operation(identifier):
            try:
                local.identifier = identifier
                answers[identifier] = acquire_volume_inventory(source, 'same-title', 'en')
                self.assertIsNone(_volume_inventory_capture.get())
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=operation, args=(n,)) for n in (1,2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(errors)
        for n in (1,2): self.assertEqual(str(n), answers[n][1][0]['id'])

    def test_nested_operation_restores_outer_capture(self):
        inner, url, inner_calls, _ = source_fixture('MangaPill')
        outer, _, outer_calls, _ = source_fixture('MangaPill')
        original = outer.get_download_plan
        def nested(*args):
            acquire_volume_inventory(inner, url, 'en')
            return original(*args)
        with patch.object(outer,'get_download_plan',side_effect=nested):
            _, rows = acquire_volume_inventory(outer,url,'en')
        self.assertEqual(3,len(rows))
        self.assertEqual(1,len(inner_calls))
        self.assertEqual(1,len(outer_calls))

    def test_actual_asynchronous_worker_runs_transport_off_caller_thread(self):
        from qt.core import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSlot
        app = QCoreApplication.instance() or QCoreApplication([])
        main_thread = threading.get_ident()
        transport_threads = []
        source,url,calls,_ = source_fixture('MangaPill',lambda *a: transport_threads.append(threading.get_ident()))
        item = worker_class()(7,source,url,'en')
        class Receiver(QObject):
            def __init__(self): super().__init__(); self.ready=[]; self.failed=[]
            @pyqtSlot(object)
            def receive(self,data): self.ready.append(data)
            @pyqtSlot(object)
            def failure(self,data): self.failed.append(data)
        receiver = Receiver(); loop = QEventLoop()
        item.ready.connect(receiver.receive); item.failed.connect(receiver.failure)
        item.finished.connect(loop.quit)
        timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(5000)
        item.start(); loop.exec(); timer.stop()
        self.assertTrue(item.wait(5000))
        app.processEvents()
        self.assertFalse(receiver.failed)
        self.assertEqual(1,len(receiver.ready))
        self.assertEqual(3,len(receiver.ready[0]['chapters']))
        self.assertTrue(transport_threads)
        self.assertTrue(all(n != main_thread for n in transport_threads))
        self.assertEqual(1,len(calls))  # worker-local title document also supplies cover metadata

    def test_actual_asynchronous_cancellation_keeps_failure_terminal(self):
        from qt.core import QCoreApplication, QEventLoop, QObject, QTimer, pyqtSlot
        app = QCoreApplication.instance() or QCoreApplication([])
        entered, release = threading.Event(), threading.Event()
        def paused(url, base):
            entered.set()
            if not release.wait(5): raise RuntimeError('test transport timed out')
        source,url,calls,_ = source_fixture('MangaK',paused)
        item = worker_class()(7,source,url,'en')
        class Receiver(QObject):
            def __init__(self): super().__init__(); self.ready=[]; self.failed=[]
            @pyqtSlot(object)
            def receive(self,data): self.ready.append(data)
            @pyqtSlot(object)
            def failure(self,data): self.failed.append(data)
        receiver=Receiver(); loop=QEventLoop()
        item.ready.connect(receiver.receive); item.failed.connect(receiver.failure)
        item.finished.connect(loop.quit)
        timer=QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(5000)
        item.start()
        started=entered.wait(5)
        item.requestInterruption(); release.set()
        loop.exec(); timer.stop()
        self.assertTrue(item.wait(5000)); app.processEvents()
        self.assertTrue(started)
        self.assertFalse(receiver.ready)
        self.assertEqual('Selection changed',receiver.failed[0]['error'])
        self.assertEqual(1,len(calls))

    def test_stale_request_and_language_callbacks_still_return_before_mutation(self):
        tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
        methods=[m for n in tree.body if isinstance(n,ast.ClassDef) for m in n.body
                 if isinstance(m,ast.FunctionDef) and m.name in ('_on_volume_plan_ready','_apply_volume_plan_data')]
        ns={}
        exec(compile(ast.Module(body=methods,type_ignores=[]),'app/main.py','exec'),ns)
        context=SimpleNamespace(_closing=False,_volume_plan_request_id=8,language=SimpleNamespace(currentData=lambda:'en'))
        ns['_on_volume_plan_ready'](context,{'request_id':7})
        ns['_apply_volume_plan_data'](context,{'request_id':8,'language':'ja'})
        self.assertEqual({'_closing','_volume_plan_request_id','language'},set(vars(context)))

    def test_experimental_features_remain_disabled_when_flags_absent(self):
        tree=ast.parse((ROOT/'publication/catalog_review.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CatalogReview')
        init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
        assignment=next(n for n in init.body if isinstance(n,ast.Assign)
                        and any(isinstance(t,ast.Attribute) and t.attr=='enabled' for t in n.targets))
        with patch.dict(os.environ,{},clear=True):
            context=SimpleNamespace()
            exec(compile(ast.Module(body=[assignment],type_ignores=[]),'publication/catalog_review.py','exec'),
                 dict(self=context,os=os,enabled=None))
            self.assertFalse(context.enabled)
            source=MangaKSource()
            source._page_props=lambda value: {'initialChapter':{'id':'exact','url':'/haikyu/chapter-2-1',
                'images':['https://fixture.invalid/a.png'],'pages':[{'url':'https://fixture.invalid/a.png'}]}}
            with patch('calibre_plugins.manganana.providers.mangak_continuations.manifest_pages',side_effect=AssertionError('continuations enabled')):
                self.assertEqual(['https://fixture.invalid/a.png'],source.get_page_manifest('https://mangak.io/haikyu/chapter-2-1')['full'])

    def test_cbz_pdf_download_planning_receives_identical_groups(self):
        from qt.core import QThread
        from calibre_plugins.manganana.publication.unified_volume import build_unified_volume_plan
        tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
        cls=deepcopy(next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DownloadWorker'))
        cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__']
        ns=dict(__name__=__name__,QThread=QThread)
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'app/main.py','exec'),ns)
        for name in ('MangaDex','MangaPill','Atsu packaged','Atsu groups'):
            with self.subTest(provider=name):
                old,url,_,_=source_fixture(name)
                expected=build_unified_volume_plan(old.get_download_plan(url,'en'),old.get_chapters(url,'en'),None,old.source_id,old.display_name)
                source,url,_,_=source_fixture(name)
                ready,failed=run_worker(source,url)
                self.assertFalse(failed)
                actual=build_unified_volume_plan(ready[0]['plan'],ready[0]['chapters'],None,source.source_id,source.display_name)
                self.assertEqual(expected['volume_groups'],actual['volume_groups'])
                for format in ('cbz','pdf'):
                    item=ns['DownloadWorker'](source,url,'Title','Author','Series','en',None,None,False,False,(),
                        chapter_output_groups=actual['volume_groups'],output_format=format,
                        processing=object(),artwork_resolver=object())
                    self.assertEqual(format,item.output_format)
                    self.assertEqual(expected['volume_groups'],item.chapter_output_groups)

    def test_mangadex_exact_page_boundary_retains_required_empty_request(self):
        source,url,calls,base=source_fixture('MangaDex')
        base.feed_pages={0:base.feed_pages[0],500:{'data':[]}}
        _,rows=acquire_volume_inventory(source,url,'en')
        self.assertEqual(4,len(rows))
        self.assertEqual(3,len(calls))
        self.assertIn('offset=500',calls[-1])

    def test_plan_exception_after_success_does_not_leak_snapshot(self):
        source,url,calls,_=source_fixture('MangaPill')
        def broken(value,language):
            source.get_chapters(value,language)
            raise RuntimeError('failed after enumeration')
        with patch.object(source,'get_download_plan',side_effect=broken):
            with self.assertRaisesRegex(RuntimeError,'after enumeration'):
                acquire_volume_inventory(source,url,'en')
        self.assertIsNone(_volume_inventory_capture.get())
        source.get_chapters(url,'en')
        self.assertEqual(2,len(calls))


if __name__ == '__main__': unittest.main()
