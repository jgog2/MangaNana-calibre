import unittest
from calibre_plugins.manganana.publication.inventory_coverage import chapter_range_text as caption

class ChapterRangeCaptionTests(unittest.TestCase):
    def rows(self,*values):return [{'chapter':v} for v in values]
    def test_requested_format(self):
        self.assertEqual('(Ch 1 - Ch 7)',caption(self.rows(7,6,5,4,3,2,1)))
    def test_decimal_sequence_is_one_compact_range(self):
        self.assertEqual('(Ch 0 - Ch 8.5)',caption(self.rows(0,1,1.1,1.2,2,2.3,3,4,6,7,8,8.1,8.2,8.3,8.5)))
    def test_single_and_zero(self):
        self.assertEqual('(Ch 0)',caption(self.rows(0)))
    def test_summary_uses_actual_numeric_endpoints(self):
        self.assertEqual('(Ch 1 - Ch 5)',caption(self.rows(1,2,4,5)))
    def test_decimal_and_special_labels_retained(self):
        self.assertEqual('(Ch 2 - Ch 2.5; Ch Extra)',caption(self.rows('2','2.5','Extra')))
    def test_publication_pre_serial_namespace_is_retained(self):
        rows=[{'chapter':i,'_publication_identity':{'episode_token':f'0-{i:02d}'}} for i in (3,2,1)]
        self.assertEqual('(Ch 0-01 - Ch 0-03)',caption(rows))
    def test_mixed_numbering_namespaces_do_not_bridge(self):
        self.assertEqual('(Ch 0-15 - Ch 0-16; Ch 1 - Ch 6)',caption(self.rows('0-15','0-16',1,2,3,4,5,6)))
    def test_duplicates_do_not_change_display_or_input(self):
        rows=self.rows(1,1,2);before=list(map(dict,rows))
        self.assertEqual('(Ch 1 - Ch 2)',caption(rows));self.assertEqual(before,rows)
    def test_missing_contents_are_not_guessed(self):
        for rows in ([],[{'id':'123'}],[{'_unit_kind':'volume','chapter':7}],[{'chapter':1},{'chapter':None}]):
            self.assertEqual('',caption(rows))
    def test_number_field_used_when_chapter_is_none(self):
        self.assertEqual('(Ch 6 - Ch 7)',caption([{'chapter':None,'number':6},{'number':7}]))

if __name__=='__main__':unittest.main()
