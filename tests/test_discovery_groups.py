import unittest
from calibre_plugins.manganana.discovery.discovery_groups import group_records, provider_key


class GroupingTests(unittest.TestCase):
    def row(self,source='mangadex',**kw):
        return dict(dict(source_id=source,id='a',url='https://example.invalid/'+source+'/a',title='Berserk',
            author='Kentaro Miura',year=1989,edition='original',medium='Manga',canonical_work_id='work:1',
            _canonical_identity_confidence='high'),**kw)

    def test_trusted_identity_groups_all_five_without_changing_records(self):
        rows=[self.row(s,id=str(i),source_chapter_count=i) for i,s in enumerate(('mangadex','mangapill','weebcentral','mangak','atsu'))]
        before=[dict(r) for r in rows];groups=group_records(rows)
        self.assertEqual(1,len(groups));self.assertEqual(rows,groups[0].records);self.assertEqual(before,rows)

    def test_similar_titles_without_evidence_remain_separate(self):
        for a,b in [('Berserk','Berserk'),('Berserk','Berserk!'),('Berserk','Berserk Remake')]:
            rows=[self.row(title=a,canonical_work_id='',author='',year=None),self.row('atsu',title=b,canonical_work_id='',author='',year=None)]
            self.assertEqual(2,len(group_records(rows)))

    def test_exact_corroborated_title_creator_year_edition_can_group(self):
        rows=[self.row(canonical_work_id=''),self.row('atsu',canonical_work_id='')]
        self.assertEqual(1,len(group_records(rows)))

    def test_different_publications_even_with_same_work_id(self):
        variations=[{'edition':'official_color'},{'edition':'fan_color'},{'edition':'remake'},
            {'edition':'webcomic'},{'medium':'Webcomic'},{'publication_format':'webcomic'},
            {'publication_identity':'new-publication'},{'language':'ja'},{'remake_of':'work:1'},
            {'canonical_work_id':'work:2'}]
        for change in variations:
            with self.subTest(change=change):self.assertEqual(2,len(group_records([self.row(),self.row('atsu',**change)])))

    def test_conflicting_creator_year_separate_without_trusted_id(self):
        for change in ({'author':'Someone Else'},{'year':2001}):
            self.assertEqual(2,len(group_records([self.row(canonical_work_id=''),self.row('atsu',canonical_work_id='',**change)])))

    def test_same_provider_distinct_ids_remain_separate(self):
        rows=[self.row(id='first'),self.row(id='second')]
        self.assertEqual(2,len(group_records(rows)))

    def test_group_order_is_first_ranked_record_child_order_retains_rank(self):
        a=self.row('atsu',id='first');b=self.row('mangak',id='other',canonical_work_id='other');c=self.row('mangadex',id='last')
        groups=group_records([a,b,c])
        self.assertEqual([a,c],groups[0].records);self.assertEqual([b],groups[1].records)
        self.assertEqual(('atsu','first'),provider_key(groups[0].records[0]))

    def test_unknown_editions_without_trusted_identity_remain_separate(self):
        self.assertEqual(2,len(group_records([self.row(canonical_work_id='',edition=''),self.row('atsu',canonical_work_id='',edition='')])))

if __name__=='__main__':unittest.main()
