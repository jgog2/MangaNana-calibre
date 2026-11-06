"""The 15 Phase 8 contract controls; no Qt, Calibre, network or database."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from calibre_plugins.manganana.publication.catalog_reader import decide, load_catalog, selected_groups

FIXTURE = Path(__file__).parent/'fixtures/catalog_bridge/vagabond_catalog.json'


class CatalogReaderTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        r = self.data['record']; self.rows = [{'id': b['acquisition_id'], '_source_id': b['provider'],
            'chapter': b['provider_chapter'], 'pages': 1} for b in r['acquisitions']]
        self.context = dict(r['work'], identity_trusted=True, layout_id=r['layout']['layout_id'])
        self.live = ({'kind': 'standalone', 'identifier': 'standalone', 'volume': None, 'chapters': tuple(self.rows)},)

    def decision(self):
        return decide(self.data, self.context, self.rows, self.live)

    def assert_declined(self):
        result = self.decision(); self.assertEqual('ineligible', result['decision'])
        self.assertIs(self.live, selected_groups(result, self.live, True))
        return result

    def test_01_catalog_absent(self):
        with self.assertRaises(FileNotFoundError): load_catalog(FIXTURE.with_name('not-present.json'))
        self.assertIs(self.live, selected_groups({'decision': 'ineligible'}, self.live))

    def test_02_disabled(self):
        self.assertIs(self.live, selected_groups(self.decision(), self.live, False))

    def test_03_corrupted_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.json'; path.write_text('{')
            with self.assertRaises(ValueError): load_catalog(path)

    def test_04_unsupported_schema(self):
        self.data['catalog_schema_version'] = 99; self.assert_declined()

    def test_05_wrong_work(self):
        self.context['canonical_work_id'] = 'different'; self.assert_declined()

    def test_06_wrong_edition(self):
        self.context['edition'] = 'omnibus'; self.assert_declined()

    def test_07_wrong_acquisition_language(self):
        self.context['acquisition_language'] = 'ja'; self.assert_declined()

    def test_08_incompatible_layout(self):
        self.context['layout_id'] = 'english-vizbig'; self.assert_declined()

    def test_09_unknown_layout(self):
        known = self.context['layout_id']
        for value in ('unknown', 'Unspecified', ''):
            self.context['layout_id'] = value; self.assert_declined()
        self.context['layout_id'] = known
        for field in ('publisher', 'market_relation', 'publication_language', 'format'):
            original = self.data['record']['layout'][field]
            self.data['record']['layout'][field] = 'unknown'; self.assert_declined()
            self.data['record']['layout'][field] = original

    def test_10_ambiguous_provider_identity(self):
        self.data['record']['acquisitions'].append(deepcopy(self.data['record']['acquisitions'][0]))
        self.assert_declined()

    def test_11_missing_required_chapter(self):
        self.rows.append({'id': 'unmapped-selected', '_source_id': 'atsu', 'chapter': '32'})
        self.assertEqual(1, len(self.assert_declined()['missing_required_relationships']))
        self.rows.pop(); self.rows.pop(0)
        self.assertEqual('1', self.assert_declined()['missing_required_relationships'][0]['chapter'])

    def test_12_unresolved_supplementary(self):
        self.data['record']['supplementary_identity_status'] = 'unresolved'
        self.data['record']['unresolved_acquisitions'].append({'provider': 'atsu', 'acquisition_id': 'opaque-extra',
            'reason': 'Chapter 12.5 has no verified canonical supplementary identity or membership.'})
        self.rows.append({'id': 'opaque-extra', '_source_id': 'atsu', 'chapter': '12.5'})
        result = self.assert_declined(); self.assertEqual(1, len(result['unresolved_identities']))
        self.rows.pop()
        result = self.decision()
        self.assertEqual('needs_consent', result['decision'])
        self.assertEqual(1, len(result['unresolved_identities']))  # Unselected unresolved acquisition retained.

    def test_13_provisional_without_approval(self):
        result = self.decision(); self.assertEqual('needs_consent', result['decision'])
        self.assertIs(self.live, selected_groups(result, self.live, False))

    def test_14_provisional_explicit_selection(self):
        groups = selected_groups(self.decision(), self.live, True)
        self.assertEqual(43, sum(len(g['chapters']) for g in groups))
        self.assertEqual(['1','2','3','37','standalone'], [g['identifier'] for g in groups])
        self.assertEqual(['323','324','325','326','327'], [r['chapter'] for r in groups[-1]['chapters']])
        self.assertIsNone(groups[-1]['volume'])

    def test_15_verified_compatible_synthetic_qualification(self):
        # Synthetic positive contract control; never exported/published as a
        # verified Vagabond record. Real integration fixture stays provisional.
        self.data['record']['qualification'] = 'verified'
        self.assert_declined()  # A qualification flag alone is insufficient.
        for kind in ('publication_scope_review', 'acquisition_scope_review'):
            self.data['record']['evidence'].append({'evidence_id': 'synthetic-'+kind,
                'source_url': 'fixture://synthetic-scope-review', 'inspected_at': '2026-10-08',
                'locator': 'Synthetic positive contract premise, not Vagabond verification', 'evidence_type': kind})
        self.data['record']['verification'] = {'scope_approved': True,
            'publication_relationships_verified': True, 'acquisition_relationships_verified': True,
            'canonical_work_id':self.context['canonical_work_id'],'layout_id':self.context['layout_id'],
            'evidence_refs': ['synthetic-publication_scope_review','synthetic-acquisition_scope_review']}
        self.assertEqual('eligible', self.decision()['decision'])
        self.assertIs(self.live, selected_groups(self.decision(), self.live, False))
        self.assertEqual(5, len(selected_groups(self.decision(), self.live, True)))

    def test_conflicting_memberships_rejected_by_changed_validator(self):
        conflict=deepcopy(self.data['record']['memberships'][0]); conflict['volume_id']='volume:2'
        self.data['record']['memberships'].append(conflict)
        self.assert_declined()


if __name__ == '__main__': unittest.main()
