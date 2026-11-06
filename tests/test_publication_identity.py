"""Contract fixtures are synthetic and never ship as approved catalog data."""
import copy
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from calibre_plugins.manganana.publication.publication_identity import PublicationIdentity, AcquisitionIdentity, validate_bridge, compile_bridge, bridge_resource_stamp, load_bridge, structural_release_claims, qualify_structural_claims, structural_claim_inventory
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.publication.publication_preparation import presentation_identity
from calibre_plugins.manganana.publication.publication_preparation import prepare_publication
from calibre_plugins.manganana.metadata.references.wikipedia_reference import WikipediaPublicationAdapter, _WikipediaPage


def artifact(rows, tokens=None, volumes=None):
    tokens=tokens or [str(i+1) for i in range(len(rows))]
    volumes=volumes or ['1']*len(rows)
    review=dict(status='approved',revision='fixture-r1',reviewer='synthetic-test',
        reviewed_at='2026-10-12',relationship_verified=True,evidence_refs=['e'])
    data=dict(contract='publication-identity-bridge-v1',revision='fixture-r1',producer='synthetic-test-only',
        scope=dict(canonical_work='work',edition='original',layout='tankobon',language='en'),
        evidence=[dict(id='e',source_url='https://example.invalid/fixture',revision='1',
            locator='controlled distinct page identities',inspected_at='2026-10-12',authority='reviewed_content')],
        targets=[],bindings=[])
    for i,(row,token,volume) in enumerate(zip(rows,tokens,volumes)):
        target='t'+str(i)
        data['targets'].append(dict(id=target,identity=asdict(PublicationIdentity('work','original','tankobon',
            'serialized',token)),volume=volume,title='',**review))
        data['bindings'].append(dict(acquisition=asdict(AcquisitionIdentity.from_row(row,'p','https://example.invalid/work','en')),
            target_id=target,content_relation='one_to_one',**review))
    return data


def row(rid,label='1',group='a',**kw):
    return dict(id=rid,chapter=label,numbering_group=group,_source_id='p',**kw)


def project(rows,data=None,work='work',edition='original',language='en',runtime=None):
    builder=PublicationManifestBuilder(dict(canonical_identity=work,title='Fixture'),edition)
    builder.apply_provider_inventory(rows,'p')
    manifest=builder.build(language)
    if runtime:manifest.runtime_publication.update(runtime)
    return build_publication_projection(rows,manifest,'p','p',data,
        dict(source_work='https://example.invalid/work',language=language))


class IdentityContracts(unittest.TestCase):
    def test_exact_tokens_do_not_normalize(self):
        tokens=['0-01','0.01','0.1','0.10','Prologue 1','1']
        self.assertEqual(len({PublicationIdentity('work','original','tankobon','serialized',t) for t in tokens}),6)

    def test_float_rejected(self):
        with self.assertRaises(ValueError):PublicationIdentity('w','e','l','n',.1)

    def test_serialization_and_immutable_index(self):
        data=artifact([row('a')]);idx=compile_bridge(json.loads(json.dumps(data)))
        self.assertEqual(idx.digest,validate_bridge(data).digest)
        with self.assertRaises(TypeError):idx.bindings['x']='bad'

    def test_unapproved_cannot_map(self):
        rows=[row('a')];data=artifact(rows)
        data['bindings'][0].update(status='pending',reason='Content not verified')
        self.assertFalse(project(rows,data).chapters[0].effective_volume.present)

    def test_two_namespaces_two_verified_episodes(self):
        rows=[row('a',group='pre'),row('b',group='regular')]
        p=project(rows,artifact(rows,['0-01','001'],['1','5']))
        self.assertEqual([c.effective_volume.value for c in p.chapters],['1','5'])
        self.assertEqual([c.acquisition['id'] for c in p.chapters],['a','b'])
        self.assertEqual([c.acquisition['chapter'] for c in p.chapters],['1','1'])

    def test_distinct_labels_same_episode_remain_ambiguous(self):
        rows=[row('a','Prologue 1'),row('b','0.01',group='b')]
        p=project(rows,artifact(rows,['0-01','0-01']))
        self.assertTrue(all(not c.effective_volume.present for c in p.chapters))
        self.assertTrue(all(c.mapping_state=='identity_bridge_conflict' for c in p.chapters))

    def test_namespace_without_proof_stays_standalone(self):
        rows=[row('a',group='pre'),row('b',group='regular')]
        p=project(rows)
        self.assertTrue(all(not c.effective_volume.present for c in p.chapters))

    def test_exact_scope_negative_matrix(self):
        original=row('a');data=artifact([original])
        for name,value in [('id','other'),('chapter','01'),('numbering_group','b'),('_source_id','other'),
                           ('language','ja'),('source_url','https://example.invalid/other')]:
            with self.subTest(name=name):
                changed=dict(original,**{name:value})
                self.assertFalse(project([changed],data).chapters[0].effective_volume.present)
        for kwargs in [dict(work='other'),dict(edition='color'),dict(edition='webcomic'),dict(language='ja')]:
            with self.subTest(kwargs=kwargs):self.assertFalse(project([original],data,**kwargs).chapters[0].effective_volume.present)

    def test_provider_explicit_volume_precedence(self):
        rows=[row('a',volume='7')];p=project(rows,artifact(rows,volumes=['1']))
        self.assertEqual(p.chapters[0].effective_volume.value,'7')
        self.assertEqual(p.chapters[0].mapping_state,'provider_explicit')

    def test_fractional_and_unnumbered_exact_records(self):
        rows=[row('a','0.10'),row('b','0.1'),row('c','')]
        data=artifact(rows,['0.10','0.1','named-episode'],['1','2','3'])
        self.assertEqual([c.effective_volume.value for c in project(rows,data).chapters],['1','2','3'])

    def test_conflicting_membership_rejected(self):
        data=artifact([row('a'),row('b')],['same','same'],['1','2'])
        with self.assertRaises(ValueError):validate_bridge(data)

    def test_duplicate_acquisition_rejected(self):
        data=artifact([row('a'),row('a')])
        with self.assertRaises(ValueError):validate_bridge(data)

    def test_malformed_array_entries_fail_closed(self):
        for name in ('evidence','targets','bindings'):
            data=artifact([row('a')]);data[name]=['invalid-entry']
            with self.subTest(name=name),self.assertRaises(ValueError):validate_bridge(data)

    def test_review_and_evidence_required(self):
        for field,value in [('relationship_verified',False),('reviewer',''),('evidence_refs',['missing'])]:
            data=artifact([row('a')]);data['bindings'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_bridge(data)

    def test_wildcard_split_merge_and_scope_rejected(self):
        for field,value in [('content_relation','split'),('content_relation','merged')]:
            data=artifact([row('a')]);data['bindings'][0][field]=value
            with self.subTest(value=value),self.assertRaises(ValueError):validate_bridge(data)
        data=artifact([row('a')]);data['bindings'][0]['acquisition']['record_id']='*'
        with self.assertRaises(ValueError):validate_bridge(data)
        data=artifact([row('a')]);data['targets'][0]['identity']['layout']='other'
        with self.assertRaises(ValueError):validate_bridge(data)

    def test_revision_invalidates_index_and_generation(self):
        data=artifact([row('a')]);idx=compile_bridge(data);before=presentation_identity(dict(bridge=data))
        data['evidence'][0]['revision']='2'
        self.assertNotEqual(idx.digest,compile_bridge(data).digest)
        self.assertNotEqual(before,presentation_identity(dict(bridge=data)))

    def test_file_revision_guard_and_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bridge.json';path.write_text(json.dumps(artifact([row('a')])) )
            with patch.dict(os.environ,MANGAANKA_PUBLICATION_BRIDGE_PATH=str(path)):
                stamp=bridge_resource_stamp();self.assertEqual(load_bridge(stamp)['revision'],'fixture-r1')
                path.write_text('{}')
                with self.assertRaises(InterruptedError):load_bridge(stamp)

    def test_structural_claims_preserved_and_unclassified_isolated(self):
        rows=[row('a','0.01'),row('b','0.01')];data=artifact(rows,['early','regular'],['1','3'])
        for b in data['bindings']:
            b['acquisition'].update(provider='mangadex',source_work='md-work',
                url='https://mangadex.org/chapter/'+b['acquisition']['record_id'],numbering_namespace='')
        aggregate=dict(volumes={'1':dict(volume='1',chapters={'a':dict(chapter='0.01',id='a',others=['unknown'])}),
                                '3':dict(volume='3',chapters={'b':dict(chapter='0.01',id='b')})})
        metadata=dict(data=[dict(id=rid,attributes=dict(title=rid,translatedLanguage='en',chapter='0.01',volume=vol),
            relationships=[dict(type='scanlation_group',id='same-group'),dict(type='manga',id='md-work')]) for rid,vol in [('a','1'),('b','3')]])
        claims=structural_release_claims(aggregate,metadata,'md-work')
        qualified,conflicts=qualify_structural_claims(claims,compile_bridge(data))
        compact=structural_claim_inventory(aggregate,metadata,'md-work')
        self.assertEqual(qualify_structural_claims(compact,compile_bridge(data)),(qualified,conflicts))
        self.assertEqual(len(qualified),3);self.assertFalse(conflicts)
        self.assertEqual([r['classification'] for r in qualified],['verified','unresolved','verified'])
        self.assertEqual(qualified[0]['group_ids'],qualified[2]['group_ids'])
        claims[2]['volume']='7'
        self.assertEqual(len(qualify_structural_claims(claims,compile_bridge(data))[1]),1)

    def test_structural_conflict_blocks_bridge_not_native(self):
        rows=[row('a')];data=artifact(rows)
        a=data['bindings'][0]['acquisition']
        claim=dict(a,volume='9');claim['classification']='unresolved'
        p=project(rows,data,runtime=dict(identity_reference_claims=[claim]))
        self.assertFalse(p.chapters[0].effective_volume.present)
        p=project([dict(rows[0],volume='7')],data,runtime=dict(identity_reference_claims=[claim]))
        self.assertEqual(p.chapters[0].effective_volume.value,'7')

    def test_unnumbered_titles_are_evidence_not_episode_numbers(self):
        page=_WikipediaPage('List of Fixture chapters','123','456',
            '{{Graphic novel list|VolumeNumber=1|ChapterList=\n* The Beginning\n* Another Episode\n* 1. Numbered\n}}')
        adapter=WikipediaPublicationAdapter()
        evidence=adapter._unnumbered_evidence(page,'Fixture')
        self.assertEqual(len(evidence),2)
        self.assertTrue(all(e['source_revision_id']=='456' and e['status']=='unassociated' for e in evidence))
        self.assertTrue(all('episode_token' not in e for e in evidence))

    def test_legacy_ordinary_and_prologue_controls(self):
        rows=[row('a','1',volume='1'),row('b','2',volume='1'),row('c','Prologue 1')]
        p=project(rows)
        self.assertEqual([c.effective_volume.value for c in p.chapters],['1','1',None])
        self.assertTrue(all(c.publication_identity is None for c in p.chapters))

    def test_captured_english_ids_exact_native_membership_fixture(self):
        root=Path(__file__).resolve().parents[1]
        evidence=json.loads((root/'build/berserk-early-volume-audit/publication-evidence.json').read_text(encoding='utf-8'))
        acquired=json.loads((root/'build/berserk-optimization/09-final-live/mangadex/cold-acquisition.json').read_text(encoding='utf-8'))
        by_id={r['id']:r for r in acquired}
        rows=[dict(by_id[e['mangadex_id']]) for e in evidence]
        # Test-only episode identities are the independently observed English
        # releases themselves. This does NOT approve WC/MP aliases or 0-xx tokens.
        data=artifact(rows,[e['mangadex_id'] for e in evidence],[e['volume'] for e in evidence])
        source='https://mangadex.org/title/801513ba-a712-498c-8f57-cae55b38cc92'
        for b in data['bindings']:b['acquisition']['source_work']=source
        data['evidence'][0].update(source_url=source,authority='provider_metadata',
            revision='captured-2026-10-11',locator='52 exact English release IDs, native volumes and titles; test-only review')
        builder=PublicationManifestBuilder(dict(canonical_identity='work',title='Berserk'),'original')
        manifest=builder.build('en')
        stripped=[dict(r,volume=None) for r in rows]
        p=build_publication_projection(stripped,manifest,'mangadex','mangadex',data,
            dict(source_work=source,language='en'))
        self.assertEqual({c.acquisition['id']:c.effective_volume.value for c in p.chapters},
                         {e['mangadex_id']:e['volume'] for e in evidence})
        self.assertEqual(len(p.chapters),52)

    def test_worker_consumes_optional_artifact_and_preserves_acquisition(self):
        rows=[row('a',group='pre'),row('b',group='regular')]
        data=artifact(rows,['early','regular'],['1','5'])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bridge.json';path.write_text(json.dumps(data))
            with patch.dict(os.environ,MANGAANKA_PUBLICATION_BRIDGE_PATH=str(path)):
                inputs=dict(work=dict(canonical_identity='work',title='Fixture'),edition='original',
                    chapters=rows,source_id='p',source_name='Fixture',source_url='https://example.invalid/work',
                    covers={},language='en',enrichment={},mode='volume',native_plan=None,
                    identity_bridge_stamp=bridge_resource_stamp())
                prepared=prepare_publication(inputs,{})
                _,manifest,p,plan=prepared.materialize()
                self.assertEqual([c.effective_volume.value for c in p.chapters],['1','5'])
                self.assertEqual([c.acquisition for c in p.chapters],rows)
                self.assertEqual(plan['volumes'],[1.,5.])
                # Invalid optional input falls back atomically, with diagnostics.
                path.write_text('{}');inputs['identity_bridge_stamp']=bridge_resource_stamp()
                _,m,p,_=prepare_publication(inputs,{}).materialize()
                self.assertIn('identity_bridge_error',m.runtime_publication)
                self.assertTrue(all(not c.effective_volume.present for c in p.chapters))

    def test_captured_wikipedia_early_unnumbered_evidence(self):
        root=Path(__file__).resolve().parents[1]
        base=root/'build/berserk-optimization/09-final-live/mangapill'
        trace=json.loads((base/'trace-live.json').read_text(encoding='utf-8'))
        body=next(base/r['body'] for r in trace['requests'] if r.get('body') and 'wikipedia' in r['url'] and
            'action=parse' in r['url'])
        payload=json.loads(body.read_text(encoding='utf-8'))
        page=payload['parse'];text=page['wikitext']['*']
        if not text:self.fail('Captured Wikipedia source text missing')
        record=_WikipediaPage(page['title'],str(page['pageid']),str(page['revid']),text)
        adapter=WikipediaPublicationAdapter();e=adapter._unnumbered_evidence(record,'Berserk')
        early=[r for r in e if r['volume'] in ('1','2','3','4','5')]
        self.assertEqual(len(early),8)
        self.assertTrue(all('episode_token' not in r and r['raw_source'] for r in early))
        b=PublicationManifestBuilder(dict(canonical_identity='work',title='Berserk'),'original')
        b.apply_wikipedia(dict(unnumbered_evidence=early))
        m=b.build('en')
        self.assertEqual(len(m.runtime_publication['unnumbered_publication_evidence']),8)
        self.assertFalse(m.chapters)


if __name__=='__main__':unittest.main()
