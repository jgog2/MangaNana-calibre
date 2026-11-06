"""Deterministic credential lifecycle and privacy tests; all keys are synthetic."""

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

from calibre_plugins.manganana.app.settings import google_books_credentials as credentials
from calibre_plugins.manganana.metadata.references.google_books_reference import GoogleBooksArtworkResolver
from calibre_plugins.manganana.diagnostics.diagnostics import redact_sensitive_text, write_diagnostic_report
from tests.test_google_books_reference import CONTEXT


class Response(io.BytesIO):
    status = 200


def accepted(request, **kwargs):
    return Response(b'{"kind":"books#volumes","totalItems":0}')


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = self.folder.name
        self.key = 'synthetic-test-key-123'

    def save(self, key=None):
        credentials.save_api_key(key or self.key, self.root, opener=accepted)

    def test_save_replace_remove_updates_existing_resolver_without_environment_resurrection(self):
        resolver = GoogleBooksArtworkResolver(config_directory=self.root,
            environ={'MANGANANA_GOOGLE_BOOKS_API_KEY': 'synthetic-environment-key'})
        self.assertFalse(resolver.enabled)
        with patch('calibre_plugins.manganana.metadata.references.google_books_reference.open_google_books', side_effect=AssertionError('network forbidden')):
            self.assertEqual('unavailable_no_api_key', resolver.resolve(CONTEXT, ('7',))['status'])
        self.save()
        self.assertTrue(resolver.enabled)
        self.assertEqual(self.key, resolver.api_key)
        self.assertNotIn(self.key, repr(vars(resolver)))
        self.save('synthetic-replacement-key')
        self.assertEqual('synthetic-replacement-key', resolver.api_key)
        credentials.clear_api_key(self.root)
        self.assertFalse(credentials.credential_path(self.root).exists())
        self.assertFalse(resolver.enabled)
        self.assertEqual('', resolver.api_key)
        self.assertFalse(credentials.has_api_key(self.root))
        with patch('calibre_plugins.manganana.metadata.references.google_books_reference.open_google_books', side_effect=AssertionError('network forbidden')):
            self.assertEqual('unavailable_no_api_key', resolver.resolve(CONTEXT, ('7',))['status'])

    def test_private_record_is_verified_and_outside_preferences_and_package(self):
        self.save()
        path = credentials.credential_path(self.root)
        record = json.loads(path.read_text(encoding='utf-8'))
        self.assertTrue(record['verified'])
        self.assertEqual(1, record['version'])
        self.assertEqual(self.key, record['key'])
        root = Path(__file__).resolve().parents[1]
        self.assertNotIn(root, path.resolve().parents)
        self.assertNotIn(self.key, (root / 'app/settings/config.py').read_text(encoding='utf-8'))
        from tools.build_plugin import files_to_package
        self.assertFalse(any(source.resolve() == path.resolve() or 'private/' in archive
                             for source, archive in files_to_package(root)))

    def test_requests_are_keyed_google_only_and_existing_objects_use_replacement(self):
        self.save()
        resolver = GoogleBooksArtworkResolver(config_directory=self.root)
        observed = []
        def request(req, **kwargs):
            parsed = urllib.parse.urlsplit(req.full_url)
            self.assertEqual('www.googleapis.com', parsed.netloc)
            self.assertTrue(parsed.path.startswith('/books/v1/volumes'))
            observed.append(urllib.parse.parse_qs(parsed.query)['key'][0])
            return Response(b'{}')
        with patch('calibre_plugins.manganana.metadata.references.google_books_reference.open_google_books', side_effect=request):
            resolver._http_json({'q': 'work'})
            self.save('synthetic-new-key')
            resolver._http_detail('volume-id')
        self.assertEqual([self.key, 'synthetic-new-key'], observed)
        with self.assertRaises(credentials.CredentialError):
            credentials.open_google_books(urllib.request.Request('https://example.test/books/v1/volumes'))

    def test_redirects_are_not_followed(self):
        handler = credentials._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, '', {}, 'https://example.test'))

    def test_inflight_response_is_discarded_after_removal(self):
        from concurrent.futures import CancelledError
        self.save()
        resolver = GoogleBooksArtworkResolver(config_directory=self.root)
        def request(*args, **kwargs):
            credentials.clear_api_key(self.root)
            return Response(b'{"items":[]}')
        with patch('calibre_plugins.manganana.metadata.references.google_books_reference.open_google_books', side_effect=request):
            with self.assertRaises(CancelledError): resolver.resolve(CONTEXT, ('7',))
        self.assertEqual('unavailable_no_api_key', resolver.resolve(CONTEXT, ('7',))['status'])

    def test_invalid_disabled_restricted_quota_and_network_failures_never_save(self):
        cases = [
            (400, {'message': 'API key not valid. ' + self.key}, 'Invalid Google Books API key'),
            (403, {'details': [{'reason': 'SERVICE_DISABLED'}]}, 'may not be enabled'),
            (403, {'errors': [{'reason': 'accessNotConfigured'}]}, 'may not be enabled'),
            (403, {'message': 'IP restriction'}, 'Check the key restrictions'),
            (429, {}, 'quota'),
            (503, {}, 'could not be reached'),
        ]
        for code, error, expected in cases:
            def fail(req, **kwargs):
                raise urllib.error.HTTPError(req.full_url, code, 'request failed ' + self.key,
                    {}, io.BytesIO(json.dumps({'error': error}).encode()))
            with self.subTest(code=code), self.assertRaises(credentials.CredentialError) as raised:
                credentials.save_api_key(self.key, self.root, opener=fail)
            self.assertIn(expected, str(raised.exception))
            self.assertNotIn(self.key, str(raised.exception))
            self.assertFalse(credentials.has_api_key(self.root))
        def offline(req, **kwargs): raise OSError('network failed ' + self.key)
        with self.assertRaisesRegex(credentials.CredentialError, 'could not be reached'):
            credentials.save_api_key(self.key, self.root, opener=offline)

    def test_empty_and_unexpected_success_responses_are_not_saved(self):
        with self.assertRaisesRegex(credentials.CredentialError, 'Enter a Google Books'):
            credentials.save_api_key('', self.root, opener=accepted)
        with self.assertRaisesRegex(credentials.CredentialError, 'unexpected response'):
            credentials.save_api_key(self.key, self.root, opener=lambda *a, **kw: Response(b'{}'))
        self.assertFalse(credentials.has_api_key(self.root))

    def test_failed_replace_and_failed_disk_write_keep_previous_key(self):
        self.save()
        with patch.object(credentials, 'validate_api_key', side_effect=credentials.CredentialError('Invalid key')):
            with self.assertRaises(credentials.CredentialError): self.save('synthetic-new')
        self.assertEqual(self.key, credentials.load_google_books_api_key(self.root).api_key)
        with patch.object(credentials.os, 'replace', side_effect=OSError('disk failure')):
            with self.assertRaises(credentials.CredentialError): self.save('synthetic-new')
        self.assertEqual(self.key, credentials.load_google_books_api_key(self.root).api_key)
        self.assertEqual([credentials.credential_path(self.root)], list(credentials.credential_path(self.root).parent.iterdir()))

    def test_unverified_legacy_file_and_environment_are_ignored(self):
        path = credentials.credential_path(self.root)
        path.parent.mkdir(parents=True)
        path.with_suffix('.txt').write_text(self.key)
        with patch.dict(os.environ, {'MANGANANA_GOOGLE_BOOKS_API_KEY': self.key}):
            self.assertFalse(credentials.has_api_key(self.root))
            path.write_text(self.key)
            self.assertFalse(credentials.has_api_key(self.root))
            path.write_text(json.dumps({'key': self.key, 'verified': False, 'version': 1}))
            self.assertFalse(credentials.has_api_key(self.root))

    def test_removal_disables_cached_google_lookup_without_disabling_other_references(self):
        from calibre_plugins.manganana.metadata.reference_integration import ReferenceMetadataService
        from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
        from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache
        class OtherReference:
            def __init__(self): self.calls = 0
            def match_publication(self, evidence):
                self.calls += 1
                return PublicationMatch('fixture', '', '', 'no_match', 'fixture')
        wiki = OtherReference(); book = OtherReference()
        cache = SearchMetadataCache(Path(self.root) / 'references.sqlite')
        self.addCleanup(cache.close)
        cache.put_reference_catalog('google:google-books-artwork-v2:work:en:standard', {
            'cache_contract': 'google-books-artwork-v2',
            'detail_cache_contract': 'google-books-volume-detail-v1',
            'configuration_status': 'configured_verified', 'target_volumes': [], 'status': 'valid',
            'covers': [{'url': 'https://images.test/cached.jpg'}],
        })
        self.save()
        resolver = GoogleBooksArtworkResolver(config_directory=self.root)
        service = ReferenceMetadataService(cache, wiki, book, resolver)
        credentials.clear_api_key(self.root)
        with patch('calibre_plugins.manganana.metadata.references.google_books_reference.open_google_books', side_effect=AssertionError('network forbidden')):
            result = service.lookup('work', {'title': 'Work', 'creators': ('Creator',),
                'requested_language': 'en', 'edition_profile': 'standard', 'reference_key': 'work'})
        self.assertGreater(wiki.calls, 0); self.assertGreater(book.calls, 0)
        self.assertEqual('unavailable_no_api_key', result['google_books']['status'])
        self.assertEqual([], result['google_books']['covers'])

    def test_request_error_and_response_cache_diagnostics_redact_credentials(self):
        self.save()
        resolver = GoogleBooksArtworkResolver(config_directory=self.root)
        url = 'https://www.googleapis.com/books/v1/volumes?key=' + self.key + '&q=test'
        with patch('calibre_plugins.manganana.metadata.references.google_books_reference.open_google_books', side_effect=OSError(url)):
            with self.assertRaises(RuntimeError) as raised: resolver._http_json({'q': 'work'})
        self.assertNotIn(self.key, str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)
        self.assertNotIn(self.key, redact_sensitive_text(url))
        path = write_diagnostic_report(self.root, version='test', build_id='test', mode='test',
                                      provider='google_books', operation='test', exc=raised.exception)
        self.assertNotIn(self.key, path.read_text(encoding='utf-8'))
        with patch('calibre_plugins.manganana.metadata.references.google_books_reference.open_google_books', return_value=Response(json.dumps({'image': url}).encode())):
            payload = resolver._http_json({'q': 'work'})
        from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache
        cache = SearchMetadataCache(Path(self.root) / 'cache.sqlite')
        cache.put_reference_catalog('test-google', payload)
        self.assertNotIn(self.key, repr(cache.get_reference_catalog('test-google').value))
        cache.close()
        self.assertNotIn(self.key.encode(), (Path(self.root) / 'cache.sqlite').read_bytes())


if __name__ == '__main__':
    unittest.main()
