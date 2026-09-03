import tempfile
import threading
import unittest
import urllib.error
from concurrent.futures import CancelledError
from pathlib import Path

from chapter_output import ChapterOutputMode, plan_chapter_outputs, resolve_volume_evidence
from reference_integration import (
    BOOKWALKER_CACHE_CONTRACT, ReferenceMetadataService, canonical_publication_context,
    canonical_reference_alias, chapter_metadata_label, fallback_source_label,
    is_placeholder_chapter_title, merge_wikipedia_chapters, preferred_description,
    _google_targets,
)
from reference_metadata import PublicationArtwork, PublicationChapter, PublicationMatch, PublicationVolume
from search_cache import IDENTITY_TTL, SearchMetadataCache
from workflow_state import HighPriestessState


class ReferenceIntegrationTests(unittest.TestCase):
    def test_google_targets_only_uncovered_canonical_volumes(self):
        wikipedia={'volumes':[{'number':str(number)} for number in (1,2,3)]}
        self.assertEqual(('2',),_google_targets({
            'wikipedia':wikipedia,
            'bookwalker':{'covers':[{'volume':'1'},{'volume':'3'}]},
        }))
        self.assertEqual((),_google_targets({
            'wikipedia':wikipedia,
            'bookwalker':{'covers':[{'volume':str(number)} for number in (1,2,3)]},
        }))
        self.assertEqual(('1','2','3'),_google_targets({
            'wikipedia':wikipedia,'bookwalker':{'covers':[]},
        }))

    def test_configured_google_key_refreshes_legacy_unkeyed_cache_once(self):
        class Wiki:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self,_evidence):
                return PublicationMatch('wikipedia','wiki-work','Work','confident','fixture')
            def get_structure_page(self,_match): return 'List of Work chapters'
            def get_chapter_list(self,_match):
                return (PublicationChapter('1','Chapter','1','chapter','wikipedia'),)
            def get_volume_list(self,_match): return (PublicationVolume('1'),)
        class Book:
            def match_publication(self,_evidence):
                return PublicationMatch('bookwalker','','','no_match','fixture')
        class Google:
            supports_detail_cache=False; api_key='fake-configured-key'
            def __init__(self): self.calls=0
            def resolve(self,_context,targets):
                self.calls+=1
                return {
                    'cache_contract':'google-books-artwork-v2',
                    'detail_cache_contract':'google-books-volume-detail-v1',
                    'status':'valid','configuration_status':'configured',
                    'key_source':'local_private_file','target_volumes':list(targets),
                    'covers':[],'candidates':[],'trusted_series_ids':[],
                }
        evidence={'title':'Work','creators':('Creator',),'requested_language':'en',
                  'edition':'original','edition_profile':'standard','reference_key':'work'}
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3')
            cache.put_reference_catalog('google:google-books-artwork-v2:work:en:standard',{
                'cache_contract':'google-books-artwork-v2',
                'detail_cache_contract':'google-books-volume-detail-v1',
                'status':'valid','target_volumes':['1'],'covers':[],'candidates':[],
            })
            google=Google(); service=ReferenceMetadataService(cache,Wiki(),Book(),google)
            first=service.lookup('work',evidence)
            second=service.lookup('work',evidence)
            self.assertEqual((1,'configured','hit'),(
                google.calls,first['google_books']['configuration_status'],
                second['google_books']['cache_state'],
            ))
            cache.close()
    def test_reference_lookup_cancelled_before_start_makes_no_source_requests(self):
        class Source:
            def __init__(self): self.calls=0
            def match_publication(self,_evidence):
                self.calls+=1
                return PublicationMatch('fixture','','','no_match','fixture')
        wiki=Source(); book=Source(); google=Source()
        with self.assertRaises(CancelledError):
            ReferenceMetadataService(None,wiki,book,google).lookup(
                'work',{'title':'Work'},should_cancel=lambda:True,
            )
        self.assertEqual((0,0,0),(wiki.calls,book.calls,google.calls))

    def test_reference_lookup_cancelled_during_wikipedia_stops_before_bookwalker(self):
        cancelled={'value':False}
        class Wiki:
            def match_publication(self,_evidence):
                cancelled['value']=True
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class Book:
            def __init__(self): self.calls=0
            def match_publication(self,_evidence):
                self.calls+=1
                return PublicationMatch('bookwalker','','','no_match','fixture')
        book=Book()
        with self.assertRaises(CancelledError):
            ReferenceMetadataService(None,Wiki(),book,object()).lookup(
                'work',{'title':'Work'},should_cancel=lambda:cancelled['value'],
            )
        self.assertEqual(0,book.calls)

    def test_reference_lookup_cancelled_during_bookwalker_stops_before_catalog_and_google(self):
        cancelled={'value':False}
        class Wiki:
            def match_publication(self,_evidence):
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class Book:
            def __init__(self): self.volume_calls=0
            def match_publication(self,_evidence):
                cancelled['value']=True
                return PublicationMatch('bookwalker','series/1','Work','confident','fixture')
            def get_volume_list(self,_match):
                self.volume_calls+=1
                return ()
        class Google:
            def __init__(self): self.calls=0
            def resolve(self,*_args): self.calls+=1; return {}
        book=Book(); google=Google()
        with self.assertRaises(CancelledError):
            ReferenceMetadataService(None,Wiki(),book,google).lookup(
                'work',{'title':'Work'},should_cancel=lambda:cancelled['value'],
            )
        self.assertEqual((0,0),(book.volume_calls,google.calls))

    def test_cancelled_refresh_does_not_replace_existing_last_known_good_catalog(self):
        cancelled={'value':False}
        existing={
            'cache_contract':BOOKWALKER_CACHE_CONTRACT,
            'match':{'confidence':'confident','publication_id':'series/old'},
            'covers':[{'volume':'1','url':'old'}],
        }
        class Hit:
            def __init__(self,value): self.value=value
        class Cache:
            def __init__(self): self.puts=[]; self.deletes=[]
            def get_reference_structure(self,_key): return None
            def get_reference_catalog(self,key):
                if key == 'work:work:original':
                    return Hit({'resolved_key':'series/old:series/old'})
                return None
            def get(self,kind,key,allow_stale=False):
                if kind == 'reference_catalog' and key == 'series/old:series/old' and allow_stale:
                    return Hit(existing)
                return None
            def put_reference_structure(self,key,value): self.puts.append((key,value))
            def put_reference_catalog(self,key,value): self.puts.append((key,value))
            def delete(self,*args): self.deletes.append(args)
        class Wiki:
            def match_publication(self,_evidence):
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class Book:
            def match_publication(self,_evidence):
                cancelled['value']=True
                return PublicationMatch('bookwalker','series/new','Work','confident','fixture')
        cache=Cache()
        with self.assertRaises(CancelledError):
            ReferenceMetadataService(cache,Wiki(),Book(),object()).lookup(
                'work',{'title':'Work','edition':'original'},
                should_cancel=lambda:cancelled['value'],
            )
        self.assertEqual([],cache.puts)
        self.assertEqual([],cache.deletes)
        self.assertEqual('old',existing['covers'][0]['url'])

    def test_stale_overlapping_lookup_stops_and_replacement_completes(self):
        started=threading.Event(); release=threading.Event(); cancelled=threading.Event()
        outcomes=[]
        class SlowWiki:
            def match_publication(self,_evidence):
                started.set(); release.wait()
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class NoMatch:
            def match_publication(self,_evidence):
                return PublicationMatch('fixture','','','no_match','fixture')
        class Google:
            def resolve(self,_context,_targets):
                return {'status':'disabled','covers':[],'candidates':[],'target_volumes':[]}
        def stale_lookup():
            try:
                ReferenceMetadataService(None,SlowWiki(),NoMatch(),Google()).lookup(
                    'old',{'title':'Old'},should_cancel=cancelled.is_set,
                )
            except CancelledError:
                outcomes.append('old_cancelled')
        thread=threading.Thread(target=stale_lookup)
        thread.start(); self.assertTrue(started.wait(2))
        cancelled.set(); release.set()
        replacement=ReferenceMetadataService(None,NoMatch(),NoMatch(),Google()).lookup(
            'new',{'title':'New'},should_cancel=lambda:False,
        )
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(['old_cancelled'],outcomes)
        self.assertEqual('new',replacement['work_key'])

    def test_google_gap_fill_cache_is_cold_warm_restart_invariant(self):
        class Wiki:
            pattern_id='fixture'; parser_version='5'
            def match_publication(self,_evidence):
                return PublicationMatch('wikipedia','wiki-work','Work','confident','fixture')
            def get_structure_page(self,_match): return 'List of Work chapters'
            def get_chapter_list(self,_match):
                return tuple(PublicationChapter(str(n),'',str(n),'chapter','wikipedia') for n in (1,2))
            def get_volume_list(self,_match):
                return tuple(PublicationVolume(str(n),source='wikipedia') for n in (1,2))
        class Book:
            def match_publication(self,_evidence):
                return PublicationMatch('bookwalker','book-series','Work','confident','fixture',edition='original',edition_id='book-series')
            def get_volume_list(self,_match): return (PublicationVolume('1'),)
            def get_volume_covers(self,_match):
                return (PublicationArtwork('book://1','volume','1','bookwalker','exact','book-series','book-series','b1'),)
            def get_edition_artwork(self,_match): return ()
            def get_description(self,_match): return ''
        class Google:
            def __init__(self): self.calls=[]
            def resolve(self,_context,targets):
                self.calls.append(tuple(targets))
                return {'cache_contract':'google-books-artwork-v2',
                        'detail_cache_contract':'google-books-volume-detail-v1',
                        'status':'valid','target_volumes':list(targets),
                        'trusted_series_ids':['g-series'],'candidates':[],'network':{'requests':1},'covers':[
                            {'url':'google://2','artwork_type':'volume','volume':'2','source':'google_books',
                             'confidence':'exact','publication_id':'g-series','edition_id':'standard:en','volume_id':'g2'}]}
        evidence={'title':'Work','aliases':(),'creators':('Creator',),'edition':'original',
                  'edition_profile':'standard','requested_language':'en','reference_key':'work|standard'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cache.sqlite3'; cache=SearchMetadataCache(path); google=Google()
            cold=ReferenceMetadataService(cache,Wiki(),Book(),google).lookup('work',evidence)
            warm=ReferenceMetadataService(cache,Wiki(),Book(),Google()).lookup('work',evidence)
            cache.close(); restarted_cache=SearchMetadataCache(path)
            restarted=ReferenceMetadataService(restarted_cache,Wiki(),Book(),Google()).lookup('work',evidence)
            self.assertEqual([('2',)],google.calls)
            self.assertEqual(('google://2','google://2','google://2'),tuple(
                row['google_books']['covers'][0]['url'] for row in (cold,warm,restarted)
            ))
            self.assertEqual(('refreshed','hit','hit'),tuple(
                row['google_books']['cache_state'] for row in (cold,warm,restarted)
            ))
            restarted_cache.close()

    def test_canonical_publication_key_is_provider_invariant_and_edition_separated(self):
        base={
            'canonical_title':'One-Punch Man','canonical_author':'ONE','provider_author':'One',
            'identity_confidence':'high','edition':'original',
            'trusted_aliases':('ワンパンマン',),
        }
        contexts=[]
        for provider in ('mangadex','mangapill','weebcentral'):
            evidence=dict(base,provider_url=f'https://{provider}.example/work',provider_id=provider)
            contexts.append(canonical_publication_context('family-opm',evidence))
        self.assertEqual(1,len({row.reference_key for row in contexts}))
        self.assertTrue(all(row.shareable for row in contexts))
        color=canonical_publication_context('family-opm',dict(base,edition='official_color'))
        fan=canonical_publication_context('family-opm',dict(base,edition='fan_color'))
        self.assertEqual(3,len({contexts[0].reference_key,color.reference_key,fan.reference_key}))
        ambiguous=canonical_publication_context('family-opm',dict(base,edition='unknown'))
        self.assertFalse(ambiguous.shareable)
        self.assertEqual('',ambiguous.reference_key)

    def test_same_normalized_title_distinct_canonical_works_do_not_collide(self):
        evidence={'canonical_title':'Example','canonical_author':'Creator',
                  'provider_author':'Creator','identity_confidence':'high','edition':'original'}
        first=canonical_publication_context('anilist:100',evidence)
        second=canonical_publication_context('anilist:200',evidence)
        self.assertTrue(first.shareable and second.shareable)
        self.assertNotEqual(first.reference_key,second.reference_key)

    def test_creator_formatting_is_safe_but_material_conflict_isolated(self):
        base={'canonical_title':'One Piece','canonical_author':'Eiichiro Oda',
              'identity_confidence':'high','edition':'original'}
        ordered=canonical_publication_context('family-one-piece',dict(base,provider_author='ODA Eiichiro'))
        conflict=canonical_publication_context('family-one-piece',dict(base,provider_author='Another Creator'))
        self.assertTrue(ordered.shareable)
        self.assertFalse(conflict.shareable)
        self.assertIn('creator contradiction',conflict.shareability_reason)

    def test_context_exports_only_canonically_equivalent_creator_aliases(self):
        context=canonical_publication_context('anilist:30012|anilist:41330',{
            'canonical_title':'Bleach','canonical_author':'Kubo Tite',
            'canonical_creator_aliases':('Kubo Tite','Tite Kubo','Other Person'),
            'provider_author':'Tite Kubo','identity_confidence':'high','edition':'original',
        })
        self.assertTrue(context.shareable)
        self.assertEqual(('Kubo Tite','Tite Kubo'),context.canonical_creator_aliases)
        self.assertEqual(('Kubo Tite','Tite Kubo'),context.lookup_evidence()['creator_aliases'])

    def test_context_preserves_structured_multi_creator_components(self):
        context=canonical_publication_context('anilist:30002|kitsu:8',{
            'canonical_title':'Berserk',
            'canonical_creators':('Creator A','Creator B'),
            'canonical_author':'Creator A, Creator B',
            'canonical_creator_aliases':('Creator A','Creator B'),
            'provider_author':'Creator A, Creator B',
            'edition':'original','identity_confidence':'high',
        })
        self.assertEqual(('Creator A','Creator B'),context.canonical_creators)
        evidence=context.lookup_evidence()
        self.assertEqual(('Creator A','Creator B'),evidence['creators'])
        self.assertEqual(('Creator A','Creator B'),evidence['creator_aliases'])

    def test_equivalent_provider_switch_reuses_canonical_bookwalker_snapshot(self):
        class NoWikipedia:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self,_evidence):
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class Bookwalker:
            calls=0; evidence=[]
            def match_publication(self,evidence):
                self.calls += 1; self.evidence.append(dict(evidence))
                return PublicationMatch('bookwalker','series/999','One-Punch Man','confident','fixture',
                                        edition='original',edition_id='series/999')
            def get_volume_list(self,_match): return ()
            def get_volume_covers(self,_match):
                return tuple(PublicationArtwork(f'https://covers/{n}.jpg','volume',str(n),'bookwalker','exact',
                                                'series/999','series/999',f'uuid-{n}') for n in range(1,38))
            def get_edition_artwork(self,_match): return ()
            def get_description(self,_match): return ''
        context=canonical_publication_context('family-opm',{
            'canonical_title':'One-Punch Man','canonical_author':'ONE','provider_author':'ONE',
            'identity_confidence':'high','edition':'original','trusted_aliases':('ワンパンマン',),
        })
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3'); adapter=Bookwalker()
            first=ReferenceMetadataService(cache,NoWikipedia(),adapter).lookup(
                context.reference_key,context.lookup_evidence())
            second=ReferenceMetadataService(cache,NoWikipedia(),adapter).lookup(
                context.reference_key,context.lookup_evidence())
            self.assertEqual((37,37,1,'hit'),(
                len(first['bookwalker']['covers']),len(second['bookwalker']['covers']),
                adapter.calls,second['bookwalker']['cache_state'],
            ))
            self.assertEqual('One-Punch Man',adapter.evidence[0]['title'])
            self.assertNotIn('provider_url',adapter.evidence[0])
            cache.close()

    def test_publication_level_last_known_good_rejects_weaker_and_accepts_stronger(self):
        class NoWikipedia:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self,_evidence): return PublicationMatch('wikipedia','','','no_match','fixture')
        class Bookwalker:
            def __init__(self,count): self.count=count
            def match_publication(self,_evidence):
                return PublicationMatch('bookwalker','series/999','Series','confident','fixture',
                                        edition='original',edition_id='series/999')
            def get_volume_list(self,_match): return ()
            def get_volume_covers(self,_match):
                return tuple(PublicationArtwork(f'https://covers/{n}.jpg','volume',str(n),'bookwalker','exact',
                                                'series/999','series/999',f'uuid-{n}') for n in range(1,self.count+1))
            def get_edition_artwork(self,_match): return ()
            def get_description(self,_match): return ''
        now=[0.0]; evidence={'title':'Series','edition':'original','reference_key':'series|standard'}
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3',clock=lambda:now[0])
            first=ReferenceMetadataService(cache,NoWikipedia(),Bookwalker(37)).lookup('ignored',evidence)
            now[0]=IDENTITY_TTL+1
            weaker=ReferenceMetadataService(cache,NoWikipedia(),Bookwalker(24)).lookup('ignored',evidence)
            now[0]=2*(IDENTITY_TTL+1)
            stronger=ReferenceMetadataService(cache,NoWikipedia(),Bookwalker(38)).lookup('ignored',evidence)
            self.assertEqual((37,'last_known_good',38),(
                len(first['bookwalker']['covers']),weaker['bookwalker']['cache_state'],
                len(stronger['bookwalker']['covers']),
            ))
            self.assertEqual(BOOKWALKER_CACHE_CONTRACT,stronger['bookwalker']['cache_contract'])
            cache.close()

    def test_partial_bookwalker_refresh_does_not_overwrite_complete_catalog(self):
        class NoWikipedia:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self,_evidence): return PublicationMatch('wikipedia','','','no_match','fixture')
        class Bookwalker:
            def __init__(self,partial=False): self.partial=partial
            def match_publication(self,_evidence):
                return PublicationMatch('bookwalker','series/999','Series','confident','fixture',edition='original',edition_id='series/999')
            def get_volume_list(self,_match): return ()
            def get_volume_covers(self,_match):
                count=1 if self.partial else 2
                return tuple(PublicationArtwork(f'https://covers/{n}.jpg','volume',str(n),'bookwalker','exact','series/999','series/999',f'u{n}') for n in range(1,count+1))
            def get_edition_artwork(self,_match): return ()
            def get_description(self,_match): return ''
            def catalog_metadata(self,_match):
                return {'complete':not self.partial,'partial':self.partial,'pages_fetched':1,'expected_total':2}
        now=[0.0]; evidence={'title':'Series','edition':'original','reference_key':'series|standard'}
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3',clock=lambda:now[0])
            ReferenceMetadataService(cache,NoWikipedia(),Bookwalker()).lookup('ignored',evidence)
            now[0]=IDENTITY_TTL+1
            result=ReferenceMetadataService(cache,NoWikipedia(),Bookwalker(True)).lookup('ignored',evidence)
            self.assertEqual(('last_known_good',2,True),(result['bookwalker']['cache_state'],
                len(result['bookwalker']['covers']),result['bookwalker']['catalog']['complete']))
            cache.close()

    def test_optional_external_id_compatibility_reuses_validated_reference_but_rejects_conflict(self):
        class Wiki:
            pattern_id='fixture'; parser_version='5'
            def __init__(self,fail=False): self.calls=0; self.fail=fail
            def match_publication(self,_evidence):
                self.calls+=1
                if self.fail: raise RuntimeError('must not cross-reuse')
                return PublicationMatch('wikipedia','wiki-bleach','Bleach','confident','fixture')
            def get_structure_page(self,_match): return 'List of Bleach chapters'
            def get_chapter_list(self,_match): return (PublicationChapter('1','Death & Strawberry','1'),)
            def get_volume_list(self,_match): return (PublicationVolume('1'),)
        class NoBook:
            def match_publication(self,_evidence): return PublicationMatch('bookwalker','','','no_match','fixture')
        base={'canonical_title':'Bleach','canonical_author':'Kubo Tite','provider_author':'Tite Kubo',
              'identity_confidence':'high','edition':'original'}
        rich=canonical_publication_context('anilist:269|kitsu:12',base)
        sparse=canonical_publication_context('anilist:269',base)
        conflict=canonical_publication_context('anilist:999',base)
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3'); first=Wiki()
            ReferenceMetadataService(cache,first,NoBook()).lookup(rich.reference_key,rich.lookup_evidence())
            reused=ReferenceMetadataService(cache,Wiki(True),NoBook()).lookup(sparse.reference_key,sparse.lookup_evidence())
            rejected_adapter=Wiki(True)
            rejected=ReferenceMetadataService(cache,rejected_adapter,NoBook()).lookup(conflict.reference_key,conflict.lookup_evidence())
            self.assertEqual(('compatible_hit',1),(reused['wikipedia']['cache_state'],len(reused['wikipedia']['chapters'])))
            self.assertEqual(1,rejected_adapter.calls)
            self.assertEqual('transient_failure',rejected['wikipedia']['status'])
            cache.close()

    def test_google_outer_cache_revalidates_current_target_set(self):
        class Google:
            def __init__(self): self.calls=[]
            def resolve(self,_context,targets):
                self.calls.append(tuple(targets))
                return {'cache_contract':'google-books-artwork-v2','detail_cache_contract':'google-books-volume-detail-v1',
                        'status':'valid','target_volumes':list(targets),'covers':[],'candidates':[]}
        evidence={'title':'Work','creators':('Creator',),'edition':'original','edition_profile':'standard',
                  'requested_language':'en','reference_key':'target-work'}
        wiki=self._wiki((PublicationChapter('1','First','1'),PublicationChapter('2','Second','2')),
                        (PublicationVolume('1'),PublicationVolume('2')))
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3'); google=Google()
            ReferenceMetadataService(cache,wiki,self._bookwalker(),google).lookup('work',evidence)
            key='google:google-books-artwork-v2:target-work:en:standard'
            cached=dict(cache.get_reference_catalog(key).value); cached['target_volumes']=['99']
            cache.put_reference_catalog(key,cached)
            second=Google(); ReferenceMetadataService(cache,self._wiki(),self._bookwalker(),second).lookup('work',evidence)
            self.assertEqual([('1','2')],second.calls)
            cache.close()

    def test_known_standard_control_matrix_is_provider_invariant(self):
        controls=(
            ('Attack on Titan','family-aot','series/aot',30),
            ('Chainsaw Man','family-csm','series/csm',24),
            ('One-Punch Man','family-opm','series/opm',37),
            ('One Piece','family-op','series/op',57),
        )
        class NoWikipedia:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self,_evidence): return PublicationMatch('wikipedia','','','no_match','fixture')
        for title,family,publication_id,count in controls:
            with self.subTest(title=title), tempfile.TemporaryDirectory() as folder:
                class Bookwalker:
                    calls=0
                    def match_publication(self,evidence):
                        self.calls += 1
                        return PublicationMatch('bookwalker',publication_id,evidence['title'],'confident','fixture',
                                                edition='original',edition_id=publication_id)
                    def get_volume_list(self,_match): return ()
                    def get_volume_covers(self,_match):
                        return tuple(PublicationArtwork(f'https://covers/{n}.jpg','volume',str(n),'bookwalker','exact',
                                                        publication_id,publication_id,f'uuid-{n}')
                                     for n in range(1,count+1))
                    def get_edition_artwork(self,_match): return ()
                    def get_description(self,_match): return ''
                contexts=tuple(canonical_publication_context(family,{
                    'canonical_title':title,'canonical_author':'Creator','provider_author':'Creator',
                    'identity_confidence':'high','edition':'original','provider_id':provider,
                }) for provider in ('mangadex','mangapill','weebcentral'))
                self.assertEqual(1,len({row.reference_key for row in contexts}))
                cache=SearchMetadataCache(Path(folder)/'cache.sqlite3'); adapter=Bookwalker()
                outputs=tuple(ReferenceMetadataService(cache,NoWikipedia(),adapter).lookup(
                    context.reference_key,context.lookup_evidence())['bookwalker'] for context in contexts)
                self.assertEqual(1,adapter.calls)
                self.assertEqual({publication_id},{row['match']['publication_id'] for row in outputs})
                self.assertEqual({count},{len(row['covers']) for row in outputs})
                cache.close()
    @staticmethod
    def _wiki(rows=(), volumes=(), failure=None):
        class Wiki:
            pattern_id='graphic-novel-list-explicit-chapter-list-v1'
            parser_version='2'
            calls=0
            def match_publication(self, _evidence):
                self.calls += 1
                if failure:
                    raise failure
                return PublicationMatch('wikipedia','1','Attack on Titan','confident','fixture')
            def get_structure_page(self, _match): return 'List of Attack on Titan chapters'
            def get_chapter_list(self, _match): return tuple(rows)
            def get_volume_list(self, _match): return tuple(volumes)
        return Wiki()

    @staticmethod
    def _bookwalker(description=''):
        class Bookwalker:
            def match_publication(self, _evidence):
                return PublicationMatch('bookwalker','','','no_match','fixture')
        return Bookwalker()

    def test_obsolete_zero_row_wikipedia_cache_is_refreshed_by_parser_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3')
            pointer='work:attack'; legacy='page:1:List of Attack on Titan chapters'
            cache.put_reference_structure(pointer,{'resolved_key':legacy})
            cache.put_reference_structure(legacy,{'match':{'title':'Attack on Titan'},'chapters':[],
                                                   'volumes':[{'number':'1'}]})
            wiki=self._wiki((PublicationChapter('1','To You, in 2000 Years','1','chapter'),),
                            (PublicationVolume('1'),))
            result=ReferenceMetadataService(cache,wiki,self._bookwalker()).lookup('attack',{'title':'Attack on Titan'})
            self.assertEqual((1,'refreshed_after_invalidation'),
                             (len(result['wikipedia']['chapters']),result['wikipedia']['cache_state']))
            self.assertEqual(1,wiki.calls)
            stored=cache.get_reference_structure(cache.get_reference_structure(pointer).value['resolved_key']).value
            self.assertEqual(('wikipedia-structure-v3-collection','2','valid_with_data'),
                             (stored['cache_contract'],stored['parser_version'],stored['status']))
            cache.close()

    def test_current_wikipedia_cache_reuses_rows_and_last_known_good_survives_failure(self):
        now=[0.0]
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3',clock=lambda:now[0])
            rows=(PublicationChapter('1','To You, in 2000 Years','1','chapter'),)
            first_wiki=self._wiki(rows,(PublicationVolume('1'),))
            ReferenceMetadataService(cache,first_wiki,self._bookwalker()).lookup('attack',{'title':'Attack on Titan'})
            cached=ReferenceMetadataService(cache,self._wiki(failure=AssertionError('cache miss')),
                                              self._bookwalker()).lookup('attack',{'title':'Attack on Titan'})
            self.assertEqual(('hit',1),(cached['wikipedia']['cache_state'],len(cached['wikipedia']['chapters'])))
            now[0]=IDENTITY_TTL + 1
            recovered=ReferenceMetadataService(cache,self._wiki(failure=RuntimeError('HTTP 429')),
                                                self._bookwalker()).lookup('attack',{'title':'Attack on Titan'})
            self.assertEqual(('last_known_good',1),
                             (recovered['wikipedia']['cache_state'],len(recovered['wikipedia']['chapters'])))
            self.assertIn('429',recovered['wikipedia']['refresh_error'])
            cache.close()

    def test_supported_empty_wikipedia_result_is_not_durable_reference_data(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3')
            result=ReferenceMetadataService(cache,self._wiki((),(PublicationVolume('1'),)),
                                            self._bookwalker()).lookup('attack',{'title':'Attack on Titan'})
            self.assertEqual(('supported_empty',[]),(result['wikipedia']['status'],result['wikipedia']['chapters']))
            self.assertIsNone(cache.get_reference_structure('work:attack'))
            cache.close()

    def test_bookwalker_description_survives_cache_without_display_precedence(self):
        class NoWikipedia:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self, _evidence):
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class Bookwalker:
            def match_publication(self, _evidence):
                return PublicationMatch('bookwalker','series/4214','Attack','confident','fixture',
                                        edition_id='series/4214')
            def get_volume_list(self, _match): return ()
            def get_volume_covers(self, _match): return ()
            def get_edition_artwork(self, _match): return ()
            def get_description(self, _match): return 'Validated BOOK☆WALKER Description'
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3')
            first=ReferenceMetadataService(cache,NoWikipedia(),Bookwalker()).lookup(
                'attack',{'title':'Attack on Titan','edition':'original'}
            )
            second=ReferenceMetadataService(cache,NoWikipedia(),Bookwalker()).lookup(
                'attack',{'title':'Attack on Titan','edition':'original'}
            )
            self.assertEqual('Validated BOOK☆WALKER Description',first['bookwalker']['description'])
            self.assertEqual(first['bookwalker']['description'],second['bookwalker']['description'])
            self.assertEqual('AniList',
                             preferred_description(second['bookwalker']['description'],'AniList','Kitsu','Wiki','Provider'))
            cache.close()

    def test_obsolete_bookwalker_cache_contract_is_not_reused(self):
        class NoWikipedia:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self,_evidence): return PublicationMatch('wikipedia','','','no_match','fixture')
        class Bookwalker:
            calls=0
            def match_publication(self,_evidence):
                self.calls += 1
                return PublicationMatch('bookwalker','series/new','Series','confident','fixture',
                                        edition='original',edition_id='series/new')
            def get_volume_list(self,_match): return ()
            def get_volume_covers(self,_match):
                return (PublicationArtwork('https://covers/new.jpg','volume','1','bookwalker','exact',
                                           'series/new','series/new','uuid-new'),)
            def get_edition_artwork(self,_match): return ()
            def get_description(self,_match): return ''
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3')
            pointer='work:series|standard:original'; resolved='series/old:series/old'
            cache.put_reference_catalog(pointer,{'resolved_key':resolved})
            cache.put_reference_catalog(resolved,{
                'match':{'confidence':'confident','publication_id':'series/old'},
                'covers':[{'url':'https://covers/old.jpg'}],
            })
            adapter=Bookwalker()
            result=ReferenceMetadataService(cache,NoWikipedia(),adapter).lookup(
                'series|standard',{'title':'Series','edition':'original','reference_key':'series|standard'})
            self.assertEqual((1,'series/new',BOOKWALKER_CACHE_CONTRACT),(
                adapter.calls,result['bookwalker']['match']['publication_id'],
                result['bookwalker']['cache_contract'],
            ))
            cache.close()

    def test_bookwalker_last_known_good_survives_transient_refresh_failure(self):
        class NoWikipedia:
            pattern_id='fixture'; parser_version='1'
            def match_publication(self, _evidence):
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class Bookwalker:
            def __init__(self, failure=None): self.failure=failure
            def match_publication(self, _evidence):
                if self.failure: raise self.failure
                return PublicationMatch('bookwalker','series/4214','Attack','confident','fixture',
                                        edition='original',edition_id='series/4214')
            def get_volume_list(self, _match): return (PublicationVolume('1'),)
            def get_volume_covers(self, _match):
                return (PublicationArtwork('https://example/1.jpg','volume','1','bookwalker','exact',
                                           'series/4214','series/4214','uuid-1'),)
            def get_edition_artwork(self, _match): return ()
            def get_description(self, _match): return 'Description'
        now=[0.0]
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3',clock=lambda:now[0])
            ReferenceMetadataService(cache,NoWikipedia(),Bookwalker()).lookup(
                'attack',{'title':'Attack on Titan','edition':'original'}
            )
            now[0]=IDENTITY_TTL + 1
            recovered=ReferenceMetadataService(cache,NoWikipedia(),Bookwalker(RuntimeError('timeout'))).lookup(
                'attack',{'title':'Attack on Titan','edition':'original'}
            )
            self.assertEqual(('last_known_good',1),(
                recovered['bookwalker']['cache_state'],len(recovered['bookwalker']['covers'])
            ))
            self.assertIn('timeout',recovered['bookwalker']['refresh_error'])
            cache.close()

    def test_exact_trusted_external_alias_bridges_attack_provider_title(self):
        candidate={
            'service':'anilist','primary_title':'Attack on Titan',
            'titles':('Attack on Titan','Shingeki no Kyojin','進撃の巨人'),
        }
        self.assertEqual('Attack on Titan',canonical_reference_alias('Shingeki no Kyojin',(candidate,)))
        self.assertEqual('',canonical_reference_alias('Shingeki no Kyojin',(
            candidate,{'service':'kitsu','primary_title':'Attack on Titan: Lost Girls',
                       'titles':('Attack on Titan: Lost Girls','Shingeki no Kyojin')},
        )))

    def test_bookwalker_404_remains_non_blocking_at_runtime_boundary(self):
        class NoWikipedia:
            def match_publication(self, _evidence):
                return PublicationMatch('wikipedia','','','no_match','fixture')
        class FailingBookwalker:
            def match_publication(self, _evidence):
                url='https://bookwalker.jp/search/?word=missing&order=score'
                raise urllib.error.HTTPError(url,404,'Not Found',{},None)
        result=ReferenceMetadataService(None,NoWikipedia(),FailingBookwalker()).lookup(
            'work',{'title':'Missing','edition':'original'}
        )
        self.assertEqual({},result['bookwalker'])
        self.assertIn('404',result['errors']['bookwalker'])

    def test_fallback_title_is_replaced_but_fallback_source_status_survives(self):
        provider=[{'id':'mp:1','chapter':'1','title':'Fallback','volume':None,
                   '_source_id':'mangapill','_fallback_reason':'missing_primary'}]
        reference=[{'number':'1','title':'To You, in 2000 Years','volume':'1','kind':'chapter'}]
        row=merge_wikipedia_chapters(provider,reference)[0]
        self.assertEqual(('To You, in 2000 Years','1','mangapill','missing_primary','wikipedia'),
                         (row['title'],row['volume'],row['_source_id'],row['_fallback_reason'],row['_title_source']))

    def test_attack_number_normalization_and_coverage_preserve_chapter_zero(self):
        provider=[
            {'id':'zero','chapter':'00','title':'','volume':None,'_source_id':'mangapill'},
            {'id':'one','chapter':'01','title':'','volume':None,'_source_id':'mangapill'},
            {'id':'one-padded','chapter':'001','title':'','volume':None,'_source_id':'mangapill'},
        ]
        merged,coverage=merge_wikipedia_chapters(
            provider,[{'number':'1','title':'To You, in 2000 Years','volume':'1','kind':'chapter'}],
            with_coverage=True,
        )
        self.assertEqual(['','',''],
                         [row['title'] for row in merged])
        self.assertEqual([None,None,None],[row['volume'] for row in merged])
        self.assertEqual((3,1,0,0,0,3),(
            coverage['provider_chapters'],coverage['reference_chapters'],coverage['chapters_matched'],
            coverage['titles_applied'],coverage['volume_assignments_applied'],
            coverage['unmapped_provider_chapters'],
        ))
        self.assertEqual(['mangapill'] * 3,[row['_source_id'] for row in merged])

    def test_decimal_matches_but_specials_and_ranges_fail_closed(self):
        provider=[
            {'chapter':'12.50','title':'','volume':None},
            {'chapter':'Special 1','title':'','volume':None},
            {'chapter':'13-14','title':'','volume':None},
        ]
        merged,coverage=merge_wikipedia_chapters(provider,[
            {'number':'12.5','title':'Decimal','volume':'4','kind':'chapter'},
            {'number':'Special 1','title':'Special','volume':'4','kind':'special'},
            {'number':'13-14','title':'Range','volume':'4','kind':'range'},
        ],with_coverage=True)
        self.assertEqual([('Decimal','4'),('',None),('',None)],
                         [(row['title'],row['volume']) for row in merged])
        self.assertEqual((1,1,2),(
            coverage['chapters_matched'],coverage['reference_chapters'],
            coverage['unmapped_provider_chapters'],
        ))

    def test_fallback_is_source_status_not_chapter_metadata(self):
        chapter={'chapter':'8','title':'Confluence','volume':'2','_source_id':'mangapill',
                 '_fallback_reason':'missing_primary'}
        self.assertEqual('Chapter 08  ·  Confluence  ·  Vol. 2',chapter_metadata_label(chapter,True))
        self.assertNotIn('Fallback',chapter_metadata_label(chapter,True))
        self.assertEqual('MangaPill · fallback',fallback_source_label('MangaPill',chapter['_fallback_reason']))
        self.assertEqual(('mangapill','missing_primary'),
                         (chapter['_source_id'],chapter['_fallback_reason']))

    def test_placeholder_fallback_title_is_not_rendered_as_metadata(self):
        chapter={'chapter':'8','title':'Fallback','volume':None,'_fallback_reason':'provider_failure'}
        self.assertEqual('Chapter 8',chapter_metadata_label(chapter,False))

    def test_useful_provider_title_and_explicit_volume_are_preserved(self):
        provider=[{'id':'md:1','chapter':'1','title':'Provider Title','volume':'7','_source_id':'mangadex'}]
        reference=[{'number':'1','title':'Reference Title','volume':'1','kind':'chapter'}]
        row=merge_wikipedia_chapters(provider,reference)[0]
        self.assertEqual(('Provider Title','7','mangadex'),(row['title'],row['volume'],row['_source_id']))

    def test_generated_number_titles_are_placeholders(self):
        self.assertTrue(is_placeholder_chapter_title('Chapter 12.5','12.5'))
        self.assertTrue(is_placeholder_chapter_title('Unknown','12'))
        self.assertFalse(is_placeholder_chapter_title('A Real Beginning','12'))

    def test_mixed_reference_mapping_keeps_unmapped_chapter_standalone(self):
        chapters=merge_wikipedia_chapters(
            [{'id':'1','chapter':'1','title':''},{'id':'2','chapter':'2','title':''}],
            [{'number':'1','title':'First','volume':'3','kind':'chapter'}],
        )
        evidence=resolve_volume_evidence(chapters,page_source_id='mangapill')
        groups=plan_chapter_outputs(chapters,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)
        self.assertEqual([('volume','3'),('chapter','2')],[(row.kind,row.identifier) for row in groups])

    def test_description_precedence_uses_one_source(self):
        self.assertEqual('AniList',preferred_description('BOOK☆WALKER','AniList','Kitsu','Wiki','Provider'))
        self.assertEqual('AniList',preferred_description('', 'AniList','Kitsu','Wiki','Provider'))

    def test_stale_reference_inventory_is_rejected_without_losing_selection(self):
        state=HighPriestessState()
        generation=state.select_provider({'source_id':'mangapill','id':'work'})
        state.apply_inventory(generation,[{'id':'1','chapter':'1'}])
        state.set_inventory_selection({'1'})
        stale=generation
        state.select_provider({'source_id':'mangadex','id':'new-work'})
        self.assertFalse(state.apply_reference_inventory(stale,[{'id':'1','title':'stale'}]))

    def test_reference_cache_namespaces_are_persistent_and_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cache.sqlite3'; cache=SearchMetadataCache(path)
            cache.put_reference_structure('work',{'chapters':[1]})
            cache.put_reference_catalog('work:original',{'covers':[2]})
            self.assertEqual({'chapters':[1]},cache.get_reference_structure('work').value)
            self.assertEqual({'covers':[2]},cache.get_reference_catalog('work:original').value)
            cache.close()

    def test_selected_description_uses_bounded_scrollable_readable_contract(self):
        source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
        self.assertIn('self.selected_synopsis_scroll=QScrollArea()',source)
        self.assertIn('self.selected_synopsis_scroll.setMaximumHeight(62)',source)
        self.assertIn("self.selected_synopsis,description,'Description: ',None",source)

    def test_runtime_description_visibility_uses_text_not_hidden_child_visibility(self):
        source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
        start=source.index('def _refresh_selected_details')
        end=source.index('def _apply_work_level_enrichment',start)
        refresh=source[start:end]
        self.assertIn('self.selected_synopsis_scroll.setVisible(bool(description))',refresh)
        self.assertNotIn('self.selected_synopsis.isVisible()',refresh)
        handler=source[source.index('def _on_reference_lookup_ready'):source.index('def _calibre_work_tags')]
        self.assertIn('description=manifest.display.description',handler)
        self.assertIn("self.loaded_metadata['description']=description.value",handler)

    def test_runtime_reference_application_keeps_provider_source_unchanged(self):
        source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
        start=source.index('def _on_reference_lookup_ready')
        end=source.index('def _calibre_work_tags',start)
        handler=source[start:end]
        self.assertNotIn('self.current_source=',handler)
        self.assertNotIn('self.current_source_id=',handler)
        self.assertIn('settle_publication_structure',handler)
        self.assertIn('_try_finalize_chapter_projection',handler)

    def test_runtime_reference_logging_reports_coverage_not_only_completion(self):
        source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
        start=source.index('def _on_reference_lookup_ready')
        end=source.index('def _calibre_work_tags',start)
        handler=source[start:end]
        self.assertIn('Publication manifest ready:',handler)
        self.assertIn('Wikipedia publication layout unsupported',handler)
        self.assertNotIn('Reference metadata applied without changing the acquisition source.',handler)
        logger=source[source.index('def _log_publication_projection'):source.index('def _try_finalize_chapter_projection')]
        self.assertIn('Acquisition projection:',logger)
        self.assertIn('Provider explicit:',logger)
        self.assertIn('Reference explicit:',logger)
        self.assertIn('Derived fractional:',logger)
        self.assertIn("if not coverage['provider_chapters']",logger)


if __name__ == '__main__':
    unittest.main()
