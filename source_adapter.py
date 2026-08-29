"""Minimal synchronous source contract for MangaNana providers."""

from abc import ABC, abstractmethod


class SourceAdapter(ABC):
    """Calibre-independent interface implemented by a manga source."""

    source_id = ''
    key = ''
    display_name = ''
    domains = ()
    enabled_by_default = True
    capabilities = frozenset()

    def can_handle_ref(self, value):
        """Return whether this adapter recognizes a direct manga reference."""
        return self.parse_manga_ref(value) is not None

    @abstractmethod
    def parse_manga_ref(self, value):
        """Return the provider manga ID represented by value, or None."""

    @abstractmethod
    def get_manga(self, value, preferred='en'):
        """Return normalized metadata for a provider manga reference."""

    @abstractmethod
    def search(self, query, offset=0, limit=12, include_adult=False,
               preferred='en', availability_cache=None):
        """Return one normalized page of searchable manga results."""

    @abstractmethod
    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        """Return normalized volume and standalone-chapter discovery data."""

    @abstractmethod
    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        """Return normalized readable chapter records."""

    @abstractmethod
    def get_volume_covers(self, value):
        """Return normalized volume-to-cover URL mappings."""

    @abstractmethod
    def get_page_manifest(self, chapter_id, retry_callback=None):
        """Return aligned full-quality and reduced-quality page URLs."""

    @abstractmethod
    def fetch_binary(self, url, **kwargs):
        """Fetch source-hosted binary content synchronously."""

    @abstractmethod
    def fetch_preview_page(self, saver_url, full_url, page_number,
                           log=None, check_cancel=None):
        """Fetch one preview page using provider fallback behavior."""
