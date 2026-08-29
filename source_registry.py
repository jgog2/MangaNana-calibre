"""Small Calibre- and Qt-independent catalog of manga source adapters."""

from dataclasses import dataclass

try:
    from .source_adapter import SourceAdapter
except ImportError:
    from source_adapter import SourceAdapter


@dataclass(frozen=True)
class SourceMatch:
    """A registered source and the provider reference parsed from user input."""

    source: SourceAdapter
    reference: str


class SourceRegistry:
    """Ordered registry used to locate synchronous source adapters."""

    def __init__(self, sources=()):
        self._sources = {}
        for source in sources:
            self.register(source)

    def register(self, source):
        if not isinstance(source, SourceAdapter):
            raise TypeError('Registered sources must implement SourceAdapter.')
        source_id = str(getattr(source, 'source_id', '') or '').strip()
        if not source_id:
            raise ValueError('Registered sources must define a stable source_id.')
        if source_id in self._sources:
            raise ValueError(f'Duplicate source id: {source_id}')
        self._sources[source_id] = source
        return source

    def get(self, source_id):
        """Return a registered adapter by stable id, or None."""
        return self._sources.get(source_id)

    def all(self):
        """Return registered adapters in deterministic registration order."""
        return tuple(self._sources.values())

    def identify(self, value):
        """Return the first registered source that recognizes a direct reference."""
        for source in self._sources.values():
            reference = source.parse_manga_ref(value)
            if reference is not None:
                return SourceMatch(source=source, reference=reference)
        return None
