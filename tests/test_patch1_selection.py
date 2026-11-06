"""Selected-operation ordering and sanitized provider regressions; no network."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from calibre_plugins.manganana.app.workflow_state import HighPriestessState
from calibre_plugins.manganana.providers.atsu_source import AtsuSource
from calibre_plugins.manganana.providers.mangak_source import MangaKSource

ROOT=Path(__file__).parents[1]
FIX=json.loads((ROOT/'tests/fixtures/patch1_provider_records.json').read_text(encoding='utf-8'))
TREE=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
CLASS=next(n for n in TREE.body if isinstance(n,ast.ClassDef) and n.name=='MangaNanaDialog')
NAMES=('_selection_snapshot','_provider_record_identity','_dispatch_selected_result','_invalidate_selected_acquisition',
       '_apply_loaded_manga','_apply_volume_plan_data','_apply_chapter_plan','_on_manga_worker_failed','_on_volume_plan_failed')
namespace={}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Harness',bases=[],keywords=[],body=[n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name in NAMES],decorator_list=[])],type_ignores=[])),'selected-production-methods','exec'),namespace)
Harness=namespace['Harness']

class SelectionTests(unittest.TestCase):
    def harness(self):
        h=Harness(); h._closing=False; h.workflow_state=HighPriestessState(); h._manga_request_id=1; h._volume_plan_request_id=1
        h._manga_load_contexts={}; h._manga_workers=[]; h._plan_workers=[]; h._invalidate_cover_requests=Mock()
        h._cancel_output_covers=Mock()
        return h

    def test_old_callbacks_during_debounce_are_inert(self):
        h=self.harness(); h.workflow_state.select_provider({'source_id':'weebcentral','id':'A'})
        owner=h._selection_snapshot(); old=h._manga_request_id; plan=h._volume_plan_request_id
        h.workflow_state.select_provider({'source_id':'mangapill','id':'B'})
        h._invalidate_selected_acquisition() # B worker has not started
        callback=Mock(); h._dispatch_selected_result(owner,callback,{})
        callback.assert_not_called()
        before=dict(h.__dict__)
        h._apply_loaded_manga(old,{'metadata':{'title':'stale'}})
        h._apply_volume_plan_data({'request_id':plan})
        h._apply_chapter_plan(plan,'en',({'id':'stale'},))
        h._on_manga_worker_failed({'request_id':old})
        h._on_volume_plan_failed({'request_id':plan})
        self.assertEqual(before,h.__dict__)
        h._invalidate_cover_requests.assert_called_once()
        h._cancel_output_covers.assert_called_once()

    def test_completion_order_b_a_d_c_only_d_mutates_all_selection_fields(self):
        h=self.harness(); owners={}; applied=[]
        for key,source in zip('ABCD',('weebcentral','mangapill','atsu','mangadex')):
            h.workflow_state.select_provider({'source_id':source,'id':key}); h._invalidate_selected_acquisition()
            owners[key]=h._selection_snapshot()
        state={}
        def apply(data):
            applied.append(data)
            for field in ('title','author','language','cover','metadata','current_source','inventory','volume_rows','chapter_rows','reference_context','next_enabled'):
                state[field]=data
        for key in 'BADC': h._dispatch_selected_result(owners[key],apply,key)
        self.assertEqual(['D'],applied); self.assertEqual({'D'},set(state.values()))

    def test_physical_interruption_requested(self):
        h=self.harness(); worker=Mock(); worker.isRunning.return_value=True; h._plan_workers=[worker]
        h._invalidate_selected_acquisition(); worker.requestInterruption.assert_called_once()

    def test_cover_numbers_cannot_be_row_source(self):
        rebuild=ast.unparse(next(n for n in CLASS.body if isinstance(n,ast.FunctionDef) and n.name=='_rebuild_volume_list'))
        self.assertNotIn('for k in covers',rebuild)
        self.assertIn('terminal_failure',rebuild)

class ProviderTests(unittest.TestCase):
    def atsu(self,rows): return AtsuSource(lambda url,**kw:json.dumps({'chapters':rows}))

    def test_802_parallel_releases_choose_one_complete_stable_release(self):
        rows=FIX['comic_chapters']; self.assertEqual(802,len(rows))
        result=self.atsu(rows).get_chapters('https://atsu.moe/manga/oZOG5','en')
        self.assertEqual(201,len(result)); self.assertEqual(201,len({r['chapter'] for r in result}))
        self.assertEqual(1,len({r['_scanlation_id'] for r in result}))
        self.assertEqual(result,self.atsu(list(reversed(rows))).get_chapters('https://atsu.moe/manga/oZOG5','en'))
        self.assertEqual('0',result[0]['chapter']); self.assertEqual('200',result[-1]['chapter'])

    def test_partial_releases_and_same_release_specials_not_arbitrarily_dropped(self):
        rows=[dict(id=str(i),number=n,pageCount=2,scanlationMangaId=g) for i,(g,n) in enumerate((('a',1),('a',2),('b',2),('b',3)))]
        self.assertEqual(4,len(self.atsu(rows).get_chapters('https://atsu.moe/manga/series','en')))
        rows[2]['scanlationMangaId']='a'
        self.assertEqual(4,len(self.atsu(rows).get_chapters('https://atsu.moe/manga/series','en')))

    def test_novel_zero_counts_and_empty_reader_remain_failures(self):
        self.assertEqual('Novel',FIX['novel_metadata']['medium'])
        with self.assertRaisesRegex(RuntimeError,'invalid page count'):
            self.atsu(FIX['novel_chapters']).get_chapters('https://atsu.moe/manga/peR8','en')
        source=AtsuSource(lambda url,**kw:json.dumps(FIX['novel_reader']))
        with self.assertRaisesRegex(RuntimeError,'readable pages'):
            source.get_page_manifest('https://atsu.moe/read/peR8/LiUp0b')
        for pages in (0,-1,'12'):
            with self.assertRaises(RuntimeError): self.atsu([dict(id='a',number=1,pageCount=pages)]).get_chapters('https://atsu.moe/manga/series','en')
        for pages in (None,12):
            self.assertEqual(pages,self.atsu([dict(id='a',number=1,pageCount=pages)]).get_chapters('https://atsu.moe/manga/series','en')[0]['pages'])

    def test_observed_mangak_reader_and_all_inventory_paths(self):
        source=MangaKSource(); source._page_props=lambda url:FIX['mangak_reader']
        url='https://mangak.io/death-note/vol-tbd-chapter-110-how-to-read'
        self.assertEqual(57,len(source.get_page_manifest(url)['full']))
        for row in FIX['mangak_chapters']['data']['chapters']:
            self.assertEqual('death-note',source.parse_manga_ref(source._public_url(row['url'],reader=True)))
        for url in ('https://evil.test/death-note/vol-tbd-chapter-110',
                    'https://mangak.io/death-note/vol-anything-chapter-110',
                    'https://user@mangak.io/death-note/chapter-1','https://mangak.io/death-note/arbitrary'):
            with self.assertRaises(ValueError): source._public_url(url,reader=True)
        source._title=lambda value:({'id':'WYXLOWYO'},'https://mangak.io/death-note')
        source._json=lambda url:{'data':{'chapters':[dict(id='x',name='Chapter 1',url='/another-title/chapter-1')]}}
        with self.assertRaisesRegex(RuntimeError,'invalid chapter record'): source.get_chapters('death-note','en')
