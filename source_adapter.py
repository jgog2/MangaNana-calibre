"""Minimal synchronous source contract for MangaNana providers."""

from abc import ABC, abstractmethod


class SourceAdapter(ABC):
    """Calibre-independent interface implemented by a manga source."""

    key = ''
    display_name = ''

    @abstractmethod
    def parse_manga_ref(self, value):
        """Return the provider manga ID represented by value, or None."""

    @abstractmethod
    def get_manga(self, value, preferred='en'):
        """Return normalized metadata for a provider manga reference."""
