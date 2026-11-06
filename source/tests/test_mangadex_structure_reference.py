"""Metadata-only structural consensus and acquisition provenance regressions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import CancelledError
from urllib.parse import urlparse, parse_qs

from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import CACHE_CONTRACT, MangaDexStructureResolver, aggregate_mappings
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.publication.unified_volume import build_unified_volume_plan
from calibre_plugins.manganana.metadata.reference_integration import ReferenceMetadataService, canonical_family_publication_context
from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache, IDENTITY_TTL
from calibre_plugins.manganana.providers.source_policy import enabled_sources
from calibre_plugins.manganana.providers.source_registry import SourceRegistry
from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
from calibre_plugins.manganana.providers.mangapill_source import MangaPillSource

FIX=json.loads((Path(__file__).parent/'fixtures/patch1c_mangadex_structure.json').read_text(encoding='utf-8'))
MID=FIX['title']['id']
EVIDENCE={'canonical_work_id':'kitsu:3021','title':'The World Is Mine','canonical_title':'The World Is Mine',
          'canonical_aliases':['ザ・ワールド・イズ・マイン'],'creators':['Hideki Arai'],
          'edition_profile':'standard','identity_confidence':'high'}


def aggregate(pairs):
    volumes={}
    for i,(chapter,volume) in enumerate(pairs):
        group=volumes.setdefault(str(volume),{'volume':volume,'chapters':{}})
        group['chapters'][str(i)]={'chapter':chapter}
    return {'result':'ok','volumes':volumes}


def structure(pairs=(('1','1'),('2','1'),('3','2'))):
    return MangaDexStructureResolver(request_json=lambda url:aggregate(pairs)).lookup(dict(EVIDENCE,mangadex_title_ids=[MID]))


def project(source='mangapill', pairs=None, native=False, extra=()):
    ref=structure(pairs) if pairs is not None else MangaDexStructureResolver(request_json=lambda url:FIX['aggregate']).lookup(dict(EVIDENCE,mangadex_title_ids=[MID]))
    rows=tuple({'id':source+'-'+n,'chapter':n,'volume':v if native else None,'_source_id':source,
                'pages':20,'page_urls':['https://selected-provider.invalid/'+n]} for n,v in ref['mappings'].items())+tuple(extra)
    builder=PublicationManifestBuilder({'canonical_identity':'kitsu:3021','title':'The World Is Mine'},'original')
    builder.apply_mangadex_structure(ref).apply_provider_inventory(rows,source)
    projection=build_publication_projection(rows,builder.build(),source,source)
    return rows,projection,build_unified_volume_plan({},rows,projection,source,source)


class StructureTests(unittest.TestCase):
    def test_explicit_numeric_and_decimal_normalization(self):
        m,a=aggregate_mappings(aggregate([('01.0','1'),('12.50','2.0'),('0.5','0.5')]))
        self.assertEqual({'1':'1','12.5':'2','0.5':'0.5'},m);self.assertEqual([],a)

    def test_duplicate_same_assignment_and_cross_language_consensus(self):
        # Aggregate represents releases from all languages under their volume/chapter pair.
        m,a=aggregate_mappings(aggregate([('1','1'),('1.0','1.0'),('2','1'),('2','1'),('3','2')]))
        self.assertEqual({'1':'1','2':'1','3':'2'},m);self.assertEqual([],a)

    def test_conflicting_assignments_are_per_chapter(self):
        m,a=aggregate_mappings(aggregate([('1','1'),('2','1'),('2.0','2'),('3','2')]))
        self.assertEqual({'1':'1','3':'2'},m);self.assertEqual(['2'],a)

    def test_missing_and_nonnumeric_fields_ignored(self):
        self.assertEqual(({},[]),aggregate_mappings(aggregate([(None,'1'),('Special','1'),('1',None),('2','none')])) )

    def test_malformed_aggregate_not_promoted(self):
        result=MangaDexStructureResolver(request_json=lambda u:{'result':'ok','volumes':{'1':{}}}).lookup(dict(EVIDENCE,mangadex_title_ids=[MID]))
        self.assertEqual('invalid_structure',result['status'])
        self.assertTrue(result['integrity_diagnostics'])

    def test_live_sanitized_world_aggregate_is_163_in_14(self):
        m,a=aggregate_mappings(FIX['aggregate'])
        self.assertEqual((163,14,[]),(len(m),len(set(m.values())),a))
        self.assertEqual(set(map(str,range(1,164))),set(m))

    def test_other_providers_derive_without_changing_acquisition(self):
        for source in ('mangapill','weebcentral','atsu','mangak'):
            with self.subTest(source=source):
                rows,projection,plan=project(source)
                self.assertEqual((0,14,0),(plan['native_volume_count'],plan['derived_volume_count'],plan['unmapped_chapter_count']))
                self.assertEqual(163,projection.coverage['reference_explicit'])
                for entry in projection.chapters:
                    self.assertEqual(source,entry.acquisition_provider)
                output=tuple(r for group in plan['volume_groups'] for r in group['chapters'])
                self.assertEqual({r['id'] for r in rows},{r['id'] for r in output})
                self.assertEqual({source},{r['_source_id'] for r in output})
                self.assertEqual(sorted(r['page_urls'] for r in rows), sorted(r['page_urls'] for r in output))

    def test_mangadex_native_stays_native(self):
        rows,projection,plan=project('mangadex',native=True)
        self.assertEqual((14,0),(plan['native_volume_count'],plan['derived_volume_count']))
        self.assertEqual((163,0),(projection.coverage['provider_explicit'],projection.coverage['reference_explicit']))

    def test_precedence_and_wikipedia_gap_fill(self):
        ref=structure([('1','1'),('2','1'),('2','2'),('3','2')])
        rows=[{'id':str(n),'chapter':str(n),'volume':'9' if n==1 else None} for n in (1,2,3)]
        wiki={'status':'valid_with_data','chapters':[{'number':str(n),'volume':'7'} for n in (1,2,3)]}
        for order in (0,1):
            b=PublicationManifestBuilder({'canonical_identity':'kitsu:3021'},'original')
            if order:b.apply_wikipedia(wiki)
            b.apply_provider_inventory(rows,'mangapill').apply_mangadex_structure(ref).apply_wikipedia(wiki)
            p=build_publication_projection(rows,b.build(),'mangapill','mangapill')
            self.assertEqual(['9','7','2'],[str(e.effective_volume.value) for e in p.chapters])
            self.assertEqual(['provider_explicit','reference_explicit','reference_explicit'],[e.mapping_state for e in p.chapters])

    def test_wikipedia_conflict_does_not_quarantine_valid_mangadex(self):
        b=PublicationManifestBuilder({'canonical_identity':'kitsu:3021'},'original').apply_mangadex_structure(structure())
        b.apply_wikipedia({'chapters':[{'number':'1','volume':'8'},{'number':'1','volume':'9'}]})
        p=build_publication_projection([{'id':'p','chapter':'1'}],b.build())
        self.assertEqual('1',p.chapters[0].effective_volume.value)

    def test_identity_and_edition_mismatch_fail_closed(self):
        for work,edition in [('kitsu:999','original'),('kitsu:3021','unknown'),('kitsu:3021','omnibus')]:
            b=PublicationManifestBuilder({'canonical_identity':work},edition).apply_mangadex_structure(structure())
            self.assertEqual((),b.build().chapters)

    def test_approved_color_numbering_compatible(self):
        for edition in ('original','official_color','fan_color'):
            b=PublicationManifestBuilder({'canonical_identity':'kitsu:3021'},edition).apply_mangadex_structure(structure())
            self.assertEqual(3,len(b.build().chapters))

    def test_no_missing_acquisition_chapters_manufactured(self):
        b=PublicationManifestBuilder({'canonical_identity':'kitsu:3021'},'original').apply_mangadex_structure(structure())
        rows=[{'id':'only-one','chapter':'1','_source_id':'mangapill'}]
        p=build_publication_projection(rows,b.build(),'mangapill','mangapill')
        self.assertEqual(1,len(p.chapters))
        self.assertEqual(1,sum(build_unified_volume_plan({},rows,p)['chapters_by_volume'].values()))

    def test_duplicate_acquisition_identity_is_not_force_mapped(self):
        _,p,plan=project('mangak',pairs=[('1','1'),('2','1')],extra=[{'id':'duplicate','chapter':'1','_source_id':'mangak'}])
        self.assertEqual(2,p.coverage['unmapped_provider_chapters'])

    def test_cross_language_lookup_has_no_language_parameter_or_page_endpoint(self):
        calls=[]
        def request(url):
            calls.append(url);self.assertTrue(url.endswith('/aggregate'))
            self.assertNotIn('translatedLanguage',url);self.assertNotIn('en',parse_qs(urlparse(url).query))
            return aggregate([('1','1'),('2','1'),('3','2')])
        r=MangaDexStructureResolver(request_json=request).lookup(dict(EVIDENCE,mangadex_title_ids=[MID],requested_language='en'))
        self.assertEqual(1,len(calls));self.assertEqual(3,r['mapped_chapter_count'])

    def test_cold_title_search_exact_unique_and_known_id_optimization(self):
        calls=[]
        def request(url):
            calls.append(url)
            if urlparse(url).path=='/manga':return {'result':'ok','data':[FIX['title']]}
            self.assertTrue(url.endswith('/aggregate'));return FIX['aggregate']
        r=MangaDexStructureResolver(request_json=request).lookup(EVIDENCE)
        self.assertEqual((MID,2,163),(r['manga_id'],len(calls),r['mapped_chapter_count']))
        calls.clear();r=MangaDexStructureResolver(request_json=request).lookup(dict(EVIDENCE,mangadex_title_ids=[MID]))
        self.assertEqual(1,len(calls))

    def test_search_bound_and_nonexact_titles_rejected(self):
        calls=[]
        wrong=copy.deepcopy(FIX['title']);wrong['attributes']['title']={'en':'The World Is Mine Another Story'};wrong['attributes']['altTitles']=[]
        r=MangaDexStructureResolver(request_json=lambda u:(calls.append(u) or {'result':'ok','data':[wrong]})).lookup(dict(EVIDENCE,canonical_aliases=['Alias '+str(n) for n in range(30)]))
        self.assertEqual((3,'no_match'),(len(calls),r['status']))

    def test_multiple_titles_or_creator_contradiction_rejected(self):
        other=copy.deepcopy(FIX['title']);other['id']='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        r=MangaDexStructureResolver(request_json=lambda u:{'result':'ok','data':[FIX['title'],other]}).lookup(EVIDENCE)
        self.assertEqual('ambiguous',r['status'])
        r=MangaDexStructureResolver(request_json=lambda u:{'result':'ok','data':[FIX['title']]}).lookup(dict(EVIDENCE,creators=['Someone Else']))
        self.assertEqual('no_match',r['status'])

    def test_insufficient_direct_link_identity_never_requests(self):
        def forbidden(u):raise AssertionError(u)
        for overrides in ({'identity_confidence':'low'},{'canonical_work_id':''},{'edition_profile':'unknown'}):
            r=MangaDexStructureResolver(request_json=forbidden).lookup(dict(EVIDENCE,**overrides))
            self.assertEqual('unavailable_identity',r['status'])

    def test_cache_language_independent_and_contract_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'reference.sqlite3');calls=[]
            def request(url):
                calls.append(url);return FIX['aggregate'] if url.endswith('/aggregate') else {'result':'ok','data':[FIX['title']]}
            resolver=MangaDexStructureResolver(cache,request)
            first=resolver.lookup(dict(EVIDENCE,requested_language='en'))
            second=resolver.lookup(dict(EVIDENCE,requested_language='ja'))
            self.assertEqual((2,0,'hit'),(len(calls),second['network']['requests'],second['cache_state']))
            # Corrupt only this result's contract, leaving unrelated reference records intact.
            original=cache.get_reference_structure
            def old(key):
                hit=original(key)
                if hit:hit.value['cache_contract']='old'
                return hit
            cache.get_reference_structure=old
            resolver.lookup(EVIDENCE);self.assertGreater(len(calls),2)
            cache.close()

    def test_ambiguous_title_not_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'ref.sqlite3');calls=[]
            second=dict(FIX['title'],id='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
            resolver=MangaDexStructureResolver(cache,lambda u:(calls.append(u) or {'result':'ok','data':[FIX['title'],second]}))
            self.assertEqual('ambiguous',resolver.lookup(EVIDENCE)['status'])
            self.assertEqual('ambiguous',resolver.lookup(EVIDENCE)['status']);self.assertEqual(2,len(calls));cache.close()

    def test_stale_pointer_skips_title_search_and_transient_uses_last_good(self):
        now=[100.0]
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'ref.sqlite3',clock=lambda:now[0])
            MangaDexStructureResolver(cache,lambda u:FIX['aggregate']).lookup(dict(EVIDENCE,mangadex_title_ids=[MID]))
            now[0]+=IDENTITY_TTL+1;calls=[]
            def fail(url):
                calls.append(url);self.assertTrue(url.endswith('/aggregate'));raise OSError('temporary')
            result=MangaDexStructureResolver(cache,fail).lookup(EVIDENCE)
            self.assertEqual(('last_known_good',163,1),(result['cache_state'],result['mapped_chapter_count'],len(calls)))
            cache.close()

    def test_refreshed_conflict_clears_previous_mangadex_assignment(self):
        b=PublicationManifestBuilder({'canonical_identity':'kitsu:3021'},'original').apply_mangadex_structure(structure())
        b.apply_mangadex_structure(structure([('1','1'),('2','1'),('2','2'),('3','2')]))
        self.assertFalse(b.build().chapter('2').volume.present)
        b.apply_wikipedia({'chapters':[{'number':'2','volume':'4'}]})
        self.assertEqual('4',b.build().chapter('2').volume.value)

    def test_multiple_known_title_ids_fail_closed_without_network(self):
        def fail(url):self.fail(url)
        r=MangaDexStructureResolver(request_json=fail).lookup(dict(EVIDENCE,mangadex_title_ids=[MID,'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa']))
        self.assertEqual('ambiguous',r['status'])

    def test_unknown_cache_contract_is_not_used_even_stale(self):
        from calibre_plugins.manganana.discovery.search_cache import CacheHit
        from unittest.mock import Mock
        old=dict(structure(),cache_contract='obsolete')
        cache=Mock();cache.get_reference_structure.return_value=CacheHit(old,0,True)
        cache.get.return_value=CacheHit(old,0,True)
        calls=[]
        def request(url):
            calls.append(url);return FIX['aggregate'] if url.endswith('/aggregate') else {'result':'ok','data':[FIX['title']]}
        r=MangaDexStructureResolver(cache,request).lookup(EVIDENCE)
        self.assertEqual((2,163),(len(calls),r['mapped_chapter_count']))

    def test_cancel_before_or_after_network(self):
        with self.assertRaises(CancelledError):MangaDexStructureResolver().lookup(EVIDENCE,lambda:True)
        stop=[False]
        def request(u):stop[0]=True;return FIX['aggregate']
        with self.assertRaises(CancelledError):MangaDexStructureResolver(request_json=request).lookup(dict(EVIDENCE,mangadex_title_ids=[MID]),lambda:stop[0])

    def test_disabled_acquisition_does_not_disable_metadata(self):
        md=MangaDexSource();pill=MangaPillSource()
        enabled=enabled_sources(SourceRegistry((md,pill)),{'source_enabled':{'mangadex':False}})
        self.assertEqual(['mangapill'],[s.source_id for s in enabled])
        class Empty:
            def match_publication(self,e):return PublicationMatch('fixture','','','no_match','fixture')
        service=ReferenceMetadataService(None,Empty(),Empty(),mangadex_structure=MangaDexStructureResolver(request_json=lambda u:FIX['aggregate']))
        result=service.lookup('work',dict(EVIDENCE,mangadex_title_ids=[MID]))
        self.assertEqual(163,result['mangadex_structure']['mapped_chapter_count'])
        self.assertEqual('unavailable_no_api_key',result['google_books']['status'])


if __name__=='__main__':unittest.main()
