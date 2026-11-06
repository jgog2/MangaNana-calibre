"""Local, opt-in-by-failure diagnostics with no network reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import traceback
from collections import OrderedDict
import hashlib
import threading
import time

from calibre_plugins.manganana.app.settings.google_books_credentials import redact_google_books_url


_SECRET_VALUE = re.compile(
    r'(?i)(password|passwd|token|api[_-]?key|cookie|authorization)\s*([=:])\s*([^\s,;]+)'
)
_BEARER_VALUE = re.compile(r'(?i)bearer\s+[A-Za-z0-9._~+/-]+=*')
_LOCK = threading.RLock()
_RECENT = OrderedDict()
_MAX_REPORT_BYTES = 64 * 1024
_MAX_LOG_BYTES = 4 * 1024 * 1024
_MAX_FINGERPRINTS = 128


def _append_bounded(path, text):
    data = text.encode('utf-8', errors='replace')[:_MAX_REPORT_BYTES]
    if path.exists() and path.stat().st_size + len(data) > _MAX_LOG_BYTES:
        path.replace(path.with_name('MangaNana-diagnostics.previous.log'))
    with path.open('ab') as report:
        report.write(data)


def flush_diagnostic_summaries(directory):
    """Persist final burst counts on dialog close without retaining UI state."""
    try:
        _flush_diagnostic_summaries(directory)
    except OSError:
        # Diagnostics being unwritable must not prevent native UI cleanup.
        return None


def _flush_diagnostic_summaries(directory):
    path = Path(directory) / 'MangaNana-diagnostics.log'
    with _LOCK:
        for (filename, fingerprint), entry in _RECENT.items():
            if filename == str(path.absolute()) and entry['count'] > entry['written_count']:
                _append_bounded(path, '\n'.join(('MangaNana repeated diagnostic',
                    f'Fingerprint: {fingerprint}', f'First (UTC): {entry["first"]}',
                    f'Last (UTC): {entry["last"]}', f'Occurrences: {entry["count"]}', '',)))
                entry['written_count'] = entry['count']


def redact_sensitive_text(value):
    """Remove common credential forms before persisting a diagnostic report."""
    text = redact_google_books_url(value)
    text = _SECRET_VALUE.sub(lambda match: f'{match.group(1)}{match.group(2)}[redacted]', text)
    return _BEARER_VALUE.sub('Bearer [redacted]', text)


def write_diagnostic_report(directory, *, version, build_id, mode, provider,
                            operation, exc_type=None, exc=None, tb=None):
    """Write a bounded sanitized record; summarize identical exception bursts.

    The caller owns choosing a Calibre-config or temporary directory.  This
    module intentionally never sends diagnostic data anywhere.
    """
    try:
        error_type = getattr(exc_type, '__name__', None) or type(exc).__name__
        trace = redact_sensitive_text(''.join(traceback.format_exception(exc_type or type(exc), exc, tb)))
        path = Path(directory) / 'MangaNana-diagnostics.log'
        now = datetime.now(timezone.utc).isoformat()
        # Include context, so a different provider/workflow remains a distinct
        # failure. Never retain exception objects or traceback frame graphs.
        signature = '\n'.join(map(str,(error_type,redact_sensitive_text(exc),trace,mode,provider,operation)))
        key = (str(path.absolute()), hashlib.sha256(signature.encode('utf-8')).hexdigest())
        with _LOCK:
            previous = _RECENT.get(key)
            if previous is not None:
                previous['count'] += 1
                previous['last'] = now
                _RECENT.move_to_end(key)
                # First repeat, powers of ten, and at most one periodic summary
                # per ten seconds. Full first traceback stays in the log.
                count = previous['count']
                milestone = count == 2 or (count >= 10 and str(count)[0] == '1' and set(str(count)[1:]) == {'0'})
                if milestone or time.monotonic() - previous['written_at'] >= 10:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _append_bounded(path, '\n'.join((
                        'MangaNana repeated diagnostic', f'Fingerprint: {key[1]}',
                        f'First (UTC): {previous["first"]}', f'Last (UTC): {now}',
                        f'Occurrences: {count}', f'Exception: {error_type}: {redact_sensitive_text(exc)}', '',
                    )))
                    previous['written_at'] = time.monotonic()
                    previous['written_count'] = count
                # Do not append an Activity Log notification for every repeat.
                return None
            _RECENT[key] = {'count':1,'first':now,'last':now,'written_at':time.monotonic(),'written_count':1}
            while len(_RECENT) > _MAX_FINGERPRINTS:
                _RECENT.popitem(last=False)
        lines = (
            'MangaNana diagnostic report',
            f'Time (UTC): {now}',
            f'Fingerprint: {key[1]}',
            f'Version: {redact_sensitive_text(version)}',
            f'Build: {redact_sensitive_text(build_id)}',
            f'Workflow mode: {redact_sensitive_text(mode or "unknown")}',
            f'Provider: {redact_sensitive_text(provider or "unknown")}',
            f'Operation: {redact_sensitive_text(operation or "unknown")}',
            f'Exception: {redact_sensitive_text(error_type)}: {redact_sensitive_text(exc)}',
            'Traceback:',
            trace,
            '',
        )
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            _append_bounded(path, '\n'.join(lines))
        return path
    except Exception:
        return None
