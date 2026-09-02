import unittest
import urllib.error

from bookwalker_reference import BookwalkerPublicationAdapter
from reference_metadata import PublicationMatch, ReferencePrototypeCache
from wikipedia_reference import WikipediaPublicationAdapter


class ReferenceMetadataPrototypeTests(unittest.TestCase):
    def test_wikipedia_requires_one_exact_title_or_alias_match(self):
        def request(params):
            if params['action'] == 'query':
                return {'query': {'search': [
                    {'pageid': 1, 'title': 'Death Note'},
                    {'pageid': 2, 'title': 'Death Note (film)'},
                ]}}
            return {}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Death Note','aliases':('Desu Noto',)})
        self.assertEqual('confident',match.confidence)
        self.assertEqual('Death Note',match.title)

    def test_wikipedia_graphic_novel_pattern_extracts_explicit_volume_chapters(self):
        list_text='''{{Graphic novel list
| VolumeNumber = 1
| LicensedTitle = First volume
| ChapterListCol1 = {{Numbered list|start=1|{{nihongo|"First"|一}}|{{nihongo|"Second"|二}}}}
| ChapterListCol2 = {{Numbered list|start=3|{{nihongo|"Third"|三}}}}
}}'''
        def request(params):
            if params['action'] == 'query':
                if params['srsearch'] == 'Test':
                    return {'query': {'search': [{'pageid': 1, 'title': 'Test'}]}}
                return {'query': {'search': [{'pageid': 2, 'title': 'List of Test chapters'}]}}
            page=params['page']
            if page == 'Test':
                return {'parse': {'wikitext': {'*': 'No table here'}}}
            return {'parse': {'wikitext': {'*': list_text}}}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Test'})
        chapters=adapter.get_chapter_list(match)
        self.assertEqual('List of Test chapters',adapter.get_structure_page(match))
        self.assertEqual(['1','2','3'],[row.number for row in chapters])
        self.assertEqual(['First','Second','Third'],[row.title for row in chapters])
        self.assertEqual({'1':'1','2':'1','3':'1'},adapter.get_chapter_volume_map(match))
        self.assertEqual(['1'],[row.number for row in adapter.get_volume_list(match)])

    def test_wikipedia_explicit_chapter_list_ordered_entries_are_supported(self):
        list_text='''== Manga ==
=== Attack on Titan ===
{{Graphic novel list|VolumeNumber=1|ChapterList=
# First
# Second
}}
=== Attack on Titan: Lost Girls ===
{{Graphic novel list|VolumeNumber=1|ChapterList=
# Side story
}}'''
        def request(params):
            if params['action'] == 'query':
                return {'query': {'search': [{'pageid': 1, 'title': 'Attack on Titan'}]}}
            return {'parse': {'wikitext': {'*': list_text}}}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Shingeki no Kyojin','aliases':('Attack on Titan',)})
        chapters=adapter.get_chapter_list(match)
        self.assertEqual('Attack on Titan',match.title)
        self.assertEqual([('1','First','1'),('2','Second','1')],
                         [(row.number,row.title,row.volume) for row in chapters])

    def test_wikipedia_bullet_ranges_and_specials_stay_verbatim_and_unmapped(self):
        list_text='''{{Graphic novel list
| VolumeNumber = 2
| ChapterListCol1 =
* 12.5. Decimal chapter
* 13–14. Combined chapters
* Special 1. Side story
}}'''
        def request(params):
            if params['action'] == 'query':
                return {'query': {'search': [{'pageid': 1, 'title': 'Test'}]}}
            return {'parse': {'wikitext': {'*': list_text}}}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Test'})
        chapters=adapter.get_chapter_list(match)
        self.assertEqual(['12.5','13–14','Special 1'],[row.number for row in chapters])
        self.assertEqual(['chapter','range','special'],[row.kind for row in chapters])
        self.assertEqual({'12.5':'2'},adapter.get_chapter_volume_map(match))

    def test_wikipedia_uses_explicit_main_series_subsection_only(self):
        list_text='''== Manga ==
=== Test ===
{{Graphic novel list|VolumeNumber=1|ChapterListCol1={{Numbered list|start=1|Main}}}}
=== Test Junior High ===
{{Graphic novel list|VolumeNumber=1|ChapterListCol1={{Numbered list|start=1|Side story}}}}'''
        def request(params):
            if params['action'] == 'query':
                return {'query': {'search': [{'pageid': 1, 'title': 'Test'}]}}
            return {'parse': {'wikitext': {'*': list_text}}}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Test'})
        self.assertEqual(['Main'],[row.title for row in adapter.get_chapter_list(match)])

    def test_wikipedia_unsupported_layout_fails_closed(self):
        def request(params):
            if params['action'] == 'query':
                return {'query': {'search': [{'pageid': 1, 'title': 'Test'}]}}
            return {'parse': {'wikitext': {'*': '== Volume 1 ==\nChapter 1 through Chapter 7'}}}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Test'})
        self.assertEqual((),adapter.get_chapter_list(match))
        self.assertEqual({},adapter.get_chapter_volume_map(match))

    def test_wikipedia_ambiguous_chapter_pages_fail_closed(self):
        def request(params):
            if params['action'] == 'query':
                if params['srsearch'] == 'Test':
                    rows = [{'pageid': 1, 'title': 'Test'}]
                else:
                    rows = [
                        {'pageid': 2, 'title': 'List of Test chapters (1–10)'},
                        {'pageid': 3, 'title': 'List of Test chapters (11–20)'},
                    ]
                return {'query': {'search': rows}}
            return {'parse': {'wikitext': {'*': 'No template on the main page'}}}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Test'})
        self.assertEqual('',adapter.get_structure_page(match))
        self.assertEqual((),adapter.get_chapter_list(match))

    def test_wikipedia_transient_page_failure_is_not_cached_as_empty(self):
        calls=[]
        def request(params):
            if params['action'] == 'query':
                return {'query': {'search': [{'pageid': 1, 'title': 'Test'}]}}
            calls.append(params['page'])
            if len(calls) == 1:
                raise RuntimeError('temporary failure')
            return {'parse': {'wikitext': {'*': '{{Graphic novel list|VolumeNumber=1}}'}}}
        adapter=WikipediaPublicationAdapter(request)
        match=adapter.match_publication({'title':'Test'})
        with self.assertRaises(RuntimeError):
            adapter.get_structure_page(match)
        self.assertEqual('Test',adapter.get_structure_page(match))
        self.assertEqual(['Test','Test'],calls)

    def test_bookwalker_confirms_catalog_uuid_series_and_exact_volume(self):
        product='11111111-1111-1111-1111-111111111111'
        search='''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Death Note モノクロ版"></a><img data-original="https://covers/edition.jpg"></div>''' % product
        page='''<link rel="canonical" href="https://bookwalker.jp/de%s/"><title>Death Note モノクロ版 1</title><a href="https://bookwalker.jp/series/42/list/">series</a><meta name="description" content="A description">''' % product
        adapter=BookwalkerPublicationAdapter(lambda url: search if '/search/' in url else page)
        match=adapter.match_publication({'title':'Death Note','aliases':('Death Note',)})
        self.assertEqual(('confident','series/42','series/42',product,'1'),
                         (match.confidence,match.publication_id,match.edition_id,match.volume_id,match.volume_number))
        self.assertEqual('A description',adapter.get_description(match))
        artwork=adapter.get_edition_artwork(match)[0]
        self.assertEqual(('edition','series/42',product),
                         (artwork.artwork_type,artwork.edition_id,artwork.volume_id))

    def test_bookwalker_no_result_404_continues_to_validated_japanese_identity(self):
        product='14b19b62-e6d8-4419-acdd-620be6c3fcd3'; calls=[]
        search='''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="進撃の巨人（別冊少年マガジン）"></a><span class="a-tag-category">マンガ</span></div>''' % product
        page='''<link rel="canonical" href="https://bookwalker.jp/de%s/"><title>進撃の巨人（1）</title><a href="/series/4214/list/">series</a><meta name="description" content="Attack description">''' % product
        series='''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="進撃の巨人（1）"></a></div>''' % product
        def request(url):
            calls.append(url)
            if 'word=Attack%20on%20Titan' in url:
                raise urllib.error.HTTPError(url,404,'Not Found',{},None)
            if '/search/' in url:
                return search
            if '/series/' in url:
                return series
            return page
        adapter=BookwalkerPublicationAdapter(request)
        match=adapter.match_publication({'title':'Attack on Titan','aliases':('進撃の巨人',),'edition':'original'})
        self.assertEqual(('confident','series/4214',product,'1'),
                         (match.confidence,match.publication_id,match.volume_id,match.volume_number))
        self.assertEqual('1',adapter.get_volume_list(match)[0].number)
        self.assertIn('https://bookwalker.jp/de'+product+'/',calls)
        self.assertIn('https://bookwalker.jp/series/4214/list/',calls)

    def test_bookwalker_product_url_normalizes_bare_prefixed_and_canonical_uuid(self):
        product='e73c05f1-dd5c-46c1-8569-0c0002db3870'; calls=[]
        adapter=BookwalkerPublicationAdapter(
            lambda url:(calls.append(url) or '<meta name="description" content="JoJolion">')
        )
        base=PublicationMatch('bookwalker','series/13018','JoJolion','confident','fixture',
                              edition_id='series/13018',volume_id='de'+product)
        canonical=PublicationMatch('bookwalker','series/13018','JoJolion','confident','fixture',
                                   edition_id='series/13018',volume_id='https://bookwalker.jp/de'+product+'/')
        self.assertEqual('JoJolion',adapter.get_description(base))
        self.assertEqual('JoJolion',adapter.get_description(canonical))
        self.assertEqual(['https://bookwalker.jp/de'+product+'/'],calls)

    def test_bookwalker_rejects_ambiguous_edition_candidates(self):
        first='11111111-1111-1111-1111-111111111111'; second='22222222-2222-2222-2222-222222222222'
        search=''.join('''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Death Note モノクロ版"></a></div>''' % item for item in (first,second))
        adapter=BookwalkerPublicationAdapter(lambda _url: search)
        self.assertEqual('ambiguous',adapter.match_publication({'title':'Death Note'}).confidence)

    def test_bookwalker_keeps_color_edition_separate(self):
        black='11111111-1111-1111-1111-111111111111'; color='22222222-2222-2222-2222-222222222222'
        search='''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Death Note モノクロ版"></a></div><div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Death Note カラー版"></a></div>''' % (black,color)
        page='''<link rel="canonical" href="https://bookwalker.jp/de%s/"><title>Death Note カラー版 1</title><a href="https://bookwalker.jp/series/43/list/">series</a>''' % color
        adapter=BookwalkerPublicationAdapter(lambda url: search if '/search/' in url else page)
        match=adapter.match_publication({'title':'Death Note','edition':'official_color'})
        self.assertEqual(('official_color','series/43',color), (match.edition,match.edition_id,match.volume_id))

    def test_bookwalker_series_cards_preserve_exact_volume_and_artwork_identity(self):
        first='11111111-1111-1111-1111-111111111111'; promo='22222222-2222-2222-2222-222222222222'
        series='''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Death Note モノクロ版 2"></a><img data-original="https://covers/2.jpg"></div><div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Death Note モノクロ版【期間限定無料】 1"></a><img data-original="https://covers/1.jpg"></div>''' % (first,promo)
        adapter=BookwalkerPublicationAdapter(lambda _url: series)
        match=PublicationMatch('bookwalker','series/42','Death Note モノクロ版','confident','fixture',url='https://bookwalker.jp/series/42/list/',edition_id='series/42')
        volumes=adapter.get_volume_list(match); covers=adapter.get_volume_covers(match)
        self.assertEqual(('2',first,'explicit'),(volumes[0].number,volumes[0].volume_id,volumes[0].confidence))
        self.assertEqual(('volume','2','exact','series/42',first),
                          (covers[0].artwork_type,covers[0].volume,covers[0].confidence,
                           covers[0].edition_id,covers[0].volume_id))

    def test_bookwalker_follows_only_explicit_same_series_next_page_and_marks_complete(self):
        first='11111111-1111-1111-1111-111111111111'; second='22222222-2222-2222-2222-222222222222'
        def card(identifier,number):
            return '''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Work %s"></a><img data-original="https://covers/%s.jpg"></div>''' % (identifier,number,number)
        pages={
            'https://bookwalker.jp/series/42/list/':card(second,2)+'<p>1～1件目/全2件</p><link rel="next" href="https://bookwalker.jp/series/42/list/?page=2">',
            'https://bookwalker.jp/series/42/list/?page=2':card(first,1)+'<p>2～2件目/全2件</p>',
        }
        adapter=BookwalkerPublicationAdapter(pages.__getitem__)
        match=PublicationMatch('bookwalker','series/42','Work','confident','fixture',url='https://bookwalker.jp/series/42/list/',edition_id='series/42')
        self.assertEqual(['1','2'],sorted((row.number for row in adapter.get_volume_list(match)),key=float))
        metadata=adapter.catalog_metadata(match)
        self.assertEqual((2,2,True,0),(metadata['pages_fetched'],metadata['expected_total'],metadata['complete'],metadata['gap_count']))

    def test_bookwalker_failed_second_page_is_explicit_partial(self):
        first='11111111-1111-1111-1111-111111111111'
        page='''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Work 2"></a></div><p>1～1件目/全2件</p><link rel="next" href="?page=2">''' % first
        def request(url):
            if 'page=2' in url: raise RuntimeError('temporary failure')
            return page
        adapter=BookwalkerPublicationAdapter(request)
        match=PublicationMatch('bookwalker','series/42','Work','confident','fixture',url='https://bookwalker.jp/series/42/list/',edition_id='series/42')
        self.assertEqual(('2',),tuple(row.number for row in adapter.get_volume_list(match)))
        metadata=adapter.catalog_metadata(match)
        self.assertEqual((1,False,True),(metadata['pages_fetched'],metadata['complete'],metadata['partial']))
        self.assertIn('temporary failure',metadata['error'])

    def test_bookwalker_transient_fetch_failure_is_not_cached_as_empty(self):
        calls=[]
        def request(url):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError('temporary failure')
            return 'recovered'
        adapter=BookwalkerPublicationAdapter(request)
        with self.assertRaises(RuntimeError):
            adapter._fetch('https://bookwalker.jp/example/')
        self.assertEqual('recovered',adapter._fetch('https://bookwalker.jp/example/'))
        self.assertEqual(2,len(calls))

    def test_bookwalker_duplicate_non_promotional_volume_rows_fail_closed(self):
        first='11111111-1111-1111-1111-111111111111'; second='22222222-2222-2222-2222-222222222222'
        series=''.join('''<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" class="m-book-item__title" title="Death Note モノクロ版 2"></a></div>''' % item for item in (first,second))
        adapter=BookwalkerPublicationAdapter(lambda _url: series)
        match=PublicationMatch('bookwalker','series/42','Death Note モノクロ版','confident','fixture',url='https://bookwalker.jp/series/42/list/',edition_id='series/42')
        self.assertEqual((),adapter.get_volume_list(match))

    def test_prototype_cache_separates_edition_artwork_and_does_not_store_empty_failures(self):
        cache=ReferencePrototypeCache()
        cache.put('bookwalker','work','cover','one',edition='original',volume='1')
        cache.put('bookwalker','work','cover','two',edition='official_color',volume='1')
        cache.put('bookwalker','work','cover','',edition='original',volume='2')
        self.assertEqual('one',cache.get('bookwalker','work','cover',edition='original',volume='1'))
        self.assertEqual('two',cache.get('bookwalker','work','cover',edition='official_color',volume='1'))
        self.assertIsNone(cache.get('bookwalker','work','cover',edition='original',volume='2'))


if __name__ == '__main__':
    unittest.main()
