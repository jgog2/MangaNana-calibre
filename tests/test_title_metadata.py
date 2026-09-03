import unittest

from enrichment_model import ExternalMangaCandidate
from title_metadata import external_candidate_title_rows, meaningful_alternate_titles, normalize_title_rows, title_language_label


class TitleMetadataTests(unittest.TestCase):
    def test_romanized_and_native_fields_keep_structured_classification(self):
        candidate=ExternalMangaCandidate(
            service='anilist',external_id='1',primary_title='Attack on Titan',
            english_title='Attack on Titan',romanized_title='Shingeki no Kyojin',native_title='進撃の巨人',
        )
        rows=external_candidate_title_rows(candidate)
        labels={row['title']:title_language_label(row) for row in rows}
        self.assertEqual('Japanese (Romanized)',labels['Shingeki no Kyojin'])
        self.assertEqual('Japanese',labels['進撃の巨人'])

    def test_structured_row_replaces_bare_unknown_duplicate(self):
        rows=normalize_title_rows((
            {'title':'Shingeki no Kyojin','language':'','primary':False},
            {'title':'Shingeki no Kyojin','language':'ja-ro','classification':'romanized','primary':False},
        ))
        self.assertEqual(1,len(rows))
        self.assertEqual('Japanese (Romanized)',rows[0]['language_label'])

    def test_one_distinct_title_does_not_enable_meaningless_chooser(self):
        self.assertEqual((),meaningful_alternate_titles((
            {'title':'Attack on Titan','language':'en','primary':True},
            {'title':' attack-on-titan ','language':'','primary':False},
        ),'Attack on Titan'))

    def test_alias_selection_data_is_metadata_only(self):
        record={'provider_id':'dex-1','work_id':'family-1','edition':'original','title':'Attack on Titan'}
        chosen=dict(record); chosen['title']='Shingeki no Kyojin'
        self.assertEqual(record['provider_id'],chosen['provider_id'])
        self.assertEqual(record['work_id'],chosen['work_id'])
        self.assertEqual(record['edition'],chosen['edition'])


if __name__ == '__main__':
    unittest.main()
