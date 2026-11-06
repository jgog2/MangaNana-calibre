"""Captured MADB bibliography and exact Berserk acquisition regression cases."""
import copy,hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from calibre_plugins.manganana.publication import publication_identity as pi
from calibre_plugins.manganana.publication.publication_preparation import prepare_publication, presentation_identity
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.diagnostics.publication_diagnostics import publication_diagnostics, evidence_capabilities
from tests.test_berserk_bridge_activation import fixture,membership,groups,read,ROOT
from tests.test_publication_manifest import work,wiki_rows
from calibre_plugins.manganana.metadata.reference_integration import canonical_family_publication_context
from calibre_plugins.manganana.metadata.references.wikipedia_reference import WikipediaPublicationAdapter
from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import MangaDexStructureResolver
OUT=ROOT/'build/madb-bridge-integration'
CATALOG=read(OUT/'catalog-capture/results.json') if (OUT/'catalog-capture/results.json').is_file() else None

def captured(sid,enabled=True,madb=True,**changes):
    base=ROOT/'build/berserk-bridge-activation/native-current'/sid
    manifest=read(base/'cold-manifest.json');bundle=read(base/'cold-reference.json')
    rows=read(base/'cold-acquisition.json');w=dict(manifest['work']);w['creator']=w['creator']['value']
    record=next(r for r in read(ROOT/'build/berserk-live-investigation/selected-records.json') if r['source_id']==sid)
    inputs=dict(work=w,edition=manifest['edition']['identity'],language='en',source_id=sid,source_name=record['source_name'],
        source_url=record['url'],chapters=rows,native_plan=read(base/'cold-native-plan.json'),covers={},enrichment={},mode='volume',
        verified_publication_mappings=enabled,identity_bridge_stamp=pi.bridge_resource_stamp(enabled))
    inputs.update(changes)
    bundle['madb']=copy.deepcopy(CATALOG) if madb else {'status':'disabled'}
    return inputs,bundle


class MadbBridgeIntegration(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{},clear=False);self.env.start()
        os.environ.pop('MANGAANKA_PUBLICATION_BRIDGE_PATH',None)
        self.addCleanup(self.env.stop)

    def test_captured_catalog_identity_is_bibliography_not_chapter_authority(self):
        self.assertEqual(CATALOG['match']['series_id'],'C254353')
        self.assertEqual(len(CATALOG['books']),40)
        self.assertFalse(evidence_capabilities({'madb':CATALOG})['madb']['exact_collected_membership'])
        builder=PublicationManifestBuilder(work(),'original')
        before=builder.apply_wikipedia(wiki_rows(8)).build()
        after=builder.apply_madb(CATALOG).build()
        self.assertEqual(before.chapters,after.chapters);self.assertEqual(before.work,after.work)
        self.assertEqual(before.edition,after.edition);self.assertEqual(before.volumes,after.volumes)

    def test_all_three_captured_sources_madb_on_off_exact_conservation(self):
        for sid,total,resolved in [('weebcentral',403,400),('mangapill',405,401),('mangadex',404,401)]:
            for catalog in (False,True):
                with self.subTest(sid=sid,catalog=catalog):
                    inputs,bundle=captured(sid,madb=catalog)
                    _,manifest,projection,plan=prepare_publication(inputs,bundle).materialize()
                    expected=fixture(sid)[2]
                    self.assertEqual([(g['volume'],[r['id'] for r in g['chapters']]) for g in plan['volume_groups']],
                                     [(g['volume'],[r['id'] for r in g['chapters']]) for g in expected['volume_groups']])
                    self.assertEqual(len(projection.chapters),total);self.assertEqual(total-len(projection.unmapped),resolved)
                    self.assertEqual(len(membership(plan)),total)
                    self.assertEqual(plan['volumes'],[float(v) for v in range(1,44)])
                    self.assertEqual([c.acquisition for c in projection.chapters],inputs['chapters'])

    def test_disable_restore_fingerprints_and_exact_volume_five(self):
        for sid in ('weebcentral','mangapill'):
            identities=[]
            for enabled in (True,False,True):
                inputs,bundle=captured(sid,enabled=enabled)
                prepared=prepare_publication(inputs,bundle);identities.append(prepared.input_identity)
                _,_,projection,plan=prepared.materialize()
                expected=fixture(sid,enabled)[2]
                self.assertEqual([(g['volume'],[r['id'] for r in g['chapters']]) for g in plan['volume_groups']],
                                 [(g['volume'],[r['id'] for r in g['chapters']]) for g in expected['volume_groups']])
                if enabled:self.assertEqual([r['id'] for r in groups(plan)[5]['chapters']],[r['id'] for r in groups(fixture(sid)[2])[5]['chapters']])
                self.assertEqual(len(membership(plan)),len(inputs['chapters']))
            self.assertNotEqual(identities[0],identities[1]);self.assertEqual(identities[0],identities[2])

    def test_reported_zero_requires_missing_independent_membership_not_catalog_count(self):
        inputs,bundle=captured('weebcentral',enabled=False)
        bundle['wikipedia']={'status':'ambiguous','match':{'reason':'controlled unresolved root'}}
        bundle['mangadex_structure']={'status':'ambiguous','mappings':{}}
        _,manifest,p,plan=prepare_publication(inputs,bundle).materialize()
        self.assertEqual(len(p.unmapped),403);self.assertFalse(plan['volumes'])
        bundle['madb']={'status':'disabled'}
        _,_,p2,plan2=prepare_publication(inputs,bundle).materialize()
        self.assertEqual(p.rows,p2.rows);self.assertEqual(plan['volume_groups'],plan2['volume_groups'])
        messages=publication_diagnostics(bundle,manifest,p)
        self.assertIn('controlled unresolved root',' '.join(messages))

    def test_work_edition_language_provider_and_changed_exact_id_fail_closed(self):
        for changes in ({'work':dict(canonical_identity='other',title='Other')},{'edition':'deluxe'},{'language':'ja'}):
            inputs,bundle=captured('weebcentral',**changes)
            _,m,p,_=prepare_publication(inputs,bundle).materialize()
            self.assertFalse(any(c.mapping_state=='identity_bridge' for c in p.chapters))
            self.assertEqual(m.runtime_publication['identity_bridge_status'],'scope_not_available')
        for change in ({'_source_id':'other'},{'id':'changed-exact-id'},{'original_label':'changed label'},{'numbering_group':'other'}):
            inputs,bundle=captured('weebcentral')
            target=next(r for r in inputs['chapters'] if r.get('numbering_group')=='prologue')
            target.update(change)
            _,_,p,_=prepare_publication(inputs,bundle).materialize()
            candidate=next(c for c in p.chapters if c.acquisition==target)
            self.assertFalse(candidate.effective_volume.present)

    def test_other_manga_complete_partial_absent_and_conflicting_evidence(self):
        rows=[dict(id=str(i),chapter=str(i),volume=None) for i in range(1,9)]
        for books in ([],CATALOG['books'][:1],CATALOG['books']):
            b=PublicationManifestBuilder(work(),'original').apply_provider_inventory(rows,'fixture')
            b.apply_madb(dict(CATALOG,books=books)).apply_wikipedia(wiki_rows(8))
            p=build_publication_projection(rows,b.build())
            self.assertEqual(len(p.unmapped),0)
        b=PublicationManifestBuilder(work(),'original').apply_provider_inventory(rows,'fixture')
        b.apply_madb(dict(CATALOG,status='ambiguous')).apply_wikipedia(wiki_rows(8))
        self.assertFalse(build_publication_projection(rows,b.build()).unmapped)
        # Genuine membership conflict stays unresolved; native ownership wins only its own record.
        from tests.test_reference_integrity import builder,md,wiki
        b=builder().apply_provider_inventory(rows,'fixture')
        b.apply_mangadex_structure(md((('1','9'),))).apply_wikipedia(wiki((('1','1'),)))
        self.assertFalse(build_publication_projection(rows,b.build()).chapters[0].effective_volume.present)
        native=[dict(rows[0],volume='7'),*rows[1:]]
        b.apply_provider_inventory(native,'fixture')
        self.assertEqual(build_publication_projection(native,b.build()).chapters[0].effective_volume.value,'7')

    def test_packaged_corruption_update_revocation_and_pending_never_partially_activate(self):
        original=read(ROOT/'assets/publication_identity/berserk-reviewed-r1.json')
        registry=read(ROOT/pi.PACKAGED_REGISTRY)
        payload={}
        def install(data):
            raw=json.dumps(data).encode();entry=registry['artifacts'][0]
            entry.update(sha256=hashlib.sha256(raw).hexdigest(),revision=data['revision'])
            payload[entry['path']]=raw;payload[pi.PACKAGED_REGISTRY]=json.dumps(registry).encode()
            pi._packaged_registry.cache_clear()
        install(original)
        with patch.object(pi,'get_resources',lambda name:payload.get(name),create=True):
            old=pi.bridge_resource_stamp(True);inputs,bundle=captured('weebcentral')
            data=copy.deepcopy(original);data['revision']='review-revoked-r2'
            data['bindings'][0].update(status='pending',reason='Review revoked')
            install(data);new=pi.bridge_resource_stamp(True);self.assertNotEqual(old,new)
            with self.assertRaises(InterruptedError):prepare_publication(inputs,bundle)
            inputs['identity_bridge_stamp']=new
            _,_,p,plan=prepare_publication(inputs,bundle).materialize()
            self.assertEqual(len(p.unmapped),4);self.assertEqual(len(membership(plan)),403)
            payload[registry['artifacts'][0]['path']]=b'{}'
            _,m,p,_=prepare_publication(inputs,bundle).materialize()
            self.assertEqual(m.runtime_publication['identity_bridge_status'],'invalid')
            self.assertEqual(len(p.unmapped),19)
        pi._packaged_registry.cache_clear()

    def test_external_override_precedence_bounded_validation_and_safe_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'private-path.json';path.write_text('{}')
            with patch.dict(os.environ,MANGAANKA_PUBLICATION_BRIDGE_PATH=str(path)):
                self.assertEqual(pi.bridge_resource_stamp(False),pi.bridge_resource_stamp(True))
                inputs,bundle=captured('weebcentral',enabled=False)
                _,m,p,_=prepare_publication(inputs,bundle).materialize()
                self.assertEqual(m.runtime_publication['identity_bridge_status'],'invalid')
                self.assertNotIn(str(path),' '.join(publication_diagnostics(bundle,m,p)))

    def test_packaged_duplicate_scope_and_registry_traversal_rejected(self):
        data=read(ROOT/pi.PACKAGED_REGISTRY);data['artifacts'][0]['path']='../outside.json'
        with patch.object(pi,'get_resources',lambda _:json.dumps(data).encode(),create=True):
            pi._packaged_registry.cache_clear()
            self.assertEqual(pi.bridge_resource_stamp(True),('packaged','unavailable'))
        pi._packaged_registry.cache_clear()

    def test_surviving_failing_manual_context_qualifies_without_catalog_precedence(self):
        captures=read(OUT/'manual-profile-audit/query_snapshot.json')
        first=min(captures,key=lambda r:r['created_utc'])
        rows=[c.get('provider_record') or c.get('primary') or c for c in first['value']['final_cards']]
        wiki_payload=read(OUT/'live-metadata/wikipedia-01.json')
        md_payload=read(OUT/'live-metadata/mangadex-02.json')
        aggregate=read(OUT/'live-metadata/mangadex-03.json')
        for sid,total,resolved in [('mangapill',405,401),('weebcentral',403,400)]:
            selected=next(r for r in rows if r.get('source_id')==sid and r.get('canonical_work_id')=='kitsu:8')
            context=canonical_family_publication_context(selected,rows,'original')
            e=context.lookup_evidence()
            self.assertEqual(e['creator_provenance'],'provider_consensus')
            self.assertEqual(e['canonical_work_id'],'kitsu:8')
            self.assertEqual(e['creators'],('MIURA Kentaro, MORI Kouji, Studio Gaga',))
            w=WikipediaPublicationAdapter(lambda params:wiki_payload).match_publication(e)
            self.assertEqual(w.confidence,'confident');self.assertEqual(w.publication_id,'1698372')
            def get(url):return aggregate if '/aggregate' in url else md_payload
            md=MangaDexStructureResolver(request_json=get).lookup(e)
            self.assertEqual(md['status'],'valid');self.assertEqual(md['manga_id'],'801513ba-a712-498c-8f57-cae55b38cc92')
            for catalog_enabled in (False,True):
                inputs,bundle=captured(sid,madb=catalog_enabled)
                inputs['work']['canonical_identity']='kitsu:8'
                bundle.update(publication_evidence=e,mangadex_structure=md)
                _,m,p,plan=prepare_publication(inputs,bundle).materialize()
                self.assertEqual(total-len(p.unmapped),resolved)
                self.assertEqual(plan['volumes'],[float(i) for i in range(1,44)])
                self.assertEqual([r['id'] for r in groups(plan)[5]['chapters']],
                                 [r['id'] for r in groups(fixture(sid)[2])[5]['chapters']])
                self.assertEqual(len(membership(plan)),total)
                self.assertEqual(m.work.canonical_identity,'kitsu:8')

    def test_work_subset_never_hides_a_conflicting_or_unknown_identifier(self):
        approved='anilist:30002|kitsu:8'
        for selected in ('kitsu:8','anilist:30002',approved):
            self.assertTrue(pi.canonical_work_scope_matches(selected,approved))
        for selected in ('kitsu:9','anilist:30003|kitsu:8','kitsu:8|mal:2','kitsu:8|kitsu:9','Berserk',''):
            self.assertFalse(pi.canonical_work_scope_matches(selected,approved))

    def test_explicit_work_id_does_not_override_trusted_creator_or_edition_conflict(self):
        payload=read(OUT/'live-metadata/mangadex-02.json')
        e=dict(canonical_work_id='kitsu:8',identity_confidence='high',title='Berserk',
               canonical_aliases=['Berserk'],creators=['Unrelated Creator'],creator_provenance='trusted_external',edition='original')
        result=MangaDexStructureResolver(request_json=lambda url:payload).lookup(e)
        self.assertEqual(result['status'],'no_match')
        e.update(creator_provenance='provider_consensus',canonical_work_id='anilist:999|kitsu:8')
        self.assertEqual(MangaDexStructureResolver(request_json=lambda url:payload).lookup(e)['status'],'no_match')
        e.update(canonical_work_id='kitsu:8',edition='deluxe')
        self.assertEqual(MangaDexStructureResolver(request_json=lambda url:payload).lookup(e)['status'],'unavailable_identity')

    def test_reused_profile_query_keys_prove_additional_adult_preference_difference(self):
        from calibre_plugins.manganana.discovery.search_cache import query_cache_key
        snapshots=sorted(read(OUT/'manual-profile-audit/query_snapshot.json'),key=lambda r:r['created_utc'])
        for snapshot,adult in zip(snapshots,(False,True)):
            self.assertEqual(snapshot['key'],query_cache_key('Berserk','volume','en',adult,
                ['mangadex','mangapill','weebcentral','mangak','atsu'],False))

if __name__=='__main__':unittest.main()
