import unittest

from chapter_output import (
    ChapterOutputMode, VolumeEvidenceSource, normalize_volume_identifier,
    plan_chapter_outputs, resolve_volume_evidence, validate_manual_assignments,
)


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

    def test_missing_assignment_disables_automatic_mode(self):
        incomplete=VolumeEvidenceSource('mangadex','trusted-work','original',self.structure.chapters[:-1])
        evidence=self.resolve(sources=(incomplete,))
        self.assertFalse(evidence.available)
        self.assertIn('no explicit volume',evidence.reason)

    def test_conflicting_explicit_assignments_disable_automatic_mode(self):
        conflict=VolumeEvidenceSource('other','trusted-work','original',(chapter('other',2,9),))
        evidence=self.resolve(sources=(self.structure,conflict))
        self.assertFalse(evidence.available)
        self.assertIn('conflicting',evidence.reason)

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


if __name__ == '__main__':
    unittest.main()
