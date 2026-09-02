#!/usr/bin/env python3
"""Bounded live validation of production Google volumes.get(full) promotion."""
import argparse, json, os
from pathlib import Path
import sys
sys.path.insert(0,'.')
from google_books_reference import GoogleBooksArtworkResolver


CASES={
    'one_piece':{'title':'One Piece','creators':('Eiichiro Oda',),'targets':('58','113'),'bookwalker':('57',)},
    'bleach':{'title':'Bleach','creators':('Tite Kubo',),'targets':('74',),'bookwalker':('60',)},
}


def api_record(row):
    series={'seriesId':row.get('series_id'),'orderNumber':float(row.get('order_number') or row.get('target_volume')),
            'seriesBookType':row.get('series_book_type') or 'COLLECTED_EDITION'}
    return {'id':row['google_volume_id'],'volumeInfo':{
        'title':row.get('title'),'subtitle':row.get('subtitle'),'authors':row.get('authors') or (),
        'publisher':row.get('publisher'),'publishedDate':row.get('published_date'),'language':row.get('language'),
        'industryIdentifiers':[{'type':kind,'identifier':value} for kind,value in row.get('isbns') or ()],
        'seriesInfo':{'volumeSeries':[series]},'imageLinks':dict(row.get('image_links') or ()),
    },'saleInfo':{'saleability':'FOR_SALE'}}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--qualification',required=True); parser.add_argument('--output',required=True)
    args=parser.parse_args()
    if not os.environ.get('MANGANANA_GOOGLE_BOOKS_API_KEY'): raise SystemExit('API key absent')
    source=json.loads(Path(args.qualification).read_text(encoding='utf-8')); output={'contract':'phase1f2-live-v1','series':{}}
    for key,case in CASES.items():
        candidates=[row for row in source['series'][key]['result']['candidates']
                    if row.get('classification') == 'EXACT_STANDARD']
        records=[api_record(row) for row in candidates]
        context={'canonical_work_id':'probe:'+key,'canonical_title':case['title'],'trusted_aliases':(case['title'],),
                 'canonical_creators':case['creators'],'canonical_creator_aliases':(),
                 'requested_language':'en','edition_profile':'standard','reference_key':'probe|'+key+'|standard'}
        resolver=GoogleBooksArtworkResolver(request_json=lambda _params,r=records:{'items':r})
        result=resolver.resolve(context,case['targets'])
        output['series'][key]={'bookwalker_controls':{volume:'bookwalker' for volume in case['bookwalker']},
                               'google_targets':list(case['targets']),'covers':result.get('covers') or (),
                               'network':result.get('network') or {}}
    output['aggregate']={'detail_requests':sum(row['network'].get('detail_requests',0) for row in output['series'].values()),
                         'google_covers':sum(len(row['covers']) for row in output['series'].values())}
    Path(args.output).write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps({'artifact':args.output,'aggregate':output['aggregate'],
                      'covers':{key:[(row['volume'],row['source_field']) for row in value['covers']]
                                for key,value in output['series'].items()}},indent=2))


if __name__=='__main__': main()
