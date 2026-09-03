#!/usr/bin/env python3
"""Bounded diagnostics for explicitly linked Wikipedia chapter-list pages."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

sys.path.insert(0, ".")

from wikipedia_reference import WikipediaPublicationAdapter, _navigation_targets


_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def _explicit_chapter_links(wikitext: str, work_title: str) -> tuple[str, ...]:
    adapter = WikipediaPublicationAdapter(request_json=lambda _params: {})
    links = []
    raw_targets = tuple(_navigation_targets(wikitext)) + tuple(_WIKILINK.findall(wikitext))
    for target in raw_targets:
        title = " ".join(target.replace("_", " ").split())
        if adapter._is_related_chapter_page(work_title, title):
            links.append(title)
    return tuple(dict.fromkeys(links))


def characterize(work_title: str, index_title: str, delay: float = 1.5) -> dict:
    adapter = WikipediaPublicationAdapter()
    original = adapter._request_json

    def paced_request(params):
        if adapter.request_count:
            time.sleep(delay)
        return original(params)

    adapter._request_json = paced_request
    index_data = adapter._query(
        action="parse", page=index_title, prop="wikitext|revid", redirects=1
    )
    index = index_data.get("parse") or {}
    index_text = str((index.get("wikitext") or {}).get("*") or "")
    candidates = _explicit_chapter_links(index_text, work_title)

    segments = []
    for title in candidates:
        data = adapter._query(
            action="parse", page=title, prop="wikitext|revid", redirects=1
        )
        page = data.get("parse") or {}
        text = str((page.get("wikitext") or {}).get("*") or "")
        adapter._wikitext_cache[title] = text
        records = adapter._parse_graphic_lists(title, work_title)
        rows = [row for _volume, chapter_rows in records for row in chapter_rows]
        volume_numbers = tuple(dict.fromkeys(volume.number for volume, _rows in records))
        segments.append(
            {
                "title": str(page.get("title") or title),
                "pageid": page.get("pageid"),
                "revid": page.get("revid"),
                "graphic_novel_lists": len(records),
                "explicit_rows": len(rows),
                "first_key": rows[0][0] if rows else "",
                "last_key": rows[-1][0] if rows else "",
                "explicit_volumes": len(volume_numbers),
                "first_volume": volume_numbers[0] if volume_numbers else "",
                "last_volume": volume_numbers[-1] if volume_numbers else "",
                "explicit_titles": sum(bool(row[1]) for row in rows),
                "special_rows": sum(row[2] == "special" for row in rows),
                "range_rows": sum(row[2] == "range" for row in rows),
            }
        )
    return {
        "work_title": work_title,
        "index": {
            "title": index.get("title"),
            "pageid": index.get("pageid"),
            "revid": index.get("revid"),
        },
        "explicit_candidates": len(candidates),
        "segments": segments,
        "requests": adapter.request_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work_title")
    parser.add_argument("index_title")
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()
    print(
        json.dumps(
            characterize(args.work_title, args.index_title, args.delay),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
