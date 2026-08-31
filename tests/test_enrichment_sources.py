import unittest

from enrichment_sources import (
    AniListAdapter, EnrichmentRateLimited, EnrichmentRegistry, KitsuAdapter,
)
from enrichment_model import ExternalMangaCandidate


class EnrichmentSourceTests(unittest.TestCase):
    def test_anilist_normalizes_only_bounded_metadata_fields(self):
        def request(_url, **_kwargs):
            return {'data': {'Page': {'media': [{
                'id': 12, 'idMal': 21, 'title': {
                    'english': 'Attack on Titan', 'romaji': 'Shingeki no Kyojin', 'native': '進撃の巨人',
                }, 'synonyms': ['AoT'], 'format': 'MANGA', 'chapters': 139, 'volumes': 34,
                'startDate': {'year': 2009}, 'averageScore': 87, 'popularity': 700000,
                'favourites': 60000, 'isAdult': False,
                'staff': {'edges': [{'role': 'Story & Art', 'node': {'name': {'full': 'Hajime Isayama'}}}]},
            }]}}}, {'X-RateLimit-Remaining': '29'}
        rows, headers = AniListAdapter(request).search('Attack on Titan')
        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual('Attack on Titan', row.primary_title)
        self.assertEqual(8.7, row.rating.score_10)
        self.assertIsNone(row.rating.sample_count)
        self.assertEqual(700000, row.popularity.readers)
        self.assertEqual('21', row.cross_ids['mal_id'])
        self.assertEqual(139, row.volume_context.reported_total_chapters)
        self.assertEqual((), row.volume_context.explicit_volume_boundaries)
        self.assertEqual('29', headers['X-RateLimit-Remaining'])

    def test_kitsu_normalizes_documented_live_contract_fields(self):
        def request(_url, **_kwargs):
            return {'data': [{
                'id': '99', 'attributes': {
                    'canonicalTitle': 'One-Punch Man',
                    'titles': {'en': 'One-Punch Man', 'en_jp': 'One Punch Man', 'ja_jp': 'ワンパンマン'},
                    'abbreviatedTitles': ['OPM'], 'startDate': '2012-06-14', 'subtype': 'manga',
                    'chapterCount': 200, 'volumeCount': 31, 'averageRating': '86.4',
                    'ratingFrequencies': {'18': '100', '20': '300'}, 'userCount': 100000,
                    'favoritesCount': 5000, 'popularityRank': 10, 'nsfw': False,
                }, 'relationships': {'chapters': {'links': {'related': 'https://example.invalid'}}},
            }]}, {'Content-Type': 'application/vnd.api+json'}
        rows, _headers = KitsuAdapter(request).search('One Punch Man')
        row = rows[0]
        self.assertAlmostEqual(8.64, row.rating.score_10)
        self.assertEqual(400, row.rating.sample_count)
        self.assertEqual(100000, row.popularity.readers)
        self.assertEqual(31, row.reported_volume_count)
        self.assertEqual((), row.volume_context.explicit_volume_boundaries)

    def test_429_is_not_retried_aggressively(self):
        calls = []
        def request(_url, **_kwargs):
            calls.append(1)
            raise EnrichmentRateLimited('AniList', 60)
        with self.assertRaises(EnrichmentRateLimited) as raised:
            AniListAdapter(request).search('Series')
        self.assertEqual(1, len(calls))
        self.assertEqual(60, raised.exception.retry_after)

    def test_one_or_both_service_failures_remain_optional(self):
        class Broken:
            def __init__(self, service_id): self.service_id = service_id
            def search(self, *_args, **_kwargs): raise RuntimeError('offline')
        rows, errors = EnrichmentRegistry((Broken('anilist'), Broken('kitsu'))).search('Series')
        self.assertEqual((), rows)
        self.assertEqual({'anilist', 'kitsu'}, set(errors))

        class Working:
            service_id = 'anilist'
            def search(self, *_args, **_kwargs):
                return (ExternalMangaCandidate('anilist', '1', 'Series'),), {}
        rows, errors = EnrichmentRegistry((Working(), Broken('kitsu'))).search('Series')
        self.assertEqual(1, len(rows))
        self.assertEqual({'kitsu'}, set(errors))


if __name__ == '__main__':
    unittest.main()
