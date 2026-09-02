"""Provider-neutral models for optional external manga search enrichment."""

from dataclasses import asdict, dataclass, field
from enum import Enum
import time


class IdentityConfidence(str, Enum):
    REJECT = 'reject'
    MEDIUM = 'medium'
    HIGH = 'high'


class EditionClass(str, Enum):
    STANDARD = 'standard'
    OFFICIAL_COLOR = 'official_color'
    FAN_COLOR = 'fan_color'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class RatingSignal:
    score_10: float = None
    sample_count: int = None
    service: str = ''


@dataclass(frozen=True)
class PopularitySignal:
    readers: int = None
    favourites: int = None
    service_rank: int = None
    service: str = ''


@dataclass(frozen=True)
class VolumeBoundaryEvidence:
    """Passive future context; totals never imply synthetic volume boundaries."""

    reported_total_chapters: int = None
    reported_total_volumes: int = None
    explicit_volume_boundaries: tuple = ()
    provenance: str = ''
    confidence: str = 'reported_totals'
    retrieved_at: float = 0.0


@dataclass(frozen=True)
class ExternalMangaCandidate:
    service: str
    external_id: str
    primary_title: str
    english_title: str = ''
    romanized_title: str = ''
    native_title: str = ''
    aliases: tuple = ()
    authors: tuple = ()
    description: str = ''
    tags: tuple = ()
    start_year: int = None
    format: str = ''
    reported_chapter_count: int = None
    reported_volume_count: int = None
    cross_ids: dict = field(default_factory=dict)
    rating: RatingSignal = field(default_factory=RatingSignal)
    popularity: PopularitySignal = field(default_factory=PopularitySignal)
    adult: bool = None
    retrieved_at: float = field(default_factory=time.time)
    volume_context: VolumeBoundaryEvidence = None

    @property
    def titles(self):
        return tuple(dict.fromkeys(
            value for value in (
                self.primary_title, self.english_title, self.romanized_title,
                self.native_title, *self.aliases,
            ) if value
        ))

    def to_record(self):
        return asdict(self)

    @classmethod
    def from_record(cls, value):
        row = dict(value or {})
        row['aliases'] = tuple(row.get('aliases') or ())
        row['authors'] = tuple(row.get('authors') or ())
        row['tags'] = tuple(row.get('tags') or ())
        row['cross_ids'] = dict(row.get('cross_ids') or {})
        row['rating'] = RatingSignal(**dict(row.get('rating') or {}))
        row['popularity'] = PopularitySignal(**dict(row.get('popularity') or {}))
        context = row.get('volume_context')
        if context:
            context = dict(context)
            context['explicit_volume_boundaries'] = tuple(context.get('explicit_volume_boundaries') or ())
            row['volume_context'] = VolumeBoundaryEvidence(**context)
        return cls(**row)
