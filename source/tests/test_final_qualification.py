"""Measured warm-path regressions: preserve reconciled identity and order."""
import unittest
from unittest.mock import patch
from dataclasses import asdict
from calibre_plugins.manganana.publication import publication_manifest as pm
from test_publication_manifest import work, wiki_rows

class WarmMembershipIndexTests(unittest.TestCase):
    def test_large_membership_matches_reconciled_order_with_linear_normalization(self):
        builder=pm.PublicationManifestBuilder(work(), 'original').apply_wikipedia(wiki_rows(1200))
        with patch.object(pm,'normalize_publication_number',wraps=pm.normalize_publication_number) as normalize:
            manifest=builder.build()
        expected={v.key:tuple(c.key for c in manifest.chapters if c.volume.present and
                   pm.normalize_publication_number(c.volume.value)==v.key) for v in manifest.volumes}
        self.assertEqual(expected,{v.key:v.chapter_keys for v in manifest.volumes})
        self.assertLess(normalize.call_count,15000,'Do not restore a chapter scan for every volume')
        self.assertEqual(asdict(manifest),asdict(builder.build()))

    def test_conflict_and_fractional_membership_remain_separate(self):
        evidence={**wiki_rows(0),'chapters':[
            {'number':'1','volume':'1','kind':'chapter'},
            {'number':'1.5','volume':'1','kind':'chapter'},
            {'number':'2','volume':'2','kind':'chapter'},
            {'number':'2','volume':'3','kind':'chapter'}]}
        manifest=pm.PublicationManifestBuilder(work(),'original').apply_wikipedia(evidence).build()
        expected={v.key:tuple(c.key for c in manifest.chapters if c.volume.present and
                  pm.normalize_publication_number(c.volume.value)==v.key) for v in manifest.volumes}
        self.assertEqual(expected,{v.key:v.chapter_keys for v in manifest.volumes})
        self.assertNotIn('2',sum((v.chapter_keys for v in manifest.volumes),()))

class ExactInventoryCacheKeyTests(unittest.TestCase):
    def test_internal_metadata_uuid_cannot_miss_provider_listing_cache(self):
        import ast
        from pathlib import Path
        from types import SimpleNamespace as S
        source=(Path(__file__).resolve().parents[1]/'app/main.py').read_text(encoding='utf8')
        tree=ast.parse(source);method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_load_volume_plan')
        from calibre_plugins.manganana.discovery.search_resolution import session_plan_fresh
        namespace={'session_plan_fresh':session_plan_fresh}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'app/main.py','exec'),namespace)
        applied=[]
        dialog=S(_closing=False,loaded_metadata={'uuid':'internal-api-id'},language=S(currentData=lambda:'en',currentText=lambda:'English'),
            current_source=S(parse_manga_ref=lambda url:'naruto'),current_source_id='mangak',current_manga_url='https://mangak.io/naruto',workflow_mode='volume',
            _volume_plan_request_id=0,_workflow_inventory_generation=1,workflow_state=S(begin_volume_preparation=lambda *a:None),
            _metadata_search_cache=S(clock=lambda:100),
            _plan_cache={('volume','mangak','naruto','en'):{'plan':{'volumes':[1]},'language':'en','_cached_at':100}},
            meta_summary=S(setText=lambda value:None),_apply_volume_plan_data=applied.append)
        namespace['_load_volume_plan'](dialog)
        self.assertEqual(1,len(applied))
        self.assertEqual([1],applied[0]['plan']['volumes'])
        self.assertEqual(1,applied[0]['request_id'])
