"""MADB tests use selected live bibliographic fixtures; never live network."""
from concurrent.futures import CancelledError
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import unittest
from calibre_plugins.manganana.metadata.references.madb_reference import MadbPublicationAdapter, candidate_query, inventory_query, _records, _book, SCHEMA, CACHE_CONTRACT
from calibre_plugins.manganana.metadata.reference_integration import ReferenceMetadataService
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from tests.test_publication_manifest import work, wiki_rows, bookwalker

FIXTURE=json.loads((Path(__file__).parent/'fixtures/madb_publications.json').read_text(encoding='utf-8'))


def response(records, variable):
    return {'head':{'vars':[variable,'property','value']},'results':{'bindings':[
        {variable:{'type':'uri','value':'https://mediaarts-db.artmuseums.go.jp/id/'+ident},
         'property':{'type':'uri','value':prop},'value':value}
        for ident,record in records.items() for prop,values in record.items() for value in values]}}


def evidence(title='JoJolion', aliases=('ジョジョリオン',), creators=('荒木飛呂彦',)):
    return dict(canonical_title=title,aliases=aliases,creators=creators,edition_profile='standard',
                identity_confidence='high',reference_key='canonical:'+title)


def adapter(candidates=None, book_records=None):
    def request(query):
        if '?series ?property' in query:
            return response(candidates if candidates is not None else FIXTURE['candidates'],'series')
        import re
        ident=re.search(r'/id/(C\d+)>',query).group(1)
        records=book_records if book_records is not None else {
            i:FIXTURE['books'][i] for i in FIXTURE['by_series'].get(ident,())}
        return response(records,'book')
    return MadbPublicationAdapter(request)


class AdapterTests(unittest.TestCase):
    def test_live_edition_controls_without_count_scoring(self):
        cases=[(evidence(),'C332620',27),
               (evidence('DEATH NOTE',(),('大場つぐみ','小畑健')),'C310756',13),
               (evidence('ONE PIECE',(),('尾田栄一郎',)),'C268196',109),
               (evidence('The World Is Mine',('ザ・ワールド・イズ・マイン',),('新井英樹',)),'C270259',14),
               (evidence('Multiple Personality Detective Psycho',('多重人格探偵サイコ',),('田島昭宇','大塚英志')),'C287063',24),
               (evidence('Solo Leveling',('俺だけレベルアップな件',),('Chugong','DUBU')),'C435131',8)]
        for row,ident,count in cases:
            with self.subTest(ident=ident):
                a=adapter(); result=a.resolve(row)
                self.assertEqual('valid',result['status'],result)
                self.assertEqual(ident,result['match']['series_id'])
                self.assertEqual(count,len(result['books']))
                self.assertEqual(2,a.request_count)
                self.assertEqual('JP',result['market']); self.assertNotIn('country_of_origin',result)

    def test_creator_contradiction_incomparable_scripts_and_low_trust_fail_closed(self):
        for row in (evidence(creators=('別人',)),):
            a=adapter(); self.assertEqual('insufficient_evidence',a.resolve(row)['status'])
            self.assertEqual(1,a.request_count)
        row=evidence(); row['identity_confidence']='low'
        a=adapter(); self.assertEqual('insufficient_evidence',a.resolve(row)['status']); self.assertEqual(0,a.request_count)

    def test_ambiguous_candidates_and_edition_contradiction(self):
        candidates={'C332620':FIXTURE['candidates']['C332620'], 'C999':FIXTURE['candidates']['C332620']}
        a=adapter(candidates); self.assertEqual('ambiguous',a.resolve(evidence())['status']); self.assertEqual(1,a.request_count)
        for edition in ('color','fan_color','unknown'):
            a=adapter(); row=evidence(); row['edition_profile']=edition
            self.assertEqual('incompatible_edition',a.resolve(row)['status']); self.assertEqual(0,a.request_count)
        books=deepcopy({i:FIXTURE['books'][i] for i in FIXTURE['by_series']['C332620']})
        next(iter(books.values()))[SCHEMA+'version']=[{'type':'literal','value':'完全収録版'}]
        self.assertEqual('ambiguous',adapter(book_records=books).resolve(evidence())['status'])

    def test_malformed_empty_timeout_cancel_and_limits(self):
        for payload in ({}, {'results':{'bindings':[{}]}}, {'results':{'bindings':'bad'}}):
            with self.assertRaises(ValueError): MadbPublicationAdapter(lambda _q:payload).resolve(evidence())
        self.assertEqual('no_match',MadbPublicationAdapter(lambda _q:response({},'series')).resolve(evidence())['status'])
        def timeout(_q): raise TimeoutError('timed out')
        with self.assertRaises(TimeoutError): MadbPublicationAdapter(timeout).resolve(evidence())
        a=adapter(); a.set_cancel_check(lambda:True)
        with self.assertRaises(CancelledError): a.resolve(evidence())
        self.assertEqual(0,a.request_count)
        with self.assertRaises(ValueError): _records({'results':{'bindings':[{}]*1001}},'series',1001)

    def test_safe_query_literals_and_id_validation(self):
        title='" } SERVICE <https://invalid/> { ?s ?p ?o } #\n\\'
        query=candidate_query([title])
        self.assertIn(json.dumps(title,ensure_ascii=False),query)
        self.assertIn('LIMIT 21',query); self.assertIn('LIMIT 251',inventory_query('C332620'))
        with self.assertRaises(ValueError): inventory_query('C1> } SERVICE')

    def test_raw_numbers_fields_missing_numbers_and_duplicates(self):
        for label,number in (('volume14','14'),('巻88','88'),('v.1','1'),('06','6'),('1.5','1.5'),
                             ('4 (東の海編)',''),('special',''),('','')):
            fields={SCHEMA+'volumeNumber':[label]} if label else {}
            b=_book('M1',fields); self.assertEqual(number,b.number); self.assertEqual(label,b.raw_number)
        result=adapter().resolve(evidence()); book=next(b for b in result['books'] if b['madb_id']=='M477585')
        self.assertIn('9784088808802',book['isbn']); self.assertEqual(('2016-12-24',),book['dates'])
        self.assertTrue(book['publishers']); self.assertTrue(book['brands'])
        fields=FIXTURE['books']['M477585']; payload=response({'M477585':fields},'book')
        payload['results']['bindings']*=2
        self.assertEqual(1,len(_records(payload,'book',6001)))


class Cache:
    def __init__(self): self.values={}; self.expired=False
    def get_reference_catalog(self,key): return None if self.expired else self.get('reference_catalog',key)
    def get(self,layer,key,allow_stale=False): return SimpleNamespace(value=self.values[key]) if key in self.values else None
    def put_reference_catalog(self,key,value): self.values[key]=json.loads(json.dumps(value))


class IntegrationTests(unittest.TestCase):
    def test_full_service_is_independent_of_google_credentials_and_madb_failure(self):
        from calibre_plugins.manganana.metadata.reference_metadata import PublicationMatch
        from calibre_plugins.manganana.metadata.references.google_books_reference import GoogleBooksArtworkResolver
        class OtherReference:
            def __init__(self): self.calls=0
            def match_publication(self,row):
                self.calls+=1
                return PublicationMatch('fixture','','','no_match','no fixture match')
        for fail in (False,True):
            wiki=OtherReference(); book=OtherReference(); a=adapter()
            if fail:
                def timeout(_query): raise TimeoutError('fixture timeout')
                a._injected=timeout
            google=GoogleBooksArtworkResolver(api_key='',enabled=False)
            service=ReferenceMetadataService(None,wiki,book,google,madb=a,madb_enabled=True)
            result=service.lookup('work',evidence())
            self.assertEqual('transient_failure' if fail else 'valid',result['madb']['status'])
            self.assertIn('google_books',result); self.assertFalse(google.enabled)
            self.assertEqual(0,google.request_count); self.assertEqual((1,1),(wiki.calls,book.calls))

    def test_disabled_cache_and_transient_last_known_good(self):
        cache=Cache(); a=adapter(); service=ReferenceMetadataService(cache,madb=a)
        row=evidence()
        self.assertEqual('disabled',service._lookup_madb('work',row,lambda:False)['status']); self.assertEqual(0,a.request_count)
        service.madb_enabled=True
        self.assertEqual('valid',service._lookup_madb('work',row,lambda:False)['status'])
        self.assertEqual('hit',service._lookup_madb('work',row,lambda:False)['cache_state'])
        cache.expired=True
        def timeout(_q): raise TimeoutError('transient')
        a._injected=timeout
        self.assertEqual('last_known_good',service._lookup_madb('work',row,lambda:False)['cache_state'])
        self.assertTrue(all(v['status']=='valid' for v in cache.values.values()))
        cache.values.clear()
        self.assertEqual('transient_failure',service._lookup_madb('work',row,lambda:False)['status'])
        self.assertEqual({},cache.values)

    def test_manifest_never_infers_structure_or_overwrites_identity_artwork(self):
        bibliography=adapter().resolve(evidence())
        bibliography['books']=[dict(number='1'),dict(number='2')]
        rows=[{'chapter':str(i),'title':'','volume':None} for i in range(1,7)]
        builder=PublicationManifestBuilder(work(),'original').apply_provider_inventory(rows,'mangak')
        before=builder.build(); after=builder.apply_madb(bibliography).build()
        self.assertEqual(before.chapters,after.chapters); self.assertEqual(before.volumes,after.volumes)
        self.assertEqual(6,len(build_publication_projection(rows,after).unmapped))
        self.assertEqual(before.work,after.work); self.assertEqual(before.edition,after.edition)
        builder.apply_wikipedia(wiki_rows(6)).apply_bookwalker(bookwalker())
        before=builder.build(); after=builder.apply_madb(bibliography).build()
        self.assertEqual(before.chapters,after.chapters); self.assertEqual(before.volumes,after.volumes)
        self.assertEqual(before.display,after.display)
        self.assertEqual('C332620',next(s for s in after.source_states if s.source=='madb').source_identity)

    def test_default_toggle_and_explicit_packaging_no_acquisition_registration(self):
        root=Path(__file__).parents[1]
        config=(root/'app/settings/config.py').read_text(encoding='utf-8')
        main=(root/'app/main.py').read_text(encoding='utf-8')
        self.assertIn("prefs.defaults['madb_enabled'] = True",config)
        self.assertIn("madb_enabled=bool(prefs['madb_enabled'])",main)
        self.assertIn("self.preferences['madb_enabled'] = self.madb_enabled.isChecked()",main)
        self.assertNotIn('MadbPublicationAdapter',main)
        self.assertIn("metadata/references/madb_reference.py",(root/'tools/build_plugin.py').read_text(encoding='utf-8'))


class CanonicalMatcherTests(unittest.TestCase):
    def test_synthetic_exact_alias_kitsu_only_provider_independence_and_shared_cache(self):
        from calibre_plugins.manganana.discovery.enrichment_sources import AniListAdapter, KitsuAdapter, EnrichmentRegistry
        from calibre_plugins.manganana.metadata.reference_integration import canonical_publication_context
        import urllib.error
        title = "JoJo's Bizarre Adventure Part 8: JoJolion"
        def unavailable(*args, **kwargs):
            raise urllib.error.HTTPError('https://example.invalid',403,'Forbidden',{},None)
        def kitsu(*args, **kwargs):
            return {'data':[{'id':'18812','attributes':{'canonicalTitle':title,
                'titles':{'en':title,'en_jp':'JoJo no Kimyou na Bouken: JoJolion',
                          'ja_jp':'ジョジョリオン'},'subtype':'manga'}}]}, {}
        candidates, errors = EnrichmentRegistry((AniListAdapter(unavailable),KitsuAdapter(kitsu))).search(title)
        self.assertIn('403',errors['anilist']); self.assertEqual(1,len(candidates))
        native = candidates[0]; self.assertFalse(native.authors)
        cache=Cache(); a=adapter(); service=ReferenceMetadataService(cache,madb=a,madb_enabled=True)
        payloads=[]
        for provider,display in [('mangak','Jojo No Kimyou Na Bouken - Jojorion'),
                                 ('atsu','JoJo no Kimyou na Bouken: JoJolion')]:
            context=canonical_publication_context('kitsu-18812',dict(
                canonical_title=title,canonical_aliases=native.titles,
                trusted_aliases=(*native.titles,display),canonical_author='ARAKI Hirohiko',
                canonical_creator_provenance='provider',provider_author='ARAKI Hirohiko',
                edition='standard',identity_confidence='high'))
            self.assertTrue(context.shareable)
            row=context.lookup_evidence(); payloads.append(row)
            result=service._lookup_madb(context.reference_key,row,lambda:False)
            self.assertEqual('valid',result['status']); self.assertEqual('C332620',result['match']['series_id'])
            self.assertEqual(27,len(result['books']))
            self.assertEqual('INCOMPARABLE_SCRIPT',result['match']['creator_relationship'])
            self.assertEqual('provider',result['match']['creator_evidence_source'])
            self.assertEqual(2 if provider=='mangak' else 0,result['network']['requests'])
            fresh=adapter().resolve(row)
            self.assertEqual('C332620',fresh['match']['series_id'])
        self.assertEqual(payloads[0]['reference_key'],payloads[1]['reference_key'])
        self.assertEqual(payloads[0]['canonical_aliases'],payloads[1]['canonical_aliases'])
        self.assertNotEqual(payloads[0]['aliases'],payloads[1]['aliases'])
        self.assertEqual(2,a.request_count)

    def test_explicit_title_fields_and_provider_alias_exclusion(self):
        from calibre_plugins.manganana.metadata.references.madb_reference import LABEL
        for field in (SCHEMA+'name',SCHEMA+'alternateName',LABEL):
            records={'C332620':deepcopy(FIXTURE['candidates']['C332620'])}
            record=records['C332620']
            for key in (SCHEMA+'name',SCHEMA+'alternateName',LABEL): record.pop(key,None)
            record[SCHEMA+'name']=[{'type':'literal','value':'Different main title'}]
            record[field]=[{'type':'literal','value':'Exact Trusted Alias'}]
            row=evidence('Canonical Work',(),('Hirohiko Araki',))
            row['canonical_aliases']=('Exact Trusted Alias',)
            result=adapter(records).resolve(row)
            self.assertEqual('valid',result['status'])
            self.assertEqual(field,result['match']['title_evidence'][0]['field'])
        row=evidence(creators=('Hirohiko Araki',)); row['canonical_aliases']=()
        self.assertNotEqual('valid',adapter().resolve(row)['status'])
        query=candidate_query(('Exact Trusted Alias',))
        self.assertIn('VALUES ?titleField { schema:name schema:alternateName rdfs:label }',query)
        self.assertNotIn('CONTAINS',query); self.assertNotIn('REGEX',query)

    def test_creator_states_and_book_contradiction(self):
        from calibre_plugins.manganana.metadata.references.madb_reference import creator_relationship
        self.assertEqual('MATCH',creator_relationship(('Hirohiko Araki',),('ARAKI Hirohiko',)))
        self.assertEqual('INCOMPARABLE_SCRIPT',creator_relationship(('Hirohiko Araki',),('荒木飛呂彦',)))
        self.assertEqual('CONTRADICTION',creator_relationship(('Hirohiko Araki',),('Different Author',)))
        records={'C332620':deepcopy(FIXTURE['candidates']['C332620'])}
        records['C332620'][SCHEMA+'creator']=[{'type':'literal','value':'Different Author'}]
        self.assertEqual('insufficient_evidence',adapter(records).resolve(evidence(creators=('Hirohiko Araki',)))['status'])
        books=deepcopy({i:FIXTURE['books'][i] for i in FIXTURE['by_series']['C332620']})
        next(iter(books.values()))[SCHEMA+'creator']=[{'type':'literal','value':'Different Author'}]
        self.assertEqual('ambiguous',adapter(book_records=books).resolve(evidence(creators=('Hirohiko Araki',)))['status'])

    def test_death_note_cross_script_ambiguity_and_no_success_cache(self):
        row=evidence('DEATH NOTE',(),('Tsugumi Ohba','Takeshi Obata'))
        self.assertEqual('C310756',adapter().resolve(row)['match']['series_id'])
        records={i:deepcopy(FIXTURE['candidates']['C310756']) for i in ('C310756','C999')}
        cache=Cache(); service=ReferenceMetadataService(cache,madb=adapter(records),madb_enabled=True)
        self.assertEqual('ambiguous',service._lookup_madb('death',row,lambda:False)['status'])
        self.assertEqual({},cache.values)

    def test_solo_leveling_preserves_work_and_source(self):
        result=adapter().resolve(evidence('Solo Leveling',('俺だけレベルアップな件',),('Chugong','DUBU')))
        builder=PublicationManifestBuilder(work(),'original').apply_provider_inventory(
            [{'chapter':'1','volume':None}],'atsu')
        before=builder.build(); after=builder.apply_madb(result).build()
        self.assertEqual('C435131',result['match']['series_id'])
        self.assertEqual(before.work,after.work); self.assertEqual(before.edition,after.edition)
        self.assertEqual(before.chapters,after.chapters); self.assertEqual(before.volumes,after.volumes)


class ActualJojolionTitleTests(unittest.TestCase):
    def test_actual_kitsu_bundle_survives_and_has_no_madb_intersection(self):
        from calibre_plugins.manganana.discovery.enrichment_sources import KitsuAdapter, AniListAdapter, EnrichmentRegistry
        from calibre_plugins.manganana.discovery.enrichment_matching import enrich_content_results
        from calibre_plugins.manganana.metadata.reference_integration import canonical_publication_context
        from calibre_plugins.manganana.metadata.references.madb_reference import trusted_titles, title_evidence
        import urllib.error
        fixture=json.loads((Path(__file__).parent/'fixtures/madb_jojolion_titles.json').read_text(encoding='utf-8'))
        def kitsu(*args, **kwargs): return {'data':[fixture['kitsu']['data']]}, {}
        def unavailable(*args, **kwargs):
            raise urllib.error.HTTPError('https://example.invalid',403,'Forbidden',{},None)
        candidates,errors=EnrichmentRegistry((KitsuAdapter(kitsu),AniListAdapter(unavailable))).search('JoJolion')
        self.assertIn('403',errors['anilist'])
        c=candidates[0]
        expected=("JoJo's Bizarre Adventure Part 8: JoJolion",
                  'JoJo no Kimyou na Bouken Part 8: JoJolion',
                  'ジョジョの奇妙な冒険 Part8 ジョジョリオン','Jojorion',
                  "JoJo's Bizarre Adventure Part 8: Jojolion")
        self.assertEqual(expected,c.titles)
        self.assertEqual(expected[1],c.romanized_title); self.assertEqual(expected[2],c.native_title)
        fields=_records(fixture['madb'],'series',101)['C332620']
        from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text
        self.assertEqual((),title_evidence(fields,{normalize_identity_text(t) for t in expected}))
        for provider,title in [('mangak','Jojo No Kimyou Na Bouken - Jojorion'),
                               ('atsu','JoJo no Kimyou na Bouken: JoJolion')]:
            row=enrich_content_results([dict(source_id=provider,id='fixture',title=title,
                author='ARAKI Hirohiko',external_ids={'kitsu_id':'18812'})],candidates)[0]
            self.assertEqual(list(expected),row['canonical_aliases'])
            # The user-established high-confidence selected work is the entry condition.
            context=canonical_publication_context('kitsu-18812',dict(row,
                edition='standard',identity_confidence='high'))
            evidence=context.lookup_evidence()
            self.assertEqual(expected,trusted_titles(evidence))
            self.assertEqual(provider,row['source_id'])
            queries=[]
            def no_exact_match(query):
                queries.append(query)
                self.assertIn('?series ?property',query)
                for term in expected: self.assertIn(json.dumps(term,ensure_ascii=False),query)
                return response({},'series')
            a=MadbPublicationAdapter(no_exact_match)
            result=a.resolve(evidence)
            self.assertEqual('no_match',result['status']); self.assertEqual(1,len(queries))
            self.assertEqual([],result['books'])
        self.assertNotIn('https://mediaarts-db.artmuseums.go.jp/data/property#variantTitle',fields)
        self.assertNotIn('https://mediaarts-db.artmuseums.go.jp/data/property#seriesName',fields)

    def test_existing_bound_keeps_canonical_roles_before_synonyms(self):
        from calibre_plugins.manganana.discovery.enrichment_model import ExternalMangaCandidate
        from calibre_plugins.manganana.metadata.references.madb_reference import trusted_titles
        c=ExternalMangaCandidate('kitsu','fixture','Canonical',english_title='English',
            romanized_title='Romanized',native_title='Native',aliases=tuple('Synonym'+str(i) for i in range(20)))
        result=trusted_titles(dict(canonical_title='Canonical',canonical_aliases=c.titles))
        self.assertEqual(('Canonical','English','Romanized','Native'),result[:4])
        self.assertEqual(8,len(result))
        self.assertEqual(result,trusted_titles(dict(canonical_title='Canonical',canonical_aliases=c.titles)))
