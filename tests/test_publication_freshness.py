"""Shared runtime release/curation tests; no Calibre or real network."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from calibre_plugins.manganana.publication.publication_freshness import release_boundary, volume_release_state, parse_release_date, catalog_freshness, source_fingerprints
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch, PublicationVolume, PublicationArtwork
from calibre_plugins.manganana.metadata.reference_integration import ReferenceMetadataService, BOOKWALKER_CACHE_CONTRACT, WIKIPEDIA_CACHE_CONTRACT
from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache, IDENTITY_TTL
from calibre_plugins.manganana.metadata.references.bookwalker_reference import _cards
from calibre_plugins.manganana.metadata.references.wikipedia_reference import WikipediaPublicationAdapter


def bundle():
    return dict(wikipedia=dict(status='valid_complete',cache_contract=WIKIPEDIA_CACHE_CONTRACT,
        cache_state='refreshed',match=dict(publication_id='wiki:fixture',title='Series',edition='original',confidence='confident'),
        chapters=[dict(number='1',volume='1',kind='chapter',source='wikipedia',source_page='Series',
            source_page_id='1',source_revision_id='2',source_record_id='row:1',confidence='explicit')],
        volumes=[dict(number='1',release_status='released')]))


def builder():
    return PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series',language='en',
        publication_context=dict(shareable=True,canonical_work_id='fixture:series',canonical_title='Series')),
                                     'original',as_of='2026-10-04')


def patch():
    return dict(status='matched',identity=dict(trusted=True,canonical_work_id='fixture:series',edition='standard',language='en'),
        fields=[dict(entity='chapter',record_key='1',field='volume',value='1',verification='VERIFIED')])


class RuntimePublication(unittest.TestCase):
    def test_plugin_projection_derives_tail_only_with_trusted_context(self):
        data=bundle();data['wikipedia']['chapters'].append(dict(data['wikipedia']['chapters'][0],
            number='2',volume='',kind='uncollected',source_record_id='row:2'))
        for trusted in (True,False):
            b=builder()
            seed=PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series',language='en'),'original').build()
            b=PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series',language='en',
                publication_context=dict(shareable=True,canonical_work_id='fixture:series',canonical_title='Series')),
                'original',existing=seed,as_of='2026-10-04')
            if not trusted:
                b=PublicationManifestBuilder(dict(canonical_identity='provider:opaque',title='Series',language='en'),'original')
            b.apply_provider_inventory([dict(chapter='1'),dict(chapter='2')]);b.apply_wikipedia(data['wikipedia'])
            row=build_publication_projection([dict(chapter='1'),dict(chapter='2')],b.build()).chapters[1].as_row()
            self.assertEqual('UNCOMPILED' if trusted else 'UNMAPPED',row['_publication_state'])
    def test_date_is_not_a_citation_or_partial_year(self):
        self.assertEqual('2026-11-04',parse_release_date('November 4, 2026'))
        self.assertEqual('',parse_release_date('2026'))
        self.assertEqual('',parse_release_date('?'))

    def test_upcoming_date_does_not_advance_boundary(self):
        data=bundle();data['wikipedia']['volumes'].append(dict(number='2',release_date='2026-11-04'))
        self.assertEqual('1',release_boundary(data,'2026-10-04')['latest_released_volume'])

    def test_date_crossing_and_source_confirmed_release(self):
        self.assertEqual('RELEASED',volume_release_state(dict(release_date='2026-11-04'),'2026-11-05'))
        self.assertEqual('PREORDER',volume_release_state(dict(release_date='2026-11-04',release_status='preorder'),'2026-11-05'))

    def test_unknown_listing_is_not_release(self):
        self.assertEqual('LISTED_BUT_NOT_RELEASED',volume_release_state(dict(number='2'),'2026-10-04'))

    def test_conflicting_current_future_claims_fail_closed(self):
        data=bundle();data['bookwalker']=dict(cache_contract=BOOKWALKER_CACHE_CONTRACT,cache_state='refreshed',
            match=dict(publication_id='series/1',confidence='confident'),catalog=dict(canonical_complete=True),
            volumes=[dict(number='1',release_date='2026-11-04')])
        self.assertEqual(['1'],release_boundary(data,'2026-10-04')['conflicts'])

    def test_sparse_patch_preserves_uncontrolled_live_structure(self):
        b=builder();b.apply_provider_inventory([dict(chapter='1'),dict(chapter='2',volume='2')],'provider')
        b.apply_curated(patch());m=b.build()
        self.assertEqual('2',m.chapter('2').volume.value)
        self.assertEqual('curated_database',m.chapter('1').volume.source)

    def test_exact_edition_and_language_isolation(self):
        for name,value in (('edition','fan_color'),('language','ja'),('canonical_work_id','fixture:other')):
            b=builder();p=patch();p['identity'][name]=value;b.apply_curated(p)
            self.assertIsNone(b.build().chapter('1'))

    def test_existing_curated_mapping_survives_provider_refresh(self):
        b=builder();b.apply_curated(patch());existing=b.build()
        new=PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series',language='en'),'original',existing)
        new.apply_provider_inventory([dict(chapter='1',volume='2')],'provider')
        new.apply_wikipedia(bundle()['wikipedia']);m=new.build()
        self.assertEqual('1',m.chapter('1').volume.value)
        self.assertEqual('CONFLICT_REVIEW',m.runtime_publication['catalog_freshness']['state'])

    def test_curated_conflict_retains_value(self):
        b=builder();b.apply_provider_inventory([dict(chapter='1',volume='2')],'provider')
        b.apply_curated(patch());b.apply_wikipedia(bundle()['wikipedia']);m=b.build()
        self.assertEqual('1',m.chapter('1').volume.value)
        self.assertTrue(m.runtime_publication['catalog_freshness']['blocking'])

    def test_curated_projection_outranks_provider_and_detects_wiki_overlap(self):
        b=builder();b.apply_curated(patch());data=bundle();data['wikipedia']['chapters'][0]['volume']='2'
        b.apply_wikipedia(data['wikipedia']);m=b.build()
        projection=build_publication_projection([dict(chapter='1',volume='3')],m)
        self.assertEqual('1',projection.chapters[0].effective_volume.value)
        self.assertEqual('CONFLICT_REVIEW',m.runtime_publication['catalog_freshness']['state'])

    def test_complete_snapshot_allows_released_live_extension(self):
        p=patch();p['coverage_contract']=dict(kind='complete_publication_snapshot',complete=True,volumes=['1'],chapter_identifiers=['1'])
        b=builder();b.apply_curated(p);data=bundle();data['wikipedia']['volumes'].append(dict(number='2',release_status='released'))
        data['wikipedia']['chapters'].append(dict(data['wikipedia']['chapters'][0],number='2',volume='2',source_record_id='row:2'))
        b.apply_wikipedia(data['wikipedia']);m=b.build()
        self.assertEqual('2',m.chapter('2').volume.value)
        self.assertEqual('EXTENSION_AVAILABLE',m.runtime_publication['catalog_freshness']['state'])

    def test_partial_released_extension_does_not_invent_membership(self):
        data=bundle();data['wikipedia']['volumes'].append(dict(number='2',release_status='released'))
        b=builder();b.apply_provider_inventory([dict(chapter='2')]);b.apply_wikipedia(data['wikipedia'])
        self.assertFalse(b.build().chapter('2').volume.present)

    def test_future_explicit_contents_do_not_map_acquisition(self):
        data=bundle();data['wikipedia']['volumes'][0]['release_date']='2026-11-04'
        b=builder();b.apply_provider_inventory([dict(chapter='1')]);b.apply_wikipedia(data['wikipedia'])
        self.assertFalse(build_publication_projection([dict(chapter='1')],b.build()).chapters[0].effective_volume.present)

    def test_bibliography_never_assigns_chapters(self):
        b=builder();b.apply_provider_inventory([dict(chapter='2')]);b.apply_bookwalker(dict(match=dict(publication_id='series/1'),volumes=[dict(number='1',release_status='released')]))
        self.assertFalse(b.build().chapter('2').volume.present)

    def test_revision_only_change_is_nonblocking(self):
        data=bundle();old=source_fingerprints(data);data['wikipedia']['chapters'][0]['source_revision_id']='3'
        p=patch();p['source_fingerprints']=old
        state=catalog_freshness(p,dict(projection=[],source_fingerprints=source_fingerprints(data)))
        self.assertEqual('SOURCE_CHANGED',state['state']);self.assertFalse(state['blocking'])

    def test_sparse_and_identity_only_legacy_have_no_complete_coverage(self):
        for p in (patch(),dict(status='matched',fields=[])):
            self.assertIsNone(catalog_freshness(p,dict(projection=[]))['curated_coverage'])

    def test_completed_snapshot_remains_current(self):
        p=patch();p['coverage_contract']=dict(kind='complete_publication_snapshot',complete=True,volumes=['1'],chapter_identifiers=['1'])
        self.assertEqual('CURRENT',catalog_freshness(p,dict(projection=[dict(chapter='1',_effective_volume='1',_volume_source='wikipedia')],release_boundary=dict(released_volumes=['1'])))['state'])

    def test_product_controls_are_scoped_and_preorder_wins(self):
        uuid='12345678-1234-1234-1234-123456789012'
        card='<div class="m-book-item"><a class="m-book-item__title" title="Series 1" href="https://bookwalker.jp/de'+uuid+'/"></a><ul class="m-book-item__btn-box"><a onclick="addToCartBA(\''+uuid+'\',this)"></a></ul>'
        self.assertEqual('released',_cards(card)[0].release_status)
        self.assertEqual('preorder',_cards(card.replace('</ul>','<a class="reserve"></a></ul>'))[0].release_status)

    def test_wikipedia_release_parser_ignores_access_date(self):
        adapter=WikipediaPublicationAdapter();adapter._wikitext=lambda _: '{{Graphic novel list|VolumeNumber=1|OriginalRelDate=November 4, 2026<ref>{{Cite web|access-date=October 1, 2026}}</ref>}}'
        volume=adapter._parse_graphic_lists('Series')[0][0]
        self.assertEqual('2026-11-04',volume.release_date)

    def test_current_cache_reused_and_stale_cache_exposes_new_release(self):
        class Wiki:
            pattern_id='fixture';parser_version='1'
            def match_publication(self,_):return PublicationMatch('wikipedia','','','no_match','fixture')
        class Book:
            count=1;calls=0
            def match_publication(self,_):
                self.calls+=1;return PublicationMatch('bookwalker','series/1','Series','confident','fixture',edition='original',edition_id='series/1')
            def get_volume_list(self,_):return tuple(PublicationVolume(str(n),release_status='released') for n in range(1,self.count+1))
            def get_volume_covers(self,_):return tuple(PublicationArtwork('https://fixture/'+str(n),'volume',str(n),'bookwalker','exact',edition_id='series/1') for n in range(1,self.count+1))
            def get_edition_artwork(self,_):return ()
            def get_description(self,_):return ''
            def catalog_metadata(self,_):return dict(canonical_complete=True,complete=True)
        now=[0.];book=Book()
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        cache=SearchMetadataCache(Path(folder.name)/'cache.db',clock=lambda:now[0]);self.addCleanup(cache.close)
        if cache:
            service=ReferenceMetadataService(cache,Wiki(),book)
            evidence=dict(title='Series',edition='original',reference_key='fixture:series')
            first=service.lookup('fixture',evidence);book.count=2
            warm=service.lookup('fixture',evidence)
            self.assertEqual(1,book.calls);self.assertEqual('1',release_boundary(warm)['latest_released_volume'])
            now[0]=IDENTITY_TTL+1
            refreshed=service.lookup('fixture',evidence)
            self.assertEqual(2,book.calls);self.assertEqual('2',release_boundary(refreshed)['latest_released_volume'])


if __name__=='__main__':unittest.main()
