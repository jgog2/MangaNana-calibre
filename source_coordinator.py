"""Provider-neutral coordination for MangaNana source adapters."""

from dataclasses import dataclass, field


class SourceSearchError(RuntimeError):
    """Raised when every enabled provider fails a coordinated search."""


def count_chapter_pages(source, chapters):
    """Return a selected chapter total without fetching any image bytes.

    Providers may report ``pages=None`` when discovery cannot cheaply know the
    count. In that case, use only the provider's lightweight page manifest. If
    any selected chapter remains indeterminate, the combined total is unknown.
    """
    total = 0
    for chapter in chapters or ():
        pages = chapter.get('pages')
        if pages is None:
            try:
                manifest = source.get_page_manifest(chapter.get('id')) or {}
                urls = manifest.get('full')
                if urls is None:
                    return None
                pages = len(urls)
            except Exception:
                return None
        try:
            total += max(0, int(pages))
        except (TypeError, ValueError):
            return None
    return total


def format_page_count(pages):
    """Format a Review page count without turning unknown into zero."""
    return 'Unknown' if pages is None else str(int(pages))


@dataclass
class ProviderSearch:
    source_id: str
    display_name: str
    status: str = 'pending'
    error: str = ''
    rows: list = field(default_factory=list)


class SourceCoordinator:
    """Keep ordered provider search state and normalized source attribution."""

    def __init__(self, registry):
        self.registry = registry
        self._states = {}
        self.reset()

    @property
    def sources(self):
        return tuple(s for s in self.registry.all() if s.enabled_by_default)

    def reset(self):
        self._states = {
            source.source_id: ProviderSearch(source.source_id, source.display_name)
            for source in self.sources
        }
        return self.snapshot()

    def mark_running(self, source_id):
        self._states[source_id].status = 'running'

    def complete(self, source_id, data):
        state = self._states[source_id]
        source = self.registry.get(source_id)
        rows = []
        for original in (data or {}).get('rows') or []:
            row = dict(original)
            row['source_id'] = source.source_id
            row['source_name'] = source.display_name
            rows.append(row)
        state.status = 'complete'
        state.error = ''
        state.rows = rows
        result = dict(data or {})
        result['rows'] = rows
        result['source_id'] = source.source_id
        result['source_name'] = source.display_name
        return result

    def fail(self, source_id, error):
        state = self._states[source_id]
        state.status = 'failed'
        state.error = str(error or 'Unknown provider error')
        state.rows = []

    def identify(self, value):
        return self.registry.identify(value)

    def source_for_result(self, result):
        return self.registry.get((result or {}).get('source_id'))

    def search(self, query, **kwargs):
        """Synchronous aggregate search, primarily useful outside Qt and in tests."""
        self.reset()
        pages = []
        for source in self.sources:
            self.mark_running(source.source_id)
            try:
                pages.append(self.complete(source.source_id, source.search(query, **kwargs)))
            except Exception as exc:
                self.fail(source.source_id, exc)
        snapshot = self.snapshot()
        if snapshot['all_failed']:
            raise SourceSearchError(snapshot['combined_error'])
        snapshot['pages'] = pages
        snapshot['rows'] = [row for page in pages for row in page.get('rows') or []]
        return snapshot

    def snapshot(self):
        ordered = [self._states[source.source_id] for source in self.sources]
        finished = sum(s.status in ('complete', 'failed') for s in ordered)
        failures = [s for s in ordered if s.status == 'failed']
        combined = '; '.join(f'{s.display_name}: {s.error}' for s in failures)
        return {
            'providers': tuple({
                'source_id': s.source_id, 'display_name': s.display_name,
                'status': s.status, 'error': s.error,
            } for s in ordered),
            'completed': finished,
            'total': len(ordered),
            'done': finished == len(ordered),
            'all_failed': bool(ordered) and len(failures) == len(ordered),
            'combined_error': combined,
        }
