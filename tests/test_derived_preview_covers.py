"""Choose Manga handoff regressions using real handlers/workers, no HTTP."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from publication_manifest import (PublicationManifestBuilder, build_publication_projection,
                                  _bookwalker_metadata_cover_url)
from unified_volume import build_unified_volume_plan, selected_unified_volume_groups
from tests.test_empress_pipeline import production_namespace, Source
from tests import test_empress_pipeline as pipeline
from tests.test_publication_manifest import bookwalker, work
from chapter_workflow import chapter_sort_key
from core_helpers import fmt_volume


def handlers():
    tree=ast.parse(Path('main.py').read_text(encoding='utf-8'))
    dialog=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MangaNanaDialog')
    names=('_preview_sample_target','_apply_volume_plan_data','_on_reference_lookup_ready')
    methods=[n for n in dialog.body if isinstance(n,ast.FunctionDef) and n.name in names]
    ns={'selected_unified_volume_groups':selected_unified_volume_groups}
    exec(compile(ast.Module(body=methods,type_ignores=[]),'main.py','exec'),ns)
    return ns


def selection(plan, volume=1, standalone=False):
    return SimpleNamespace(_has_volume_selection=lambda:True,loaded_metadata={'title':'Fixture'},
                           workflow_mode='volume',_current_plan=plan,
                           _selected_volumes=set() if standalone else {volume},
                           _standalone_selected=standalone)


def derived_plan(title, source, count, volumes):
    # Synthetic fully-resolved inventories of the reported sizes, not scraped
    # title-specific chapter boundaries. Projection and planning are production.
    rows=tuple({'id':f'{source}-{i}','chapter':str(i),'volume':None,
                '_source_id':source,'acquisition_token':f'token-{i}'} for i in range(1,count+1))
    structure=[{'chapter':str(i),'volume':str((i-1)*volumes//count+1)} for i in range(1,count+1)]
    manifest=PublicationManifestBuilder(work(title)).apply_wikipedia(
        {'status':'valid_with_data','chapters':structure}).build()
    return build_unified_volume_plan({},rows,build_publication_projection(rows,manifest,source,source),source,source)


class DerivedPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): pipeline.PipelineTests.setUpClass()
    @classmethod
    def tearDownClass(cls): pipeline.PipelineTests.tearDownClass()

    def run_preview(self,target,source):
        ns=production_namespace()
        ns['SOURCE_REGISTRY']=SimpleNamespace(get=lambda key:source if key==source.source_id else None)
        worker=ns['PairingPreviewWorker'](source,'url','en',target['volume'],'rtl',
                                        target['chapters'],layout='original_pages')
        worker.run()
        self.assertFalse(worker.failed.calls)
        self.assertTrue(worker.ready.calls)
        return worker

    def assert_derived(self,title,provider,count,volumes):
        plan=derived_plan(title,provider,count,volumes)
        self.assertEqual((0,volumes,0),(plan['native_volume_count'],plan['derived_volume_count'],plan['bonus_chapters']))
        self.assertEqual(count,sum(len(g['chapters']) for g in plan['volume_groups']))
        for volume in (1,volumes//2):
            target=handlers()['_preview_sample_target'](selection(plan,volume))
            final=selected_unified_volume_groups(plan,(volume,),False)[0]['chapters']
            self.assertEqual(tuple(final),target['chapters'])
            ids=[r['id'] for r in target['chapters']]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertTrue(all(r['_source_id']==provider and r['acquisition_token'] for r in target['chapters']))
            self.assertIsNot(final[0],target['chapters'][0])
            source=Source(); source.source_id=provider; seen=[]
            def forbidden(*a,**k): self.fail('Resolved membership must not query native volumes')
            source.get_chapters=forbidden
            def manifest(chapter): seen.append(chapter); return {'full':['page.png']}
            source.get_page_manifest=manifest
            worker=self.run_preview(target,source)
            self.assertEqual(ids,seen)  # each selected group fits the sample bound
            self.assertEqual(len(ids),worker.ready.calls[0][0]['source_pages'])
            ns=production_namespace()
            ns.update(chapter_sort_key=chapter_sort_key,fmt_volume=fmt_volume,
                      review_manifest_progress=lambda *args:'Counting fixture pages')
            tree=ast.parse(Path('main.py').read_text(encoding='utf-8'))
            node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PreviewWorker')
            exec(compile(ast.Module(body=[node],type_ignores=[]),'main.py','exec'),ns)
            finalization=ns['PreviewWorker'](source,'url',title,'Author',title,'en',volume,volume,True,(),
                chapter_output_plan=selected_unified_volume_groups(plan,(volume,),False))
            finalization.run(); self.assertFalse(finalization.failed.calls)
            output_group=finalization.ready.calls[0][0]['rows'][0]['group']
            self.assertEqual(ids,[r['id'] for r in output_group['chapters']])

    def test_attack_on_titan_weebcentral_fully_derived(self):
        self.assert_derived('Attack on Titan','weebcentral',142,34)

    def test_chainsaw_man_mangapill_fully_derived(self):
        self.assert_derived('Chainsaw Man','mangapill',232,24)

    def test_chainsaw_man_weebcentral_fully_derived(self):
        self.assert_derived('Chainsaw Man','weebcentral',232,24)

    def test_standalone_uses_exact_group_not_native_lookup(self):
        rows=({'id':'extra','chapter':'99','volume':None,'_source_id':'synthetic'},)
        plan=build_unified_volume_plan({},rows,build_publication_projection(rows,None))
        target=handlers()['_preview_sample_target'](selection(plan,standalone=True))
        final=selected_unified_volume_groups(plan,(),True)[0]['chapters']
        self.assertEqual(tuple(final),target['chapters'])
        source=Source(); source.get_chapters=lambda *a,**k:self.fail('No native standalone lookup')
        self.run_preview(target,source)

    def test_steel_ball_run_legacy_native_volume_and_standalone_fallback(self):
        for volume in (1,None):
            target=handlers()['_preview_sample_target'](selection({'volumes':list(range(1,25))},volume,volume is None))
            self.assertEqual((),target['chapters'])
            source=Source(); calls=[]
            def chapters(*args):
                calls.append(args)
                return [{'id':'native','chapter':'1','volume':volume}]
            source.get_chapters=chapters
            self.run_preview(target,source)
            self.assertEqual([('url','en',volume,volume)],calls)

    def test_unified_native_steel_ball_run_keeps_exact_membership(self):
        rows=tuple({'id':str(v),'chapter':str(v),'volume':v,'_source_id':'mangadex'} for v in range(1,25))
        plan=build_unified_volume_plan({},rows,build_publication_projection(rows,None))
        target=handlers()['_preview_sample_target'](selection(plan,12))
        self.assertEqual(('12',),tuple(r['id'] for r in target['chapters']))
        self.assertEqual(24,plan['native_volume_count']); self.assertEqual(0,plan['derived_volume_count'])

    def test_chapter_mode_is_unchanged(self):
        c=selection({}); c.workflow_mode='chapter'; rows=({'id':'selected'},)
        c._selected_chapter_rows=lambda:rows
        self.assertEqual(rows,handlers()['_preview_sample_target'](c)['chapters'])


class CoverRepairTests(unittest.TestCase):
    thumbnail='https://rimg.bookwalker.jp/7605876/eUnObgIVNjRTJtVUNQrbaQ__.jpg'
    metadata='https://c.bookwalker.jp/7605876/t_700x780.jpg'
    provider='https://uploads.mangadex.org/covers/steel-ball-run/original.jpg'

    def test_numeric_and_hashed_rimg_ids(self):
        self.assertEqual(self.metadata,_bookwalker_metadata_cover_url(self.thumbnail))
        self.assertEqual('https://c.bookwalker.jp/abc_123-XYZ/t_700x780.jpg',
                         _bookwalker_metadata_cover_url('https://rimg.bookwalker.jp/abc_123-XYZ/cover.jpg?size=small'))

    def test_unknown_url_forms_are_not_rewritten(self):
        for url in (self.provider,self.metadata,'https://rimg.bookwalker.jp/id/a/b.jpg',
                    'http://rimg.bookwalker.jp/123/a.jpg','https://rimg.bookwalker.jp/123/',
                    'https://rimg.bookwalker.jp.evil/123/a.jpg','https://rimg.bookwalker.jp/123/a.jpg#fragment'):
            self.assertEqual(url,_bookwalker_metadata_cover_url(url))

    def manifest(self):
        book=bookwalker(); book['covers'][0]['url']=self.thumbnail
        book['edition_artwork'][0]['url']=self.thumbnail
        return PublicationManifestBuilder(work('Steel Ball Run')).apply_bookwalker(book).build()

    def test_cached_manifest_keeps_thumbnail_and_uses_large_metadata_rendition(self):
        manifest=self.manifest()
        for artwork in (manifest.volumes[0].cover,manifest.display.edition_artwork):
            self.assertEqual(self.thumbnail,artwork.preview_url)
            self.assertEqual(self.metadata,artwork.url)
            self.assertEqual(self.metadata,artwork.source_url)

    def provider_arrives(self,c,covers):
        c._volume_plan_request_id=1; c.language=SimpleNamespace(currentData=lambda:'en')
        c.workflow_mode='chapter'; c._apply_chapter_plan=lambda *args:None
        handlers()['_apply_volume_plan_data'](c,{'request_id':1,'language':'en','covers':covers})

    def reference_arrives(self,c):
        # Execute the real callback through manifest promotion and cover merging;
        # stop at its next log, before unrelated reference-presentation UI work.
        class MergeComplete(Exception): pass
        c._reference_request_id=1; c.loaded_metadata={'title':'Steel Ball Run'}
        c.workflow_mode='volume'; c._pending_search_result={}
        c.workflow_state=SimpleNamespace(selected_record_load_generation=1,settle_publication_resolution=lambda _:True)
        c._publication_manifest_builder=lambda:PublicationManifestBuilder(work('Steel Ball Run'))
        c._promote_publication_manifest=lambda _:self.manifest()
        c._refresh_selected_details=lambda _:None
        def done(*args): raise MergeComplete()
        c.add_log=done
        with self.assertRaises(MergeComplete):
            handlers()['_on_reference_lookup_ready'](c,{'request_id':1,'generation':1})

    def test_provider_first_reference_later_preserves_exact_steel_ball_run_cover(self):
        c=SimpleNamespace(_loaded_covers={1.:self.provider},_reference_volume_covers={})
        self.reference_arrives(c)
        self.assertEqual(self.provider,c._loaded_covers[1.])
        self.assertEqual(self.metadata,c._reference_volume_covers[1.])

    def test_reference_first_provider_later_preserves_provider_and_fills_gap(self):
        c=SimpleNamespace(_loaded_covers={},_reference_volume_covers={})
        self.reference_arrives(c)
        c._reference_volume_covers[2.]=self.metadata
        self.provider_arrives(c,{1.:self.provider})
        self.assertEqual({1.:self.provider,2.:self.metadata},c._loaded_covers)

    def test_reference_only_derived_volume_gets_useful_cover(self):
        c=SimpleNamespace(_loaded_covers={},_reference_volume_covers={})
        self.reference_arrives(c); self.provider_arrives(c,{})
        self.assertEqual(self.metadata,c._loaded_covers[1.])


if __name__=='__main__': unittest.main()
