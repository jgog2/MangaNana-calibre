import tempfile
import unittest
from pathlib import Path

from canonical_identity import group_canonical_results
from enrichment_matching import resolve_canonical_work_facts
from publication_manifest import PublicationManifestBuilder, build_publication_projection
from reference_integration import ReferenceMetadataService, canonical_publication_context
from reference_metadata import PublicationChapter, PublicationMatch, PublicationVolume
from search_cache import SearchMetadataCache, final_search_records


class NoBookwalker:
    def match_publication(self, _evidence):
        return PublicationMatch('bookwalker', '', '', 'no_match', 'fixture')


class FixtureCollection:
    def metadata(self):
        return {
            'root': {'title': 'Bleach (manga)', 'page_id': '660333', 'revision_id': '1'},
            'index_pages': [], 'segments': [], 'status': 'valid_partial',
            'raw_publication_records': 688, 'safe_aggregated_records': 686,
            'reused_label_records': 2, 'quarantined_records': 2,
            'quarantined_groups': [{
                'display_key': '0', 'classification': 'explicit_reused_label',
                'row_count': 2, 'acquisition_projection': 'ambiguous_unprojected',
            }],
            'conflicts': [],
        }


class FixtureWikipedia:
    pattern_id = 'fixture-single'
    collection_pattern_id = 'fixture-collection'
    parser_version = '4'

    def __init__(self, explode=False):
        self.explode = explode
        self.request_count = self.retry_count = self.rate_limit_count = self.segment_cache_hits = 0

    def match_publication(self, _evidence):
        if self.explode:
            raise AssertionError('warm reference cache missed')
        return PublicationMatch('wikipedia', '660333', 'Bleach (manga)', 'confident', 'fixture')

    def resolve_publication(self, _match, *_cache_callbacks):
        chapters = tuple(
            PublicationChapter(str(number), f'Title {number}', str((number - 1) // 10 + 1),
                               source='wikipedia', confidence='explicit')
            for number in range(1, 687)
        )
        volumes = tuple(PublicationVolume(str(number), source='wikipedia') for number in range(1, 70))
        return {
            'status': 'valid_partial', 'structure_page': 'List of Bleach volumes',
            'chapters': chapters, 'volumes': volumes, 'collection': FixtureCollection(),
        }


def bleach_card(source, fitness='direct'):
    return {
        'source_id': source, 'source_name': source, 'id': source + '-bleach',
        'title': 'Bleach', 'author': 'Tite Kubo', '_provider_native_author': 'Kubo Tite',
        'canonical_work_id': 'anilist:30012|anilist:41330',
        'canonical_title': 'Bleach', 'canonical_author': 'Tite Kubo',
        'canonical_creator_provenance': 'trusted_external',
        'canonical_creator_aliases': ['Tite Kubo', 'Kubo Tite'],
        'canonical_creators': ['Tite Kubo'],
        'canonical_aliases': ['BLEACH'], 'work_family_id': 'canonical:bleach:original',
        '_canonical_identity_confidence': 'high', '_acquisition_fitness': fitness,
        '_qualification_status': 'qualified', '_qualification_chapter_count': 698,
        'edition': 'original',
    }


class WarmSearchCanonicalInvarianceTests(unittest.TestCase):
    def test_ippo_anilist_only_final_title_survives_warm_restart_and_reordering(self):
        cards=[]
        for source,title in (
                ('mangadex','Hajime no Ippo: Fighting Spirit!'),
                ('mangapill','Hajime no Ippo'),
                ('weebcentral','Hajime no Ippo')):
            cards.append({
                'source_id':source,'source_name':source,'id':source+'-ippo',
                'title':title,'canonical_title':title,
                'canonical_work_id':'anilist:30007',
                'canonical_author':'George Morikawa',
                'canonical_creators':['George Morikawa'],
                'canonical_creator_provenance':'trusted_external',
                '_canonical_identity_confidence':'high',
                'work_family_id':'canonical:hajime no ippo:original',
                'edition':'original',
            })

        def facts(rows):
            value=next(iter(resolve_canonical_work_facts(
                group_canonical_results(tuple(rows))
            ).values()))
            context=canonical_publication_context(value.canonical_work_id,{
                'canonical_title':value.canonical_title,
                'canonical_author':value.creator,'canonical_creators':value.creators,
                'provider_author':'George Morikawa','edition':'original',
                'identity_confidence':'high',
            })
            return value.canonical_title,value.canonical_work_id,context.reference_key

        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ippo.sqlite3'
            cache=SearchMetadataCache(path)
            cache.put_query_snapshot('ippo',{
                'provider_candidates':cards,
                'final_cards':[{'provider_record':row} for row in cards],
                'final_result_count':len(cards),
            })
            warm=final_search_records(cache.get_query_snapshot('ippo').value)
            cache.close()
            restarted=SearchMetadataCache(path)
            restart=final_search_records(restarted.get_query_snapshot('ippo').value)
            restarted.close()
        expected=('Hajime no Ippo','anilist:30007',
                  'anilist-30007|hajime-no-ippo|standard')
        self.assertEqual(expected,facts(cards))
        self.assertEqual(expected,facts(reversed(warm)))
        self.assertEqual(expected,facts(restart))

    def test_cold_warm_restart_and_cross_work_preserve_bleach_projection(self):
        inventory = [
            {'chapter': str(number), 'title': '', 'volume': None, '_source_id': 'mangapill'}
            for number in range(1, 687)
        ]
        inventory.extend(
            {'chapter': f'{number}.5', 'title': '', 'volume': None, '_source_id': 'mangapill'}
            for number in range(1, 12)
        )
        inventory.append({'chapter': '999', 'title': '', 'volume': '99', '_source_id': 'mangapill'})
        cards = [bleach_card('mangapill'), bleach_card('mangadex', 'fallback_only'),
                 bleach_card('weebcentral', 'fallback_only')]

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'cache.sqlite3'
            cache = SearchMetadataCache(path)
            cache.put_query_snapshot('bleach', {
                'provider_candidates': [dict(row, author='Kubo Tite') for row in cards],
                'final_cards': [{'provider_record': row} for row in cards],
                'final_result_count': 3,
            })
            cold_cards = tuple(cards)
            warm_cards = final_search_records(cache.get_query_snapshot('bleach').value)
            context = canonical_publication_context(cold_cards[0]['canonical_work_id'], {
                'canonical_title': cold_cards[0]['canonical_title'],
                'canonical_author': cold_cards[0]['canonical_author'],
                'canonical_creators': cold_cards[0]['canonical_creators'],
                'canonical_creator_aliases': cold_cards[0]['canonical_creator_aliases'],
                'provider_author': cold_cards[0]['_provider_native_author'],
                'identity_confidence': cold_cards[0]['_canonical_identity_confidence'],
                'edition': 'original',
            })
            cold_wiki = ReferenceMetadataService(
                cache, FixtureWikipedia(), NoBookwalker()
            ).lookup(context.reference_key, context.lookup_evidence())['wikipedia']
            cache.put_query_snapshot('chainsaw', {
                'provider_candidates': [{'source_id': 'mangapill', 'id': 'chainsaw'}],
                'final_cards': [{'provider_record': {
                    'source_id': 'mangapill', 'id': 'chainsaw', 'title': 'Chainsaw Man',
                }}], 'final_result_count': 1,
            })
            after_cross_work = final_search_records(cache.get_query_snapshot('bleach').value)
            cache.close()

            restarted = SearchMetadataCache(path)
            restart_cards = final_search_records(restarted.get_query_snapshot('bleach').value)
            warm_wiki = ReferenceMetadataService(
                restarted, FixtureWikipedia(explode=True), NoBookwalker()
            ).lookup(context.reference_key, context.lookup_evidence())['wikipedia']
            restarted.close()

        stable = ('canonical_work_id', 'canonical_title', 'canonical_author','canonical_creators',
                  'canonical_creator_aliases', 'canonical_aliases', 'work_family_id',
                  '_canonical_identity_confidence', '_acquisition_fitness',
                  '_qualification_status', '_qualification_chapter_count')
        expected = tuple(tuple(row[key] for key in stable) for row in cold_cards)
        self.assertEqual(expected, tuple(tuple(row[key] for key in stable) for row in warm_cards))
        self.assertEqual(expected, tuple(tuple(row[key] for key in stable) for row in after_cross_work))
        self.assertEqual(expected, tuple(tuple(row[key] for key in stable) for row in restart_cards))
        self.assertEqual(('valid_partial', 686, 2), (
            warm_wiki['status'], len(warm_wiki['chapters']),
            warm_wiki['collection']['quarantined_records'],
        ))
        self.assertEqual(cold_wiki['cache_identity'], warm_wiki['cache_identity'])

        builder = PublicationManifestBuilder(
            {'canonical_identity': context.canonical_work_id, 'title': 'Bleach'}, 'original'
        )
        builder.apply_provider_inventory(inventory, 'mangapill').apply_wikipedia(warm_wiki)
        projection = build_publication_projection(inventory, builder.build(), 'mangapill', 'mangapill')
        self.assertEqual((698, 1, 686, 11, 0), (
            projection.coverage['provider_chapters'], projection.coverage['provider_explicit'],
            projection.coverage['reference_explicit'], projection.coverage['derived_fractional'],
            projection.coverage['unmapped_provider_chapters'],
        ))


if __name__ == '__main__':
    unittest.main()
