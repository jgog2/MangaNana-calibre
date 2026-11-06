"""Fault injection for the six core-reliability repairs; no real HTTP or library."""
from copy import deepcopy
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.source_bootstrap import ensure_source_package
ensure_source_package()
from calibre_plugins.manganana.common.bounded_cache import BoundedCache, artwork_caches
from calibre_plugins.manganana.discovery import saved_manga as saved
from calibre_plugins.manganana.discovery.search_resolution import session_plan_fresh
from calibre_plugins.manganana.providers.mangapill_source import MangaPillSource
from calibre_plugins.manganana.books.imports.output_import import OutputImporter, OutputReconciliation


def listing(identity):
    return dict(source_id='mangapill', id=identity, title='Fixture ' + identity,
                url='https://mangapill.com/manga/' + identity)


class FavoritesOwnershipTests(unittest.TestCase):
    def test_slow_closed_writer_and_reopened_store_conserve_both_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            first = saved.FavoritesStore(directory)
            entered, release = threading.Event(), threading.Event()
            replace = saved.os.replace
            calls = []
            def gate(source, target):
                calls.append(threading.get_ident())
                if len(calls) == 1:
                    entered.set()
                    if not release.wait(5):
                        raise OSError('Test gate timed out')
                return replace(source, target)
            second = None
            try:
                with patch.object(saved.os, 'replace', gate):
                    first.toggle(listing('101'))
                    self.assertTrue(entered.wait(2))
                    self.assertFalse(first.close(timeout=.01))
                    second = saved.FavoritesStore(directory)
                    self.assertTrue(second.contains(listing('101')))
                    second.toggle(listing('202'))
                    self.assertFalse(second.close(timeout=.01))
                    release.set()
                    self.assertTrue(first.close())
                restored = saved.FavoritesStore(directory)
                self.assertEqual({'101','202'}, {r['id'] for r in restored.records.values()})
                self.assertTrue(restored.close())
                self.assertEqual(1, len(set(calls)), 'Only one writer owns the path')
            finally:
                release.set()
                first.close()
                if second: second.close()

    def test_failed_write_retains_unsaved_edit_for_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            first = saved.FavoritesStore(directory)
            with patch.object(saved.os, 'replace', side_effect=OSError('Storage unavailable')):
                first.toggle(listing('101'))
                self.assertFalse(first.close())
            reopened = saved.FavoritesStore(directory)
            self.assertTrue(reopened.contains(listing('101')))
            self.assertTrue(reopened.close())
            self.assertEqual('101', json.loads(reopened.path.read_text())['records'][0]['listing']['id'])

    def test_concurrent_open_clients_share_edit_state(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = saved.FavoritesStore(directory), saved.FavoritesStore(directory)
            first.toggle(listing('101')); second.toggle(listing('202'))
            self.assertTrue(first.contains(listing('202')))
            first.close(); self.assertTrue(second.close())
            self.assertEqual(2, len(json.loads(first.path.read_text())['records']))


class ArtworkBudgetTests(unittest.TestCase):
    def test_byte_entry_lru_and_oversized_values(self):
        cache = BoundedCache(10, 3)
        cache['a'] = b'aaa'; cache['b'] = b'bbb'; cache['c'] = b'ccc'
        cache['a']; cache['d'] = b'ddd'
        self.assertNotIn('b', cache)
        self.assertEqual(9, cache.bytes_used)
        cache['large'] = b'x' * 11
        self.assertNotIn('large', cache)
        cache['a'] = b'aa'
        self.assertEqual(8, cache.bytes_used)
        cache.clear(); self.assertEqual(0, cache.bytes_used)

    def test_raw_eviction_removes_scaled_variants(self):
        from qt.core import QApplication, QPixmap
        app = QApplication.instance() or QApplication([])
        raw, scaled = artwork_caches()
        raw.max_entries = 1
        raw['a'] = b'raw'
        scaled[('a',100)] = QPixmap(100,100)
        raw['b'] = b'raw'
        self.assertFalse(scaled)
        self.assertLessEqual(raw.bytes_used,raw.max_bytes)
        for i in range(500): scaled[('b',i)] = QPixmap(156,218)
        self.assertLessEqual(scaled.bytes_used,scaled.max_bytes)
        self.assertLessEqual(len(scaled),scaled.max_entries)

    def test_evicted_completed_cover_can_be_requested_again(self):
        import ast
        from types import SimpleNamespace as S
        from unittest.mock import Mock
        from qt.core import Qt
        source=Path(__file__).resolve().parents[1]/'app/main.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        methods={n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        for name,kind in (('_load_visible_volume_thumbs','volume'),('_load_visible_search_thumbs','search')):
            with self.subTest(kind=kind):
                raw,scaled=artwork_caches();raw.max_entries=1
                raw['old']=b'displayed';raw['new']=b'newer'
                info=dict(cover_url='old',thumb_requested=True)
                item=S(data=lambda _:info,setData=lambda _role,value:info.update(value))
                view=S(item=lambda _:item,itemWidget=lambda _:None)
                workers=[]
                def worker(*args,**kwargs):
                    w=S(image_ready=Mock(),image_failed=Mock(),finished=Mock(),start=Mock(),entries=args[1])
                    workers.append(w);return w
                namespace=dict(Qt=Qt,COVER_BATCH_LIMIT=6,SEARCH_RESULT_ROW_HEIGHT=66,ImageBatchWorker=worker,
                               SOURCE_REGISTRY=S(get=lambda _:S(source_id='mangapill')),MANGADEX_SOURCE=None)
                exec(compile(ast.Module(body=[methods[name]],type_ignores=[]),str(source),'exec'),namespace)
                owner=S(_closing=False,volume_thumb_worker=None,search_thumb_worker=None,_selected_cover_url='',
                        _image_cache=raw,_failed_image_urls=set(),_visible_row_range=lambda *_:range(1),
                        volume_list=view,search_results=view,_retain_async_worker=lambda w:w,_cover_generation=1,
                        _volume_cover_batch_token=0,_search_cover_batch_token=0,current_source=None,
                        _get_artwork_resolver=lambda:S(peek_display=lambda *_:None),_on_volume_thumb_ready=lambda _:None,
                        _on_volume_thumb_failed=lambda _:None,_on_volume_thumb_finished=lambda _:None,
                        _on_search_thumb_ready=lambda _:None,_on_search_thumb_failed=lambda _:None,
                        _on_search_thumb_finished=lambda _:None)
                namespace[name](owner)
                self.assertEqual(1,len(workers))
                self.assertEqual('old',workers[0].entries[0][0])
                workers[0].start.assert_called_once()


class MangaPillCancellationTests(unittest.TestCase):
    def test_cancellation_during_failed_text_request_prevents_next_attempt(self):
        cancelled = []
        def check():
            if cancelled: raise InterruptedError('Closed')
        def request(*_,**__):
            cancelled.append(True)
            raise OSError('Socket failed')
        source = MangaPillSource().with_cancel_check(check)
        with patch.object(source,'_request',side_effect=request) as transport:
            with self.assertRaises(InterruptedError): source.search('Fixture')
            self.assertEqual(1,transport.call_count)

    def test_binary_cancellation_after_response_is_not_retried(self):
        cancelled = []
        def check():
            if cancelled: raise InterruptedError('Closed')
        class Response(BytesIO):
            def read1(self,*args):
                cancelled.append(True)
                return super().read1(*args)
        source = MangaPillSource(cancel_check=check)
        with patch('urllib.request.urlopen',return_value=Response(b'image')) as transport:
            with self.assertRaises(InterruptedError): source.fetch_binary('https://example.invalid/image')
            self.assertEqual(1,transport.call_count)

    def test_backoff_remains_paced_and_interruptible(self):
        now, cancelled, sleeps = [0.], [], []
        def check():
            if cancelled: raise InterruptedError('Closed')
        def sleep(seconds):
            now[0] += seconds; sleeps.append(seconds)
            if now[0] >= .15: cancelled.append(True)
        source = MangaPillSource(cancel_check=check,sleeper=sleep,clock=lambda:now[0])
        with patch.object(source,'_request',side_effect=OSError('Timeout')) as transport:
            with self.assertRaises(InterruptedError): source.search('Fixture')
            self.assertEqual(1,transport.call_count)
            self.assertLessEqual(max(sleeps),.05)
        self.assertLess(now[0],.75)

    def test_clone_does_not_mutate_registered_provider(self):
        source = MangaPillSource(fetch_text=lambda *_a,**_k:'')
        def closed(): raise InterruptedError()
        clone = source.with_cancel_check(closed)
        with self.assertRaises(InterruptedError): clone._cancel_check()
        source._cancel_check()
        self.assertIs(source._injected_text,clone._injected_text)


class SessionFreshnessTests(unittest.TestCase):
    def test_healthy_partial_legacy_and_clock_changes(self):
        self.assertFalse(session_plan_fresh({},100))
        self.assertTrue(session_plan_fresh({'_cached_at':100},101))
        self.assertFalse(session_plan_fresh({'_cached_at':100},100+3*3600))
        self.assertFalse(session_plan_fresh({'_cached_at':100,'inventory_error':'partial'},160))
        self.assertFalse(session_plan_fresh({'_cached_at':100},99))

    def test_inherited_deadline_cannot_be_extended_by_mode_switch(self):
        snapshot={'_cached_at':200,'_expires_at':210}
        self.assertTrue(session_plan_fresh(snapshot,209))
        self.assertFalse(session_plan_fresh(snapshot,210))
        snapshot['_cached_at']=209
        self.assertFalse(session_plan_fresh(snapshot,210))


class ReplacementTests(unittest.TestCase):
    def _scenario(self, stage, existed=True, rollback_fails=False):
        from calibre.ebooks.metadata.book.base import Metadata
        with tempfile.TemporaryDirectory() as directory:
            payload=dict(kind='chapter',source_id='fixture',chapter_id='opaque-a')
            key='v2:'+hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            old = Metadata('Before',['Author']); old.series='Series'; old.series_index=2.
            old.languages=['eng']; old.set_identifier('mangaanka_output',key)
            replacement=Metadata('After',['Author']); replacement.series='Series';replacement.series_index=9.;replacement.languages=['eng']
            class Database:
                def __init__(self): self.mi=old.deepcopy_metadata(); self.blob=b'old' if existed else None; self.art=b'cover';self.failed=False
                def all_book_ids(self): return {1}
                def field_for(self,field,bid): return deepcopy(self.mi.get_identifiers() if field=='identifiers' else getattr(self.mi,field))
                def get_metadata(self,bid): return self.mi.deepcopy_metadata()
                def has_format(self,*_): return self.blob is not None
                def cover(self,bid): return self.art
                def copy_format_to(self,bid,fmt,dest): Path(dest).write_bytes(self.blob)
                def set_cover(self,values): self.art=values[1]
                def remove_formats(self,*_): self.blob=None
                def add_format(self,bid,fmt,path,**kwargs):
                    self.blob=Path(path).read_bytes()
                    self._fail('format')
                def set_metadata(self,bid,mi,**kwargs):
                    if rollback_fails and self.failed: raise OSError('Rollback storage failure')
                    self.mi=mi.deepcopy_metadata();self._fail('metadata')
                def format_metadata(self,*_,**__):
                    self._fail('verify')
                    return dict(size=len(self.blob))
                def _fail(self,point):
                    if stage==point and not self.failed:
                        self.failed=True
                        raise OSError('Controlled '+point+' failure')
            db=Database(); path=Path(directory)/'replacement.cbz';path.write_bytes(b'new')
            item=dict(output_identity=key,output_acquisition=payload,path=str(path),format='cbz',title='After')
            importer=OutputImporter(db,recovery_root=Path(directory)/'backups')
            run=OutputReconciliation([item],[item],importer,lambda _:replacement,'replace')
            row=run.step()
            if stage:
                self.assertEqual('failed',row['status'])
                self.assertEqual(not rollback_fails,row['rollback_verified'])
                self.assertEqual(b'old' if existed else None,db.blob)
                if rollback_fails:
                    recovery=Path(row['replacement_recovery_directory'])
                    self.assertTrue((recovery/'previous.opf').exists())
                    self.assertTrue((recovery/'recovery.json').exists())
                else:
                    self.assertEqual('Before',db.mi.title)
                    self.assertFalse(list((Path(directory)/'backups').iterdir()))
            else:
                self.assertEqual('updated',row['status'],row)
                self.assertEqual('After',db.mi.title)
                self.assertEqual(b'new',db.blob)

    def test_format_failure_rolls_back(self): self._scenario('format')
    def test_metadata_failure_rolls_back(self): self._scenario('metadata')
    def test_verification_failure_rolls_back(self): self._scenario('verify')
    def test_added_format_removed_on_failure(self): self._scenario('metadata',existed=False)
    def test_incomplete_rollback_retains_backup_and_explicit_outcome(self): self._scenario('metadata',rollback_fails=True)
    def test_successful_replacement_cleans_backup(self): self._scenario(None)


class RecoveryRetentionTests(unittest.TestCase):
    def _finish(self, status, failure='none'):
        import ast
        import shutil
        import time
        from types import SimpleNamespace
        from calibre_plugins.manganana.books.imports.output_import import save_ledger
        source=Path(__file__).resolve().parents[1]/'app/main.py'
        tree=ast.parse(source.read_text(encoding='utf8'))
        method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_finish_download_import')
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);work=base/'prepared';work.mkdir()
            payload=work/'book.cbz';payload.write_bytes(b'prepared book')
            def persist(ledger,destination):
                if failure=='all' or failure=='history' and Path(destination).name=='MangaAnka-output-history':
                    raise OSError('Disk unavailable')
                return save_ledger(ledger,destination)
            namespace=dict(time=time,Path=Path,config_dir=str(base),save_ledger=persist,shutil=shutil)
            exec(compile(ast.Module(body=[method],type_ignores=[]),str(source),'exec'),namespace)
            owner=SimpleNamespace(_closing=True,destination=SimpleNamespace(snapshot=lambda:{'path':'disposable'}))
            ledger=dict(outputs=[dict(status=status)],unexpected=[],counts={'cancelled':0})
            namespace['_finish_download_import'](owner,dict(workdir=str(work)),None,time.perf_counter(),ledger)
            if status in ('failed','conflicted','cancelled') or failure!='none':
                self.assertTrue(payload.is_file())
                self.assertEqual(str(work),ledger['recovery_directory'])
                if failure=='all':self.assertIn('recovery_accounting_error',ledger)
                else:self.assertTrue(Path(owner._last_output_ledger_path).is_file())
            else:self.assertFalse(work.exists())

    def test_closed_failed_conflicted_cancelled_outputs_survive(self):
        for status in ('failed','conflicted','cancelled'):
            with self.subTest(status=status):self._finish(status)

    def test_history_failure_uses_accounting_beside_prepared_file(self): self._finish('conflicted','history')
    def test_total_accounting_failure_still_preserves_payload(self): self._finish('conflicted','all')
    def test_successful_closed_batch_can_clean_prepared_files(self): self._finish('imported')


if __name__=='__main__': unittest.main()
