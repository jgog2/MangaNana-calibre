"""Atsu alternate groups are acquisitions, not implicit new story chapters."""
import unittest
from calibre_plugins.manganana.providers.atsu_source import AtsuSource
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.providers.atsu_acquisition import resolve_atsu_acquisition


def source(primary,alternate,groups=None):
    page=dict(id='fixture',title='Series',scanlators=groups or [dict(id='a',name='Alpha'),dict(id='b',name='Delta')])
    rows=[dict(id=g+str(n).replace('.','_'),number=n,title='Chapter '+str(n),pageCount=1,scanlationMangaId=g)
          for g,numbers in [('a',primary),('b',alternate)] for n in numbers]
    s=AtsuSource();s._api=lambda path,**kw:dict(mangaPage=page) if path.endswith('/page') else dict(chapters=rows)
    return s


class AtsuGroups(unittest.TestCase):
    def test_complete_primary_retains_parallel_inventory(self):
        rows=source(range(1,249),range(1,234)).get_chapters('https://atsu.moe/manga/fixture','en')
        self.assertEqual(248,len(rows))
        diag=resolve_atsu_acquisition(rows)
        self.assertEqual(233,len(diag['alternatives']))
        self.assertEqual(481,diag['raw_count'])

    def test_unsupported_fraction_is_not_main_and_is_not_erased(self):
        rows=source([19],[19,19.5]).get_chapters('https://atsu.moe/manga/fixture','en')
        selection=resolve_atsu_acquisition(rows)
        self.assertEqual(['19'],[r['chapter'] for r in selection['rows']])
        decimal=next(r for r in selection['alternatives'] if r['chapter']=='19.5')
        self.assertEqual('b',decimal['_scanlation_id'])
        self.assertTrue(decimal['requires_review'])

    def test_independent_reference_recovers_missing_alternate(self):
        rows=source([1,3],[1,2,3]).get_chapters('https://atsu.moe/manga/fixture','en')
        b=PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series'),'original')
        b.apply_mangadex_structure(dict(status='valid',cache_contract='mangadex-structure-v1',
            manga_id='md',edition_profile='original',canonical_work_id='fixture:series',mappings={'1':'1','2':'1','3':'1'}))
        selection=resolve_atsu_acquisition(rows,b.build())
        self.assertEqual(['1','2','3'],[r['chapter'] for r in selection['rows']])
        projected=build_publication_projection(rows,b.build(),'atsu','atsu')
        self.assertEqual(3,len(projected.chapters))
        self.assertTrue(all(c.effective_volume.present for c in projected.chapters))

    def test_two_complete_groups_are_one_sequence(self):
        rows=source([1,2],[1,2]).get_chapters('https://atsu.moe/manga/fixture','en')
        self.assertEqual(2,len(rows))
        self.assertEqual(2,len(resolve_atsu_acquisition(rows)['alternatives']))

    def test_unknown_or_incompatible_group_never_fills_a_gap(self):
        for bad in (dict(id='b',name='Other',mangaId='other'),dict(id='b',name='Other',mangaTitle='Unrelated'),
                    dict(id='b',name='Other',edition='fan_color')):
            rows=source([1],[2],groups=[dict(id='a',name='Alpha'),bad]).get_chapters('https://atsu.moe/manga/fixture','en')
            b=PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series'),'original')
            b.apply_provider_inventory([dict(chapter='2',volume='1')],'mangadex_structure')
            self.assertEqual(['1'],[r['chapter'] for r in resolve_atsu_acquisition(rows,b.build())['rows']])

    def test_other_providers_are_unchanged(self):
        rows=[dict(chapter='1',id='x'),dict(chapter='1.5',id='y')]
        self.assertEqual(rows,resolve_atsu_acquisition(rows)['rows'])

    def test_conflicting_alternates_do_not_choose_an_arbitrary_fallback(self):
        rows=source([1],[2]).get_chapters('https://atsu.moe/manga/fixture','en')
        first=rows[0]['_atsu_group_inventory']['alternatives'][0];first['title']='Different A'
        rows[0]['_atsu_group_inventory']['alternatives'].append(dict(first,id='c2',_scanlation_id='c',title='Different B'))
        b=PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series'),'original')
        b.apply_mangadex_structure(dict(status='valid',cache_contract='mangadex-structure-v1',manga_id='md',
            canonical_work_id='fixture:series',edition_profile='original',mappings={'2':'1'}))
        selection=resolve_atsu_acquisition(rows,b.build())
        self.assertEqual(['1'],[r['chapter'] for r in selection['rows']])
        self.assertTrue(all(r['requires_review'] for r in selection['alternatives']))

    def test_unified_volume_plan_includes_actual_supported_fallback(self):
        from calibre_plugins.manganana.publication.unified_volume import build_unified_volume_plan
        rows=source([1,3],[2]).get_chapters('https://atsu.moe/manga/fixture','en')
        b=PublicationManifestBuilder(dict(canonical_identity='fixture:series',title='Series'),'original')
        b.apply_mangadex_structure(dict(status='valid',cache_contract='mangadex-structure-v1',manga_id='md',
            canonical_work_id='fixture:series',edition_profile='original',mappings={'1':'1','2':'1','3':'1'}))
        projection=build_publication_projection(rows,b.build(),'atsu','atsu')
        plan=build_unified_volume_plan({},rows,projection,'atsu','Atsu')
        self.assertEqual({1.0:3},plan['chapters_by_volume'])

    def test_single_group_and_unknown_recommendation_remain_conservative(self):
        s=source([1,2],[]);s._api=lambda path,**kw:dict(chapters=[dict(id='a1',number=1,pageCount=1,scanlationMangaId='a')])
        rows=s.get_chapters('https://atsu.moe/manga/fixture','en');self.assertEqual(1,len(rows))
        self.assertNotIn('_atsu_group_inventory',rows[0])
        s=source([1],[2]);api=s._api;s._api=lambda path,**kw:dict(mangaPage={}) if path.endswith('/page') else api(path,**kw)
        self.assertEqual(2,len(s.get_chapters('https://atsu.moe/manga/fixture','en')))

    def test_volume_filter_does_not_switch_to_an_unrecommended_group(self):
        s=source([1],[1]);api=s._api
        def request(path,**kw):
            data=api(path,**kw)
            if 'chapters' in data:data['chapters'][1]['title']='Volume 1'
            return data
        s._api=request
        self.assertEqual([],s.get_chapters('https://atsu.moe/manga/fixture','en',1,1))


if __name__=='__main__':unittest.main()
