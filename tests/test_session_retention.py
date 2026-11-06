"""Bound retained UI state without changing source identities or selections."""
import unittest
from tools.source_bootstrap import ensure_source_package
ensure_source_package()
from calibre_plugins.manganana.common.session_retention import (
    ActivityHistory, payload_bytes, measured_payload, session_caches,
)


class SessionRetentionTests(unittest.TestCase):
    def test_shared_graph_counted_once_and_cycles_terminate(self):
        rows = [{'id':str(i)} for i in range(100)]
        self.assertLess(payload_bytes([rows, rows]), payload_bytes([rows, [dict(r) for r in rows]]))
        cycle = []; cycle.append(cycle)
        self.assertLess(payload_bytes(cycle), 1000)
        self.assertGreater(payload_bytes(object()), 16*1024*1024)

    def test_entry_byte_eviction_does_not_mutate_acquisition_or_overrides(self):
        metadata, plans = session_caches()
        original = dict(id='opaque', chapter='Prologue 1', _cache_bytes=256*1024)
        for i in range(120):
            metadata[str(i)] = original
            plans[str(i)] = original
        self.assertLessEqual(metadata.bytes_used, metadata.max_bytes)
        self.assertLessEqual(plans.bytes_used, plans.max_bytes)
        self.assertEqual(16, len(metadata)); self.assertEqual(32, len(plans))
        self.assertEqual('opaque', original['id'])
        self.assertEqual('Prologue 1', original['chapter'])
        plans['unmeasured'] = {'chapters':[original]}
        self.assertNotIn('unmeasured', plans)
        oversized = dict(chapters=[original], _cache_bytes=plans.max_bytes+1)
        plans['oversized'] = oversized
        self.assertNotIn('oversized', plans)
        self.assertEqual(original, oversized['chapters'][0])

    def test_worker_measurement_and_mode_copy_reuse_cost(self):
        _, plans = session_caches()
        payload = measured_payload(chapters=[dict(id=str(i), chapter='Extra') for i in range(1169)])
        plans['chapter'] = payload; plans['volume'] = dict(payload)
        self.assertIs(plans['chapter']['chapters'], plans['volume']['chapters'])
        self.assertGreater(payload['_cache_bytes'], 1169)
        plans.clear(); self.assertEqual(0, plans.bytes_used)

    def test_metadata_worker_caches_by_requested_source_ref_not_unrelated_uuid(self):
        import threading
        from types import SimpleNamespace
        from unittest.mock import Mock
        from qt.core import QCoreApplication, QEventLoop, QTimer
        from calibre_plugins.manganana.app.main import MangaLoadWorker, MangaNanaDialog
        caller=threading.get_ident();threads=[]
        class Source:
            source_id='mangak'
            def parse_manga_ref(self,url): return 'fixture-slug'
            def get_manga(self,url,preferred):
                threads.append(threading.get_ident())
                return dict(uuid='separate-provider-uuid',title='Controlled fixture')
        app=QCoreApplication.instance();loop=QEventLoop()
        ready=[];failed=[]
        worker=MangaLoadWorker(7,Source(),'https://mangak.io/fixture-slug')
        worker.ready.connect(ready.append);worker.failed.connect(failed.append)
        worker.finished.connect(loop.quit);QTimer.singleShot(3000,loop.quit)
        worker.start();loop.exec();self.assertTrue(worker.wait(3000))
        app.processEvents()
        self.assertFalse(failed);self.assertEqual(1,len(ready))
        self.assertTrue(threads and all(t!=caller for t in threads))
        metadata,_=session_caches();owner=SimpleNamespace(_closing=False,_manga_cache=metadata,_apply_loaded_manga=Mock())
        MangaNanaDialog._on_manga_worker_ready(owner,ready[0])
        self.assertIn(('mangak','fixture-slug'),metadata)
        self.assertNotIn(('mangak','separate-provider-uuid'),metadata)
        owner._apply_loaded_manga.assert_called_once_with(7,ready[0])

    def test_history_caps_entries_and_export_discloses_omission(self):
        history = ActivityHistory()
        lines = []
        for i in range(5000):
            line = history.prepare('Message '+str(i))
            lines.append(line)
            del lines[:history.append(line)]
        self.assertEqual(1000,len(lines)); self.assertEqual(4000,history.dropped)
        exported = history.export(lines)
        self.assertIn('4000 older messages omitted',exported)
        self.assertIn('Message 4999',exported)
        history.clear(); self.assertEqual('',history.export([]))

    def test_utf8_and_single_giant_message_stay_bounded(self):
        history = ActivityHistory(max_rows=100, max_bytes=200, max_line_bytes=64)
        for _ in range(1000):
            text = history.prepare('日本語'*10000)
            self.assertLessEqual(len(text.encode('utf8')),64)
            history.append(text)
        self.assertLessEqual(history.bytes_used,200)
        self.assertGreater(history.dropped,0)


if __name__ == '__main__': unittest.main()
