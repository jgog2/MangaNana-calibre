"""Bound response buffering and check worker cancellation between socket reads."""
import time

TEXT_LIMIT = 16 * 1024 * 1024
IMAGE_LIMIT = 64 * 1024 * 1024


class ResponseLimitExceeded(RuntimeError):
    """An explicit failed request, never a truncated successful inventory/image."""


def read_response(response, limit, check_cancel=None):
    check = check_cancel or (lambda: None)
    check()
    headers = getattr(response, 'headers', {})
    try:
        expected = int(headers.get('Content-Length', ''))
    except (ValueError, TypeError):
        expected = None
    if expected is not None and expected > limit:
        raise ResponseLimitExceeded(f'Response exceeds the {limit // (1024*1024)} MiB safety limit.')
    result = bytearray()
    # HTTPResponse.read1 returns currently available bytes, allowing cancellation
    # during a trickling response. Socket connection/idle timeouts remain active.
    read = getattr(response, 'read1', None) or response.read
    while True:
        check()
        chunk = read(min(64 * 1024, limit - len(result) + 1))
        check()
        if not chunk:
            break
        result.extend(chunk)
        if len(result) > limit:
            raise ResponseLimitExceeded(f'Response exceeds the {limit // (1024*1024)} MiB safety limit.')
    if expected is not None and len(result) != expected:
        raise OSError(f'Incomplete response: expected {expected} bytes, received {len(result)}.')
    return bytes(result)


def cooperative_wait(seconds, check_cancel=None):
    if check_cancel is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + max(0, seconds)
    while True:
        check_cancel()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(.1, remaining))
