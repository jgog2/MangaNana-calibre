#!/usr/bin/env python3
"""Bounded live Phase 1F qualification using the production classifier."""

from collections import Counter
from datetime import datetime
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,'.')
from google_books_reference import GoogleBooksArtworkResolver


CASES={
    'one_piece':('One Piece',('Eiichiro Oda',),(1,2,7,8,25,50,57,58,75,100,107,110,111,112,113,114)),
    'bleach':('Bleach',('Tite Kubo',),(1,2,20,21,40,41,60,61,65,73,74)),
    'death_note':('Death Note',('Tsugumi Ohba','Takeshi Obata'),(1,2,6,12)),
    'attack_on_titan':('Attack on Titan',('Hajime Isayama',),(1,5,9,20,34)),
    'one_punch_man':('One-Punch Man',('ONE','Yusuke Murata'),(1,15,25,30,31)),
    'chainsaw_man':('Chainsaw Man',('Tatsuki Fujimoto',),(1,11,12,20,21,22)),
    'berserk':('Berserk',('Kentaro Miura',),(1,10,20,30,40,41,42)),
    'jojolion':('JoJolion',('Hirohiko Araki',),(1,10,20,27)),
}
UNSAFE=re.compile(r'\b(?:omnibus|3[ -]?in[ -]?1|deluxe|library edition|black edition|box set|before the fall|buddy stories|guidebook|novel)\b',re.I)


def context(key,title,creators):
    return {'canonical_work_id':'probe:'+key,'canonical_title':title,'trusted_aliases':(title,),
            'canonical_creators':creators,'canonical_creator_aliases':(),
            'requested_language':'en','edition_profile':'standard',
            'reference_key':'probe|'+key+'|standard'}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    args=parser.parse_args(); report={'contract':'google-books-qualification-v1','created_at':datetime.now().isoformat(),'series':{}}
    totals=Counter(); unsafe=[]
    for key,(title,creators,targets) in CASES.items():
        resolver=GoogleBooksArtworkResolver()
        try:
            result=resolver.resolve(context(key,title,creators),targets)
        except Exception as exc:
            result={'status':'network_failure','error':str(exc),'covers':[],'candidates':[],
                    'target_volumes':[str(v) for v in targets],'network':{'requests':resolver.request_count}}
        counts=Counter(row.get('classification') for row in result.get('candidates') or ())
        for row in result.get('candidates') or ():
            if row.get('accepted') and (row.get('language') != 'en' or UNSAFE.search(' '.join((row.get('title') or '',row.get('subtitle') or '')))):
                unsafe.append({'series':key,'google_volume_id':row.get('google_volume_id'),'title':row.get('title'),'classification':row.get('classification')})
        report['series'][key]={'title':title,'targets':list(targets),'result':result,'classification_counts':dict(counts)}
        totals['target_volumes_checked']+=len(targets)
        totals['requests']+=int((result.get('network') or {}).get('requests') or 0)
        totals['candidates']+=len(result.get('candidates') or ())
        totals['usable_covers']+=len(result.get('covers') or ())
        totals['high_quality_covers']+=sum(row.get('artwork_quality')=='HIGH' for row in result.get('covers') or ())
        totals['exact_standard_manifestations']+=counts['EXACT_STANDARD']
        totals['coverless_exact']+=counts['EXACT_STANDARD_COVERLESS']
        totals['alternate_rejected']+=counts['ALTERNATE_EDITION']+counts['BOX_SET']
        totals['collections_rejected']+=counts['OMNIBUS_COLLECTION']
        totals['foreign_rejected']+=counts['FOREIGN_LANGUAGE']
        totals['spinoffs_rejected']+=counts['SPINOFF']+counts['NOVEL_GUIDEBOOK']
        totals['ambiguous']+=counts['AMBIGUOUS']
    totals['unsafe_promotions']=len(unsafe); report['aggregate']=dict(totals); report['unsafe_promotions']=unsafe
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'artifact':str(path),'aggregate':report['aggregate'],
                      'series':{key:{'status':value['result'].get('status'),'covers':len(value['result'].get('covers') or ()),
                                             'requests':(value['result'].get('network') or {}).get('requests',0)}
                                for key,value in report['series'].items()}},indent=2))


if __name__=='__main__':
    main()
