#!/usr/bin/env python3
"""Bounded live Phase 1D.2 identity and projection measurement."""

from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from canonical_identity import normalize_identity_text
from mangapill_source import MangaPillSource
from publication_manifest import PublicationManifestBuilder, build_publication_projection
from reference_integration import ReferenceMetadataService
from reference_metadata import PublicationMatch
from weebcentral_source import WeebCentralSource
from wikipedia_reference import WikipediaPublicationAdapter


class NoBookwalker:
    def match_publication(self, _evidence):
        return PublicationMatch("bookwalker", "", "", "no_match", "measurement isolation")


def nearby(rows):
    wanted = {"0", "0.8", "88.5", "520.5"}
    return [
        {"chapter": row.get("chapter"), "title": row.get("title"), "id": row.get("id")}
        for row in rows if str(row.get("chapter") or "") in wanted
    ]


def main():
    mangapill = MangaPillSource()
    inventory = mangapill.get_chapters("https://mangapill.com/manga/552/bleach", "en")
    for row in inventory:
        row["_source_id"] = "mangapill"

    adapter = WikipediaPublicationAdapter()
    wikipedia = ReferenceMetadataService(None, adapter, NoBookwalker()).lookup(
        "phase1d2-live-bleach",
        {"title": "Bleach", "author": "Tite Kubo", "edition": "original"},
    )["wikipedia"]
    collection = dict(wikipedia.get("collection") or {})

    builder = PublicationManifestBuilder(
        {"canonical_identity": "bleach", "title": "Bleach", "creator": "Tite Kubo"},
        "original",
    )
    builder.apply_provider_inventory(inventory, "mangapill")
    builder.apply_wikipedia(wikipedia)
    projection = build_publication_projection(
        inventory, builder.build(), "mangapill", "mangapill"
    )

    weeb = {"status": "not_attempted", "chapters": 0, "nearby": []}
    try:
        search = WeebCentralSource().search("Bleach")
        hit = next(
            row for row in search.get("rows") or ()
            if normalize_identity_text(row.get("title")) == "bleach"
        )
        rows = WeebCentralSource().get_chapters(hit["url"], "en")
        weeb = {"status": "ok", "chapters": len(rows), "nearby": nearby(rows)}
    except Exception as exc:
        weeb = {"status": "unavailable", "error": str(exc), "chapters": 0, "nearby": []}

    print(json.dumps({
        "wikipedia": {
            "status": wikipedia.get("status"),
            "raw_records": collection.get("raw_publication_records"),
            "safe_records": collection.get("safe_aggregated_records"),
            "reused_label_records": collection.get("reused_label_records"),
            "quarantined_records": collection.get("quarantined_records"),
            "quarantined_groups": collection.get("quarantined_groups"),
            "accepted_segments": collection.get("accepted_segments"),
            "conflicts": collection.get("conflicts"),
            "distinct_volumes": len({
                row.get("volume") for row in wikipedia.get("chapters") or () if row.get("volume")
            }),
            "explicit_fractional": sorted({
                row.get("number") for row in wikipedia.get("chapters") or ()
                if "." in str(row.get("number") or "")
            }, key=float),
            "explicit_negative": sorted({
                row.get("number") for row in wikipedia.get("chapters") or ()
                if str(row.get("number") or "").startswith("-")
            }, key=float),
            "requests": adapter.request_count,
            "rate_limits": adapter.rate_limit_count,
        },
        "mangapill": {"chapters": len(inventory), "nearby": nearby(inventory)},
        "weebcentral": weeb,
        "projection": {
            **projection.coverage,
            "wikipedia_titles": sum(
                row.resolved_title.source == "wikipedia" for row in projection.chapters
            ),
            "wikipedia_volumes": sum(
                row.effective_volume.source == "wikipedia" for row in projection.chapters
            ),
            "chapter_zero": [
                row.as_row() for row in projection.chapters if row.canonical_key == "0"
            ],
        },
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
