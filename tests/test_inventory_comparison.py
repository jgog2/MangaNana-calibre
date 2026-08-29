import unittest

from inventory_comparison import compare_inventories, inspect_source_inventory


class FakeSource:
    def __init__(self, source_id, name, plan=None, error=''):
        self.source_id=source_id; self.display_name=name
        self.capabilities=frozenset({'chapters'} | ({'volumes'} if source_id == 'mangadex' else set()))
        self.plan=plan or {}; self.error=error; self.calls=[]

    def get_download_plan(self, value, language):
        self.calls.append((value,language))
        if self.error:
            raise RuntimeError(self.error)
        return self.plan

    def get_chapters(self, value, language):
        if self.error:
            raise RuntimeError(self.error)
        rows=[]
        for volume, count in (self.plan.get('chapters_by_volume') or {}).items():
            for index in range(int(count or 0)):
                rows.append({'id':f'{self.source_id}-{volume}-{index}', 'volume':float(volume), 'chapter':str(index + 1)})
        for index in range(int(self.plan.get('bonus_chapters') or 0)):
            rows.append({'id':f'{self.source_id}-bonus-{index}', 'volume':None, 'chapter':str(index + 1)})
        return rows


def candidate(source_id, badge='', full_title='Series'):
    return {'source_id':source_id,'source_name':'MangaDex' if source_id=='mangadex' else 'MangaPill',
            'id':source_id+'-id','url':'https://example.test/'+source_id,
            'title':'Series','full_title':full_title,'badge':badge}


def plan(volumes=(), counts=(), standalone=0, aggregate_error='', feed_error=''):
    return {'volumes':list(volumes),'chapters_by_volume':dict(counts),
            'bonus_chapters':standalone,'aggregate_error':aggregate_error,'feed_error':feed_error}


class InventoryComparisonTests(unittest.TestCase):
    def inspect(self, source, language='en', result=None):
        return inspect_source_inventory(source,result or candidate(source.source_id),language)

    def test_mangadex_unusable_and_mangapill_usable_selects_mangapill(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan()))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=144)))
        decision=compare_inventories((dex,pill))
        self.assertEqual(decision.selected.source_id,'mangapill')
        self.assertIn('only source',decision.reason)

    def test_mangadex_usable_and_mangapill_unusable_selects_mangadex(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan((1,2),((1,10),(2,9)))))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan()))
        self.assertEqual(compare_inventories((dex,pill)).selected.source_id,'mangadex')

    def test_clearly_more_complete_source_is_selected(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan((1,),((1,20),))))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=100)))
        decision=compare_inventories((dex,pill))
        self.assertEqual(decision.selected.source_id,'mangapill')
        self.assertIn('more complete',decision.reason)

    def test_complete_inventory_beats_partial_inventory(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan((1,2),((1,50),(2,50)),feed_error='feed failed')))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=80)))
        decision=compare_inventories((dex,pill))
        self.assertEqual(decision.selected.source_id,'mangapill')
        self.assertIn('complete inventory',decision.reason)

    def test_native_volume_structure_breaks_close_volume_workflow_tie(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan((1,2),((1,20),(2,20)))))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=42)))
        decision=compare_inventories((dex,pill),workflow='volume')
        self.assertEqual(decision.selected.source_id,'mangadex')
        self.assertEqual(decision.selected.volume_ids,(1,2))
        self.assertTrue(decision.selected.language_match)

    def test_similarly_usable_sources_remain_ambiguous(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan((1,2),((1,20),(2,20)))))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=42)))
        decision=compare_inventories((dex,pill),workflow='chapter')
        self.assertTrue(decision.ambiguous)
        self.assertIsNone(decision.selected)
        self.assertIn('2 volumes, 40 chapters',dex.summary)
        self.assertIn('42 standalone chapters',pill.summary)

    def test_one_provider_failure_does_not_block_success(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',error='offline'))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=12)))
        decision=compare_inventories((dex,pill))
        self.assertEqual(decision.selected.source_id,'mangapill')
        self.assertEqual(dex.error,'offline')

    def test_all_provider_failure_has_combined_error(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',error='dex down'))
        pill=self.inspect(FakeSource('mangapill','MangaPill',error='pill down'))
        error=compare_inventories((dex,pill)).error
        self.assertIn('MangaDex: Unavailable (dex down)',error)
        self.assertIn('MangaPill: Unavailable (pill down)',error)

    def test_edition_mismatch_is_not_ranked(self):
        colored=self.inspect(FakeSource('mangadex','MangaDex',plan((1,),((1,20),))),
                             result=candidate('mangadex','COLOR','Series Official Colored'))
        original=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=100)))
        decision=compare_inventories((colored,original),expected_edition='official_color')
        self.assertEqual(decision.selected.source_id,'mangadex')

    def test_language_mismatch_producing_no_inventory_loses(self):
        dex_source=FakeSource('mangadex','MangaDex',plan())
        pill_source=FakeSource('mangapill','MangaPill',plan(standalone=8))
        dex=self.inspect(dex_source,'fr'); pill=self.inspect(pill_source,'fr')
        self.assertEqual(compare_inventories((dex,pill)).selected.source_id,'mangapill')
        self.assertEqual(dex_source.calls,[('https://example.test/mangadex','fr')])

    def test_provenance_and_deterministic_ranking_are_preserved(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan((1,),((1,10),))))
        pill=self.inspect(FakeSource('mangapill','MangaPill',plan(standalone=30)))
        first=compare_inventories((dex,pill)); second=compare_inventories((dex,pill))
        self.assertEqual(first,second)
        self.assertEqual(first.selected.result['source_id'],'mangapill')

    def test_single_provider_result_selects_directly(self):
        dex=self.inspect(FakeSource('mangadex','MangaDex',plan((1,),((1,10),))))
        decision=compare_inventories((dex,))
        self.assertEqual(decision.selected.source_id,'mangadex')
        self.assertFalse(decision.ambiguous)

    def test_native_metadata_without_readable_volume_chapters_is_not_usable(self):
        source=FakeSource('mangadex','MangaDex',plan((1,),(),0))
        inventory=self.inspect(source)
        self.assertEqual(inventory.native_volume_metadata, 1)
        self.assertEqual(inventory.native_volumes, 0)
        self.assertFalse(compare_inventories((inventory,), workflow='volume').selected)


if __name__ == '__main__':
    unittest.main()
