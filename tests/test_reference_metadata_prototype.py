import tempfile
import unittest
import urllib.error
from pathlib import Path

from bookwalker_reference import BookwalkerPublicationAdapter, _CatalogCard
from reference_integration import ReferenceMetadataService
from reference_metadata import PublicationMatch, ReferencePrototypeCache
from search_cache import SearchMetadataCache
from wikipedia_reference import WikipediaPublicationAdapter


def bookwalker_card_match(card_title, evidence, series_id='13000'):
    product = '33333333-3333-3333-3333-333333333333'
    search = (
        '<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" '
        'class="m-book-item__title" title="%s"></a>'
        '<span class="a-tag-category">マンガ</span></div>'
    ) % (product, card_title)
    page = (
        '<link rel="canonical" href="https://bookwalker.jp/de%s/">'
        '<title>%s</title><a href="https://bookwalker.jp/series/%s/list/">series</a>'
    ) % (product, card_title, series_id)
    adapter = BookwalkerPublicationAdapter(
        lambda url: search if '/search/' in url else page
    )
    return adapter.match_publication(evidence)


def bookwalker_multi_fixture(search_volumes=(24, 7, 1), catalog_volumes=range(1, 25),
                             catalog_total=24, canonical_seed=None,
                             series_ids=('13021',), partial=False,
                             promotion_position=None, promotion_wrapper='div',
                             extra_normal_volume=None, extra_color_volume=None,
                             malformed_extra=False):
    identifiers = {
        number: f'{number:08x}-0000-0000-0000-{number:012x}'
        for number in set(search_volumes) | set(catalog_volumes)
    }

    def card(number, image=False):
        return (
            '<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" '
            'class="m-book-item__title" title="ジョジョの奇妙な冒険 第7部 '
            'スティール・ボール・ラン %s"></a>%s'
            '<span class="a-tag-category">マンガ</span></div>'
        ) % (identifiers[number], number,
             '<img data-original="https://covers/%s.jpg">' % number if image else '')

    promotion_id = 'ffffffff-0000-0000-0000-000000000001'
    promotion = (
        '<%s class="m-book-item "><a href="https://bookwalker.jp/de%s/" '
        'class="m-book-item__title" title="ジョジョの奇妙な冒険 第7部 '
        'スティール・ボール・ラン〖期間限定無料〗 1"></a>'
        '<img data-original="https://covers/promotion.jpg">'
        '<span class="a-tag-category">マンガ</span></%s>'
    ) % (promotion_wrapper, promotion_id, promotion_wrapper)
    def extra_card(label, number):
        product_id = 'eeeeeeee-0000-0000-0000-%012x' % int(number)
        return (
            '<div class="m-book-item "><a href="https://bookwalker.jp/de%s/" '
            'class="m-book-item__title" title="ジョジョの奇妙な冒険 第7部 '
            'スティール・ボール・ラン%s %s"></a>'
            '<img data-original="https://covers/extra-%s.jpg">'
            '<span class="a-tag-category">マンガ</span></div>'
        ) % (product_id, label, number, number)

    search = ''.join(card(number) for number in search_volumes)
    seed_number = min(search_volumes)
    seed = identifiers[seed_number]
    canonical = canonical_seed or seed
    product = (
        '<link rel="canonical" href="https://bookwalker.jp/de%s/">'
        '<title>ジョジョの奇妙な冒険 第7部 スティール・ボール・ラン %s</title>%s'
    ) % (canonical, seed_number, ''.join(
        '<a href="https://bookwalker.jp/series/%s/list/">series</a>' % series_id
        for series_id in series_ids
    ))
    series = ''.join(card(number, True) for number in catalog_volumes)
    if promotion_position == 'before':
        series = promotion + series
    elif promotion_position == 'after':
        series += promotion
    if extra_normal_volume is not None:
        series += extra_card('', extra_normal_volume)
    if extra_color_volume is not None:
        series += extra_card(' カラー版', extra_color_volume)
    if malformed_extra:
        series += (
            '<li class="m-book-item campaign"><a '
            'href="https://bookwalker.jp/dedddddddd-0000-0000-0000-000000000001/" '
            'class="m-book-item__title">Unclassified campaign product</a></li>'
        )
    series += '<p>1～%s件目/全%s件</p>' % (len(tuple(catalog_volumes)), catalog_total)
    if partial:
        series += '<link rel="next" href="https://bookwalker.jp/series/13021/list/?page=2">'
    calls = []

    def request(url):
        calls.append(url)
        if '/search/' in url:
            return search
        if url == 'https://bookwalker.jp/de' + seed + '/':
            return product
        if url == 'https://bookwalker.jp/series/13021/list/?page=2':
            raise RuntimeError('partial catalog fixture')
        if url == 'https://bookwalker.jp/series/13021/list/':
            return series
        raise AssertionError('Unexpected BOOK☆WALKER request: ' + url)

    return BookwalkerPublicationAdapter(request), calls, identifiers


def bookwalker_aot_fixture(specials_before=False, missing_normal=(),
                           unknown_suffix=False, color_collision=False):
    ordinary_ids = {
        number: f'{number:08x}-4214-0000-0000-{number:012x}'
        for number in range(1, 35)
    }
    def card(product_id, title, image=True, wrapper='div'):
        return (
            '<%s class="m-book-item "><a href="https://bookwalker.jp/de%s/" '
            'class="m-book-item__title" title="%s"></a>%s'
            '<span class="a-tag-category">マンガ</span></%s>'
        ) % (wrapper, product_id, title,
             '<img data-original="https://covers/%s.jpg">' % product_id if image else '',
             wrapper)
    search = card(ordinary_ids[1], '進撃の巨人（週刊少年マガジン）', False)
    product = (
        '<link rel="canonical" href="https://bookwalker.jp/de%s/">'
        '<title>進撃の巨人（1）</title>'
        '<a href="https://bookwalker.jp/series/4214/list/">series</a>'
    ) % ordinary_ids[1]
    normal = ''.join(
        card(ordinary_ids[number], '進撃の巨人（' + str(number).translate(str.maketrans('0123456789','０１２３４５６７８９')) + '）')
        for number in range(1, 35) if number not in set(missing_normal)
    )
    special_titles = (
        (34, '進撃の巨人（３４）　特装版　Ｅｎｄｉｎｇ'),
        (34, '進撃の巨人（３４）　特装版　Ｂｅｇｉｎｎｉｎｇ'),
        (31, '進撃の巨人（３１）特装版'),
        (30, '進撃の巨人（３０）特装版'),
        (29, '進撃の巨人（２９）特装版'),
    )
    specials = ''.join(card(
        f'aaaa{index:04x}-4214-0000-0000-{index:012x}', title,
    ) for index, (_number, title) in enumerate(special_titles, 1))
    promotion = ''.join(card(
        f'bbbbbbbb-4214-0000-0000-{number:012x}',
        f'進撃の巨人（{number}）〖期間限定無料〗', wrapper='li',
    ) for number in range(1,13))
    extras = ''
    if unknown_suffix:
        extras += card('cccccccc-4214-0000-0000-000000000001', '進撃の巨人（20） 謎版')
    if color_collision:
        extras += card('dddddddd-4214-0000-0000-000000000001', '進撃の巨人 カラー版（20）')
    series = ((specials + normal) if specials_before else (normal + specials)) + promotion + extras
    expected = len(tuple(range(1, 35))) - len(set(missing_normal)) + 17
    expected += int(bool(unknown_suffix)) + int(bool(color_collision))
    series += '<p>1～%s件目/全%s件</p>' % (expected, expected)
    calls = []
    def request(url):
        calls.append(url)
        if '/search/' in url:
            return search
        if url == 'https://bookwalker.jp/de' + ordinary_ids[1] + '/':
            return product
        if url == 'https://bookwalker.jp/series/4214/list/':
            return series
        raise AssertionError('Unexpected BOOK☆WALKER request: ' + url)
    return BookwalkerPublicationAdapter(request), calls, ordinary_ids


class ReferenceMetadataPrototypeTests(unittest.TestCase):
    def test_standard_catalog_count_controls_remain_27_74_and_43(self):
        for title,count in (('ジョジョの奇妙な冒険 第8部 ジョジョリオン',27),
                            ('BLEACH',74),('ベルセルク',43)):
            with self.subTest(title=title):
                adapter=BookwalkerPublicationAdapter()
                raw=tuple(_CatalogCard(str(n),f'{title}（{n}）',f'product/{n}',
                                       image=f'cover/{n}') for n in range(1,count+1))
                adapter._catalogs['series/control']=(raw,{
                    'complete':True,'record_count_delta':0,'records_fetched':count,
                    'expected_total':count,
                })
                match=PublicationMatch('bookwalker','series/control',title,'confident',
                    'fixture',edition='original',edition_id='series/control')
                self.assertEqual(count,len(adapter.get_volume_covers(match)))
                self.assertTrue(adapter.catalog_metadata(match)['canonical_complete'])

    def test_supplementary_unicode_boundary_is_bounded_and_preserves_raw_records(self):
        for suffix,accepted in (
                ('特装版 Ending',True),('特装版　Ｅｎｄｉｎｇ',True),
                ('特装版　Ｂｅｇｉｎｎｉｎｇ',True),('特装版',True),
                ('限定版 Ending',True),('特装版 Deluxe',False),
                ('カラー版 特装版',False),('モノクロ版 特装版',False),
                ('full color 特装版',False)):
            with self.subTest(suffix=suffix):
                adapter=BookwalkerPublicationAdapter()
                raw=(
                    _CatalogCard('normal','進撃の巨人（３４）','normal-url',image='normal-cover'),
                    _CatalogCard('special','進撃の巨人（３４）　'+suffix,'special-url',image='special-cover'),
                )
                adapter._catalogs['series/4214']=(raw,{
                    'complete':True,'partial':False,'record_count_delta':0,
                    'expected_total':2,'records_fetched':2,
                })
                match=PublicationMatch('bookwalker','series/4214','進撃の巨人','confident',
                    'fixture',edition='original',edition_id='series/4214')
                metadata=adapter.catalog_metadata(match)
                self.assertEqual(accepted,metadata['canonical_complete'])
                covers=adapter.get_volume_covers(match)
                self.assertEqual(('normal-cover',) if accepted else (),
                                 tuple(cover.url for cover in covers))
                self.assertEqual(raw,adapter._catalogs['series/4214'][0])
                self.assertEqual('進撃の巨人（３４）　'+suffix,raw[1].title)

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

    def test_bookwalker_accepts_exact_jojo_standard_catalog_bases(self):
        fixtures = (
            ("JoJo's Bizarre Adventure: Part 7-Steel Ball Run",
             'ジョジョの奇妙な冒険 スティール・ボール・ラン',
             'ジョジョの奇妙な冒険 第7部 スティール・ボール・ラン 1'),
            ("JoJo's Bizarre Adventure Part 8: JoJolion",
             'ジョジョの奇妙な冒険 ジョジョリオン',
             'ジョジョの奇妙な冒険 第8部 ジョジョリオン 1'),
        )
        for title, alias, card in fixtures:
            with self.subTest(card=card):
                match = bookwalker_card_match(card, {
                    'title': title, 'aliases': (alias,), 'edition': 'original',
                })
                self.assertEqual(('confident', 'original', '1'),
                                 (match.confidence, match.edition, match.volume_number))

    @staticmethod
    def steel_ball_run_evidence():
        return {
            'title': "JoJo's Bizarre Adventure: Part 7-Steel Ball Run",
            'aliases': ('ジョジョの奇妙な冒険 スティール・ボール・ラン',),
            'edition': 'original',
        }

    def test_bookwalker_consolidates_exact_multi_products_into_one_complete_series(self):
        adapter, calls, identifiers = bookwalker_multi_fixture()
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual(('confident', 'series/13021', identifiers[1], '1'),
                         (match.confidence, match.publication_id,
                          match.volume_id, match.volume_number))
        self.assertEqual(3, len(calls))
        self.assertEqual('https://bookwalker.jp/de' + identifiers[1] + '/', calls[1])
        volumes = adapter.get_volume_list(match)
        covers = adapter.get_volume_covers(match)
        metadata = adapter.catalog_metadata(match)
        self.assertEqual((24, 24, True, 0),
                         (len(volumes), len(covers), metadata['complete'],
                          metadata['record_count_delta']))
        self.assertEqual(3, len(calls))

    def test_bookwalker_live_shaped_promotion_is_parsed_raw_and_excluded_canonically(self):
        adapter, calls, _identifiers = bookwalker_multi_fixture(
            catalog_total=25, promotion_position='before',
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        metadata = adapter.catalog_metadata(match)
        self.assertEqual('confident', match.confidence)
        self.assertEqual((25, 25, 0), (
            metadata['expected_total'], metadata['records_fetched'],
            metadata['record_count_delta'],
        ))
        self.assertEqual((25, 1, 24, True), (
            metadata['raw_records_fetched'],
            metadata['promotional_products_excluded'],
            metadata['canonical_volume_count'], metadata['canonical_complete'],
        ))
        self.assertEqual((24, 24), (
            len(adapter.get_volume_list(match)), len(adapter.get_volume_covers(match)),
        ))
        self.assertEqual(3, len(calls))

    def test_bookwalker_aot_special_editions_leave_34_ordinary_canonical_covers(self):
        adapter, calls, ordinary_ids = bookwalker_aot_fixture()
        match = adapter.match_publication({
            'title': 'Attack on Titan', 'aliases': ('進撃の巨人',),
            'edition': 'original',
        })
        metadata = adapter.catalog_metadata(match)
        volumes = {row.number: row for row in adapter.get_volume_list(match)}
        self.assertEqual((51, 12, 5, 34, True), (
            metadata['raw_records_fetched'],
            metadata['promotional_products_excluded'],
            metadata['supplementary_variants_excluded'],
            metadata['canonical_volume_count'], metadata['canonical_complete'],
        ))
        self.assertEqual((34, 34, ordinary_ids[34]), (
            len(volumes), len(adapter.get_volume_covers(match)), volumes['34'].volume_id,
        ))
        self.assertEqual(3, len(calls))

    def test_bookwalker_aot_special_order_does_not_change_ordinary_covers(self):
        outputs=[]
        for specials_before in (False,True):
            adapter, _calls, ordinary_ids = bookwalker_aot_fixture(specials_before)
            match=adapter.match_publication({
                'title':'Attack on Titan','aliases':('進撃の巨人',),'edition':'original',
            })
            volumes={row.number:row.volume_id for row in adapter.get_volume_list(match)}
            outputs.append((len(volumes),volumes.get('34'),adapter.catalog_metadata(match)[
                'supplementary_variants_excluded'
            ]))
            self.assertEqual(ordinary_ids[34],volumes['34'])
        self.assertEqual([(34,outputs[0][1],5),(34,outputs[0][1],5)],outputs)

    def test_bookwalker_aot_special_without_ordinary_counterpart_fails_closed(self):
        adapter, _calls, _ordinary_ids = bookwalker_aot_fixture(missing_normal=(34,))
        match=adapter.match_publication({
            'title':'Attack on Titan','aliases':('進撃の巨人',),'edition':'original',
        })
        metadata=adapter.catalog_metadata(match)
        self.assertFalse(metadata['canonical_complete'])
        self.assertIn('lacks one ordinary counterpart',metadata['canonical_rejection_reason'])
        self.assertEqual((),adapter.get_volume_list(match))

    def test_bookwalker_aot_unknown_suffix_and_color_collision_fail_closed(self):
        for option in ('unknown_suffix','color_collision'):
            with self.subTest(option=option):
                adapter, _calls, _ordinary_ids = bookwalker_aot_fixture(**{option:True})
                match=adapter.match_publication({
                    'title':'Attack on Titan','aliases':('進撃の巨人',),'edition':'original',
                })
                metadata=adapter.catalog_metadata(match)
                self.assertFalse(metadata['canonical_complete'])
                self.assertEqual((),adapter.get_volume_covers(match))

    def test_bookwalker_promotional_anchor_in_alternate_wrapper_is_still_raw_product(self):
        adapter, _calls, _identifiers = bookwalker_multi_fixture(
            catalog_total=25, promotion_position='before', promotion_wrapper='li',
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual('confident', match.confidence)
        metadata = adapter.catalog_metadata(match)
        self.assertEqual((25, 25, 0, 24), (
            metadata['expected_total'], metadata['records_fetched'],
            metadata['record_count_delta'], len(adapter.get_volume_list(match)),
        ))

    def test_bookwalker_promotion_order_never_displaces_normal_volume_one(self):
        for position in ('before', 'after'):
            with self.subTest(position=position):
                adapter, _calls, identifiers = bookwalker_multi_fixture(
                    catalog_total=25, promotion_position=position,
                )
                match = adapter.match_publication(self.steel_ball_run_evidence())
                volumes = {row.number: row for row in adapter.get_volume_list(match)}
                self.assertEqual(identifiers[1], volumes['1'].volume_id)

    def test_bookwalker_two_normal_products_for_one_volume_fail_closed(self):
        adapter, _calls, _identifiers = bookwalker_multi_fixture(
            catalog_total=25, extra_normal_volume=1,
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual('ambiguous', match.confidence)

    def test_bookwalker_standard_catalog_rejects_color_product_collision(self):
        adapter, _calls, _identifiers = bookwalker_multi_fixture(
            catalog_total=25, extra_color_volume=1,
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual('ambiguous', match.confidence)

    def test_bookwalker_advertised_25_but_parsed_24_rejects_exact_count_deficit(self):
        adapter, _calls, _identifiers = bookwalker_multi_fixture(catalog_total=25)
        match = adapter.match_publication(self.steel_ball_run_evidence())
        metadata = dict(adapter._catalogs['series/13021'][1])
        self.assertEqual('ambiguous', match.confidence)
        self.assertEqual((25, 24, 1), (
            metadata['expected_total'], metadata['records_fetched'],
            metadata['record_count_delta'],
        ))

    def test_bookwalker_malformed_extra_product_does_not_explain_raw_deficit(self):
        adapter, _calls, _identifiers = bookwalker_multi_fixture(
            catalog_total=25, malformed_extra=True,
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        metadata = dict(adapter._catalogs['series/13021'][1])
        self.assertEqual('ambiguous', match.confidence)
        self.assertEqual((24, 1), (
            metadata['records_fetched'], metadata['record_count_delta'],
        ))
        self.assertIn('record-count deficit', match.reason)

    def test_bookwalker_promotional_catalog_persists_24_covers_and_warm_hit_is_request_free(self):
        class NoWikipedia:
            pattern_id = 'fixture'; parser_version = '1'
            def match_publication(self, _evidence):
                return PublicationMatch('wikipedia', '', '', 'no_match', 'fixture')
        class NoGoogle:
            def resolve(self, _context, _targets):
                return {'status': 'disabled', 'covers': [], 'candidates': []}
        adapter, calls, _identifiers = bookwalker_multi_fixture(
            catalog_total=25, promotion_position='before', promotion_wrapper='li',
        )
        evidence = {
            **self.steel_ball_run_evidence(),
            'reference_key': 'fixture-sbr|standard',
            'edition_profile': 'standard',
        }
        with tempfile.TemporaryDirectory() as folder:
            cache = SearchMetadataCache(Path(folder) / 'cache.sqlite3')
            service = ReferenceMetadataService(cache, NoWikipedia(), adapter, NoGoogle())
            cold = service.lookup('fixture-sbr|standard', evidence)
            warm = service.lookup('fixture-sbr|standard', evidence)
            self.assertEqual((24, 24, 'hit'), (
                len(cold['bookwalker']['covers']), len(warm['bookwalker']['covers']),
                warm['bookwalker']['cache_state'],
            ))
            self.assertEqual((25, 1, 24), (
                cold['bookwalker']['catalog']['raw_records_fetched'],
                cold['bookwalker']['catalog']['promotional_products_excluded'],
                cold['bookwalker']['catalog']['canonical_volume_count'],
            ))
            self.assertEqual(3, len(calls))
            cache.close()

    def test_bookwalker_multi_product_two_series_collision_fails_closed(self):
        adapter, _calls, _identifiers = bookwalker_multi_fixture(
            search_volumes=(1, 7), catalog_volumes=(1,), catalog_total=1,
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual('ambiguous', match.confidence)

    def test_bookwalker_multi_product_partial_catalog_fails_closed(self):
        adapter, calls, _identifiers = bookwalker_multi_fixture(
            search_volumes=(1, 7), catalog_volumes=(1,), catalog_total=2, partial=True,
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual('ambiguous', match.confidence)
        self.assertEqual(1, sum('?page=2' in url for url in calls))

    def test_bookwalker_multi_product_seed_canonical_mismatch_fails_closed(self):
        adapter, calls, _identifiers = bookwalker_multi_fixture(
            search_volumes=(1, 7), catalog_volumes=(1, 7), catalog_total=2,
            canonical_seed='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual('ambiguous', match.confidence)
        self.assertFalse(any('/series/' in url for url in calls))

    def test_bookwalker_multi_product_seed_with_two_series_fails_closed(self):
        adapter, calls, _identifiers = bookwalker_multi_fixture(
            search_volumes=(1, 7), catalog_volumes=(1, 7), catalog_total=2,
            series_ids=('13021', '99999'),
        )
        match = adapter.match_publication(self.steel_ball_run_evidence())
        self.assertEqual('ambiguous', match.confidence)
        self.assertFalse(any('/series/' in url for url in calls))

    def test_bookwalker_rejects_jojo_part_mismatch_even_when_base_matches(self):
        match = bookwalker_card_match(
            'ジョジョの奇妙な冒険 第7部 ジョジョリオン 1',
            {'title': "JoJo's Bizarre Adventure Part 8: JoJolion",
             'aliases': ('ジョジョの奇妙な冒険 ジョジョリオン',),
             'edition': 'original'},
        )
        self.assertEqual('ambiguous', match.confidence)

    def test_bookwalker_keeps_jojolion_color_out_of_standard_catalog(self):
        card = 'ジョジョの奇妙な冒険 第8部 ジョジョリオン カラー版 1'
        evidence = {
            'title': "JoJo's Bizarre Adventure Part 8: JoJolion",
            'aliases': ('ジョジョの奇妙な冒険 ジョジョリオン',),
        }
        standard = bookwalker_card_match(card, {**evidence, 'edition': 'original'})
        color = bookwalker_card_match(card, {**evidence, 'edition': 'official_color'})
        self.assertEqual('ambiguous', standard.confidence)
        self.assertEqual(('confident', 'official_color'), (color.confidence, color.edition))

    def test_bookwalker_exact_base_rejects_unrelated_and_promotional_cards(self):
        evidence = {
            'title': "JoJo's Bizarre Adventure Part 8: JoJolion",
            'aliases': ('ジョジョの奇妙な冒険 ジョジョリオン',),
            'edition': 'original',
        }
        unrelated = bookwalker_card_match(
            '別冊 ジョジョの奇妙な冒険 第8部 ジョジョリオン 1', evidence
        )
        promotion = bookwalker_card_match(
            'ジョジョの奇妙な冒険 第8部 ジョジョリオン【期間限定無料】 1', evidence
        )
        self.assertEqual(('ambiguous', 'ambiguous'),
                         (unrelated.confidence, promotion.confidence))

    def test_bookwalker_bleach_standard_behavior_remains_exact(self):
        match = bookwalker_card_match(
            'BLEACH モノクロ版 1',
            {'title': 'Bleach', 'aliases': ('BLEACH',), 'edition': 'original'},
        )
        self.assertEqual(('confident', 'original', '1'),
                         (match.confidence, match.edition, match.volume_number))

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
        self.assertEqual((),adapter.get_volume_list(match))
        metadata=adapter.catalog_metadata(match)
        self.assertEqual((1,False,True),(metadata['pages_fetched'],metadata['complete'],metadata['partial']))
        self.assertIn('temporary failure',metadata['error'])
        self.assertFalse(metadata['canonical_complete'])

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
