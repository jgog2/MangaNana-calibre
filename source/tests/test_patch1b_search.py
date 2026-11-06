"""Offline media, packaged-reader, effective-search and cache regression controls."""
import json
import tempfile
import unittest
from pathlib import Path
from copy import deepcopy
from calibre_plugins.manganana.providers.atsu_source import AtsuSource, packaged_volume
from calibre_plugins.manganana.providers.source_policy import media_class, supported_media
from calibre_plugins.manganana.discovery.canonical_identity import group_canonical_results
from calibre_plugins.manganana.discovery.enrichment_matching import effective_search_rows
from calibre_plugins.manganana.discovery.search_ranking import rank_canonical_results, rank_provider_results, present_search_candidate
from calibre_plugins.manganana.discovery.search_resolution import qualification_targets, resolve_search_group
from calibre_plugins.manganana.providers.source_registry import SourceRegistry
from calibre_plugins.manganana.discovery.search_cache import SearchMetadataCache, query_cache_key
from calibre_plugins.manganana.publication.inventory_comparison import inspect_source_inventory
from calibre_plugins.manganana.metadata.reference_integration import chapter_metadata_label
from tests.test_search_resolution import FakeSource

FIX=json.loads((Path(__file__).parent/'fixtures/patch1b_atsu.json').read_text(encoding='utf-8'))

def source(chapters='banana_chapters', reader='banana_reader'):
    def fetch(url,**kw):
        if '/allChapters' in url:return json.dumps(FIX[chapters])
        if '/read/chapter' in url:return json.dumps(FIX[reader])
        if '/api/manga/page' in url:return json.dumps(FIX['epl_metadata'])
        return json.dumps(FIX['search'])
    return AtsuSource(fetch_text=fetch)

def row(id,source='atsu',**extra):
    return dict(source_id=source,id=id,title='Banana Fish',author='Creator',
                canonical_work_id='kitsu:banana',_canonical_identity_confidence='high',
                canonical_title='Banana Fish',**extra)

class MediaTests(unittest.TestCase):
    def test_explicit_medium_wins_unknown_is_retained(self):
        for medium in ('Comic','Manga','Manhwa','Manwha','Manhua'):
            self.assertEqual('comic',media_class({'medium':medium}))
        for medium in ('Novel','Light Novel','LightNovel','Light-Novel','Web Novel'):
            self.assertFalse(supported_media({'type':'Manga','medium':medium}))
        for value in ({},{'title':'Novel Comic Volume Manga'},{'medium':'unknown','type':'Manga'}):
            self.assertEqual('unknown',media_class(value)); self.assertTrue(supported_media(value))

    def test_search_filters_novels_and_returns_actual_other_names(self):
        result=source().search('Solo Leveling')
        rows={r['id']:r for r in result['rows']}
        self.assertNotIn('peR8',rows); self.assertNotIn('ydof',rows)
        self.assertIn('oZOG5',rows); self.assertIn('EPL96',rows)
        self.assertIn('Solo Leveling',rows['EPL96']['alternate_titles'])
        self.assertEqual(2,result['filtered_unsupported_media'])

    def test_direct_novel_fails_before_reader_or_reference(self):
        calls=[]
        def fetch(url,**kw):
            calls.append(url)
            return json.dumps({'mangaPage':{'id':'peR8','title':'Solo Leveling','medium':'Novel','type':'Manga'}})
        with self.assertRaisesRegex(RuntimeError,'Novel'):
            AtsuSource(fetch_text=fetch).get_manga('https://atsu.moe/manga/peR8')
        self.assertEqual(1,len(calls))

    def test_media_and_conflicting_work_ids_block_canonical_join(self):
        a=row('a','atsu',medium='Comic'); b=row('b','mangadex',medium='Novel')
        self.assertEqual(2,len(group_canonical_results([a,b])))
        b.pop('medium'); self.assertEqual(1,len(group_canonical_results([a,b])))
        b['canonical_work_id']='kitsu:different'
        self.assertEqual(2,len(group_canonical_results([a,b])))

class PackageTests(unittest.TestCase):
    def test_anchored_volume_labels_and_number_consistency(self):
        for title in ('Volume 1','Volume 01','Vol 1','Vol. 1','Volume 1.5'):
            n=1.5 if '1.5' in title else 1
            self.assertEqual(n,packaged_volume({'title':title,'number':n}))
        for title in ('End of Volume 2','Volume Extra','Volume Discussion','Volume 3 Bonus Chapter',
                      'Chapter 10 - Volume 2','Volume Two','Chapter 1','Episode 1'):
            self.assertIsNone(packaged_volume({'title':title,'number':1}))
        self.assertIsNone(packaged_volume({'title':'Volume 4','number':17}))

    def test_banana_19_native_no_standalone_exact_reader_membership(self):
        s=source();url='https://atsu.moe/manga/W6oyN'; rows=s.get_chapters(url,'en');plan=s.get_download_plan(url,'en')
        self.assertEqual(list(range(1,20)),plan['volumes'])
        self.assertEqual(19,len(rows));self.assertEqual(0,plan['bonus_chapters']);self.assertEqual(0,plan['bonus_pages'])
        for raw in FIX['banana_chapters']['chapters']:
            current=next(r for r in rows if r['id'].endswith('/'+raw['id']))
            self.assertEqual(raw['number'],current['volume']);self.assertEqual(raw['pageCount'],plan['pages_by_volume'][current['volume']])
            self.assertEqual('volume',current['_unit_kind']); self.assertEqual(raw['title'],chapter_metadata_label(current))
        inv=inspect_source_inventory(s,{'url':url},'en','volume')
        self.assertEqual(19,inv.native_volumes);self.assertEqual(0,inv.standalone_chapters)
        self.assertNotIn('chapter',inv.summary)

    def test_selected_volume_3_uses_original_190_page_reader(self):
        s=source();rows=s.get_chapters('https://atsu.moe/manga/W6oyN','en',3,3)
        self.assertEqual(1,len(rows)); self.assertTrue(rows[0]['id'].endswith('/HgLZyj76'))
        self.assertEqual(190,len(s.get_page_manifest(rows[0]['id'])['full']))

    def test_mixed_and_conflicting_units_not_force_grouped(self):
        rows=[dict(id=str(i),number=i,title=title,pageCount=10) for i,title in enumerate(('Volume 0','Volume 1','Chapter 2','Volume 4'))]
        s=AtsuSource(fetch_text=lambda *a,**k:json.dumps({'chapters':rows}))
        out=s.get_chapters('https://atsu.moe/manga/mixed','en')
        self.assertEqual([0.,1.,None,None],[r['volume'] for r in out])
        self.assertEqual(2,s.get_download_plan('https://atsu.moe/manga/mixed','en')['bonus_chapters'])

    def test_epl_volume_title_is_not_volume_evidence(self):
        s=source('epl_chapters','epl_reader'); rows=s.get_chapters('https://atsu.moe/manga/EPL96','en')
        self.assertEqual(48,len(rows)); self.assertTrue(all(r['volume'] is None for r in rows))
        self.assertEqual([],s.get_download_plan('https://atsu.moe/manga/EPL96','en')['volumes'])
        self.assertEqual(15,len(s.get_page_manifest(rows[0]['id'])['full']))

class EffectiveSearchTests(unittest.TestCase):
    def test_late_identity_shared_with_qualification_and_presentation(self):
        raws=[dict(source_id='mangadex',id='donor',title='Banana Fish',author='Creator'),
              dict(source_id='atsu',id='W6oyN',title='Banana Fish',author='Creator')]
        overlay={('mangadex','donor'):row('donor','mangadex',external_ids={'kitsu_id':'banana'})}
        effective=effective_search_rows(raws,overlay)
        self.assertTrue(all(r['canonical_work_id']=='kitsu:banana' for r in effective))
        targets=qualification_targets(rank_canonical_results('Banana Fish',effective))
        keys={r['id'] for g in targets for r in g.group.results}
        self.assertEqual({'donor','W6oyN'},keys)
        for r in effective:
            self.assertEqual(r['canonical_work_id'],present_search_candidate(r,r).canonical_work_id)
        self.assertEqual(effective,effective_search_rows(raws,overlay))
        self.assertNotIn('canonical_work_id',raws[0])

    def test_qualification_singletons_weak_rows_and_record_bound(self):
        rows=[row(str(i),'atsu') for i in range(12)]
        rows.append(dict(source_id='mangak',id='weak',title='Unrelated'))
        targets=qualification_targets(rank_canonical_results('Banana Fish',rows))
        selected=[r for g in targets for r in g.group.results]
        self.assertEqual(8,len(selected));self.assertNotIn('weak',[r['id'] for r in selected])
        novel=row('novel',medium='Novel')
        self.assertEqual((),effective_search_rows([novel]))

    def test_volume_fitness_reorders_only_same_family_slots(self):
        a=row('chapters',_acquisition_fitness='direct',_qualification_chapter_count=110)
        b=row('volumes','mangapill',_acquisition_fitness='direct',_qualification_native_volume_count=19)
        b['title']='Banana Fish (Volume)'; b['alternate_titles']=['Banana Fish']
        other=row('other','weebcentral',_acquisition_fitness='direct',_qualification_native_volume_count=99)
        other.update(title='Banana Fish Sequel',canonical_work_id='kitsu:sequel')
        chapter=rank_provider_results('Banana Fish',[a,b,other],workflow='chapter')
        volume=rank_provider_results('Banana Fish',[a,b,other],workflow='volume')
        self.assertEqual('chapters',chapter[0].result['id']);self.assertEqual('volumes',volume[0].result['id'])
        self.assertEqual([i for i,r in enumerate(chapter) if r.result['id']=='other'],[i for i,r in enumerate(volume) if r.result['id']=='other'])
        self.assertNotIn('_qualification_native_volume_count',present_search_candidate(row('refs',bookwalker_covers=25,madb_books=19)).raw_result)

    def test_inventory_budget_prevents_unbounded_language_probes(self):
        # No source call is allowed when the shared search budget is exhausted.
        s=source(); registry=SourceRegistry((s,))
        result=resolve_search_group(registry,[dict(source_id='atsu',id='W6oyN',url='https://atsu.moe/manga/W6oyN',available_languages=['en'],adult=False)],'en','volume',inspection_budget=[0])
        self.assertEqual('Qualification budget exhausted.',result.error);self.assertEqual((),result.inventories)

class CacheMigrationTests(unittest.TestCase):
    def test_old_inventory_and_novel_query_do_not_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchMetadataCache(Path(folder)/'cache.db')
            key=('acquisition','atsu','W6oyN','en','original')
            old={'native_volumes':0,'standalone_chapters':19}
            cache.put('inventory',repr(('provider-chapter-contract-v2',key)),old)
            self.assertIsNone(cache.get_inventory(key))
            cache.put('query_snapshot','old',{'contract':'provider-candidates-v3','final':True,'final_result_count':1,'provider_candidates':[row('peR8',medium='Novel')]})
            self.assertIsNone(cache.get_query_snapshot('old'))
            args=('Solo Leveling','volume','en',False,('atsu',),False,True)
            self.assertNotEqual(query_cache_key(*args),query_cache_key(*args,algorithm_version='high-priestess-provider-candidates-v4'))
            cache.put_reference_catalog('madb:preserve',{'status':'valid'})
            self.assertIsNotNone(cache.get_reference_catalog('madb:preserve'))
            cache.close()
