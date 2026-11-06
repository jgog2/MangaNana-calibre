"""Captured exact acquisitions and independently reviewed collected episodes."""
import copy
import json
from collections import Counter
from pathlib import Path
import unittest
from calibre_plugins.manganana.publication.publication_identity import validate_bridge
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.publication.unified_volume import build_unified_volume_plan, selected_unified_volume_groups
from calibre_plugins.manganana.publication.chapter_workflow import chapter_sort_key

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/berserk-bridge-activation'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def fixture(sid, bridge=True):
    base=OUT/'native-current'/sid
    captured=read(base/'cold-manifest.json');bundle=read(base/'cold-reference.json')
    rows=read(base/'cold-acquisition.json');work=dict(captured['work']);work['creator']=work['creator']['value']
    builder=PublicationManifestBuilder(work,captured['edition']['identity'],as_of=captured['runtime_publication']['as_of'])
    builder.apply_provider_inventory(rows,sid).apply_madb(bundle.get('madb')).apply_mangadex_structure(bundle.get('mangadex_structure')).apply_wikipedia(bundle.get('wikipedia'))
    manifest=builder.build('en')
    data=read(ROOT/'assets/publication_identity/berserk-reviewed-r1.json') if bridge is True else bridge if bridge else None
    records=read(ROOT/'build/berserk-live-investigation/selected-records.json')
    record=next(r for r in records if r['source_id']==sid)
    projection=build_publication_projection(rows,manifest,sid,sid,data,dict(source_work=record['url'],language='en'))
    plan=build_unified_volume_plan(read(base/'cold-native-plan.json'),rows,projection,sid,record['source_name'])
    return rows,projection,plan
def membership(plan):return {r['id']:g['volume'] for g in plan['volume_groups'] for r in g['chapters']}
def groups(plan):return {int(g['volume']):g for g in plan['volume_groups'] if g['volume'] is not None}

class CapturedBridgeActivation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUT/'native-current').is_dir():
            raise unittest.SkipTest('Private native acquisition/review captures are not distributed')
        cls.data=read(ROOT/'assets/publication_identity/berserk-reviewed-r1.json')
        cls.before={sid:fixture(sid,False) for sid in ('mangapill','weebcentral','mangadex')}
        cls.after={sid:fixture(sid) for sid in cls.before}

    def test_review_is_exact_and_schema_valid(self):
        index=validate_bridge(self.data)
        self.assertEqual(len(index.bindings),48);self.assertEqual(len(index.targets),32)
        ledger=read(OUT/'candidate-review-ledger.json')
        self.assertEqual(len(ledger),48)
        self.assertTrue(all(r['review_status']=='approved' and r['boundary_review'] and r['title_sample_page'] for r in ledger))
        self.assertTrue(all(s['status']==200 for r in ledger for s in r['reviewed_samples']))

    def test_all_acquisition_ids_urls_and_namespaces_conserved(self):
        for sid,count in [('weebcentral',403),('mangapill',405),('mangadex',404)]:
            rows,projection,plan=self.after[sid]
            with self.subTest(sid=sid):
                self.assertEqual(len(rows),count)
                self.assertEqual([c.acquisition for c in projection.chapters],rows)
                self.assertEqual(Counter(r['id'] for g in plan['volume_groups'] for r in g['chapters']),Counter(r['id'] for r in rows))
                self.assertEqual(len(membership(plan)),count)

    def test_only_48_reviewed_memberships_change(self):
        for sid in self.before:
            before=membership(self.before[sid][2]);after=membership(self.after[sid][2])
            changed={rid for rid in before if before[rid]!=after[rid]}
            expected={b['acquisition']['record_id'] for b in self.data['bindings'] if b['acquisition']['provider']==sid}
            self.assertEqual(changed,expected,sid)

    def test_new_volumes_have_exact_reviewed_episode_sets_and_order(self):
        for sid in ('mangapill','weebcentral'):
            byvol=groups(self.after[sid][2])
            self.assertEqual(self.after[sid][2]['volumes'],[float(n) for n in range(1,44)])
            for volume,pre,regular in [(1,range(1,4),[]),(2,range(4,6),[]),(3,range(6,10),[]),(4,range(10,15),[]),(5,[15,16],range(1,7)),(6,[],range(7,17))]:
                ordered=byvol[volume]['chapters']
                expected_pre=[b['acquisition']['record_id'] for n in pre for b in self.data['bindings'] if b['acquisition']['provider']==sid and b['target_id']==f'0-{n:02}']
                if sid=='mangapill':
                    expected_regular=[b['acquisition']['record_id'] for n in regular for b in self.data['bindings'] if b['acquisition']['provider']==sid and b['target_id']==f'{n:03}']
                else:
                    expected_regular=[r['id'] for n in regular for r in self.after[sid][0] if r['chapter']==str(n) and r.get('numbering_group')!='prologue']
                self.assertEqual([r['id'] for r in ordered],expected_pre+expected_regular,(sid,volume))
                self.assertEqual([r['id'] for r in sorted(ordered,key=chapter_sort_key)],expected_pre+expected_regular)
                self.assertEqual(selected_unified_volume_groups(self.after[sid][2],[volume])[0]['chapters'],ordered)

    def test_mangadex_plan_remains_identical(self):
        self.assertEqual(self.before['mangadex'][2],self.after['mangadex'][2])

    def test_partial_review_keeps_verified_subset_without_inventing_completeness(self):
        data=copy.deepcopy(self.data)
        binding=next(b for b in data['bindings'] if b['acquisition']['provider']=='mangapill' and b['target_id']=='0-16')
        missing=binding['acquisition']['record_id'];binding.update(status='pending',reason='Controlled revoked relationship')
        rows,p,plan=fixture('mangapill',data)
        self.assertEqual(len(groups(plan)[5]['chapters']),7)
        self.assertIsNone(membership(plan)[missing]);self.assertEqual(len(membership(plan)),405)
        self.assertNotIn('complete',groups(plan)[5])

    def test_disabling_and_revoking_bridge_restore_legacy_membership(self):
        data=copy.deepcopy(self.data);data['revision']='review-revoked'
        for b in data['bindings']:b.update(status='rejected',reason='Controlled review revocation')
        for sid in ('mangapill','weebcentral'):
            self.assertEqual(fixture(sid,data)[2],self.before[sid][2])

class PackagedBridgeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=read(ROOT/'assets/publication_identity/berserk-reviewed-r1.json')

    def test_packaged_review_counts_and_schema(self):
        index=validate_bridge(self.data)
        self.assertEqual(48,len(index.bindings));self.assertEqual(32,len(index.targets))

    def test_order_requires_identity_and_valid_review(self):
        rows=[dict(id='a',chapter='2',_publication_reading_order=-10),dict(id='b',chapter='1')]
        self.assertEqual([r['id'] for r in sorted(rows,key=chapter_sort_key)],['b','a'])
        for bad in (True,1.2,'1',1000001):
            data=copy.deepcopy(self.data);data['targets'][0]['reading_order']=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):validate_bridge(data)

    def test_duplicate_order_rejected(self):
        data=copy.deepcopy(self.data)
        approved=[t for t in data['targets'] if t['status']=='approved' and t['volume']=='1']
        approved[1]['reading_order']=approved[0]['reading_order']
        with self.assertRaises(ValueError):validate_bridge(data)

if __name__=='__main__':unittest.main()
