"""Explicit semantic context for asynchronous manga metadata loads."""

from dataclasses import dataclass


VALID_DISCOVERY_KINDS = frozenset({'search','direct'})


@dataclass(frozen=True)
class MangaLoadContext:
    discovery_kind: str
    discovery_value: str
    requested_language: str = ''

    def __post_init__(self):
        if self.discovery_kind not in VALID_DISCOVERY_KINDS:
            raise ValueError(f'Unsupported manga discovery kind: {self.discovery_kind!r}')


def take_manga_load_context(contexts, request_id):
    """Consume the required context for one current worker/cache callback."""
    context=contexts.pop(request_id,None)
    if not isinstance(context,MangaLoadContext):
        raise RuntimeError(f'Missing manga load context for request {request_id}.')
    return context
