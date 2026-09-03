import unittest

from chapter_output import (
    ChapterOutputMode, VolumeEvidenceSource, normalize_volume_identifier,
    plan_chapter_outputs, resolve_group_cover_url, resolve_volume_evidence,
    validate_manual_assignments,
)
from chapter_workflow import chapter_output_title


def chapter(source, number, volume=None, pages=10, title=''):
    return {
        'id':f'{source}-{number}','chapter':str(number),'volume':volume,
        'pages':pages,'title':title,'_source_id':source,'_source_name':source.title(),
    }


class ChapterOutputTests(unittest.TestCase):
    def setUp(self):
        self.pages=(chapter('mangapill',1),chapter('mangapill',2),chapter('mangapill',3),chapter('mangapill',4))
        self.structure=VolumeEvidenceSource(
            'mangadex','trusted-work','original',
            (chapter('mangadex',1,1),chapter('mangadex',2,1),chapter('mangadex',3,2),chapter('mangadex',4,2)),
        )

    def resolve(self, chapters=None, sources=None, work='trusted-work', edition='original'):
        return resolve_volume_evidence(
            chapters or self.pages,(self.structure,) if sources is None else sources,page_source_id='mangapill',
            page_work_id=work,page_edition=edition,
        )

    def test_complete_explicit_cross_provider_mapping_enables_detected_groups(self):
        evidence=self.resolve()
        self.assertTrue(evidence.available)
        groups=plan_chapter_outputs(self.pages,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)
        self.assertEqual(['1','2'],[group.identifier for group in groups])
        self.assertEqual([2,2],[len(group.chapters) for group in groups])
        self.assertEqual(('mangapill',),groups[0].page_sources)
        self.assertIn('mangadex',evidence.provenance)

    def test_missing_assignment_becomes_standalone_without_disabling_mapped_groups(self):
        incomplete=VolumeEvidenceSource('mangadex','trusted-work','original',self.structure.chapters[:-1])
        evidence=self.resolve(sources=(incomplete,))
        self.assertTrue(evidence.available)
        groups=plan_chapter_outputs(self.pages,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)
        self.assertEqual('chapter',groups[-1].kind)
        self.assertEqual('4',groups[-1].chapters[0]['chapter'])

    def test_mixed_explicit_and_unassigned_chapters_keep_detected_volumes_available(self):
        selected=(chapter('mangadex',1,1),chapter('mangapill',2,None))
        structure=VolumeEvidenceSource('mangadex','trusted-work','original',(chapter('mangadex',1,1),))
        evidence=self.resolve(selected,(structure,))
        self.assertTrue(evidence.available)
        self.assertEqual((selected[1]['id'],),evidence.unassigned)
        groups=plan_chapter_outputs(selected,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)
        self.assertEqual(['volume','chapter'],[group.kind for group in groups])
        self.assertEqual(['1'],[row['chapter'] for row in groups[0].chapters])
        self.assertEqual(['2'],[row['chapter'] for row in groups[1].chapters])

    def test_all_unmapped_selection_keeps_detected_volumes_unavailable(self):
        evidence=self.resolve(sources=())
        self.assertFalse(evidence.available)
        self.assertEqual(tuple(row['id'] for row in self.pages),evidence.unassigned)

    def test_conflicting_explicit_assignment_becomes_standalone_without_inference(self):
        conflict=VolumeEvidenceSource('other','trusted-work','original',(chapter('other',2,9),))
        evidence=self.resolve(sources=(self.structure,conflict))
        self.assertTrue(evidence.available)
        groups=plan_chapter_outputs(self.pages,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)
        standalone=next(group for group in groups if group.kind == 'chapter')
        self.assertEqual('2',standalone.chapters[0]['chapter'])

    def test_no_volume_data_defaults_to_individual_compatible_plan(self):
        evidence=self.resolve(sources=())
        self.assertFalse(evidence.available)
        groups=plan_chapter_outputs(self.pages,ChapterOutputMode.INDIVIDUAL_CHAPTERS)
        self.assertEqual(4,len(groups))
        self.assertTrue(all(group.kind == 'chapter' for group in groups))

    def test_cross_provider_structure_requires_same_canonical_work(self):
        wrong=VolumeEvidenceSource('mangadex','different-work','original',self.structure.chapters)
        self.assertFalse(self.resolve(sources=(wrong,)).available)

    def test_cross_provider_structure_requires_compatible_edition(self):
        color=VolumeEvidenceSource('mangadex','trusted-work','official_color',self.structure.chapters)
        self.assertFalse(self.resolve(sources=(color,)).available)

    def test_manual_grouping_requires_every_chapter_and_supports_reassignment(self):
        assignments={row['id']:('1' if index < 2 else '2') for index,row in enumerate(self.pages)}
        self.assertTrue(validate_manual_assignments(self.pages,assignments))
        assignments.pop(self.pages[-1]['id'])
        self.assertFalse(validate_manual_assignments(self.pages,assignments))
        assignments[self.pages[-1]['id']]='2'
        assignments[self.pages[1]['id']]='1'
        groups=plan_chapter_outputs(self.pages,ChapterOutputMode.MANUAL_VOLUMES,manual_assignments=assignments)
        self.assertEqual(['1','2'],[group.identifier for group in groups])
        self.assertEqual([['1','2'],['3','4']],[[row['chapter'] for row in group.chapters] for group in groups])

    def test_selected_subset_is_all_or_nothing_for_that_subset(self):
        subset=(self.pages[1],self.pages[2])
        evidence=self.resolve(chapters=subset)
        groups=plan_chapter_outputs(subset,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)
        self.assertEqual([['2'],['3']],[[row['chapter'] for row in group.chapters] for group in groups])

    def test_mixed_plan_groups_all_mapped_chapters_and_drops_none(self):
        mixed=self.pages + (chapter('mangapill',5),)
        evidence=self.resolve(mixed)
        groups=plan_chapter_outputs(mixed,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)
        self.assertEqual(['volume','volume','chapter'],[group.kind for group in groups])
        self.assertEqual({'1','2','3','4','5'}, {
            row['chapter'] for group in groups for row in group.chapters
        })

    def test_decimal_chapters_are_safe_but_specials_are_not_inferred(self):
        decimal_pages=(chapter('mangapill','12.5'),)
        decimal_structure=VolumeEvidenceSource('mangadex','trusted-work','original',(chapter('mangadex','12.5','3.5'),))
        evidence=self.resolve(decimal_pages,(decimal_structure,))
        self.assertTrue(evidence.available)
        self.assertEqual('3.5',plan_chapter_outputs(decimal_pages,ChapterOutputMode.DETECTED_VOLUMES,evidence=evidence)[0].identifier)
        special=(chapter('mangapill','Special'),)
        self.assertFalse(self.resolve(special,(VolumeEvidenceSource('mangadex','trusted-work','original',(chapter('mangadex','Special',1),)),)).available)

    def test_totals_cannot_manufacture_boundaries(self):
        totals_only=VolumeEvidenceSource('anilist','trusted-work','original',())
        self.assertFalse(self.resolve(sources=(totals_only,)).available)

    def test_volume_metadata_and_review_totals_are_derivable_from_plan(self):
        groups=plan_chapter_outputs(self.pages,ChapterOutputMode.DETECTED_VOLUMES,evidence=self.resolve())
        records=[group.to_record() for group in groups]
        self.assertEqual([1.0,2.0],[row['volume'] for row in records])
        self.assertEqual(40,sum(chapter['pages'] for row in records for chapter in row['chapters']))

    def test_volume_identifier_uses_existing_decimal_numeric_conventions(self):
        self.assertEqual('2.5',normalize_volume_identifier('02.500'))
        self.assertIsNone(normalize_volume_identifier('Volume Two'))

    def test_generated_volumes_use_matching_selected_provider_covers(self):
        covers={1.0:'selected://volume-1',2.0:'selected://volume-2'}
        self.assertEqual(
            'selected://volume-1',
            resolve_group_cover_url('volume','1',covers,'selected://series'),
        )
        self.assertEqual(
            'selected://volume-2',
            resolve_group_cover_url('volume','2.0',covers,'selected://series'),
        )

    def test_generated_volume_cover_fallback_does_not_leak_between_volumes(self):
        covers={1:'selected://volume-1'}
        self.assertEqual(
            'selected://volume-1',
            resolve_group_cover_url('volume',1,covers,'selected://series'),
        )
        self.assertEqual(
            'selected://series',
            resolve_group_cover_url('volume',2,covers,'selected://series'),
        )

    def test_compatible_metadata_cover_wins_when_page_provider_differs(self):
        metadata_records=({'volume':'2.0','cover_url':'metadata://volume-2'},)
        self.assertEqual(
            'metadata://volume-2',
            resolve_group_cover_url(
                'volume',2,{2:'page-provider://volume-2'},'selected://series',metadata_records,
            ),
        )

    def test_distinct_record_level_covers_do_not_collide_between_volumes(self):
        metadata_records=(
            {'volume':'1','cover_url':'metadata://volume-1'},
            {'volume':'2','cover_url':'metadata://volume-2'},
        )
        self.assertEqual('metadata://volume-1',resolve_group_cover_url('volume',1,{},'selected://series',metadata_records))
        self.assertEqual('metadata://volume-2',resolve_group_cover_url('volume',2,{},'selected://series',metadata_records))

    def test_structural_evidence_never_becomes_cover_authority(self):
        evidence_provider_covers={1:'evidence://volume-1'}
        self.assertEqual(
            'selected://series',
            resolve_group_cover_url('volume',1,{},'selected://series'),
        )
        self.assertNotEqual(
            evidence_provider_covers[1],
            resolve_group_cover_url('volume',1,{},'selected://series'),
        )

    def test_individual_chapter_keeps_series_cover_fallback(self):
        self.assertEqual(
            'selected://series',
            resolve_group_cover_url('chapter',None,{1:'selected://volume-1'},'selected://series'),
        )

    def test_individual_chapter_titles_include_series_number_and_optional_name(self):
        self.assertEqual('Series (Ch. 05) - A New Beginning', chapter_output_title(
            'Series', chapter('mangadex','5',title='A New Beginning'), True,
        ))
        self.assertEqual('Series (Ch. 5)', chapter_output_title('Series', chapter('mangadex','5'), False))


if __name__ == '__main__':
    unittest.main()
