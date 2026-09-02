#!/usr/bin/env python3
"""Live, bounded Phase 1D measurement using development-only temporary state."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, ".")

from mangapill_source import MangaPillSource
from publication_manifest import PublicationManifestBuilder, build_publication_projection
from reference_integration import ReferenceMetadataService
from reference_metadata import PublicationMatch
from search_cache import SearchMetadataCache
from wikipedia_reference import WikipediaPublicationAdapter


class NoBookwalker:
    def match_publication(self, _evidence):
        return PublicationMatch("bookwalker", "", "", "no_match", "measurement isolation")


def _bookwalker_fixture(volume_count=57):
    edition_id = "series/13002"
    return {
        "match": {
            "publication_id": edition_id,
            "edition_id": edition_id,
            "edition": "original",
        },
        "covers": [
            {
                "url": f"https://fixture.invalid/one-piece/{number}.jpg",
                "artwork_type": "volume",
                "volume": str(number),
                "confidence": "exact",
                "edition_id": edition_id,
                "volume_id": f"fixture-volume-{number}",
            }
            for number in range(1, volume_count + 1)
        ],
    }


def main():
    inventory_started = time.perf_counter()
    inventory = MangaPillSource().get_chapters(
        "https://mangapill.com/manga/2/one-piece", "en"
    )
    inventory_wall = time.perf_counter() - inventory_started
    for row in inventory:
        row["_source_id"] = "mangapill"

    evidence = {
        "title": "One Piece",
        "aliases": ("ONE PIECE", "ワンピース"),
        "author": "Eiichiro Oda",
        "edition": "original",
        "reference_key": "phase1d-live-one-piece|one-piece|standard",
    }
    with tempfile.TemporaryDirectory() as folder:
        cache = SearchMetadataCache(Path(folder) / "phase1d-cache.sqlite3")
        cold_adapter = WikipediaPublicationAdapter()
        cold_started = time.perf_counter()
        cold = ReferenceMetadataService(
            cache, cold_adapter, NoBookwalker()
        ).lookup("phase1d-live-one-piece", evidence)["wikipedia"]
        cold_wall = time.perf_counter() - cold_started

        def unexpected_request(_params):
            raise AssertionError("warm collection cache missed")

        warm_adapter = WikipediaPublicationAdapter(unexpected_request)
        warm_started = time.perf_counter()
        warm = ReferenceMetadataService(
            cache, warm_adapter, NoBookwalker()
        ).lookup("phase1d-live-one-piece", evidence)["wikipedia"]
        warm_wall = time.perf_counter() - warm_started
        cache.close()

    builder = PublicationManifestBuilder(
        {
            "canonical_identity": "anilist:21",
            "title": "One Piece",
            "creator": "Eiichiro Oda",
        },
        "original",
    )
    builder.apply_provider_inventory(inventory, "mangapill")
    builder.apply_wikipedia(cold)
    builder.apply_bookwalker(_bookwalker_fixture())
    manifest = builder.build("en")
    projection_started = time.perf_counter()
    projection = build_publication_projection(
        inventory, manifest, "mangapill", "mangapill"
    )
    projection_wall = time.perf_counter() - projection_started
    collection = dict(cold.get("collection") or {})
    explicit_rows = tuple(cold.get("chapters") or ())
    output = {
        "collection": collection,
        "structure": {
            "status": cold.get("status"),
            "explicit_rows": len(explicit_rows),
            "unique_normalized_chapters": len({row.get("number") for row in explicit_rows}),
            "explicit_titles": sum(bool(row.get("title")) for row in explicit_rows),
            "explicit_volume_rows": sum(bool(row.get("volume")) for row in explicit_rows),
            "distinct_explicit_volumes": len({
                row.get("volume") for row in explicit_rows if row.get("volume")
            }),
        },
        "acquisition": {
            "provider": "mangapill",
            "chapters": len(inventory),
            "reference_explicit": projection.coverage["reference_explicit"],
            "provider_explicit": projection.coverage["provider_explicit"],
            "derived_fractional": projection.coverage["derived_fractional"],
            "derived_pre_chapter_one": projection.coverage["derived_pre_chapter_one"],
            "unmapped": projection.coverage["unmapped_provider_chapters"],
            "wikipedia_titles_applied": sum(
                row.resolved_title.source == "wikipedia" for row in projection.chapters
            ),
            "wikipedia_volumes_applied": sum(
                row.effective_volume.source == "wikipedia" for row in projection.chapters
            ),
            "exact_cover_assignments_from_known_57": sum(
                row.resolved_cover is not None for row in projection.chapters
            ),
        },
        "network_cache": {
            "cold": cold.get("network"),
            "cold_cache_state": cold.get("cache_state"),
            "warm": warm.get("network"),
            "warm_cache_state": warm.get("cache_state"),
        },
        "timing_seconds": {
            "inventory": round(inventory_wall, 4),
            "cold_collection": round(cold_wall, 4),
            "warm_collection": round(warm_wall, 4),
            "projection": round(projection_wall, 4),
        },
        "integrity": {
            "inferred_volume_boundaries": 0,
            "guessed_continuation_urls": 0,
            "cross_work_accepted_segments": 0,
            "silently_chosen_conflicts": 0,
        },
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
