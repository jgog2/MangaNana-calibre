"""Native Import ownership and exact-match planner work at large inventory size."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from qt.core import QApplication,QDialog,QFileDialog,Qt
from calibre_plugins.manganana.presentation.non_modal_window import PluginFileDialog
from calibre_plugins.manganana.providers import cross_source_fallback as fallback
from tests import test_cross_source_fallback as fixtures

APP=QApplication.instance() or QApplication([])
ROOT=Path(__file__).resolve().parents[1]

class ImportResponseTests(unittest.TestCase):
    def test_bulk_metadata_publishes_once_and_keeps_unchecked_outputs_untouched(self):
        from calibre_plugins.manganana.books.imports.import_workflow import ImportWorkflowMixin
        rows=[dict(selected=True,title='A'),dict(selected=False,title='B'),dict(selected=True,title='C')]
        refreshed=[];published=[]
        def override(row,key,value,refresh=True):
            row[key]=value
            if refresh:refreshed.append((row,key))
        owner=SimpleNamespace(preview_data=dict(rows=rows),_preview_build_signature=None,
            _import_edited_fields={'title','author'},
            title=SimpleNamespace(text=lambda:'Edited'),author=SimpleNamespace(text=lambda:'Author'),
            series=SimpleNamespace(text=lambda:'Series'),_set_output_override=override,
            _set_applied_metadata=lambda *a,**k:None,on_preview_ready=lambda data:published.append(data))
        ImportWorkflowMixin._apply_import_metadata(owner)
        self.assertEqual([],refreshed);self.assertEqual([owner.preview_data],published)
        self.assertEqual(['Edited','B','Edited'],[r['title']for r in rows])
        self.assertNotIn('author',rows[1]);self.assertFalse(owner._import_edited_fields)

    def test_native_picker_retains_owned_dialog_and_balanced_exec(self):
        owner=QDialog();owner.setProperty('mangaankaWindow',True);owner._nested_dialog_depth=0
        seen=[]
        def execute(dialog):
            seen.append((dialog.testOption(QFileDialog.Option.DontUseNativeDialog),
                         dialog.property('mangaankaNativeFileDialog'),dialog.windowModality(),owner._nested_dialog_depth))
            return QDialog.DialogCode.Rejected
        with patch.object(QFileDialog,'exec',execute):
            paths,_=PluginFileDialog.getOpenFileNames(owner,'Import','','Books (*.cbz *.pdf)',native=True)
            self.assertEqual([],paths);self.assertEqual(0,owner._nested_dialog_depth)
            PluginFileDialog.getOpenFileNames(owner,'Other','','Books (*.cbz *.pdf)')
        self.assertEqual((False,True,Qt.WindowModality.WindowModal,1),seen[0])
        self.assertEqual((True,False,Qt.WindowModality.WindowModal,1),seen[1])
        owner.deleteLater()

    def test_fallback_matching_scales_with_equal_number_candidates(self):
        fixture=fixtures.CrossSourceFallbackTests();fixture.setUp()
        fixture.dex.chapters=[fixtures.chapter(str(n),source_id='dex')for n in range(2000)]
        fixture.pill.chapters=[fixtures.chapter(str(n),source_id='pill')for n in range(2000)]
        with patch.object(fallback,'chapter_identities_match',wraps=fallback.chapter_identities_match)as match:
            plan=fixture.plan()
        self.assertEqual(2000,len(plan.items));self.assertFalse(plan.gaps)
        self.assertTrue(all(item.source_id=='mangadex'for item in plan.items))
        self.assertLessEqual(match.call_count,4000)

    def test_reference_waits_for_actual_chapter_acquisition_before_starting(self):
        tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf8'))
        method=next(n for n in ast.walk(tree)if isinstance(n,ast.FunctionDef)and n.name=='_start_reference_lookup')
        # The lightweight owner has no worker dependencies: unready acquisition
        # must return before those dependencies can be accessed.
        gate=ast.Module(body=[method],type_ignores=[]);scope={}
        exec(compile(gate,'reference-start-gate','exec'),scope)
        for status in ('idle','pending'):
            d=SimpleNamespace(_closing=False,loaded_metadata={'title':'Fixture'},workflow_mode='chapter',
                workflow_state=SimpleNamespace(chapter_acquisition_state=status),_reference_waiting_for_inventory=False)
            scope['_start_reference_lookup'](d)
            self.assertTrue(d._reference_waiting_for_inventory)
