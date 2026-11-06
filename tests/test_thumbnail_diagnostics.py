import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from calibre_plugins.manganana.diagnostics.thumbnail_diagnostics import ThumbnailAudit, public_url, scope, http_event
from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource

class ThumbnailDiagnosticsTests(unittest.TestCase):
    def test_public_urls_strip_secrets_and_reject_userinfo(self):
        self.assertEqual('',public_url('https://user:password@uploads.mangadex.org/covers/x'))
        self.assertEqual('',public_url('file:///C:/private/book.cbz'))
        self.assertEqual('https://uploads.mangadex.org/covers/x.jpg',public_url('https://uploads.mangadex.org/covers/x.jpg?token=secret#private'))
    def test_ring_file_and_event_fields_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'trace.json';audit=ThumbnailAudit(path)
            for i in range(900):audit.event('record',id=i,data='x'*100000)
            audit.flush();value=json.loads(path.read_text())
            self.assertLessEqual(len(value['events']),384);self.assertLessEqual(path.stat().st_size,256*1024)
            self.assertEqual(900,value['events'][-1]['sequence']);self.assertGreater(value['dropped_before_sequence'],0)
    def test_unchanged_repaint_does_not_evict_a_failure(self):
        audit=ThumbnailAudit('unused');audit.event('http.failure',status=403)
        for _ in range(1000):audit.event('paint',id='work',cached=False)
        self.assertEqual(2,len(audit.events));self.assertEqual('http.failure',audit.events[0]['event'])
    def test_scope_restores_previous_worker(self):
        outer=ThumbnailAudit('outer');inner=ThumbnailAudit('inner')
        with scope(outer):
            http_event('outer.first')
            with scope(inner):http_event('inner')
            http_event('outer.last')
        http_event('disabled')
        self.assertEqual(['outer.first','outer.last'],[e['event'] for e in outer.events])
        self.assertEqual(['inner'],[e['event'] for e in inner.events])
    def test_transport_observation_preserves_bytes_headers_and_attempt_count(self):
        class Response(__import__('io').BytesIO):
            def __init__(self):super().__init__(b'original-body')
            status=200;headers={'Content-Type':'image/jpeg'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
        audit=ThumbnailAudit('unused')
        with patch('calibre_plugins.manganana.providers.mangadex_source.urllib.request.urlopen',return_value=Response()) as request,scope(audit):
            result=MangaDexSource._default_fetch_binary('https://uploads.mangadex.org/covers/test.jpg',retries=1)
        self.assertEqual(b'original-body',result);self.assertEqual(1,request.call_count)
        events=list(audit.events);self.assertEqual(['http.start','http.finish'],[e['event'] for e in events])
        self.assertEqual({'User-Agent','Accept'},set(events[0]['headers']));self.assertEqual(200,events[1]['status'])
    def test_diagnostic_write_failure_does_not_raise(self):
        audit=ThumbnailAudit('unused');audit.event('record',id='work')
        with patch.object(Path,'mkdir',side_effect=OSError('read only')):audit.flush()

if __name__=='__main__':unittest.main()
