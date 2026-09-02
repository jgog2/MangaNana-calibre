"""Calibre-independent contracts for the reference-metadata prototype."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PublicationMatch:
    source: str
    publication_id: str
    title: str
    confidence: str
    reason: str
    edition: str = 'unknown'
    url: str = ''
    edition_id: str = ''
    volume_id: str = ''
    volume_number: str = ''


@dataclass(frozen=True)
class PublicationChapter:
    number: str
    title: str = ''
    volume: str = ''
    kind: str = 'chapter'
    source: str = ''
    source_page: str = ''
    parser_pattern: str = ''
    confidence: str = 'unknown'
    source_page_id: str = ''
    source_revision_id: str = ''
    source_pages: tuple = ()
    source_record_id: str = ''


@dataclass(frozen=True)
class PublicationVolume:
    number: str
    title: str = ''
    source: str = ''
    volume_id: str = ''
    url: str = ''
    edition_id: str = ''
    confidence: str = 'unknown'


@dataclass(frozen=True)
class PublicationArtwork:
    url: str
    artwork_type: str
    volume: str = ''
    source: str = ''
    confidence: str = 'unknown'
    publication_id: str = ''
    edition_id: str = ''
    volume_id: str = ''


@dataclass(frozen=True)
class PublicationRecord:
    match: PublicationMatch
    chapters: tuple = ()
    volumes: tuple = ()
    artwork: tuple = ()
    description: str = ''
    tags: tuple = ()
    creators: tuple = ()
    request_count: int = 0
    notes: tuple = ()


class ReferencePrototypeCache:
    """Small in-memory cache proving source and artwork identity separation."""

    def __init__(self):
        self._values = {}

    @staticmethod
    def key(source, publication_id, kind, edition='unknown', volume=''):
        return (str(source), str(publication_id), str(kind), str(edition), str(volume))

    def get(self, source, publication_id, kind, edition='unknown', volume=''):
        return self._values.get(self.key(source, publication_id, kind, edition, volume))

    def put(self, source, publication_id, kind, value, edition='unknown', volume=''):
        # Empty/failure results are intentionally not cached: callers may retry.
        if value not in (None, '', (), [], {}):
            self._values[self.key(source, publication_id, kind, edition, volume)] = value
