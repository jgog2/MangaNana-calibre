"""Certificate failures are terminal; transient retries and verified TLS remain intact."""
import io
import ssl
import unittest
import urllib.error
from unittest.mock import Mock, patch

from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource


URL = 'https://api.mangadex.org/manga?title=private-test-query'


def certificate(message='certificate has expired', code=10):
    error = ssl.SSLCertVerificationError(1, message)
    error.verify_code = code
    error.verify_message = message
    return error


class CertificateErrors(unittest.TestCase):
    def test_api_expired_direct_and_urllib_wrapped_stop_without_retry(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                error = certificate()
                if wrapped:
                    error = urllib.error.URLError(error)
                callback = Mock()
                with patch('urllib.request.urlopen', side_effect=error) as opened, \
                     patch('calibre_plugins.manganana.providers.mangadex_source.time.sleep') as sleep:
                    with self.assertRaises(RuntimeError) as caught:
                        MangaDexSource._default_api_json(URL, retry_callback=callback)
                self.assertEqual(opened.call_count, 1)
                sleep.assert_not_called()
                callback.assert_not_called()
                text = str(caught.exception)
                self.assertIn('api.mangadex.org', text)
                self.assertIn("certificate chain has expired", text)
                self.assertIn("computer's date and time", text)
                self.assertIn('antivirus/proxy', text)
                self.assertIn('certificate verification remains enabled', text)
                self.assertNotIn('private-test-query', text)
                self.assertNotIn('after 3', text)
                self.assertIs(caught.exception.__cause__, error)
                self.assertNotIn('context', opened.call_args.kwargs)

    def test_expired_without_verify_attributes_is_still_classified(self):
        with patch('urllib.request.urlopen', side_effect=ssl.SSLCertVerificationError(
                1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired')):
            with self.assertRaisesRegex(RuntimeError, 'certificate chain has expired'):
                MangaDexSource._default_api_json(URL)

    def test_other_certificate_failures_do_not_claim_expiration(self):
        for message, code in [('unable to get local issuer certificate', 20),
                              ('self-signed certificate', 18),
                              ('Hostname mismatch', 62)]:
            with self.subTest(message=message), \
                 patch('urllib.request.urlopen', side_effect=urllib.error.URLError(certificate(message, code))) as opened, \
                 patch('calibre_plugins.manganana.providers.mangadex_source.time.sleep') as sleep:
                with self.assertRaises(RuntimeError) as caught:
                    MangaDexSource._default_api_json(URL)
                self.assertIn(message, str(caught.exception))
                self.assertNotIn('has expired', str(caught.exception))
                self.assertEqual(opened.call_count, 1)
                sleep.assert_not_called()

    def test_legacy_typed_verification_error(self):
        error = ssl.SSLError(1, 'certificate has expired')
        error.reason = 'CERTIFICATE_VERIFY_FAILED'
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError(error)) as opened:
            with self.assertRaisesRegex(RuntimeError, 'certificate chain has expired'):
                MangaDexSource._default_api_json(URL)
        self.assertEqual(opened.call_count, 1)

    def test_explicit_exception_cause_is_retained(self):
        original = certificate()
        error = RuntimeError('transport wrapper')
        error.__cause__ = original
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'certificate chain has expired') as caught:
                MangaDexSource._default_api_json(URL)
        self.assertIs(caught.exception.__cause__, error)

    def test_binary_certificate_error_stops_without_retry(self):
        for wrapped in (False, True):
            error = certificate()
            if wrapped:
                error = urllib.error.URLError(error)
            with self.subTest(wrapped=wrapped), \
                 patch('urllib.request.urlopen', side_effect=error) as opened, \
                 patch('calibre_plugins.manganana.providers.mangadex_source.time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'certificate chain has expired'):
                    MangaDexSource._default_fetch_binary('https://uploads.mangadex.org/cover.jpg')
                self.assertEqual(opened.call_count, 1)
                sleep.assert_not_called()

    def test_preview_certificate_error_does_not_attempt_full_quality_fallback(self):
        source = MangaDexSource(fetch_binary=Mock())
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError(certificate())) as opened, \
             patch('calibre_plugins.manganana.providers.mangadex_source.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'certificate chain has expired'):
                source.fetch_preview_page('https://example.org/saver', 'https://example.org/full', 1)
        self.assertEqual(opened.call_count, 1)
        source._fetch_binary.assert_not_called()
        sleep.assert_not_called()

    def test_preview_full_quality_certificate_failure_keeps_clear_error(self):
        source = MangaDexSource(fetch_binary=Mock(side_effect=urllib.error.URLError(certificate())))
        with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError(URL, 404, 'Missing', {}, None)):
            with self.assertRaisesRegex(RuntimeError, 'certificate chain has expired'):
                source.fetch_preview_page('https://example.org/saver', 'https://example.org/full', 1)
        source._fetch_binary.assert_called_once()

    def test_non_certificate_network_failures_keep_retries(self):
        for error in (TimeoutError('timed out'), ssl.SSLEOFError(8, 'unexpected EOF'),
                      urllib.error.URLError('certificate has expired')):
            with self.subTest(error=type(error).__name__), \
                 patch('urllib.request.urlopen', side_effect=error) as opened, \
                 patch('calibre_plugins.manganana.providers.mangadex_source.time.sleep') as sleep:
                with self.assertRaisesRegex(RuntimeError, 'after 3 attempt'):
                    MangaDexSource._default_api_json(URL)
                self.assertEqual(opened.call_count, 3)
                self.assertEqual(sleep.call_count, 2)

    def test_rate_limit_and_success_keep_existing_behavior(self):
        response = io.BytesIO(b'{"data": []}')
        rate_limit = urllib.error.HTTPError(URL, 429, 'Rate limited', {'Retry-After': '4'}, io.BytesIO())
        with patch('urllib.request.urlopen', side_effect=[rate_limit, response]) as opened, \
             patch('calibre_plugins.manganana.providers.mangadex_source.time.sleep') as sleep:
            self.assertEqual(MangaDexSource._default_api_json(URL), {'data': []})
        self.assertEqual(opened.call_count, 2)
        sleep.assert_called_once_with(4)

    def test_permanent_http_failure_does_not_become_certificate_error(self):
        with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError(URL, 403, 'Forbidden', {}, None)) as opened, \
             patch('calibre_plugins.manganana.providers.mangadex_source.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'HTTP Error 403'):
                MangaDexSource._default_api_json(URL)
        self.assertEqual(opened.call_count, 1)
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
