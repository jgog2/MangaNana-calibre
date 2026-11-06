"""Deterministic bounded buffering and request-local cancellation controls."""
from io import BytesIO
import unittest
from unittest.mock import patch
from tools.source_bootstrap import ensure_source_package
ensure_source_package()
from calibre_plugins.manganana.providers.transport import read_response, ResponseLimitExceeded
from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
from calibre_plugins.manganana.providers.mangapill_source import MangaPillSource
from calibre_plugins.manganana.providers.weebcentral_source import WeebCentralSource
from calibre_plugins.manganana.providers.mangak_source import MangaKSource
from calibre_plugins.manganana.providers.atsu_source import AtsuSource


class Response(BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}


class TransportBoundsTests(unittest.TestCase):
    def test_exact_limit_and_chunked_body_preserve_all_bytes(self):
        blob = bytes(range(256))*1024
        self.assertEqual(blob, read_response(Response(blob), len(blob)))
        self.assertEqual(blob, read_response(Response(blob,{'Content-Length':str(len(blob))}),len(blob)))

    def test_declared_oversized_body_is_not_read(self):
        response = Response(b'', {'Content-Length':'1000000'})
        with patch.object(response,'read1',side_effect=AssertionError('Must not allocate')):
            with self.assertRaises(ResponseLimitExceeded): read_response(response,100)

    def test_unannounced_overflow_and_truncation_are_explicit_failures(self):
        with self.assertRaises(ResponseLimitExceeded): read_response(Response(b'x'*101),100)
        with self.assertRaisesRegex(OSError,'Incomplete response'):
            read_response(Response(b'x',{'Content-Length':'10'}),100)

    def test_stream_cancellation_stops_before_consuming_remaining_body(self):
        cancelled = []
        class Stream(Response):
            def read1(self,size):
                result = super().read1(size)
                cancelled.append(True)
                return result
        def check():
            if cancelled: raise InterruptedError('Window closed')
        response = Stream(b'x'*1000000)
        with self.assertRaises(InterruptedError): read_response(response,1000000,check)
        self.assertLessEqual(response.tell(),65536)

    def test_all_five_default_transports_propagate_stream_cancellation_without_retry(self):
        for cls in (MangaDexSource,MangaPillSource,WeebCentralSource,MangaKSource,AtsuSource):
            with self.subTest(provider=cls.source_id):
                cancelled = []
                def check():
                    if cancelled: raise InterruptedError('Closed')
                class Stream(Response):
                    def read1(self,size):
                        result=super().read1(size);cancelled.append(True);return result
                registered = cls(); source = registered.with_cancel_check(check)
                with patch('urllib.request.urlopen',return_value=Stream(b'valid body')) as transport:
                    with self.assertRaises(InterruptedError): source.fetch_binary('https://example.invalid/page')
                self.assertEqual(1,transport.call_count)
                registered._cancel_check()

    def test_mangadex_retry_after_wait_is_cancelled_without_starting_another_request(self):
        import urllib.error
        source = MangaDexSource()
        checks = []
        def cancel():
            checks.append(True)
            if len(checks)>1: raise InterruptedError('Closed during rate-limit wait')
        clone = source.with_cancel_check(cancel)
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError(
                'https://api.mangadex.org/manga',429,'wait',{'Retry-After':'60'},None)) as opened:
            with self.assertRaises(InterruptedError): clone._api_json('https://api.mangadex.org/manga')
        self.assertEqual(1,opened.call_count)

    def test_json_wrappers_preserve_response_limit_error_without_retries(self):
        for cls in (MangaKSource,AtsuSource):
            with self.subTest(provider=cls.source_id):
                with patch('urllib.request.urlopen',return_value=Response(b'',{'Content-Length':str(17*1024*1024)})) as opened:
                    with self.assertRaisesRegex(ResponseLimitExceeded,'16 MiB safety limit'):
                        cls()._json('https://example.invalid/inventory')
                self.assertEqual(1,opened.call_count)


if __name__ == '__main__': unittest.main()
