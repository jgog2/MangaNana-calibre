"""Stage requests and selection restoration across asynchronous inventory states."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from qt.core import QApplication, QPushButton, Qt
from calibre_plugins.manganana.presentation.mangaanka_widgets import WorkflowStepper

APP=QApplication.instance() or QApplication([])
ROOT=Path(__file__).resolve().parents[1]

def method(name):
    tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf8'))
    fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
    namespace={}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(ROOT/'app/main.py'),'exec'),namespace)
    return namespace[name]

class StepNavigationTests(unittest.TestCase):
    def test_stage_buttons_emit_exact_requests_without_owning_workflow(self):
        stepper=WorkflowStepper();seen=[];stepper.stage_requested.connect(seen.append)
        for key,button in stepper.labels.items():
            self.assertIsInstance(button,QPushButton)
            self.assertEqual(Qt.FocusPolicy.StrongFocus,button.focusPolicy())
            self.assertEqual(Qt.CursorShape.PointingHandCursor,button.cursor().shape())
            self.assertIn(':hover',button.styleSheet());self.assertIn(':focus',button.styleSheet())
            button.click();self.assertEqual(key,seen[-1])
        self.assertEqual('choose_manga',stepper.active_stage)
        stepper.set_active('finalization')
        self.assertTrue(stepper.labels['finalization'].property('active'))
        stepper.deleteLater()

    def test_checkpoint_waits_for_final_records_and_exact_owner(self):
        restore=method('_restore_mode_selection')
        for mode in ('volume','chapter'):
            state=SimpleNamespace(chapter_presentation_frozen=False,volume_inventory_final=False)
            saved=('owner',frozenset({1.0,5.0}),frozenset({'prologue-1','chapter-1'}),True)
            d=SimpleNamespace(workflow_mode=mode,workflow_state=state,_mode_selection_checkpoints={mode:saved},
                              _mode_selection_owner=lambda:'owner',_selected_volumes=set(),_selected_chapter_ids=set())
            restore(d)
            self.assertIn(mode,d._mode_selection_checkpoints)
            self.assertFalse(d._selected_volumes)
            state.chapter_presentation_frozen=True;state.volume_inventory_final=True
            restore(d)
            self.assertEqual({1.0,5.0},d._selected_volumes)
            self.assertEqual({'prologue-1','chapter-1'},d._selected_chapter_ids)
            self.assertNotIn(mode,d._mode_selection_checkpoints)
            d._mode_selection_checkpoints={mode:('different provider',*saved[1:])}
            d._selected_volumes=set();restore(d)
            self.assertFalse(d._selected_volumes)

    def test_stage_navigation_uses_validation_and_cannot_run_when_busy_or_closed(self):
        navigate=method('_navigate_stage');stages=('choose_manga','book_customization','finalization')
        d=SimpleNamespace(_closing=False,_download_in_progress=False,back_btn=SimpleNamespace(isEnabled=lambda:True),
            preview_btn=SimpleNamespace(isEnabled=lambda:True),workflow_state=SimpleNamespace(stage=stages[0]),
            workflow_hint=SimpleNamespace(setText=lambda text:None))
        calls=[]
        def advance():
            calls.append('next');d.workflow_state.stage=stages[stages.index(d.workflow_state.stage)+1]
        def back():
            calls.append('back');d.workflow_state.stage=stages[stages.index(d.workflow_state.stage)-1]
        d._advance_stage=advance;d._back_stage=back
        navigate(d,'finalization');self.assertEqual(['next','next'],calls)
        navigate(d,'choose_manga');self.assertEqual(['next','next','back','back'],calls)
        d.preview_btn.isEnabled=lambda:False;navigate(d,'finalization')
        self.assertEqual('choose_manga',d.workflow_state.stage)
        for attr in ('_closing','_download_in_progress'):
            setattr(d,attr,True);navigate(d,'finalization');setattr(d,attr,False)
        self.assertEqual(4,len(calls))
