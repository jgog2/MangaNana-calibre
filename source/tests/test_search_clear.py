"""Clearing selection resets the real foreground owner and deferred dispatch."""
import ast,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from qt.core import QApplication,QWidget,QLabel,QPushButton,QHBoxLayout,QEvent
from calibre_plugins.manganana.presentation.choose_manga_reference import ReferenceFidelityLayout,ElidedField
ROOT=Path(__file__).resolve().parents[1]
def method(path,cls,name):
    tree=ast.parse((ROOT/path).read_bytes());owner=next(v for v in tree.body if isinstance(v,ast.ClassDef)and v.name==cls)
    return next(v for v in owner.body if isinstance(v,ast.FunctionDef)and v.name==name)

class SearchClearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance()or QApplication([])
    def foreground(self):
        class Base:
            def _clear_active_provider_selection(self,message):
                self.loaded_metadata=None;self.selected_title.setText('No manga selected')
        node=method('presentation/choose_manga_ui.py','ChooseMangaDialog','_clear_active_provider_selection')
        tree=ast.Module(body=[ast.ClassDef(name='Dialog',bases=[ast.Name(id='Base',ctx=ast.Load())],keywords=[],body=[node],decorator_list=[])],type_ignores=[])
        space={'Base':Base};exec(compile(ast.fix_missing_locations(tree),'clear-hook','exec'),space)
        d=space['Dialog']();d.root=QWidget();d._set_hero_provider=Mock()
        for name in ('selected_title','native_title','selected_rating','selected_author','selected_tags','hero_facts','selected_aliases','selected_inventory_summary','selected_synopsis'):
            setattr(d,name,QLabel(d.root))
        for name in ('selected_cover','selected_source_host','edition_badge_host','hero_stats','selected_synopsis_scroll','_source_selected_page'):setattr(d,name,QWidget(d.root))
        d.height=lambda:900
        f=ReferenceFidelityLayout.__new__(ReferenceFidelityLayout);f.d=d;f._typography=lambda:None
        f.fact_values=[QLabel(d.root)for _ in range(3)];f.fact_fields=[ElidedField(v)for v in f.fact_values]
        f.title_field=ElidedField(d.selected_title);f.native_field=ElidedField(d.native_title)
        f.genre_heading=QLabel(d.root);f.genre_host=QWidget(d.root);f.genre_row=QHBoxLayout(f.genre_host)
        f.empty_instruction=QLabel(d.root);f.facts=QWidget(d.root);f.details_button=QPushButton(d.root);f.set_state=Mock()
        d.fidelity=f;d.loaded_metadata=dict(title='Chainsaw Man',author='Tatsuki Fujimoto',year='2018',tags=['Action','Drama'])
        f.metadata(d.loaded_metadata);return d
    def test_clear_updates_all_foreground_fields_and_visibility(self):
        d=self.foreground();self.assertEqual('Tatsuki Fujimoto',d.fidelity.fact_fields[0].text)
        d._clear_active_provider_selection()
        self.assertEqual('Search',d.fidelity.title_field.text)
        self.assertEqual(['—']*3,[v.text for v in d.fidelity.fact_fields]);self.assertEqual(0,d.fidelity.genre_row.count())
        self.assertEqual('',d.fidelity.native_field.text);self.assertTrue(d.fidelity.empty_instruction.isHidden())
        self.assertTrue(all(w.isHidden()for w in (d.selected_cover,d.hero_stats,d.fidelity.facts,d.fidelity.details_button)))
        d.root.deleteLater()
    def test_clear_title_survives_following_font_and_resize_events(self):
        d=self.foreground();d._clear_active_provider_selection();d.selected_title.resize(900,40)
        self.app.sendEvent(d.selected_title,QEvent(QEvent.Type.FontChange));self.app.sendEvent(d.selected_title,QEvent(QEvent.Type.Resize))
        self.assertEqual('Search',d.selected_title.text())
        d.root.deleteLater()
    def test_clear_cancels_deferred_selection_and_interrupts_owned_loaders(self):
        space={};nodes=[method('app/main.py','MangaNanaDialog',n)for n in('_clear_active_provider_selection','_load_debounced_search_result')]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'controller-clear','exec'),space)
        worker=SimpleNamespace(isRunning=lambda:True,requestInterruption=Mock())
        d=SimpleNamespace(_closing=False,_pending_result_token=7,_pending_search_url='https://example/title',_pending_search_result={'id':'old'},_manga_request_id=4,_volume_plan_request_id=2,_selected_fallback_request_id=1,_selected_fallback_worker=None,_manga_load_contexts={4:'old'},_manga_workers=[worker],_plan_workers=[],workflow_state=SimpleNamespace(clear_selection=Mock()),_selected_chapter_ids=set(),_selected_volumes=set(),_set_applied_metadata=Mock(),_clear_selected_details=Mock(),_set_selected_source_badge=Mock(),_set_edition_badge=Mock(),load_metadata=Mock())
        for name in ('selected_cover','selected_title','selected_author','selected_rating','availability_badge','volume_list','select_all_btn','clear_volume_btn','preview_btn','download_btn','workflow_hint'):setattr(d,name,Mock())
        space['_clear_active_provider_selection'](d);space['_load_debounced_search_result'](d,7)
        d.load_metadata.assert_not_called();worker.requestInterruption.assert_called_once();self.assertFalse(d._manga_load_contexts);self.assertFalse(d._volume_plan_loading)
