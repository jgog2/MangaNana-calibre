"""Trusted structure drives exact artwork gaps; no live requests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import CancelledError
from unittest.mock import Mock

from calibre_plugins.manganana.metadata.references.mangadex_artwork_reference import MangaDexArtworkResolver, exact_cover_catalog, CACHE_CONTRACT
from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import MangaDexStructureResolver
from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, trusted_volume_numbers, build_publication_projection
from calibre_plugins.manganana.metadata.reference_integration import ReferenceMetadataService, reference_artwork_builder, _google_targets
from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch, PublicationChapter, PublicationVolume, PublicationArtwork
from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache, CacheHit, IDENTITY_TTL
from calibre_plugins.manganana.publication.unified_volume import build_unified_volume_plan
from tests.test_mangadex_structure_reference import FIX,MID,EVIDENCE,structure
from tests.test_patch1c_publication import family,bookwalker_fixture

FIX_ART=json.loads((Path(__file__).parent/'fixtures/patch1d_mangadex_covers.json').read_text(encoding='utf-8'))
E=dict(EVIDENCE,edition='original',requested_language='en')


def md_art(numbers=range(1,15)):
    return dict(source='mangadex_artwork',status='valid',cache_contract=CACHE_CONTRACT,
                canonical_work_id=E['canonical_work_id'],manga_id=MID,edition='original',
                covers=[c for c in exact_cover_catalog(FIX_ART['data'],MID) if int(c['volume']) in numbers])


def cover(source,number):
    return {'volume':str(number),'source':source,'artwork_type':'volume','confidence':'exact',
            'url':f'https://covers.invalid/{source}/{number}.jpg','edition_id':'fixture','volume_id':str(number)}


def book(numbers):
    return {'match':{'publication_id':'series/fixture','edition_id':'fixture','edition':'original'},
            'covers':[cover('bookwalker',n) for n in numbers]}


def builder(numbers=(1,2,3,4)):
    return PublicationManifestBuilder({'canonical_identity':E['canonical_work_id']},'original').apply_provider_inventory(
        [{'chapter':str(n),'volume':str(n),'id':'p-'+str(n)} for n in numbers],'mangapill')


class Wiki:
    pattern_id='fixture';parser_version='1'
    def __init__(self,numbers=()):self.numbers=numbers
    def match_publication(self,e):return PublicationMatch('wikipedia','wiki' if self.numbers else '',e.get('title',''),'confident' if self.numbers else 'no_match','fixture')
    def get_structure_page(self,m):return 'fixture'
    def get_chapter_list(self,m):return tuple(PublicationChapter(str(n),'Chapter',str(n),'chapter','wikipedia') for n in self.numbers)
    def get_volume_list(self,m):return tuple(PublicationVolume(str(n)) for n in self.numbers)


class Book:
    def __init__(self,numbers=()):self.numbers=numbers;self.evidence=[]
    def match_publication(self,e):
        self.evidence.append(copy.deepcopy(e))
        return PublicationMatch('bookwalker','series/fixture','Work','confident','fixture',edition='original',edition_id='fixture')
    def get_volume_list(self,m):return tuple(PublicationVolume(str(n)) for n in self.numbers)
    def get_volume_covers(self,m):return tuple(PublicationArtwork(f'https://covers.invalid/bookwalker/{n}.jpg','volume',str(n),'bookwalker','exact','series/fixture','fixture',str(n)) for n in self.numbers)
    def get_edition_artwork(self,m):return ()
    def get_description(self,m):return 'Publication metadata retained'


class Google:
    supports_detail_cache=False;api_key='explicit-test-injection'
    def __init__(self):self.targets=[]
    def resolve(self,context,targets):
        self.targets.append(tuple(targets))
        return {'status':'valid','covers':[cover('google_books',n) for n in targets], 'target_volumes':list(targets)}


def service_result(md_numbers=(),bw_numbers=(),wiki_numbers=(),md_structure=True,acquisition=None):
    google=Google();refs=structure([('1','1'),('2','2'),('3','3')]) if md_structure else {}
    resolver=Mock();resolver.lookup.return_value=refs
    art=Mock();art.lookup.return_value=md_art(md_numbers)
    service=ReferenceMetadataService(None,Wiki(wiki_numbers),Book(bw_numbers),google,
                                     mangadex_structure=resolver,mangadex_artwork=art)
    return service.lookup('work',E,acquisition=acquisition),google


class ArtworkTests(unittest.TestCase):
    def test_verified_15_records_cover_14_numeric_volumes(self):
        self.assertEqual(15,len(FIX_ART['data']))
        covers=exact_cover_catalog(FIX_ART['data'],MID)
        self.assertEqual(list(map(str,range(1,15))),[c['volume'] for c in covers])
        self.assertEqual({'ja'},{c['locale'] for c in covers})

    def test_japanese_duplicate_wins_in_every_order(self):
        forward=exact_cover_catalog(FIX_ART['data'],MID)
        self.assertEqual(forward,exact_cover_catalog(list(reversed(FIX_ART['data'])),MID))
        self.assertEqual('96bd5e5e-f93a-4f66-a755-2d38429704b2',forward[0]['cover_id'])

    def test_native_mangadex_uses_the_same_japanese_duplicate_choice(self):
        expected={float(r['volume']):r['url'] for r in exact_cover_catalog(FIX_ART['data'],MID)}
        for records in (FIX_ART['data'],list(reversed(FIX_ART['data']))):
            adapter=MangaDexSource(lambda u,**kw:{'data':records})
            self.assertEqual(expected,adapter.get_volume_covers('https://mangadex.org/title/'+MID))

    def test_stable_id_breaks_same_locale_tie(self):
        one=copy.deepcopy(FIX_ART['data'][-1]);two=copy.deepcopy(one);two['id']='00000000-0000-0000-0000-000000000000'
        self.assertEqual(two['id'],exact_cover_catalog([one,two],MID)[0]['cover_id'])

    def test_null_nonnumeric_generic_and_wrong_title_rejected(self):
        rows=[]
        for value in (None,'','Special','nan','Infinity'):
            row=copy.deepcopy(FIX_ART['data'][0]);row['attributes']['volume']=value;rows.append(row)
        wrong=copy.deepcopy(FIX_ART['data'][0]);wrong['relationships']=[];rows.append(wrong)
        self.assertEqual([],exact_cover_catalog(rows,MID))

    def test_known_identity_cost_and_download_language_independence(self):
        calls=[];resolver=MangaDexArtworkResolver(request_json=lambda u:(calls.append(u) or FIX_ART))
        identity=dict(structure(),identity_edition='original')
        a=resolver.lookup(E,identity);b=resolver.lookup(dict(E,requested_language='fr'),identity)
        self.assertEqual(a['covers'],b['covers']);self.assertEqual(2,len(calls))
        self.assertTrue(all('/cover?' in u and 'translatedLanguage' not in u for u in calls))

    def test_old_structure_pointer_uses_detail_not_title_search(self):
        calls=[]
        def request(url):
            calls.append(url)
            return {'data':FIX['title']} if '/manga/' in url else FIX_ART
        identity=dict(structure());identity.pop('identity_edition',None)
        result=MangaDexArtworkResolver(request_json=request).lookup(E,identity)
        self.assertEqual((14,2),(len(result['covers']),len(calls)))
        self.assertFalse(any('/manga?' in u for u in calls))

    def test_edition_mismatch_never_fetches_covers(self):
        request=Mock();identity=dict(structure(),identity_edition='official_color')
        self.assertEqual('incompatible_edition',MangaDexArtworkResolver(request_json=request).lookup(E,identity)['status'])
        request.assert_not_called()

    def test_identity_mismatch_and_low_confidence_make_no_requests(self):
        request=Mock()
        for e,i in ((dict(E,identity_confidence='low'),structure()),(E,dict(structure(),canonical_work_id='wrong'))):
            self.assertEqual('unavailable_identity',MangaDexArtworkResolver(request_json=request).lookup(e,i)['status'])
        request.assert_not_called()

    def test_cache_cross_provider_language_hit_and_old_contract_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'ref.sqlite3');calls=[]
            resolver=MangaDexArtworkResolver(cache,lambda u:(calls.append(u) or FIX_ART))
            first=resolver.lookup(E,structure());second=resolver.lookup(dict(E,requested_language='fr'),structure())
            self.assertEqual((1,'hit',0),(len(calls),second['cache_state'],second['network']['requests']))
            cache.put_reference_catalog(CACHE_CONTRACT+':'+MID+':original',dict(first,cache_contract='old'))
            resolver.lookup(E,structure());self.assertEqual(2,len(calls));cache.close()

    def test_transient_catalog_failure_preserves_last_known_good(self):
        now=[1.0]
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'ref.sqlite3',clock=lambda:now[0])
            MangaDexArtworkResolver(cache,lambda u:FIX_ART).lookup(E,structure());now[0]+=IDENTITY_TTL+1
            def fail(url):raise OSError('temporary')
            result=MangaDexArtworkResolver(cache,fail).lookup(E,structure())
            self.assertEqual(('last_known_good',14),(result['cache_state'],len(result['covers'])));cache.close()

    def test_cancel_and_incomplete_pagination_fail_closed(self):
        with self.assertRaises(CancelledError):MangaDexArtworkResolver().lookup(E,structure(),lambda:True)
        result=MangaDexArtworkResolver(request_json=lambda u:dict(FIX_ART,total=500)).lookup(E,structure())
        self.assertEqual('transient_failure',result['status']);self.assertEqual([],result['covers'])

    def test_volume_universe_ignores_bibliography_and_art(self):
        b=PublicationManifestBuilder({'canonical_identity':E['canonical_work_id']},'original')
        b.apply_enrichment({'volume_count':99,'kitsu_id':'x'}).apply_madb({'books':[{'number':'1'}]}).apply_bookwalker(book(range(1,20))).apply_google_books({'covers':[cover('google_books',1)]}).apply_mangadex_artwork(md_art())
        self.assertEqual((),trusted_volume_numbers(b.build()));self.assertEqual((),b.build().volumes)

    def test_native_mangadex_and_wikipedia_each_supply_universe(self):
        self.assertEqual(('1','2','3','4'),trusted_volume_numbers(builder().build()))
        b=PublicationManifestBuilder({'canonical_identity':E['canonical_work_id']},'original').apply_mangadex_structure(structure())
        self.assertEqual(('1','2'),trusted_volume_numbers(b.build()))
        b=PublicationManifestBuilder({'canonical_identity':'wiki'},'original').apply_wikipedia({'chapters':[{'number':'1','volume':'7'}]})
        self.assertEqual(('7',),trusted_volume_numbers(b.build()))

    def test_all_four_artwork_priorities(self):
        for reverse in (False,True):
            b=builder()
            actions=[lambda:b.apply_provider_covers({1:'https://provider/1.jpg'},'atsu'),lambda:b.apply_mangadex_artwork(md_art((1,2))),
                     lambda:b.apply_bookwalker(book((1,2,3))),lambda:b.apply_google_books({'covers':[cover('google_books',n) for n in (1,2,3,4)]})]
            for action in reversed(actions) if reverse else actions:action()
            self.assertEqual(['atsu','mangadex_artwork','bookwalker','google_books'],[v.cover.source for v in b.build().volumes])

    def test_artwork_outside_universe_does_not_create_volume(self):
        b=builder((1,2));b.apply_mangadex_artwork(md_art()).apply_bookwalker(book(range(1,20))).apply_google_books({'covers':[cover('google_books',20)]})
        self.assertEqual(['1','2'],[v.key for v in b.build().volumes])

    def test_google_targets_distinguish_no_wikipedia_from_full_mangadex_art(self):
        ref=MangaDexStructureResolver(request_json=lambda u:FIX['aggregate']).lookup(dict(E,mangadex_title_ids=[MID]))
        result={'publication_evidence':E,'mangadex_structure':ref,'wikipedia':{'status':'unsupported_layout'}}
        self.assertEqual(tuple(map(str,range(1,15))),_google_targets(result))
        result['mangadex_artwork']=md_art()
        self.assertEqual((),_google_targets(result))
        self.assertEqual(tuple(map(str,range(1,15))),trusted_volume_numbers(reference_artwork_builder(result).build()))

    def test_mangadex_without_covers_drives_bookwalker_and_google(self):
        # No Wiki structure or MangaDex artwork is present.
        result,g=service_result(bw_numbers=(1,))
        self.assertEqual(('1','2','3'),result['bookwalker_targets']);self.assertEqual([('2','3')],g.targets)
        b=reference_artwork_builder(result).apply_bookwalker(result['bookwalker']).apply_google_books(result['google_books'])
        self.assertEqual(['bookwalker','google_books','google_books'],[v.cover.source for v in b.build().volumes])

    def test_google_receives_only_fourth_volume_after_all_higher_priorities(self):
        result,g=service_result(md_numbers=(1,2),bw_numbers=(1,2,3),acquisition={
            'source_id':'atsu','chapters':[{'chapter':str(n),'volume':str(n)} for n in range(1,5)],
            'covers':{1:'https://atsu/1.jpg'}})
        self.assertEqual(('3','4'),result['bookwalker_targets']);self.assertEqual([('4',)],g.targets)

    def test_google_can_fill_all_mangadex_structure_volumes_without_wiki_or_other_art(self):
        result,g=service_result()
        self.assertEqual([('1','2','3')],g.targets)

    def test_known_identity_without_aggregate_structure_can_supply_wiki_art(self):
        identity=dict(structure(),status='no_structure',mappings={})
        art=MangaDexArtworkResolver(request_json=lambda u:FIX_ART).lookup(E,identity)
        b=reference_artwork_builder({'publication_evidence':E,'mangadex_structure':identity,
            'wikipedia':{'chapters':[{'number':'1','volume':'1'}]},'mangadex_artwork':art})
        self.assertEqual('mangadex_artwork',b.build().volume('1').cover.source)

    def test_artwork_result_edition_mismatch_is_not_applied(self):
        b=builder();b.apply_mangadex_artwork(dict(md_art(),edition='official_color'))
        self.assertFalse(any(v.cover for v in b.build().volumes))

    def test_wikipedia_without_mangadex_drives_gaps(self):
        result,g=service_result(bw_numbers=(1,2),wiki_numbers=(1,2,3),md_structure=False)
        self.assertEqual(('1','2','3'),result['trusted_volumes']);self.assertEqual([('3',)],g.targets)

    def test_native_provider_without_either_reference_drives_gaps(self):
        result,g=service_result(md_structure=False,acquisition={'source_id':'atsu','chapters':[{'chapter':'1','volume':'1'},{'chapter':'2','volume':'2'}], 'covers':{1:'https://atsu/1.jpg'}})
        self.assertEqual(('1','2'),result['trusted_volumes']);self.assertEqual([('2',)],g.targets)

    def test_world_cold_all_acquisition_sources_keep_provenance(self):
        for source in ('mangak','mangapill','weebcentral','atsu','mangadex'):
            with self.subTest(source=source):
                google=Google();calls=[]
                sr=MangaDexStructureResolver(request_json=lambda u: FIX['aggregate'] if '/aggregate' in u else {'result':'ok','data':[FIX['title']]})
                ar=MangaDexArtworkResolver(request_json=lambda u:(calls.append(u) or FIX_ART))
                result=ReferenceMetadataService(None,Wiki(),Book(),google,mangadex_structure=sr,mangadex_artwork=ar).lookup('work',E)
                rows=[{'id':source+str(n),'chapter':str(n),'volume':result['mangadex_structure']['mappings'][str(n)] if source=='mangadex' else None,
                       '_source_id':source,'page_urls':['https://'+source+'/page']} for n in range(1,164)]
                b=reference_artwork_builder(result).apply_provider_inventory(rows,source)
                if source=='mangadex':b.apply_provider_covers({n:f'https://provider/{n}' for n in range(1,15)},source)
                projection=build_publication_projection(rows,b.build(),source,source)
                plan=build_unified_volume_plan({},rows,projection,source,source)
                self.assertEqual((14,0),(len(plan['volumes']),plan['unmapped_chapter_count']))
                self.assertEqual(14 if source=='mangadex' else 0,plan['native_volume_count'])
                self.assertTrue(all(v.cover for v in b.build().volumes));self.assertEqual([()],google.targets)
                self.assertEqual(1,len(calls));self.assertTrue('/cover?' in calls[0])
                self.assertEqual(rows,[c.acquisition for c in projection.chapters])

    def test_artwork_cannot_fix_ambiguous_structure(self):
        ref=structure([('1','1'),('2','1'),('2','2')])
        b=PublicationManifestBuilder({'canonical_identity':E['canonical_work_id']},'original').apply_mangadex_structure(ref).apply_mangadex_artwork(md_art())
        p=build_publication_projection([{'id':'ambiguous','chapter':'2','_source_id':'mangak'}],b.build(),'mangak','mangak')
        self.assertFalse(p.chapters[0].effective_volume.present)


if __name__=='__main__':unittest.main()
