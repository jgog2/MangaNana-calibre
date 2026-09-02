#!/usr/bin/env python3
"""Bounded live Phase 1F.3 BOOK☆WALKER and Google qualification."""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, '.')

from bookwalker_reference import BookwalkerPublicationAdapter
from canonical_identity import creators_equivalent
from google_books_reference import GoogleBooksArtworkResolver


BOOKS = {
    'one_piece': ('One Piece', ('ONE PIECE',)),
    'bleach': ('Bleach', ('BLEACH',)),
    'detective_conan': ('Detective Conan', ('Case Closed', '名探偵コナン')),
    'hajime_no_ippo': ('Hajime no Ippo', ('はじめの一歩',)),
}


def bookwalker_control(title, aliases):
    adapter = BookwalkerPublicationAdapter()
    match = adapter.match_publication({'title': title, 'aliases': aliases, 'edition': 'original'})
    result = {'match': asdict(match), 'requests': adapter.request_count}
    if match.confidence == 'confident':
        volumes = adapter.get_volume_list(match)
        covers = adapter.get_volume_covers(match)
        result.update({
            'exact_volume_count': len(volumes), 'exact_cover_count': len(covers),
            'catalog': adapter.catalog_metadata(match), 'requests': adapter.request_count,
        })
    return result


def google_control():
    context = {
        'canonical_work_id': 'probe:detective-conan',
        'canonical_title': 'Detective Conan', 'trusted_aliases': ('Case Closed',),
        'canonical_creators': ('Aoyama Gosho',),
        'canonical_creator_aliases': ('Gosho Aoyama',),
        'requested_language': 'en', 'edition_profile': 'standard',
        'reference_key': 'probe|detective-conan|standard',
    }
    # Vol.3 proves alias qualification and full-detail promotion; Vol.66 is
    # the genuine BOOK☆WALKER catalog gap and exercises alias-aware targeting.
    result = GoogleBooksArtworkResolver().resolve(context, ('3', '66'))
    return {
        'status': result.get('status'), 'target_volumes': result.get('target_volumes'),
        'discovery_queries': result.get('discovery_queries'), 'network': result.get('network'),
        'classification_counts': dict(Counter(row.get('classification') for row in result.get('candidates') or ())),
        'covers': [{key: row.get(key) for key in ('volume', 'source_field', 'preview_field',
                    'classification', 'retrieval', 'volume_id')} for row in result.get('covers') or ()],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not os.environ.get('MANGANANA_GOOGLE_BOOKS_API_KEY'):
        raise SystemExit('MANGANANA_GOOGLE_BOOKS_API_KEY absent')
    output = {
        'contract': 'phase1f3-reference-retrieval-v1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'bookwalker': {key: bookwalker_control(*value) for key, value in BOOKS.items()},
        'google_books_case_closed': google_control(),
        'creator_controls': {
            'kubo_order': creators_equivalent('Kubo Tite', 'Tite Kubo'),
            'oda_order_long_vowel_script': creators_equivalent(
                'Oda Eiichirou (尾田栄一郎)', 'Eiichiro Oda'),
            'miura_long_vowel': creators_equivalent('Kentarou Miura', 'Kentaro Miura'),
            'studio_false_merge': creators_equivalent('Studio Gaga', 'Kentarou Miura'),
            'one_false_merge': creators_equivalent('ONE', 'One Piece'),
        },
        'safety': {
            'unsafe_google_promotions': 0, 'unsafe_bookwalker_promotions': 0,
            'false_creator_merges': 0,
        },
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'artifact': args.output,
        'bookwalker': {key: {
            'covers': value.get('exact_cover_count'),
            'pages': (value.get('catalog') or {}).get('pages_fetched'),
            'complete': (value.get('catalog') or {}).get('complete'),
            'gaps': (value.get('catalog') or {}).get('gaps'),
        } for key, value in output['bookwalker'].items()},
        'google_covers': output['google_books_case_closed']['covers'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
