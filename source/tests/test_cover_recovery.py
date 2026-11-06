import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from calibre_plugins.manganana.books.imaging.artwork_delivery import ArtworkResolver, candidate_for_url
from tests.test_artwork_delivery import GOOD
from calibre_plugins.manganana.diagnostics.thumbnail_diagnostics import ThumbnailAudit, scope, public_url
from calibre_plugins.manganana.providers.weebcentral_source import WeebCentralSource
from calibre_plugins.manganana.providers.mangak_source import MangaKSource

class RecoveryTests(unittest.TestCase):
    def test_explicit_retry_only_clears_target_chain_negative_cache(self):
        source=SimpleNamespace(source_id='weebcentral',fetch_binary=lambda *a,**k:GOOD)
        resolver=ArtworkResolver();url='https://temp.compsci88.com/cover/small/A.webp'
        other='https://temp.compsci88.com/cover/small/B.webp'
        a=candidate_for_url(url,source);b=candidate_for_url(other,source)
        resolver.chains[url]=(a,);resolver.negative[a.key]=(0,'failed');resolver.negative[b.key]=(0,'failed')
        resolver.valid[b.key]=GOOD;resolver.valid_at[b.key]=0
        resolver.retry_failed_url(url,source)
        self.assertNotIn(a.key,resolver.negative);self.assertIn(b.key,resolver.negative)
        self.assertEqual((a,),resolver.chains[url]);self.assertEqual(GOOD,resolver.valid[b.key])
        self.assertEqual(GOOD,resolver.resolve_url(url,source)['raw'])

    def test_public_cover_urls_reject_noncover_paths_and_secrets(self):
        for url in ('https://temp.compsci88.com/cover/small/A.webp','https://rx.resmk.org/covers/a.webp'):
            self.assertEqual(url,public_url(url+'?token=secret#private'))
        for url in ('https://rx.resmk.org/private/a','https://temp.compsci88.com/profile','https://other.invalid/covers/a'):
            self.assertEqual('',public_url(url))

    def test_provider_transport_observation_keeps_headers_bytes_and_attempts(self):
        class Response(__import__('io').BytesIO):
            def __init__(self):super().__init__(GOOD)
            status=200;headers={'Content-Type':'image/webp'}
            def __enter__(self):return self
            def __exit__(self,*a):pass
        for source,url in ((WeebCentralSource(),'https://temp.compsci88.com/cover/small/A.webp'),(MangaKSource(),'https://rx.resmk.org/covers/a.webp')):
            audit=ThumbnailAudit('unused')
            with patch('urllib.request.urlopen',return_value=Response()) as request,scope(audit):
                self.assertEqual(GOOD,source.fetch_binary(url,retries=1))
            self.assertEqual(1,request.call_count)
            self.assertEqual(['http.start','http.finish'],[v['event'] for v in audit.events])
            self.assertEqual({'User-Agent','Accept','Referer'},set(audit.events[0]['headers']))
            self.assertEqual(200,audit.events[1]['status']);self.assertEqual(len(GOOD),audit.events[1]['bytes'])
            self.assertEqual('image/webp',audit.events[1]['content_type'])
            self.assertTrue(audit.events[1]['utc']);self.assertEqual(audit.events[0]['session'],audit.events[1]['session'])

    def test_provider_http_failure_retains_original_error_and_status(self):
        for source,url in ((WeebCentralSource(),'https://temp.compsci88.com/cover/small/A.webp'),(MangaKSource(),'https://rx.resmk.org/covers/a.webp')):
            audit=ThumbnailAudit('unused')
            with patch('urllib.request.urlopen',side_effect=HTTPError(url,403,'blocked',{},None)) as request,scope(audit):
                with self.assertRaises(RuntimeError):source.fetch_binary(url,retries=1)
            self.assertEqual(1,request.call_count)
            self.assertEqual('http.failure',audit.events[-1]['event']);self.assertEqual(403,audit.events[-1]['status'])

if __name__=='__main__':unittest.main()
