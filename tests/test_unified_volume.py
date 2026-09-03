import unittest

from publication_manifest import PublicationManifestBuilder, build_publication_projection
from unified_volume import build_unified_volume_plan, selected_unified_volume_groups


def manifest(chapters):
    builder = PublicationManifestBuilder({'canonical_identity':'work','title':'Work'})
    builder.apply_wikipedia({'status':'valid_with_data','chapters':chapters})
    return builder.build()


class UnifiedVolumePlanTests(unittest.TestCase):
    def test_steel_ball_run_native_24_volume_control(self):
        rows = tuple({'id':str(volume), 'chapter':str(volume), 'volume':str(volume)}
                     for volume in range(1, 25))
        plan = build_unified_volume_plan({}, rows, build_publication_projection(rows, None))
        self.assertEqual(list(map(float, range(1, 25))), plan['volumes'])
        self.assertEqual((24, 0, 0), (plan['native_volume_count'],
                                     plan['derived_volume_count'], plan['bonus_chapters']))

    def test_native_inventory_is_immediate_without_reference(self):
        rows = ({'id':'a','chapter':'1','volume':'1'}, {'id':'b','chapter':'2','volume':'2'})
        projection = build_publication_projection(rows, None, 'provider', 'provider')
        plan = build_unified_volume_plan({}, rows, projection, 'provider', 'Provider')
        self.assertEqual([1.0, 2.0], plan['volumes'])
        self.assertEqual(2, plan['native_volume_count'])
        self.assertEqual(0, plan['derived_volume_count'])
        self.assertFalse(plan['requires_grouped_output'])

    def test_chapter_only_inventory_becomes_safe_derived_volumes(self):
        rows = tuple({'id':str(ch), 'chapter':str(ch), 'volume':None} for ch in range(1, 7))
        structure = tuple({'chapter':str(ch), 'volume':'1' if ch <= 3 else '2'} for ch in range(1, 7))
        projection = build_publication_projection(rows, manifest(structure), 'mangapill', 'mangapill')
        plan = build_unified_volume_plan({}, rows, projection, 'mangapill', 'MangaPill')
        self.assertEqual([1.0, 2.0], plan['volumes'])
        self.assertEqual({1.0:3, 2.0:3}, plan['chapters_by_volume'])
        self.assertEqual(0, plan['bonus_chapters'])
        self.assertEqual(2, plan['derived_volume_count'])
        self.assertTrue(plan['requires_grouped_output'])

    def test_bleach_698_chapters_derive_exactly_74_volumes(self):
        rows = tuple({'id':str(ch), 'chapter':str(ch), 'volume':None,
                      '_source_id':'mangapill'} for ch in range(1, 699))
        structure = tuple({'chapter':str(ch), 'volume':str(((ch - 1) * 74 // 698) + 1)}
                          for ch in range(1, 699))
        projection = build_publication_projection(rows, manifest(structure), 'mangapill', 'mangapill')
        plan = build_unified_volume_plan({}, rows, projection, 'mangapill', 'MangaPill')
        self.assertEqual(74, len(plan['volumes']))
        self.assertEqual(698, sum(plan['chapters_by_volume'].values()))
        self.assertEqual(0, plan['bonus_chapters'])

    def test_mangadex_native_volume_39_does_not_materialize_catalog_only_volumes(self):
        rows = ({'id':'39','chapter':'340','volume':'39','_source_id':'mangadex'},)
        structure = tuple({'chapter':str(ch), 'volume':str(((ch - 1) // 10) + 1)}
                          for ch in range(1, 741))
        projection = build_publication_projection(rows, manifest(structure), 'mangadex', 'mangadex')
        plan = build_unified_volume_plan({}, rows, projection, 'mangadex', 'MangaDex')
        self.assertEqual([39.0], plan['volumes'])
        self.assertEqual(0, plan['derived_volume_count'])

    def test_mixed_native_derived_and_unmapped_remain_distinct(self):
        rows = (
            {'id':'1','chapter':'1','volume':'1'},
            {'id':'2','chapter':'2','volume':'2'},
            {'id':'3','chapter':'3','volume':None},
            {'id':'4','chapter':'4','volume':None},
        )
        projection = build_publication_projection(rows, manifest((
            {'chapter':'1','volume':'1'}, {'chapter':'2','volume':'2'},
            {'chapter':'3','volume':'3'},
        )), 'provider', 'provider')
        plan = build_unified_volume_plan({}, rows, projection, 'provider', 'Provider')
        self.assertEqual([1.0, 2.0, 3.0], plan['volumes'])
        self.assertEqual(2, plan['native_volume_count'])
        self.assertEqual(1, plan['derived_volume_count'])
        self.assertEqual(1, plan['bonus_chapters'])
        groups = selected_unified_volume_groups(plan, (2, 3), True)
        self.assertEqual(['volume','volume','standalone'], [row['kind'] for row in groups])
        self.assertEqual(['2','3','4'], [row['chapters'][0]['id'] for row in groups])

    def test_duplicate_chapter_rows_are_not_force_mapped(self):
        rows = ({'id':'a','chapter':'1','volume':None}, {'id':'b','chapter':'1','volume':None})
        projection = build_publication_projection(rows, manifest(({'chapter':'1','volume':'1'},)))
        plan = build_unified_volume_plan({}, rows, projection)
        self.assertEqual([], plan['volumes'])
        self.assertEqual(2, plan['bonus_chapters'])

    def test_one_piece_scale_keeps_unmapped_tail_out_of_volume_groups(self):
        rows = tuple({'id':str(ch), 'chapter':str(ch), 'volume':None,
                      '_source_id':'mangapill', '_source_name':'MangaPill'}
                     for ch in range(1, 1208))
        structure = tuple({'chapter':str(ch), 'volume':str(((ch - 1) * 115 // 1195) + 1)}
                          for ch in range(1, 1196))
        projection = build_publication_projection(rows, manifest(structure), 'mangapill', 'mangapill')
        plan = build_unified_volume_plan({}, rows, projection, 'mangapill', 'MangaPill')
        self.assertEqual(115, len(plan['volumes']))
        self.assertEqual(12, plan['bonus_chapters'])
        mapped = sum(len(group['chapters']) for group in plan['volume_groups']
                     if group['kind'] == 'volume')
        self.assertEqual(1195, mapped)

    def test_conan_tail_does_not_invent_volume_109(self):
        rows = tuple({'id':str(ch), 'chapter':str(ch), 'volume':None} for ch in range(1154, 1160))
        projection = build_publication_projection(
            rows, manifest(({'chapter':'1154','volume':'108'},)), 'mangadex', 'mangadex'
        )
        plan = build_unified_volume_plan({}, rows, projection, 'mangadex', 'MangaDex')
        self.assertEqual([108.0], plan['volumes'])
        self.assertEqual(5, plan['bonus_chapters'])
        self.assertNotIn(109.0, plan['volumes'])

    def test_selected_derived_volumes_finalize_once_with_acquisition_source(self):
        rows = tuple({'id':str(ch), 'chapter':str(ch), 'volume':None,
                      '_source_id':'mangapill', '_source_name':'MangaPill'} for ch in range(1, 7))
        structure = tuple({'chapter':str(ch), 'volume':str((ch + 1) // 2)} for ch in range(1, 7))
        projection = build_publication_projection(rows, manifest(structure), 'mangapill', 'mangapill')
        plan = build_unified_volume_plan({}, rows, projection, 'mangapill', 'MangaPill')
        groups = selected_unified_volume_groups(plan, (2, 3), False)
        self.assertEqual([2.0, 3.0], [group['volume'] for group in groups])
        self.assertTrue(all({row['_source_id'] for row in group['chapters']} == {'mangapill'}
                            for group in groups))

    def test_ippo_scale_groups_1517_rows_in_one_pass_model(self):
        rows = tuple({'id':str(ch), 'chapter':str(ch), 'volume':None}
                     for ch in range(1, 1518))
        structure = tuple({'chapter':str(ch), 'volume':str(((ch - 1) * 145 // 1517) + 1)}
                          for ch in range(1, 1518))
        projection = build_publication_projection(rows, manifest(structure))
        plan = build_unified_volume_plan({}, rows, projection)
        self.assertEqual(145, len(plan['volumes']))
        self.assertEqual(1517, sum(plan['chapters_by_volume'].values()))

    def test_fractional_chapter_uses_existing_projection_semantics(self):
        rows = ({'id':'12','chapter':'12','volume':None},
                {'id':'12.5','chapter':'12.5','volume':None})
        projection = build_publication_projection(
            rows, manifest(({'chapter':'12','volume':'2'},))
        )
        plan = build_unified_volume_plan({}, rows, projection)
        self.assertEqual({2.0:2}, plan['chapters_by_volume'])
        self.assertEqual(1, projection.coverage['derived_fractional'])


if __name__ == '__main__':
    unittest.main()
