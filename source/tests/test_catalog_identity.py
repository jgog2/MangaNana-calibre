"""Exact acquisition relabeling controls; no database, Qt, or network."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from calibre_plugins.manganana.publication.catalog_reader import decide, selected_groups

FIXTURE = Path(__file__).parent/'fixtures/catalog_bridge/haikyu_catalog.json'


class CatalogIdentityTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        record = self.data['record']; binding = record['acquisitions'][0]
        self.context = dict(record['work'], identity_trusted=True, layout_id=record['layout']['layout_id'])
        self.row = {'id':binding['acquisition_id'],'_source_id':'mangak','chapter':'2.1',
                    '_provider_record_id':'D6jMm9xD','_provider_label':'Chapter 2.1','volume':None}
        self.rows = [self.row]
        self.live = ({'kind':'standalone','identifier':'standalone','volume':None,'chapters':tuple(self.rows)},)

    def decision(self): return decide(self.data,self.context,self.rows,self.live)
    def declined(self):
        decision = self.decision()
        self.assertEqual('ineligible',decision['decision'],decision)
        self.assertIs(self.live,selected_groups(decision,self.live,True))
        return decision

    def test_exact_identity_and_volume_with_preserved_provenance(self):
        decision = self.decision(); self.assertEqual('needs_consent',decision['decision'],decision)
        groups = selected_groups(decision,self.live,True)
        self.assertEqual('5',groups[0]['identifier'])
        row = groups[0]['chapters'][0]
        self.assertEqual('41',row['chapter']); self.assertEqual(self.row['id'],row['id'])
        self.assertEqual('2.1',row['_provider_chapter'])
        self.assertEqual('D6jMm9xD',row['_provider_record_id'])
        self.assertEqual('Chapter 2.1',row['_catalog_identity']['provider_label'])
        self.assertEqual(['phase9c-target-inspection','phase9d-owner-scope'],row['_catalog_identity']['evidence_refs'])
        self.assertEqual('ja',decision['layout']['publication_language'])
        self.assertEqual('en',self.context['acquisition_language'])
        self.assertEqual('2.1',self.row['chapter']); self.assertNotIn('_catalog_identity',self.row)

    def test_live_default_and_decline_exact_noop(self):
        self.assertIs(self.live,selected_groups(self.decision(),self.live))
        self.assertEqual('2.1',self.live[0]['chapters'][0]['chapter'])

    def test_different_acquisition_url_same_label(self):
        self.row['id']='https://mangak.io/other-work/chapter-2-1'; self.declined()

    def test_reused_url_different_opaque_record(self):
        self.row['_provider_record_id']='different'; self.declined()

    def test_missing_opaque_record(self):
        del self.row['_provider_record_id']; self.declined()

    def test_missing_captured_opaque_record(self):
        del self.data['record']['acquisitions'][0]['provider_record_id']; self.declined()

    def test_empty_captured_record_rejected(self):
        self.data['record']['acquisitions'][0]['provider_record_id']=''; self.declined()

    def test_other_provider_same_url_label_record(self):
        self.row['_source_id']='atsu'; self.declined()

    def test_colored_edition_not_inherited(self):
        for edition in ('official_color','fan_color','omnibus','unknown'):
            self.context['edition']=edition; self.declined()

    def test_unknown_or_wrong_language_not_inferred_from_layout(self):
        for language in ('ja','unknown',''):
            self.context['acquisition_language']=language; self.declined()

    def test_other_market_layout_not_inherited(self):
        self.context['layout_id']='english-viz'; self.declined()

    def test_changed_provider_number_fails(self):
        self.row['chapter']='41'; self.declined()

    def test_missing_untrusted_or_conflicting_work_fails(self):
        self.context['identity_trusted']=False; self.declined()
        self.context['identity_trusted']=True; self.context['external_ids']={'anilist_id':'other'}; self.declined()

    def test_duplicate_selected_acquisition(self):
        self.rows.append(deepcopy(self.row)); self.declined()

    def test_conflicting_binding(self):
        binding=deepcopy(self.data['record']['acquisitions'][0]); binding['chapter_id']='42'
        self.data['record']['acquisitions'].append(binding); self.declined()

    def test_two_selected_acquisitions_for_same_canonical_identity_fail(self):
        binding=deepcopy(self.data['record']['acquisitions'][0]); binding['acquisition_id']+='-alternate'
        self.data['record']['acquisitions'].append(binding)
        self.rows.append(dict(self.row,id=binding['acquisition_id'])); self.declined()

    def test_unmapped_selected_row_is_retained_as_missing(self):
        self.rows.append(dict(self.row,id='unresolved'))
        self.assertEqual('unresolved',self.declined()['missing_required_relationships'][0]['acquisition_id'])

    def test_membership_evidence_and_missing_member_guards(self):
        self.data['record']['memberships'][0]['evidence_refs']=[]; self.declined()
        self.data['record']['memberships'][0]['evidence_refs']=['shueisha-volume5-toc']
        self.data['record']['memberships'].append(dict(self.data['record']['memberships'][0],chapter_id='42'))
        self.declined()

    def test_identity_difference_visible_even_if_same_live_volume(self):
        self.live[0]['identifier']='5'
        self.assertEqual('2.1',self.decision()['differences'][0]['provider_chapter'])

    def test_group_order_is_canonical_without_mutating_acquisition_ids(self):
        record=self.data['record']; other=deepcopy(record['acquisitions'][0])
        other.update(acquisition_id='https://mangak.io/haikyu/chapter-40',provider_record_id='control-40',
                     provider_chapter='40',chapter_id='40')
        record['acquisitions'].append(other)
        record['memberships'].append(dict(record['memberships'][0],chapter_id='40'))
        self.rows.append(dict(self.row,id=other['acquisition_id'],chapter='40',_provider_record_id='control-40'))
        decision=self.decision(); self.assertEqual('needs_consent',decision['decision'],decision)
        self.assertEqual(['40','41'],[r['chapter'] for r in decision['groups'][0]['chapters']])


if __name__=='__main__': unittest.main()
