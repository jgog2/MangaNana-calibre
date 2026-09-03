"""Bounded live controls for the Wikipedia publication-structure salvage gate."""

import json
import sys

sys.path.insert(0, '.')

from wikipedia_reference import WikipediaPublicationAdapter


CONTROLS = ('Attack on Titan', 'Death Note', 'JoJolion', 'Chainsaw Man', 'One-Punch Man')


def probe(title):
    adapter = WikipediaPublicationAdapter()
    match = adapter.match_publication({'title': title})
    resolved = adapter.resolve_publication(match) if match.confidence == 'confident' else {}
    page = str(resolved.get('structure_page') or '')
    chapters = tuple(resolved.get('chapters') or ())
    volumes = tuple(resolved.get('volumes') or ())
    return {
        'query': title,
        'matched_page': match.title,
        'match_confidence': match.confidence,
        'structure_page': page,
        'structure_status': resolved.get('status'),
        'chapter_rows': len(chapters),
        'chapter_titles': sum(bool(row.title) for row in chapters),
        'chapter_volume_rows': sum(bool(row.volume) for row in chapters),
        'volume_rows': len(volumes),
        'special_rows': sum(row.kind == 'special' for row in chapters),
        'range_rows': sum(row.kind == 'range' for row in chapters),
        'requests': adapter.request_count,
        'retries': adapter.retry_count,
        'rate_limits': adapter.rate_limit_count,
    }


if __name__ == '__main__':
    controls = tuple(sys.argv[1:]) or CONTROLS
    results = []
    for title in controls:
        try:
            result = probe(title)
        except Exception as exc:
            result = {'query': title, 'error': str(exc)}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    print(json.dumps(results, indent=2, ensure_ascii=False))
