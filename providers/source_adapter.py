"""Minimal synchronous source contract for MangaNana providers."""

from abc import ABC, abstractmethod
from contextvars import ContextVar
from functools import wraps
from contextlib import nullcontext


_volume_inventory_capture = ContextVar('volume_inventory_capture', default=None)
_not_captured = object()


def acquire_volume_inventory(source, value, language):
    """Return the provider plan and its successful rows for this operation only.

    Providers opt in at their chapter method. An unsupported adapter, or a feed
    failure caught by the plan, retains the existing independent enumeration.
    Plan diagnostics remain authoritative and are never reconstructed from rows.
    """
    capture = {'source': source, 'value': value, 'language': language,
               'rows': _not_captured}
    token = _volume_inventory_capture.set(capture)
    try:
        plan = source.get_download_plan(value, language)
    finally:
        _volume_inventory_capture.reset(token)
    chapters = capture['rows']
    if chapters is _not_captured:
        chapters = source.get_chapters(value, language)
    return plan, chapters


class SourceAdapter(ABC):
    """Calibre-independent interface implemented by a manga source."""

    source_id = ''
    key = ''
    display_name = ''
    domains = ()
    enabled_by_default = True
    capabilities = frozenset()
    # A non-empty value is an adapter-owned language contract for providers
    # whose entire readable catalogue is published in fixed languages.
    content_languages = ()

    def operation_context(self):
        """Optional worker-local reuse; default adapters keep existing behavior."""
        return nullcontext()

    @staticmethod
    def capture_chapter_inventory(method):
        """Expose only a fully returned, matching enumeration to a local plan."""
        @wraps(method)
        def captured(self, value, language, start_volume=None, end_volume=None):
            rows = method(self, value, language, start_volume, end_volume)
            capture = _volume_inventory_capture.get()
            if (capture is not None and capture['source'] is self
                    and capture['value'] == value and capture['language'] == language
                    and start_volume is None and end_volume is None):
                capture['rows'] = rows
            return rows
        return captured

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
