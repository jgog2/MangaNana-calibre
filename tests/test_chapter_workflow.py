import unittest
from pathlib import Path

from chapter_workflow import chapter_label, chapter_output_title, chapter_series_index, chapter_sort_key, chapter_selection_ids
from inventory_comparison import SourceInventory, compare_inventories


class ChapterWorkflowTests(unittest.TestCase):
    def test_numeric_decimal_and_special_ordering(self):
        rows = [{'id':'s','chapter':'Special'}, {'id':'d','chapter':'12.5'}, {'id':'n','chapter':'2'}]
        self.assertEqual([row['id'] for row in sorted(rows, key=chapter_sort_key)], ['n', 'd', 's'])

    def test_chapter_naming_and_calibre_index(self):
        chapter = {'id':'x', 'chapter':'12.5'}
        self.assertEqual(chapter_label(chapter, True), '12.5')
        self.assertEqual(chapter_output_title('Attack on Titan', chapter, True), 'Attack on Titan (Ch. 12.5)')
        self.assertEqual(chapter_series_index(chapter), 12.5)
        self.assertIsNone(chapter_series_index({'chapter':'Bonus'}))

    def test_individual_select_all_and_deselect_data_model(self):
        rows = [{'id':'1','chapter':'1'}, {'id':'2','chapter':'2'}]
        selected = chapter_selection_ids(rows)
        self.assertEqual(selected, {'1','2'})
        selected.discard('1')
        self.assertEqual(selected, {'2'})
        selected.clear()
        self.assertFalse(selected)

    def test_mode_changes_provider_preference(self):
        dex = SourceInventory('mangadex','MangaDex',{},'en','original',native_volumes=2,chapter_count=40,usable=True,complete=True)
        pill = SourceInventory('mangapill','MangaPill',{},'en','original',chapter_count=80,usable=True,complete=True)
        self.assertEqual(compare_inventories((dex,pill), workflow='volume').selected.source_id, 'mangadex')
        self.assertEqual(compare_inventories((dex,pill), workflow='chapter').selected.source_id, 'mangapill')

    def test_chapter_only_provider_qualifies_for_safe_volume_projection(self):
        pill = SourceInventory('mangapill','MangaPill',{},'en','original',chapter_count=80,usable=True,complete=True)
        decision = compare_inventories((pill,), workflow='volume')
        self.assertIs(decision.selected, pill)
        self.assertEqual(0, decision.selected.native_volumes)

    def test_readme_has_the_plain_language_tagline(self):
        readme = (Path(__file__).resolve().parent.parent / 'README.md').read_text(encoding='utf-8')
        self.assertIn("Reading manga shouldn't turn into a damn IT project.", readme)


if __name__ == '__main__':
    unittest.main()
