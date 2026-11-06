import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from calibre_plugins.manganana.discovery.canonical_identity import merge_calibre_tags

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('series_test_package'); package.__path__ = [str(ROOT)]
with patch.dict(sys.modules, {'series_test_package':package}):
    spec = importlib.util.spec_from_file_location('series_test_package.output_series_metadata', ROOT/'books/output/output_series_metadata.py')
    metadata = importlib.util.module_from_spec(spec); spec.loader.exec_module(metadata)

MAIN = (ROOT/'app/main.py').read_text(encoding='utf-8')
tree = ast.parse(MAIN)
dialog = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MangaNanaDialog')


class SeriesIndexTests(unittest.TestCase):
    def test_explicit_import_number_survives_flat_worker_snapshot_without_source_volume(self):
        row = dict(kind='import', import_id='pdf', volume=None, title='PDF')
        self.assertEqual(metadata.effective_output_metadata(row)['cover_number_kind'], 'standalone')
        row['output_overrides'] = {'series_index': 67}
        effective = metadata.effective_output_metadata(row)
        self.assertEqual((effective['cover_number_kind'], effective['series_index']), ('volume', 67))
        snapshot = dict(effective, kind='import', volume=None)
        self.assertEqual(metadata.effective_output_metadata(snapshot)['cover_number_kind'], 'volume')
        self.assertIsNone(row['volume'])

    def test_effective_overrides_win_without_mutating_source(self):
        row = dict(kind='volume',volume=14,title='Detected',series='Source',author='Source author',
                   output_overrides=dict(title='Corrected',series='Edited',author='Edited author',series_index=21))
        identity = metadata.output_identity(row)
        result = metadata.effective_output_metadata(row,output_format='pdf',cover_mode='stamp')
        self.assertEqual((result['title'],result['series'],result['author'],result['series_index']),
                         ('Corrected','Edited','Edited author',21))
        self.assertEqual((result['format'],result['cover_mode']),('pdf','stamp'))
        self.assertEqual((row['volume'],row['title']),(14,'Detected'))
        self.assertEqual(metadata.output_identity(dict(row,**result)),identity)

    def test_renumber_preserves_existing_fractional_support(self):
        self.assertEqual(metadata.renumber_values(3,5,1),[5,6,7])
        self.assertEqual(metadata.renumber_values(3,'5.5','.25'),[5.5,5.75,6])
        with self.assertRaises(ValueError): metadata.renumber_values(3,'NaN',1)

    def test_defaults_match_current_calibre_indices(self):
        self.assertEqual(metadata.planned_series_index(dict(volume=23)),23)
        self.assertEqual(metadata.planned_series_index(dict(kind='chapter',volume=None,chapter={'chapter':'5.5'})),5.5)
        self.assertEqual(metadata.planned_series_index(dict(kind='import',volume=2.5)),2.5)
        self.assertEqual(metadata.planned_series_index(dict(volume=None)),1)

    def test_integer_decimal_and_invalid_values(self):
        for text, value in (('5',5),('5.5',5.5),('23',23),('-0.5',-.5),('.25',.25)):
            self.assertEqual(metadata.parse_series_index(text),value)
        for text in ('','NaN','Infinity','1e3','5,5','abc','1.2.3'):
            with self.assertRaises(ValueError): metadata.parse_series_index(text)
        self.assertEqual(metadata.format_series_index(1e-7),'0.0000001')

    def test_multi_book_snapshot_does_not_modify_identity_or_other_fields(self):
        rows = [dict(kind='import',import_id=str(i),volume=i,title=f'Book {i}',selected=True,
                     series_index_override=value,cover_key=('unchanged',i)) for i,value in ((1,5),(2,5.5))]
        snapshots = [dict(row) for row in rows]
        overrides = metadata.snapshot_overrides(rows)
        for index, row in enumerate(rows):
            result = {key:value for key,value in row.items() if key != 'series_index_override'}
            result['path'] = f'{index}.cbz'
            updated = metadata.with_series_override(result,overrides)
            self.assertEqual(metadata.planned_series_index(updated),(5,5.5)[index])
            self.assertEqual({k:v for k,v in updated.items() if k != 'series_index_override'},result)
        self.assertEqual(rows,snapshots)

    def test_native_and_chapter_results_match_planned_rows(self):
        rows = [dict(kind='volume',volume=23,title='Volume',selected=True,series_index_override=5),
                dict(kind='chapter',volume=None,chapter={'chapter':'5.5'},title='Chapter',selected=True,series_index_override=23)]
        overrides = metadata.snapshot_overrides(rows)
        for result, expected in ((dict(volume=23,title='Volume'),5),
                                 (dict(kind='chapter',volume=5.5,title='Chapter'),23)):
            self.assertEqual(metadata.planned_series_index(metadata.with_series_override(result,overrides)),expected)


class VirtualLibraryTests(unittest.TestCase):
    def test_new_tag_preserves_existing_legacy_tags(self):
        self.assertIn("VL_NAME = 'MangaAnkā'", MAIN)
        self.assertIn("VL_TAG = 'MangaAnkā'", MAIN)
        tags = merge_calibre_tags(('MangaNana','User tag'),(), 'MangaAnkā')
        self.assertEqual(set(tags), {'MangaNana','MangaAnkā','User tag'})

    def test_new_virtual_library_preserves_existing_entries(self):
        method = next(node for node in dialog.body if isinstance(node,ast.FunctionDef) and node.name == 'maybe_offer_virtual_library')
        box = Mock(); create = object()
        box.addButton.side_effect = [create,object()]; box.clickedButton.return_value = create
        message = Mock(return_value=box); message.Icon.Question = 1
        message.ButtonRole.AcceptRole = 1; message.ButtonRole.RejectRole = 2
        checkbox = Mock(); checkbox.isChecked.return_value = False
        ns = dict(QMessageBox=message,QCheckBox=Mock(return_value=checkbox),VL_NAME='MangaAnkā',VL_TAG='MangaAnkā',prefs={'ask_virtual_library':True})
        exec(compile(ast.Module(body=[method],type_ignores=[]),'app/main.py','exec'),ns)
        old = {'MangaNana':'tags:="MangaNana"','Other':'tags:="Other"'}
        db = Mock(); db.pref.return_value = old
        owner = types.SimpleNamespace(db=db,destination=types.SimpleNamespace(api=Mock(return_value=db)),icon=None,add_log=Mock())
        ns['maybe_offer_virtual_library'](owner)
        self.assertEqual(owner.destination.api.call_count,2)
        db.set_pref.assert_called_once_with('virtual_libraries', {**old,'MangaAnkā':'tags:="MangaAnkā"'})
        self.assertEqual(old,{'MangaNana':'tags:="MangaNana"','Other':'tags:="Other"'})
        box.setWindowTitle.assert_called_once_with('MangaAnkā Virtual Library')
        owner.add_log.assert_called_once_with('Created MangaAnkā Virtual Library.')


if __name__ == '__main__': unittest.main()
