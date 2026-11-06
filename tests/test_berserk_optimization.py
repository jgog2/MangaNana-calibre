"""Captured real identities and conservative publication regression tests."""
import dataclasses, json, re, unittest
from pathlib import Path
from calibre_plugins.manganana.providers.mangapill_source import MangaPillSource
from calibre_plugins.manganana.providers.weebcentral_source import WeebCentralSource
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.providers.cross_source_fallback import chapter_identity, chapter_identities_match
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/berserk-live-investigation'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def replay(sid):
    p=BASE/sid
    request=next(r for r in read(p/'trace-live.json')['requests'] if r.get('body') and ('/manga/1' in r['url'] if sid=='mangapill' else '/full-chapter-list' in r['url']))
    html=(p/request['body']).read_text(encoding='utf-8')
    cls=MangaPillSource if sid=='mangapill' else WeebCentralSource
    return cls(fetch_text=lambda *a,**k:html).get_chapters(read(p/'regression-fixture.json')['url'],'en')
class ProviderIdentities(unittest.TestCase):
    def test_weebcentral_all_records_survive_and_ordinary_rows_unchanged(self):
        rows=replay('weebcentral');old=read(BASE/'weebcentral/cold-acquisition.json')
        self.assertEqual(403,len(rows));byid={r['id']:r for r in rows}
        for row in old:
            self.assertEqual({k:v for k,v in row.items() if k not in ('_source_id','_source_name')},byid[row['id']])
        prologues=[r for r in rows if r.get('numbering_group')=='prologue']
        self.assertEqual(16,len(prologues))
        self.assertEqual({str(n) for n in range(1,17)},{r['numbering_ordinal'] for r in prologues})
        manifest=PublicationManifestBuilder({'title':'Berserk'}).apply_provider_inventory(rows,'weebcentral').build()
        projected=build_publication_projection(prologues,manifest,'weebcentral','weebcentral')
        self.assertTrue(all(c.mapping_state=='unmapped' and not c.canonical_key for c in projected.chapters))
    def test_mangapill_all_urls_and_numbering_namespaces(self):
        rows=replay('mangapill');old=read(BASE/'mangapill/cold-acquisition.json')
        self.assertEqual(405,len(rows));self.assertEqual({r['id'] for r in old},{r['id'] for r in rows})
        for n in range(1,17):
            pair=[r for r in rows if r['chapter']==str(n)]
            self.assertEqual({'2','unlabelled'},{r['numbering_group'] for r in pair})
            self.assertFalse(chapter_identities_match(*map(chapter_identity,pair)))
            projection=build_publication_projection(pair,None,'mangapill','mangapill')
            self.assertEqual(2,len({c.acquisition_identity for c in projection.chapters}))
            self.assertTrue(all(c.mapping_state=='unmapped' for c in projection.chapters))
    def test_weebcentral_other_labels_and_fractional_ordinals(self):
        labels=['Chapter 1','Episode 2.5','Prologue 1','Prologue 1.5','Special Bonus']
        html=''.join('<a href="/chapters/'+str(i).zfill(26)+'">'+s+'</a>' for i,s in enumerate(labels))
        rows=WeebCentralSource(fetch_text=lambda *a,**k:html).get_chapters('https://weebcentral.com/series/01J76XY7EF75DJNQCV04HTPDZK/Berserk','en')
        self.assertEqual({'1','2.5','Prologue 1','Prologue 1.5'},{r['chapter'] for r in rows})
    def test_explicit_provider_volume_still_wins_with_numbering_namespace(self):
        row=dict(id='actual',chapter='1',numbering_group='2',volume='3',_source_id='mangapill')
        projected=build_publication_projection([row],None,'mangapill','mangapill').chapters[0]
        self.assertEqual(('3','provider_explicit'),(projected.effective_volume.value,projected.mapping_state))
    def test_namespaced_identity_cannot_borrow_unqualified_other_provider(self):
        self.assertFalse(chapter_identities_match(chapter_identity(dict(chapter='1',numbering_group='2',_source_id='mangapill')),chapter_identity(dict(chapter='1',_source_id='mangadex'))))

class AmbiguityIndex(unittest.TestCase):
    def test_index_matches_original_predicate_including_multikey_conflicts(self):
        from calibre_plugins.manganana.publication.publication_freshness import ambiguity_diagnostic_index
        from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number as norm
        diagnostics=read(BASE/'mangapill/cold-reference.json')['mangadex_structure']['integrity_diagnostics']
        diagnostics += [dict(chapter='1.50',chapters=['2','1.5'],reason='release_id_conflict',release_ids=['a','b']),dict(chapters=['3','bad'],reason='unknown')]
        indexed=ambiguity_diagnostic_index(diagnostics)
        for key in [None,'1.5','2','3',*[str(n) for n in range(400)]]:
            old=[d for d in diagnostics if norm(d.get('chapter'))==key or key in {norm(k) for k in d.get('chapters') or ()}]
            def thaw(v):
                from collections.abc import Mapping
                if isinstance(v,Mapping):return {k:thaw(x) for k,x in v.items()}
                if isinstance(v,tuple):return [thaw(x) for x in v]
                return v
            self.assertEqual(old,thaw(indexed.get(key,())))
        with self.assertRaises(TypeError): indexed['2'][0]['reason']='changed'
        with self.assertRaises(TypeError): indexed['new']=()


class ScopedValidation(unittest.TestCase):
    def test_output_evidence_does_not_equate_numbering_groups(self):
        from calibre_plugins.manganana.books.output.chapter_output import resolve_volume_evidence, VolumeEvidenceSource
        rows=[dict(id='actual',chapter='1',numbering_group='2',_source_id='mangapill')]
        evidence=VolumeEvidenceSource('mangadex','same-work','original',({'id':'reference','chapter':'1','volume':'5','_source_id':'mangadex'},))
        result=resolve_volume_evidence(rows,[evidence],page_work_id='same-work',page_source_id='mangapill')
        self.assertFalse(result.available);self.assertEqual(('actual',),result.unassigned)
    def test_large_art_inventory_reuses_structure_and_revalidates_changes(self):
        from unittest.mock import patch
        b=PublicationManifestBuilder({'canonical_identity':'fixture:work','title':'Work'},'original')
        b.apply_provider_inventory([dict(id='a',chapter='1',volume='1')],'mangapill')
        original=b._build_structure
        with patch.object(b,'_build_structure',wraps=original) as counted:
            for _ in range(1000):b.apply_provider_covers({'1':'https://fixture.invalid/a'})
            self.assertEqual(1,counted.call_count)
            first=b.build();first.runtime_publication['corrupt']='external mutation'
            self.assertNotIn('corrupt',b.build().runtime_publication)
            b.apply_provider_inventory([dict(id='a',chapter='1',volume='2')],'mangapill')
            b.apply_provider_covers({'2':'https://fixture.invalid/b'})
            self.assertEqual(2,counted.call_count)
            self.assertEqual('2',b.build().chapter('1').volume.value)
            b.apply_enrichment({'canonical_author':'New creator'})
            self.assertEqual('New creator',b.build().work.creator.value)
            self.assertEqual(3,counted.call_count)
    def test_prepared_payload_is_immutable_and_consumers_are_independent(self):
        from calibre_plugins.manganana.publication.publication_preparation import PreparedPublication
        import pickle
        p=PreparedPublication('current',pickle.dumps({'chapters':['actual']}))
        a=p.materialize();a['chapters'].append('unwanted')
        self.assertEqual(['actual'],p.materialize()['chapters'])
        with self.assertRaises(dataclasses.FrozenInstanceError):p.payload=b'changed'

class CacheContracts(unittest.TestCase):
    def test_actual_fresh_bounded_out_is_reused_stale_and_old_contract_are_not(self):
        import hashlib,tempfile
        from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache, IDENTITY_TTL
        from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import MangaDexStructureResolver, CACHE_CONTRACT
        bundle=read(BASE/'mangapill/cold-reference.json');value=bundle['mangadex_structure']
        self.assertEqual('bounded_out',value['special_metadata_status'])
        evidence=dict(bundle['publication_evidence'],mangadex_title_ids=[value['manga_id']])
        key=CACHE_CONTRACT+':'+hashlib.sha256((value['canonical_work_id']+'|standard').encode()).hexdigest()
        now=[100.0];calls=[]
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.sqlite3',clock=lambda:now[0])
            cache.put_reference_structure(key,value)
            def request(url):calls.append(url);raise RuntimeError('controlled failure')
            resolver=MangaDexStructureResolver(cache,request)
            hit=resolver.lookup(evidence)
            self.assertEqual('hit',hit['cache_state']);self.assertEqual('bounded_out',hit['special_metadata_status'])
            self.assertEqual([],calls);self.assertEqual(value['mappings'],hit['mappings'])
            now[0]+=IDENTITY_TTL+1
            stale=resolver.lookup(evidence)
            self.assertEqual('last_known_good',stale['cache_state']);self.assertTrue(calls)
            self.assertEqual('transient_failure',stale['refresh_status'])
            cache.put_reference_structure(key,dict(value,special_metadata_contract='obsolete'))
            calls.clear();resolver.lookup(evidence);self.assertTrue(calls)
            cache.close()
    def test_cover_identity_context_expiry_and_selection_reuse(self):
        from calibre_plugins.manganana.books.imaging.artwork_delivery import ArtworkResolver, ArtworkCandidate
        from PIL import Image
        from io import BytesIO
        from types import SimpleNamespace
        image=BytesIO();Image.new('RGB',(20,30),'green').save(image,'PNG');raw=image.getvalue()
        calls=[];now=[0.0]
        provider=SimpleNamespace(source_id='mangapill',fetch_binary=lambda u,**k:calls.append(u) or raw)
        resolver=ArtworkResolver(clock=lambda:now[0])
        b=PublicationManifestBuilder({'canonical_identity':'work','title':'Work'},'original')
        b.apply_provider_inventory([dict(id='real',chapter='1',volume='1')],'mangapill').apply_provider_covers({'1':'https://fixture.invalid/1'},'mangapill')
        manifest=b.build();resolver.register_manifest(manifest)
        resolver.resolve_url('https://fixture.invalid/1',provider)
        resolver.clear_manifest();resolver.register_manifest(manifest)
        self.assertTrue(resolver.has_validated_url('https://fixture.invalid/1',provider))
        resolver.resolve_url('https://fixture.invalid/1',provider);self.assertEqual(1,len(calls))
        other=dataclasses.replace(manifest,work=dataclasses.replace(manifest.work,language='ja'))
        resolver.register_manifest(other)
        self.assertFalse(resolver.has_validated_url('https://fixture.invalid/1',provider))
        resolver.resolve_url('https://fixture.invalid/1',provider);self.assertEqual(2,len(calls))
        now[0]=3601
        self.assertFalse(resolver.has_validated_url('https://fixture.invalid/1',provider))
        resolver.resolve_url('https://fixture.invalid/1',provider);self.assertEqual(3,len(calls))
        # Restoring cached winners must obey the same bound as fresh validation.
        for n in range(300):
            candidate=ArtworkCandidate('mangapill','https://fixture.invalid/'+str(n),volume=str(n))
            resolver.chains[candidate.url]=(candidate,)
            resolver.valid[candidate.key]=raw;resolver.valid_at[candidate.key]=now[0]
            self.assertTrue(resolver.has_validated_url(candidate.url,provider))
        self.assertEqual(256,len(resolver.winners))
    def test_document_reuse_is_operation_local_and_cannot_survive_exception(self):
        calls=[]
        source=MangaPillSource(fetch_text=lambda u,**k:calls.append(u) or '<h1>Work</h1><a href="/chapters/a">Chapter 1</a>')
        with source.operation_context():
            source.get_chapters('https://mangapill.com/manga/1/work','en')
            source.get_volume_covers('https://mangapill.com/manga/1/work')
        self.assertEqual(1,len(calls))
        with self.assertRaises(RuntimeError):
            with source.operation_context():
                source.get_manga('https://mangapill.com/manga/1/work')
                raise RuntimeError('cancelled')
        source.get_manga('https://mangapill.com/manga/1/work')
        self.assertEqual(3,len(calls))

if __name__=='__main__': unittest.main()
