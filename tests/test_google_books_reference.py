import unittest
import urllib.error

from google_books_reference import (
    CACHE_CONTRACT, Classification, GoogleBooksArtworkResolver,
    classify_manifestation, normalize_google_volume, trusted_series_ids,
)


CONTEXT={
    'canonical_work_id':'anilist:21','canonical_title':'One Piece',
    'trusted_aliases':('One Piece',),'canonical_creators':('Eiichiro Oda',),
    'canonical_creator_aliases':('Oda Eiichiro',),'requested_language':'en',
    'edition_profile':'standard','reference_key':'anilist-21|one-piece|standard',
}


def volume(identifier='v7',title='One Piece, Vol. 7',order=7,series='series-one-piece',
           language='en',authors=('Eiichiro Oda',),images=None,saleability='FOR_SALE',
           series_type='COLLECTED_EDITION',issues=()):
    series_row={'seriesId':series,'orderNumber':order,'seriesBookType':series_type}
    if issues:
        series_row['issue']=[{'issueOrderNumber':number,'issueDisplayNumber':str(number)} for number in issues]
    return {'id':identifier,'volumeInfo':{
        'title':title,'authors':list(authors),'language':language,'publisher':'VIZ Media',
        'publishedDate':'2020-01-01','industryIdentifiers':[{'type':'ISBN_13','identifier':'9780000000000'}],
        'seriesInfo':{'bookDisplayNumber':str(order),'volumeSeries':[series_row]},
        'imageLinks':images if images is not None else {'small':'https://images/'+identifier+'.jpg'},
    },'saleInfo':{'saleability':saleability,'isEbook':True}}


class GoogleBooksReferenceTests(unittest.TestCase):
    def test_normalization_uses_order_number_and_largest_returned_field(self):
        row=normalize_google_volume(volume(images={'thumbnail':'thumb','medium':'medium','large':'large'}))
        self.assertEqual(('7','large','large','HIGH'),(
            row.order_number,row.selected_image_field,row.selected_artwork_url,row.artwork_quality,
        ))

    def test_book_display_number_is_not_order_authority(self):
        raw=volume(); raw['volumeInfo']['seriesInfo']['bookDisplayNumber']='999'
        self.assertEqual('7',normalize_google_volume(raw).order_number)

    def test_subtitle_safe_explicit_volume_marker_qualifies(self):
        row=normalize_google_volume(volume(title='One Piece, Vol. 7: A True Friend',series=''))
        self.assertEqual(Classification.EXACT_STANDARD,classify_manifestation(row,CONTEXT,'7',())[0])

    def test_series_fingerprint_requires_two_compatible_orders(self):
        rows=tuple(map(normalize_google_volume,(volume(),volume('v8','One Piece, Vol. 8',8))))
        self.assertEqual(('series-one-piece',),trusted_series_ids(rows,CONTEXT))
        self.assertEqual((),trusted_series_ids(rows[:1],CONTEXT))

    def test_exact_standard_requires_title_creator_and_exact_volume(self):
        row=normalize_google_volume(volume())
        classification,evidence=classify_manifestation(row,CONTEXT,'7',('series-one-piece',))
        self.assertEqual(Classification.EXACT_STANDARD,classification)
        self.assertIn('exact orderNumber',evidence)

    def test_foreign_language_rejected_even_with_same_series(self):
        row=normalize_google_volume(volume(language='fr'))
        self.assertEqual(Classification.FOREIGN_LANGUAGE,
                         classify_manifestation(row,CONTEXT,'7',('series-one-piece',))[0])

    def test_omnibus_and_structured_multi_issue_are_rejected(self):
        textual=normalize_google_volume(volume(title='One Piece 3-in-1, Vol. 1',order=1))
        structured=normalize_google_volume(volume(issues=(7,8,9)))
        self.assertEqual(Classification.OMNIBUS_COLLECTION,classify_manifestation(textual,CONTEXT,'1',())[0])
        self.assertEqual(Classification.OMNIBUS_COLLECTION,classify_manifestation(structured,CONTEXT,'7',())[0])

    def test_alternate_box_spinoff_and_novel_are_distinct(self):
        cases=(
            ('One Piece, Vol. 7 Deluxe Edition',Classification.ALTERNATE_EDITION),
            ('One Piece Box Set 1',Classification.BOX_SET),
            ('One Piece: Buddy Stories',Classification.SPINOFF),
            ('One Piece Guidebook',Classification.NOVEL_GUIDEBOOK),
        )
        for title,expected in cases:
            with self.subTest(title=title):
                self.assertEqual(expected,classify_manifestation(
                    normalize_google_volume(volume(title=title)),CONTEXT,'7',('series-one-piece',)
                )[0])

    def test_preorder_and_coverless_are_preserved_but_not_normal_exact(self):
        preorder=normalize_google_volume(volume(saleability='FOR_PREORDER'))
        coverless=normalize_google_volume(volume(images={}))
        self.assertEqual(Classification.EXACT_STANDARD_PREORDER,
                         classify_manifestation(preorder,CONTEXT,'7',('series-one-piece',))[0])
        self.assertEqual(Classification.EXACT_STANDARD_COVERLESS,
                         classify_manifestation(coverless,CONTEXT,'7',('series-one-piece',))[0])

    def test_thumbnail_only_exact_is_not_promoted(self):
        def request(_params):
            return {'items':[volume(images={'thumbnail':'https://images/t.jpg'}),
                             volume('v8','One Piece, Vol. 8',8,images={'small':'https://images/8.jpg'})]}
        result=GoogleBooksArtworkResolver(request_json=request,api_key='',enabled=True).resolve(CONTEXT,('7','8'))
        self.assertEqual([],result['covers'])
        seven=next(row for row in result['candidates'] if row['target_volume']=='7')
        self.assertEqual(('EXACT_STANDARD',False,'THUMBNAIL_ONLY'),(
            seven['classification'],seven['accepted'],seven['artwork_quality'],
        ))

    def test_deterministic_manifestation_selection_ignores_arrival_order(self):
        records=[volume('z','One Piece, Vol. 7',7,images={'small':'z'}),
                 volume('a','One Piece, Vol. 7',7,images={'small':'a'}),
                 volume('v8','One Piece, Vol. 8',8)]
        outputs=[]
        for rows in (records,list(reversed(records))):
            calls=[]
            def detail(volume_id):
                calls.append(volume_id); return volume(volume_id,'One Piece, Vol. 7',7,images={'extraLarge':volume_id})
            result=GoogleBooksArtworkResolver(request_json=lambda _params,r=rows:{'items':r},request_detail=detail,api_key='configured',enabled=True).resolve(CONTEXT,('7',))
            outputs.append(result['covers'][0]['volume_id'])
        self.assertEqual(['a','a'],outputs)

    def test_disabled_non_english_and_missing_context_are_nonfatal(self):
        calls=[]
        resolver=GoogleBooksArtworkResolver(request_json=lambda p:calls.append(p),api_key='',enabled=False)
        self.assertEqual('disabled',resolver.resolve(CONTEXT,('7',))['status'])
        self.assertEqual([],calls)
        foreign={**CONTEXT,'requested_language':'ja'}
        self.assertEqual('disabled',GoogleBooksArtworkResolver(api_key='',enabled=True).resolve(foreign,('7',))['status'])
        missing={**CONTEXT,'canonical_creators':()}
        self.assertEqual('insufficient_canonical_evidence',GoogleBooksArtworkResolver(api_key='',enabled=True).resolve(missing,('7',))['status'])

    def test_result_preserves_contract_evidence_and_bounded_requests(self):
        calls=[]
        def request(params):
            calls.append(params); return {'items':[volume(),volume('v8','One Piece, Vol. 8',8)]}
        result=GoogleBooksArtworkResolver(request_json=request,api_key='',enabled=True).resolve(CONTEXT,range(1,30))
        self.assertEqual(CACHE_CONTRACT,result['cache_contract'])
        self.assertLessEqual(result['network']['requests'],10)
        self.assertTrue(all('identity_evidence' in row for row in result['candidates']))

    def test_creator_variant_and_trusted_title_alias_discovery_are_staged_and_bounded(self):
        context={**CONTEXT,'canonical_title':'Detective Conan','trusted_aliases':('Case Closed',),
                 'canonical_creators':('Aoyama Gosho',),'canonical_creator_aliases':()}
        calls=[]
        def request(params):
            calls.append(params['q'])
            if 'Case Closed' not in params['q'] or 'gosho aoyama' not in params['q'].casefold():
                return {'items':[]}
            return {'items':[
                volume('c1','Case Closed, Vol. 1',1,'case-closed',authors=('Gosho Aoyama',)),
                volume('c2','Case Closed, Vol. 2',2,'case-closed',authors=('Gosho Aoyama',)),
            ]}
        result=GoogleBooksArtworkResolver(request_json=request,api_key='',enabled=True).resolve(context,('1','2'))
        self.assertTrue(any('Case Closed' in query for query in calls))
        self.assertEqual('EXACT_STANDARD',next(row for row in result['candidates'] if row['target_volume']=='1')['classification'])
        self.assertLessEqual(len(calls),10)

    def test_targeted_gap_search_reuses_trusted_title_alias(self):
        context={**CONTEXT,'canonical_title':'Detective Conan','trusted_aliases':('Case Closed',),
                 'canonical_creators':('Gosho Aoyama',),'canonical_creator_aliases':()}
        calls=[]
        def request(params):
            calls.append(params['q'])
            if 'Case Closed Vol. 66' in params['q']:
                return {'items':[volume('c66','Case Closed, Vol. 66',66,'case-closed',authors=('Gosho Aoyama',))]}
            if 'Case Closed' in params['q']:
                return {'items':[volume('c1','Case Closed, Vol. 1',1,'case-closed',authors=('Gosho Aoyama',)),
                                 volume('c2','Case Closed, Vol. 2',2,'case-closed',authors=('Gosho Aoyama',))]}
            return {'items':[]}
        result=GoogleBooksArtworkResolver(request_json=request,api_key='',enabled=True).resolve(context,('66',))
        self.assertTrue(any('Case Closed Vol. 66' in query for query in calls))
        self.assertEqual('EXACT_STANDARD',next(row for row in result['candidates'] if row['target_volume']=='66')['classification'])
        self.assertLessEqual(result['network']['requests'],10)

    def test_oda_long_vowel_and_name_order_pass_strict_creator_qualification(self):
        context={**CONTEXT,'canonical_creators':('Oda Eiichirou (尾田栄一郎)',),'canonical_creator_aliases':()}
        row=normalize_google_volume(volume(authors=('Eiichiro Oda',)))
        self.assertEqual(Classification.EXACT_STANDARD,classify_manifestation(row,context,'7',('series-one-piece',))[0])

    def test_full_record_selects_light_preview_and_extra_large_source(self):
        rows=[volume(),volume('v8','One Piece, Vol. 8',8)]
        def detail(volume_id):
            return volume(volume_id,'One Piece, Vol. 7',7,images={
                'thumbnail':'preview','small':'small','extraLarge':'source',
            })
        result=GoogleBooksArtworkResolver(request_json=lambda _p:{'items':rows},request_detail=detail,
                                          api_key='configured',enabled=True).resolve(CONTEXT,('7',))
        cover=result['covers'][0]
        self.assertEqual(('small','source','extraLarge','volumes_get_full'),(
            cover['preview_url'],cover['source_url'],cover['source_field'],cover['retrieval'],
        ))

    def test_multiple_manifestations_stop_on_first_success_and_try_at_most_two(self):
        rows=[volume('a','One Piece, Vol. 7',7),volume('b','One Piece, Vol. 7',7),
              volume('c','One Piece, Vol. 7',7),volume('v8','One Piece, Vol. 8',8)]
        calls=[]
        def second_wins(volume_id):
            calls.append(volume_id)
            images={'thumbnail':'tiny'} if volume_id=='a' else {'extraLarge':'large'}
            return volume(volume_id,'One Piece, Vol. 7',7,images=images)
        result=GoogleBooksArtworkResolver(request_json=lambda _p:{'items':rows},request_detail=second_wins,
                                          api_key='configured',enabled=True).resolve(CONTEXT,('7',))
        self.assertEqual((['a','b'],'b'),(calls,result['covers'][0]['volume_id']))
        calls.clear()
        result=GoogleBooksArtworkResolver(request_json=lambda _p:{'items':rows},request_detail=lambda value:(calls.append(value) or volume(value,'One Piece, Vol. 7',7,images={'extraLarge':'large'})),
                                          api_key='configured',enabled=True).resolve(CONTEXT,('7',))
        self.assertEqual((['a'],'a'),(calls,result['covers'][0]['volume_id']))

    def test_full_record_contradiction_and_preorder_never_promote(self):
        rows=[volume(),volume('v8','One Piece, Vol. 8',8)]
        contradiction=lambda value:volume(value,'One Piece, Vol. 7 Deluxe Edition',7,images={'extraLarge':'wrong'})
        result=GoogleBooksArtworkResolver(request_json=lambda _p:{'items':rows},request_detail=contradiction,
                                          api_key='configured',enabled=True).resolve(CONTEXT,('7',))
        self.assertEqual([],result['covers'])
        preorder=[volume(saleability='FOR_PREORDER'),volume('v8','One Piece, Vol. 8',8)]
        calls=[]
        result=GoogleBooksArtworkResolver(request_json=lambda _p:{'items':preorder},request_detail=lambda value:calls.append(value),
                                          api_key='configured',enabled=True).resolve(CONTEXT,('7',))
        self.assertEqual(([],[]),(calls,result['covers']))

    def test_detail_cache_warm_hit_and_transient_failure_not_persisted(self):
        rows=[volume(),volume('v8','One Piece, Vol. 8',8)]; stored={}; calls=[]
        def detail(value): calls.append(value); return volume(value,'One Piece, Vol. 7',7,images={'extraLarge':'large'})
        resolver=lambda:GoogleBooksArtworkResolver(request_json=lambda _p:{'items':rows},request_detail=detail,api_key='configured',enabled=True)
        first=resolver().resolve(CONTEXT,('7',),stored.get,lambda key,value:stored.__setitem__(key,value))
        second=resolver().resolve(CONTEXT,('7',),stored.get,lambda key,value:stored.__setitem__(key,value))
        self.assertEqual((['v7'],'large','large'),(calls,first['covers'][0]['source_url'],second['covers'][0]['source_url']))

    def test_429_and_auth_failures_open_run_circuit(self):
        rows=[volume('a','One Piece, Vol. 7',7),volume('b','One Piece, Vol. 7',7),
              volume('v8','One Piece, Vol. 8',8)]; calls=[]
        for code in (401,403,429):
            calls.clear()
            def fail(value,c=code):
                calls.append(value); raise urllib.error.HTTPError('https://books.test/'+value,c,'failure',{},None)
            result=GoogleBooksArtworkResolver(request_json=lambda _p:{'items':rows},request_detail=fail,
                                              api_key='configured',enabled=True).resolve(CONTEXT,('7',))
            self.assertEqual([],result['covers'])
            self.assertTrue(result['network']['detail_circuit_open'])
            self.assertEqual(1,len(calls))


if __name__ == '__main__':
    unittest.main()
