"""Local, opt-in-by-failure diagnostics with no network reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import traceback


_SECRET_VALUE = re.compile(
    r'(?i)(password|passwd|token|api[_-]?key|cookie|authorization)\s*([=:])\s*([^\s,;]+)'
)
_BEARER_VALUE = re.compile(r'(?i)bearer\s+[A-Za-z0-9._~+/-]+=*')


def redact_sensitive_text(value):
    """Remove common credential forms before persisting a diagnostic report."""
    text = str(value or '')
    text = _SECRET_VALUE.sub(lambda match: f'{match.group(1)}{match.group(2)}[redacted]', text)
    return _BEARER_VALUE.sub('Bearer [redacted]', text)


def write_diagnostic_report(directory, *, version, build_id, mode, provider,
                            operation, exc_type=None, exc=None, tb=None):
    """Append a sanitized local exception record and return its path.

    The caller owns choosing a Calibre-config or temporary directory.  This
    module intentionally never sends diagnostic data anywhere.
    """
    try:
        error_type = getattr(exc_type, '__name__', None) or type(exc).__name__
        trace = ''.join(traceback.format_exception(exc_type or type(exc), exc, tb))
        lines = (
            'MangaNana diagnostic report',
            f'Time (UTC): {datetime.now(timezone.utc).isoformat()}',
            f'Version: {redact_sensitive_text(version)}',
            f'Build: {redact_sensitive_text(build_id)}',
            f'Workflow mode: {redact_sensitive_text(mode or "unknown")}',
            f'Provider: {redact_sensitive_text(provider or "unknown")}',
            f'Operation: {redact_sensitive_text(operation or "unknown")}',
            f'Exception: {redact_sensitive_text(error_type)}: {redact_sensitive_text(exc)}',
            'Traceback:',
            redact_sensitive_text(trace),
            '',
        )
        path = Path(directory) / 'MangaNana-diagnostics.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as report:
            report.write('\n'.join(lines))
        return path
    except Exception:
        return None
