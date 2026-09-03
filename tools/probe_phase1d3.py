#!/usr/bin/env python3
"""Sequential, read-only live characterization for Phase 1D.3."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from canonical_identity import normalize_identity_text
from wikipedia_reference import (
    WikipediaPublicationAdapter,
    _GRAPHIC_LIST,
    _HEADING,
    _NUMBERED_LIST,
    _navigation_targets,
    _publication_index_targets,
    _templates,
    _wikilink_targets,
)


CASES = {
    "naruto": {
        "title": "Naruto", "author": "Masashi Kishimoto",
        "aliases": ("NARUTO",),
    },
    "case-closed": {
        "title": "Case Closed", "author": "Gosho Aoyama",
        "aliases": ("Detective Conan",),
    },
    "hajime-no-ippo": {
        "title": "Hajime no Ippo", "author": "George Morikawa",
        "aliases": (),
    },
    "berserk": {
        "title": "Berserk", "author": "Kentaro Miura",
        "aliases": (),
    },
}

_TEMPLATE_NAME = re.compile(r"\{\{\s*([^|}\n]+)")
_SPECIAL = re.compile(
    r"(?i)(?:^|\b)(?:prologue|pilot|extra|special|bonus|side stor|uncollected|"
    r"deluxe|omnibus|collector|negative)(?:\b|$)"
)


def page_summary(adapter, page, root_title):
    text = page.wikitext
    records = adapter._parse_graphic_lists(page.title, root_title)
    rows = [row for _volume, values in records for row in values]
    templates = []
    for name in _TEMPLATE_NAME.findall(text):
        cleaned = " ".join(name.split())
        if cleaned and cleaned.casefold() not in {value.casefold() for value in templates}:
            templates.append(cleaned)
    links = tuple(dict.fromkeys(
        _navigation_targets(text) + _publication_index_targets(text) + _wikilink_targets(text)
    ))
    structuralish = [
        value for value in links
        if any(token in normalize_identity_text(value) for token in
               ("chapter", "volume", "publication", "episode", "tankobon", "deluxe", "omnibus"))
    ]
    special_lines = [
        " ".join(line.split())[:300] for line in text.splitlines()
        if _SPECIAL.search(line)
    ][:30]
    return {
        "title": page.title,
        "page_id": page.page_id,
        "revision_id": page.revision_id,
        "bytes": len(text.encode("utf-8")),
        "headings": [" ".join(match.group(2).split()) for match in _HEADING.finditer(text)],
        "graphic_novel_lists": len(_templates(text, _GRAPHIC_LIST)),
        "numbered_list_samples": [
            " ".join(block.split())[:900] for block in _templates(text, _NUMBERED_LIST)[:3]
        ],
        "parsed_volumes": len(records),
        "parsed_rows": len(rows),
        "template_names": templates[:50],
        "navigation_targets": list(_navigation_targets(text)),
        "publication_index_targets": list(_publication_index_targets(text)),
        "structuralish_links": structuralish[:60],
        "special_lines": special_lines[:12],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=CASES)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    evidence = {**CASES[args.case], "edition": "original", "identity_confidence": "high"}
    adapter = WikipediaPublicationAdapter()
    started = time.perf_counter()
    match = adapter.match_publication(evidence)
    matched_at = adapter.request_count
    try:
        resolved = adapter.resolve_publication(match) if match.confidence == "confident" else {}
        error = ""
    except Exception as exc:
        resolved = {}
        error = f"{type(exc).__name__}: {exc}"
    collection = resolved.get("collection")
    collection_metadata = collection.metadata() if collection is not None else None
    if collection_metadata:
        collection_metadata["conflict_count"] = len(collection_metadata.get("conflicts") or ())
        collection_metadata["conflicts"] = (collection_metadata.get("conflicts") or ())[:12]
        collection_metadata["quarantine_group_count"] = len(
            collection_metadata.get("quarantined_groups") or ()
        )
        collection_metadata["quarantined_groups"] = [
            {key: value for key, value in row.items() if key != "records"}
            for row in (collection_metadata.get("quarantined_groups") or ())[:15]
        ]
    pages = []
    unique = {}
    for page in adapter._page_cache.values():
        unique[page.page_id] = page
    for page in unique.values():
        pages.append(page_summary(adapter, page, match.title))
    chapters = tuple(resolved.get("chapters") or ())
    volumes = tuple(resolved.get("volumes") or ())
    output = {
        "case": args.case,
        "evidence": evidence,
        "match": getattr(match, "__dict__", {}),
        "status": resolved.get("status"),
        "error": error,
        "structure_page": resolved.get("structure_page"),
        "root_page_id": resolved.get("root_page_id"),
        "root_revision_id": resolved.get("root_revision_id"),
        "collection": collection_metadata,
        "safe_rows": len(chapters),
        "volumes": len({row.volume for row in chapters if row.volume}),
        "identifier_examples": sorted({row.number for row in chapters}, key=str)[:20],
        "special_rows": [row.__dict__ for row in chapters if row.kind != "chapter"][:30],
        "kind_counts": {
            kind: sum(row.kind == kind for row in chapters)
            for kind in sorted({row.kind for row in chapters})
        },
        "leading_zero_examples": [
            row.number for row in chapters
            if re.fullmatch(r"0\d+", row.number or "")
        ][:12],
        "pages": pages,
        "network": {
            "requests": adapter.request_count,
            "match_requests": matched_at,
            "retries": adapter.retry_count,
            "rate_limits": adapter.rate_limit_count,
            "page_cache_entries": len(unique),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        },
    }
    if args.compact:
        output["special_rows"] = [
            {"number": row.number, "title": row.title, "volume": row.volume,
             "kind": row.kind}
            for row in chapters if row.kind != "chapter"
        ][:30]
        output["pages"] = [
            {key: page[key] for key in (
                "title", "page_id", "revision_id", "bytes", "headings",
                "graphic_novel_lists", "parsed_volumes", "parsed_rows",
                "navigation_targets",
            )}
            for page in pages
        ]
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
