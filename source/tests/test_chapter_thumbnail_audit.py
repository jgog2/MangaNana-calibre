import itertools,json,unittest
from pathlib import Path
from calibre_plugins.manganana.discovery.discovery_groups import group_records, evidence_key
from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text

ROOT=Path(__file__).resolve().parents[1]
class IdentityAudit(unittest.TestCase):
    def row(self,sid='mangadex',**kw):
        return dict(dict(source_id=sid,id=sid,title='Attack on Titan',canonical_work_id='anilist:53390|kitsu:14916',
            _canonical_identity_confidence='high',author='Hajime Isayama',year=2009,edition='original'),**kw)
    def test_case_punctuation_and_unicode(self):
        for title in ('ATTACK ON TITAN','attack on titan','aTtAcK oN tItAn','Attack-on-Titan','Ａｔｔａｃｋ ｏｎ Ｔｉｔａｎ'):
            self.assertEqual(1,len(group_records([self.row(),self.row('atsu',title=title,medium='Comic')])))
    def test_verified_japanese_romanized_and_english_aliases(self):
        for title in ('進撃の巨人','Shingeki no Kyojin','Attack on Titan'):
            self.assertEqual(1,len(group_records([self.row(),self.row('atsu',title=title,medium='Comic')])))
    def test_titles_do_not_override_trusted_contradictions(self):
        for work in ('anilist:53391|kitsu:14916','anilist:53390|kitsu:14917','anilist:1','anilist:53390|anilist:2'):
            self.assertEqual(2,len(group_records([self.row(),self.row('atsu',canonical_work_id=work)])))
    def test_partial_compatible_ids(self):
        for work in ('kitsu:14916','anilist:53390','kitsu:14916|anilist:53390'):
            self.assertEqual(1,len(group_records([self.row(),self.row('atsu',canonical_work_id=work)])))
    def test_no_overlap_is_insufficient(self):
        self.assertEqual(2,len(group_records([self.row(canonical_work_id='anilist:53390'),self.row('atsu',canonical_work_id='kitsu:14916')])))
    def test_contradictory_trusted_external_links(self):
        self.assertEqual(2,len(group_records([self.row(external_ids={'mal_id':'23390'}),self.row('atsu',external_ids={'mal_id':'1'})])))
    def test_no_transitive_conflict_through_partial_id(self):
        rows=[self.row(),self.row('atsu',canonical_work_id='kitsu:14916'),self.row('weebcentral',canonical_work_id='anilist:1|kitsu:14916')]
        for permutation in itertools.permutations(rows):
            for group in group_records(permutation):
                self.assertFalse({'mangadex','weebcentral'}<={r['source_id'] for r in group.records})
    def test_editions_and_publication_layouts_stay_distinct(self):
        for kw in ({'edition':'official_color'},{'edition':'fan_color'},{'publication_format':'webcomic'},
                {'medium':'Webcomic'},{'remake_of':'work:1'},{'publication_identity':'remake'},{'language':'ja'}):
            self.assertEqual(2,len(group_records([self.row(),self.row('atsu',**kw)])))
    def test_opm_original_webcomic_vs_murata(self):
        self.assertEqual(2,len(group_records([self.row(title='One-Punch Man',publication_format='webcomic'),self.row('atsu',title='One Punch Man',publication_format='manga')])))
    def test_spinoffs_keep_trusted_work_identity(self):
        self.assertEqual(2,len(group_records([self.row(),self.row('atsu',title='Attack on Titan: No Regrets',canonical_work_id='anilist:85199|kitsu:18567')])))
    def test_unknown_titles_without_evidence_never_join(self):
        self.assertEqual(2,len(group_records([self.row(canonical_work_id='',author='',year=None),self.row('atsu',title='ATTACK ON TITAN',canonical_work_id='',author='',year=None)])))
    def test_incremental_compatible_group_keeps_rank_and_representative(self):
        rows=[self.row(),self.row('atsu',medium='Comic'),self.row('weebcentral')]
        key=group_records(rows[:1])[0].key
        for n in (2,3):
            groups=group_records(rows[:n]);self.assertEqual(key,groups[0].key);self.assertEqual(rows[:n],groups[0].records)
    def test_live_atsu_divergence_is_broad_medium_not_case(self):
        path=ROOT/'build/chapter-mode-search-thumbnail/attack-on-titan-before.json'
        if not path.exists():self.skipTest('Local capture absent')
        values=json.loads(path.read_text(encoding='utf-8'));rows=[v['record'] for v in values]
        self.assertTrue(any(r['source_id']=='atsu' and r['medium']=='Comic' for r in rows))
        self.assertEqual(1,len({normalize_identity_text(r['title']) for r in rows}))
        self.assertEqual(1,len(group_records(rows)))

class AcquisitionCacheAudit(unittest.TestCase):
    def source(self):
        from types import SimpleNamespace
        source=SimpleNamespace(source_id='source',display_name='Source',capabilities=(),calls=0,parse_manga_ref=lambda value:value)
        def chapters(*a):source.calls+=1;return [{'id':'one','chapter':'1','volume':None}]
        source.get_chapters=chapters
        return source
    def test_selected_and_fallback_workers_share_exact_inventory(self):
        from calibre_plugins.manganana.discovery.search_resolution import cached_source_inventory
        source=self.source();cache={};candidate={'id':'work','url':'work','edition':'original'}
        a=cached_source_inventory(cache,source,candidate,'en','chapter')
        b=cached_source_inventory(cache,source,candidate,'en','chapter')
        self.assertEqual(1,source.calls);self.assertEqual(a.chapter_records,b.chapter_records)
    def test_language_and_edition_cache_partition(self):
        from calibre_plugins.manganana.discovery.search_resolution import cached_source_inventory
        source=self.source();cache={}
        for edition,language in [('original','en'),('original','ja'),('official_color','en')]:
            cached_source_inventory(cache,source,{'id':'work','edition':edition},language,'chapter')
        self.assertEqual(3,source.calls)
    def test_cold_failure_is_not_cached(self):
        from calibre_plugins.manganana.discovery.search_resolution import cached_source_inventory
        source=self.source();cache={};original=source.get_chapters
        source.get_chapters=lambda *a:(_ for _ in ()).throw(RuntimeError('Unavailable'))
        self.assertFalse(cached_source_inventory(cache,source,{'id':'work'},'en','chapter').usable)
        source.get_chapters=original
        self.assertTrue(cached_source_inventory(cache,source,{'id':'work'},'en','chapter').usable)
    def test_cancelled_owner_does_not_publish_inventory(self):
        from calibre_plugins.manganana.discovery.search_resolution import cached_source_inventory
        source=self.source();cache={}
        def cancel():raise InterruptedError()
        with self.assertRaises(InterruptedError):cached_source_inventory(cache,source,{'id':'work'},'en','chapter',cancel)
        self.assertEqual({},cache);self.assertEqual(0,source.calls)
    def test_concurrent_consumers_enumerate_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from calibre_plugins.manganana.discovery.search_resolution import cached_source_inventory
        source=self.source();cache={};entered=Event();release=Event();original=source.get_chapters
        def chapters(*a):entered.set();release.wait(2);return original(*a)
        source.get_chapters=chapters
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(cached_source_inventory,cache,source,{'id':'work'},'en','chapter')
            self.assertTrue(entered.wait(2))
            second=pool.submit(cached_source_inventory,cache,source,{'id':'work'},'en','chapter')
            release.set();self.assertEqual(first.result().chapter_records,second.result().chapter_records)
        self.assertEqual(1,source.calls)

if __name__=='__main__':unittest.main()
