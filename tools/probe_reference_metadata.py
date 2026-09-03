"""Run the four bounded live reference-source prototype probes."""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bookwalker_reference import BookwalkerPublicationAdapter
from wikipedia_reference import WikipediaPublicationAdapter


CONTROLS = (
    {'title': 'Death Note', 'aliases': ('デスノート',), 'author': 'Takeshi Obata'},
    {'title': 'Attack on Titan', 'aliases': ('進撃の巨人',), 'author': 'Hajime Isayama'},
    {'title': 'JoJolion', 'aliases': ('ジョジョリオン',), 'author': 'Hirohiko Araki'},
    {'title': 'One Piece', 'aliases': ('ワンピース',), 'author': 'Eiichiro Oda'},
)


def probe(adapter, evidence, methods):
    started=time.monotonic()
    try:
        match=adapter.match_publication(evidence)
        result={'confidence':match.confidence,'title':match.title,'reason':match.reason,
                'requests':adapter.request_count}
        if match.confidence == 'confident':
            for name in methods:
                try:
                    value=getattr(adapter,name)(match)
                    result[name]=len(value) if isinstance(value,(tuple,list,dict)) else bool(value)
                except Exception as exc:
                    result[name + '_error']=str(exc)
            result['requests']=adapter.request_count
    except Exception as exc:
        result={'error':str(exc),'requests':adapter.request_count}
    result['seconds']=round(time.monotonic()-started,2)
    return result


def main():
    output={}
    for evidence in CONTROLS:
        wiki=WikipediaPublicationAdapter()
        bookwalker=BookwalkerPublicationAdapter()
        output[evidence['title']]={
            'wikipedia':probe(wiki,evidence,('get_chapter_list','get_chapter_volume_map','get_volume_list')),
            'bookwalker':probe(bookwalker,evidence,('get_volume_list','get_volume_covers','get_chapter_artwork','get_description','get_tags','get_creators')),
        }
    print(json.dumps(output,ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == '__main__':
    main()
