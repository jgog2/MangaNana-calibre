#!/usr/bin/env python3
"""Bounded live cold/warm canonical-state invariance measurement."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, ".")

from canonical_identity import edition_identity, group_canonical_results, normalize_identity_text
from enrichment_matching import enrich_content_results, resolve_canonical_work_facts
from enrichment_sources import DEFAULT_ENRICHMENT_REGISTRY
from mangadex_source import MangaDexSource
from mangapill_source import MangaPillSource
from publication_manifest import PublicationManifestBuilder, build_publication_projection
from reference_integration import ReferenceMetadataService, canonical_publication_context
from reference_metadata import PublicationMatch
from search_cache import SearchMetadataCache, final_search_records
from search_ranking import AcquisitionFitness, present_search_candidate, rank_provider_results
from weebcentral_source import WeebCentralSource
from wikipedia_reference import WikipediaPublicationAdapter


class NoBookwalker:
    def match_publication(self, _evidence):
        return PublicationMatch("bookwalker", "", "", "no_match", "measurement isolation")


def provider_key(row):
    return str(row.get("source_id") or ""), str(row.get("id") or row.get("url") or "")


def exact_result(source, query):
    result = source.search(query)
    rows = result.get("rows") or ()
    return next(row for row in rows if normalize_identity_text(row.get("title")) == "bleach")


def context_for(record):
    return canonical_publication_context(record.get("canonical_work_id"), {
        "canonical_title": record.get("canonical_title"),
        "canonical_author": record.get("canonical_author"),
        "canonical_creator_aliases": record.get("canonical_creator_aliases") or (),
        "provider_author": record.get("_provider_native_author") or record.get("author"),
        "identity_confidence": record.get("_canonical_identity_confidence"),
        "edition": edition_identity(record),
    })


def checkpoint(record, wikipedia, projection, order):
    collection = dict(wikipedia.get("collection") or {})
    return {
        "canonical_work_id": record.get("canonical_work_id"),
        "canonical_title": record.get("canonical_title"),
        "creator": record.get("canonical_author"),
        "creator_provenance": record.get("canonical_creator_provenance"),
        "creator_aliases": record.get("canonical_creator_aliases"),
        "aliases": record.get("canonical_aliases"),
        "work_family_id": record.get("work_family_id"),
        "fitness": record.get("_acquisition_fitness"),
        "qualification": record.get("_qualification_status"),
        "ranking_order": order,
        "reference_key": context_for(record).reference_key,
        "wikipedia_status": wikipedia.get("status"),
        "wikipedia_root": (collection.get("root") or {}).get("title"),
        "wikipedia_safe_rows": len(wikipedia.get("chapters") or ()),
        "quarantined_rows": collection.get("quarantined_records"),
        "manifest_rows": len(projection.chapters),
        "coverage": projection.coverage,
        "wikipedia_cache_state": wikipedia.get("cache_state"),
    }


def main():
    query = "Bleach"
    sources = (MangaDexSource(), MangaPillSource(), WeebCentralSource())
    raw = []
    provider_errors = {}
    for source in sources:
        try:
            row = dict(exact_result(source, query))
            row.setdefault("source_id", source.source_id)
            row.setdefault("source_name", source.display_name)
            raw.append(row)
        except Exception as exc:
            provider_errors[source.source_id] = str(exc)

    enrichment_candidates, enrichment_errors = DEFAULT_ENRICHMENT_REGISTRY.search(query)
    enriched = tuple(enrich_content_results(raw, enrichment_candidates))
    overlays = {provider_key(row): row for row in enriched}
    groups = group_canonical_results(raw)
    facts = resolve_canonical_work_facts(groups, overlays)
    canonical = {}
    for group in groups:
        group_key = tuple(sorted(provider_key(row) for row in group.results))
        fact = facts.get(group_key)
        family = "canonical:" + normalize_identity_text(group.display_title) + ":" + edition_identity(group.results[0])
        for row in group.results:
            canonical[provider_key(row)] = {
                "work_family_id": family,
                "canonical_work_id": fact.canonical_work_id if fact else "",
                "canonical_title": fact.canonical_title if fact else group.display_title,
                "canonical_author": fact.creator if fact else "",
                "canonical_creator_provenance": fact.creator_provenance if fact else "",
                "canonical_creator_conflicted": fact.creator_conflicted if fact else False,
                "canonical_creator_aliases": fact.creator_aliases if fact else (),
            }

    pill = MangaPillSource()
    inventory = pill.get_chapters("https://mangapill.com/manga/552/bleach", "en")
    for row in inventory:
        row["_source_id"] = "mangapill"
    presentations = []
    for row in raw:
        overlay = dict(overlays.get(provider_key(row)) or {})
        overlay.update(canonical.get(provider_key(row)) or {})
        direct = row.get("source_id") == "mangapill"
        presentations.append(present_search_candidate(
            row, overlay, AcquisitionFitness.DIRECT if direct else AcquisitionFitness.UNKNOWN,
            "qualified" if direct else "not_measured", len(inventory) if direct else 0,
        ).as_record())
    ranked = tuple(row.result for row in rank_provider_results(query, presentations))
    order = [row.get("source_id") for row in ranked]
    pill_record = next(row for row in ranked if row.get("source_id") == "mangapill")
    context = context_for(pill_record)

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "phase1d2a.sqlite3"
        cache = SearchMetadataCache(path)
        cache.put_query_snapshot("bleach", {
            "provider_candidates": raw,
            "display_results": raw,
            "final_cards": [{"provider_record": row} for row in ranked],
            "final_result_count": len(ranked),
        })
        cold_wikipedia = ReferenceMetadataService(
            cache, WikipediaPublicationAdapter(), NoBookwalker()
        ).lookup(context.reference_key, context.lookup_evidence())["wikipedia"]
        cold_builder = PublicationManifestBuilder({
            "canonical_identity": context.canonical_work_id,
            "title": context.canonical_title,
            "creator": context.canonical_creators[0] if context.canonical_creators else "",
        }, "original")
        cold_builder.apply_provider_inventory(inventory, "mangapill").apply_wikipedia(cold_wikipedia)
        cold_projection = build_publication_projection(
            inventory, cold_builder.build(), "mangapill", "mangapill"
        )
        cold = checkpoint(pill_record, cold_wikipedia, cold_projection, order)
        cache.put_query_snapshot("chainsaw", {
            "provider_candidates": [{"source_id": "mangapill", "id": "chainsaw"}],
            "final_cards": [{"provider_record": {
                "source_id": "mangapill", "id": "chainsaw", "title": "Chainsaw Man",
            }}], "final_result_count": 1,
        })
        cache.close()

        restarted = SearchMetadataCache(path)
        warm_ranked = final_search_records(restarted.get_query_snapshot("bleach").value)
        warm_pill = next(row for row in warm_ranked if row.get("source_id") == "mangapill")
        warm_context = context_for(warm_pill)
        warm_wikipedia = ReferenceMetadataService(
            restarted, WikipediaPublicationAdapter(
                lambda _params: (_ for _ in ()).throw(AssertionError("warm Wikipedia cache missed"))
            ), NoBookwalker()
        ).lookup(warm_context.reference_key, warm_context.lookup_evidence())["wikipedia"]
        warm_builder = PublicationManifestBuilder({
            "canonical_identity": warm_context.canonical_work_id,
            "title": warm_context.canonical_title,
            "creator": warm_context.canonical_creators[0] if warm_context.canonical_creators else "",
        }, "original")
        warm_builder.apply_provider_inventory(inventory, "mangapill").apply_wikipedia(warm_wikipedia)
        warm_projection = build_publication_projection(
            inventory, warm_builder.build(), "mangapill", "mangapill"
        )
        warm = checkpoint(
            warm_pill, warm_wikipedia, warm_projection,
            [row.get("source_id") for row in warm_ranked],
        )
        restarted.close()

    print(json.dumps({
        "provider_errors": provider_errors,
        "enrichment_errors": enrichment_errors,
        "cold": cold,
        "warm_restart_after_chainsaw": warm,
        "semantic_equal": cold == {**warm, "wikipedia_cache_state": cold["wikipedia_cache_state"]},
    }, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
