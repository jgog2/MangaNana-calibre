"""Private, verified Google Books credentials. Never uses normal preferences."""
from calibre_plugins.manganana.common.plugin_paths import plugin_root

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request


PRIVATE_KEY_RELATIVE_PATH = ('plugins', 'manganana', 'private', 'google_books_api_key.json')
API_URL = 'https://www.googleapis.com/books/v1/volumes'
CREDENTIALS_URL = 'https://console.cloud.google.com/apis/credentials'
GUIDE_URL = 'https://developers.google.com/books/docs/v1/getting_started'
_generations = {}
_generation_lock = threading.Lock()


class CredentialError(RuntimeError):
    """Only fixed, non-secret messages cross the credential boundary."""


class GoogleBooksKeyConfiguration:
    __slots__ = ('api_key', 'source', 'status')

    def __init__(self, api_key='', source='', status='missing'):
        self.api_key = str(api_key or '')
        self.source = source
        self.status = status

    def __repr__(self):
        return f'GoogleBooksKeyConfiguration(source={self.source!r}, status={self.status!r}, api_key=<redacted>)'


def credential_path(config_directory=None):
    if config_directory is None:
        try:
            from calibre.constants import config_dir
            config_directory = config_dir
        except ImportError:
            config_directory = os.environ.get('CALIBRE_CONFIG_DIRECTORY')
    return Path(config_directory).joinpath(*PRIVATE_KEY_RELATIVE_PATH) if config_directory else None


def load_google_books_api_key(config_directory=None, environ=None, read_text=None):
    """Legacy environment arguments are ignored; only verified records activate."""
    path = credential_path(config_directory)
    if path is None:
        return GoogleBooksKeyConfiguration()
    try:
        raw = (read_text or (lambda p: p.read_text(encoding='utf-8')))(path)
        record = json.loads(raw)
        if (isinstance(record, dict) and record.get('version') == 1 and
                record.get('verified') is True and isinstance(record.get('key'), str) and
                record['key'].strip()):
            return GoogleBooksKeyConfiguration(record['key'].strip(), 'local_private_file', 'configured_verified')
        return GoogleBooksKeyConfiguration(status='unverified')
    except FileNotFoundError:
        return GoogleBooksKeyConfiguration()
    except Exception:
        return GoogleBooksKeyConfiguration(status='file_unreadable')


def has_api_key(config_directory=None):
    return bool(load_google_books_api_key(config_directory).api_key)


def credential_generation(config_directory=None, advance=False):
    """Non-secret change counter used to discard responses from an old credential."""
    path = credential_path(config_directory)
    identity = str(path.resolve()) if path is not None else ''
    with _generation_lock:
        value = _generations.get(identity, 0) + int(advance)
        if advance:
            _generations[identity] = value
        return value


def redact_google_books_url(value, api_key=''):
    text = re.sub(r'(?i)([?&](?:k|%6b)(?:e|%65)(?:y|%79)=)[^&\s\"\'<>]*',
                  r'\1<redacted>', str(value or ''))
    if api_key:
        for secret in (str(api_key), urllib.parse.quote(str(api_key), safe=''),
                       urllib.parse.quote_plus(str(api_key))):
            text = text.replace(secret, '<redacted>')
    return text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A credential-bearing request must never follow a redirect to another service.
        return None


def open_google_books(request, timeout=12):
    parsed = urllib.parse.urlsplit(request.full_url)
    if (parsed.scheme != 'https' or parsed.netloc != 'www.googleapis.com' or
            not parsed.path.startswith('/books/v1/')):
        raise CredentialError('Google Books request destination is invalid.')
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def sanitize_response(value, key):
    if isinstance(value, dict):
        return {name: sanitize_response(item, key) for name, item in value.items()}
    if isinstance(value, list):
        return [sanitize_response(item, key) for item in value]
    return redact_google_books_url(value, key) if isinstance(value, str) else value


def validation_error(code, body):
    # Inspect Google's evidence, but never echo its message or request URL.
    try:
        error = json.loads(body).get('error') or {}
        evidence = json.dumps(error).casefold()
    except Exception:
        evidence = ''
    if 'api_key_invalid' in evidence or 'api key not valid' in evidence or 'keyinvalid' in evidence:
        return 'Invalid Google Books API key. The key was not saved.'
    if ('service_disabled' in evidence or 'accessnotconfigured' in evidence or
            ('books' in evidence and ('has not been used' in evidence or 'is disabled' in evidence))):
        return ('This API key exists, but the Google Books API may not be enabled for its '
                'Google Cloud project. The key was not saved.')
    if code == 429 or 'quota' in evidence or 'ratelimit' in evidence:
        return 'Google Books quota is currently exhausted. The key was not confirmed or saved.'
    if code in (401, 403):
        return ('Google Books rejected this request. Check the key restrictions and Books API '
                'access in Google Cloud. The key was not confirmed or saved.')
    return 'Google Books could not be reached. The API key has not been confirmed or saved.'


def validate_api_key(key, opener=None):
    key = str(key or '').strip()
    if not key:
        raise CredentialError('Enter a Google Books API key.')
    request = urllib.request.Request(API_URL + '?' + urllib.parse.urlencode(
        {'q': 'isbn:9781421536255', 'maxResults': 1, 'key': key}),
        headers={'Accept': 'application/json', 'User-Agent': 'MangaNana reference/0.11'})
    try:
        with (opener or open_google_books)(request, timeout=12) as response:
            if response.status != 200:
                raise CredentialError(validation_error(response.status, response.read()))
            data = json.loads(response.read().decode('utf-8'))
        if not isinstance(data, dict) or data.get('kind') != 'books#volumes' or not isinstance(data.get('totalItems'), int):
            raise CredentialError('Google Books returned an unexpected response. The key was not confirmed or saved.')
    except urllib.error.HTTPError as exc:
        try:
            message = validation_error(exc.code, exc.read(65536))
        except Exception:
            message = validation_error(exc.code, b'')
        raise CredentialError(message) from None
    except CredentialError:
        raise
    except Exception:
        raise CredentialError('Google Books could not be reached. The API key has not been confirmed or saved.') from None


def _restrict_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'nt':
        flags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                capture_output=True, text=True, check=True, creationflags=flags)
        sid = re.search(r'S-1-\d+(?:-\d+)+', result.stdout)
        if not sid:
            raise OSError('Cannot determine local owner')
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                        '*' + sid.group(0) + ':(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'],
                       capture_output=True, check=True, creationflags=flags)
    else:
        path.chmod(0o700)


def save_api_key(key, config_directory=None, opener=None, cancelled=lambda: False):
    """Validate first; atomically replace the private record only on success."""
    key = str(key or '').strip()
    validate_api_key(key, opener)
    if cancelled():
        raise InterruptedError('Google Books setup cancelled')
    path = credential_path(config_directory)
    if path is None:
        raise CredentialError('Calibre private configuration is unavailable. The key was not saved.')
    if plugin_root() in path.resolve().parents:
        raise CredentialError('Private credentials must be stored outside the plugin directory. The key was not saved.')
    temporary = None
    try:
        _restrict_directory(path.parent)
        descriptor, temporary = tempfile.mkstemp(prefix='.google-books-', dir=path.parent)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump({'version': 1, 'verified': True, 'key': key}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if cancelled():
            raise InterruptedError('Google Books setup cancelled')
        os.replace(temporary, path)
        temporary = None
        credential_generation(config_directory, advance=True)
    except InterruptedError:
        raise
    except Exception:
        raise CredentialError('The verified Google Books key could not be saved privately. Previous settings were kept.') from None
    finally:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def clear_api_key(config_directory=None):
    path = credential_path(config_directory)
    try:
        if path is not None:
            path.unlink(missing_ok=True)
        credential_generation(config_directory, advance=True)
    except Exception:
        raise CredentialError('The private Google Books key could not be removed. Please check file permissions.') from None
