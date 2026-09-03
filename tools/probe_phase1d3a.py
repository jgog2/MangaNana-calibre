#!/usr/bin/env python3
"""Bounded live qualification for Phase 1D.3A identity and multiplicity repairs."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, ".")
if hasattr(sys.stdout,"reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from canonical_identity import edition_identity, group_canonical_results, normalize_identity_text
from cross_source_fallback import build_cross_source_plan, normalize_chapter_number
from enrichment_matching import enrich_content_results, resolve_canonical_work_facts
from enrichment_sources import AniListAdapter, DEFAULT_ENRICHMENT_REGISTRY, EnrichmentRegistry
from inventory_comparison import inspect_source_inventory
from mangadex_source import MangaDexSource
from mangapill_source import MangaPillSource
from publication_manifest import PublicationManifestBuilder, build_publication_projection
from reference_integration import ReferenceMetadataService, canonical_publication_context
from reference_metadata import PublicationMatch
from search_cache import (
    PROVIDER_MAPPING_CONTRACT, QUERY_SNAPSHOT_CONTRACT, SEARCH_ALGORITHM_VERSION,
    SearchMetadataCache, final_search_records,
)
from search_ranking import AcquisitionFitness, present_search_candidate
from source_registry import SourceRegistry
from weebcentral_source import WeebCentralSource
from wikipedia_reference import WikipediaPublicationAdapter


# Read-only diagnostic fixtures for canonical cards already verified in the
# user's Phase 1D.3 cache. They are never used by production search logic.
QUALIFIED_DIRECT_REFS={
    ("mangadex","Berserk"):
        "https://mangadex.org/title/801513ba-a712-498c-8f57-cae55b38cc92",
}


class NoBookwalker:
    def match_publication(self, _evidence):
        return PublicationMatch("bookwalker", "", "", "no_match", "qualification isolation")


def provider_key(row):
    return str(row.get("source_id") or ""), str(row.get("id") or row.get("url") or "")


def exact_result(source, query):
    rows=tuple((source.search(query) or {}).get("rows") or ())
    key=normalize_identity_text(query)
    exact=[row for row in rows if normalize_identity_text(row.get("title")) == key]
    if not exact:
        direct=QUALIFIED_DIRECT_REFS.get((source.source_id,query))
        if direct:
            metadata=source.get_manga(direct,"en")
            exact=[{
                "source_id":source.source_id,"source_name":source.display_name,
                "id":metadata.get("uuid") or source.parse_manga_ref(direct),"url":direct,
                "title":metadata.get("title") or query,"full_title":metadata.get("title") or query,
                "alternate_titles":metadata.get("alternate_titles") or (),
                "author":metadata.get("author") or "","year":metadata.get("year"),
            }]
        else:
            raise RuntimeError(f"{source.display_name} returned no exact {query!r} result")
    row=dict(exact[0]); row.setdefault("source_id",source.source_id)
    row.setdefault("source_name",source.display_name)
    return row


def final_cards(raw,candidates):
    enriched=tuple(enrich_content_results(raw,candidates))
    overlays={provider_key(row):dict(row) for row in enriched}
    groups=group_canonical_results(raw)
    facts=resolve_canonical_work_facts(groups,overlays)
    canonical={}
    for group in groups:
        group_key=tuple(sorted(provider_key(row) for row in group.results))
        fact=facts.get(group_key)
        family="canonical:"+normalize_identity_text(group.display_title)+":"+edition_identity(group.results[0])
        for row in group.results:
            canonical[provider_key(row)]={
                "work_family_id":family,
                "canonical_work_id":fact.canonical_work_id if fact else "",
                "canonical_title":fact.canonical_title if fact else group.display_title,
                "canonical_author":fact.creator if fact else "",
                "canonical_creators":fact.creators if fact else (),
                "canonical_creator_provenance":fact.creator_provenance if fact else "",
                "canonical_creator_conflicted":fact.creator_conflicted if fact else False,
                "canonical_creator_aliases":fact.creator_aliases if fact else (),
            }
    cards=[]
    for row in raw:
        overlay=dict(overlays.get(provider_key(row)) or {})
        overlay.update(canonical.get(provider_key(row)) or {})
        cards.append(present_search_candidate(
            row,overlay,AcquisitionFitness.DIRECT,"qualified",0,
        ).as_record())
    return tuple(cards)


def cohort_for(cards,selected_source="mangapill"):
    selected=next(row for row in cards if row.get("source_id") == selected_source)
    key=provider_key(selected)
    group=next(group for group in group_canonical_results(cards)
               if key in {provider_key(row) for row in group.results})
    return tuple(row.get("source_id") for row in group.results)


def context_for(card):
    return canonical_publication_context(card.get("canonical_work_id"),{
        "canonical_title":card.get("canonical_title"),
        "canonical_author":card.get("canonical_author"),
        "canonical_creators":card.get("canonical_creators") or (),
        "canonical_creator_aliases":card.get("canonical_creator_aliases") or (),
        "provider_author":card.get("_provider_native_author") or card.get("author"),
        "identity_confidence":card.get("_canonical_identity_confidence"),
        "edition":edition_identity(card),
    })


def projection_for(inventory,wikipedia,work_id,title):
    builder=PublicationManifestBuilder({"canonical_identity":work_id,"title":title},"original")
    by_source={}
    for row in inventory:
        by_source.setdefault(str(row.get("_source_id") or "provider"),[]).append(row)
    for source,rows in by_source.items():
        builder.apply_provider_inventory(rows,source)
    builder.apply_wikipedia(wikipedia)
    return build_publication_projection(inventory,builder.build(),"mangapill","mangapill")


def qualify(query,sources,registry,cache,enrichment_registry=DEFAULT_ENRICHMENT_REGISTRY):
    raw=[]; provider_errors={}
    for source in sources:
        try:
            raw.append(exact_result(source,query))
        except Exception as exc:
            provider_errors[source.source_id]=str(exc)
    candidates,enrichment_errors=enrichment_registry.search(query)
    cards=final_cards(raw,candidates)
    selected=next(row for row in cards if row.get("source_id") == "mangapill")
    context=context_for(selected)
    cold_cohort=cohort_for(cards)
    cache.put_query_snapshot(query,{
        "provider_candidates":raw,"final_cards":[{"provider_record":row} for row in cards],
        "final_result_count":len(cards),
    })
    warm_cards=final_search_records(cache.get_query_snapshot(query).value)
    warm_cohort=cohort_for(warm_cards)

    inventories=[]
    for card in cards:
        source=registry.get(card.get("source_id"))
        inventories.append(inspect_source_inventory(source,card,"en","chapter"))
    primary=next(row for row in inventories if row.source_id == "mangapill")
    plan=build_cross_source_plan(inventories,registry,primary=primary,workflow="chapter")
    acquisition=[]
    for item in plan.items:
        row=dict(item.reference); row["_source_id"]=item.source_id
        acquisition.append(row)
    wikipedia=ReferenceMetadataService(
        cache,WikipediaPublicationAdapter(),NoBookwalker()
    ).lookup(context.reference_key,context.lookup_evidence())["wikipedia"]
    projection=projection_for(acquisition,wikipedia,context.canonical_work_id,context.canonical_title)
    counts=Counter(normalize_chapter_number(row.get("chapter")) for row in acquisition)
    duplicate_keys=tuple(sorted((key for key,count in counts.items() if key and count > 1),key=float))
    duplicate_rows=[row for row in projection.chapters if row.canonical_key in duplicate_keys]
    candidate_ids=sorted(f"{row.service}:{row.external_id}" for row in candidates)
    return {
        "query":query,"provider_errors":provider_errors,"enrichment_errors":enrichment_errors,
        "external_candidate_ids":candidate_ids,
        "canonical_title":context.canonical_title,"canonical_work_id":context.canonical_work_id,
        "canonical_creators":context.canonical_creators,"reference_key":context.reference_key,
        "cohort":{"cold":cold_cohort,"warm":warm_cohort},
        "inventories":{row.source_id:row.chapter_count for row in inventories},
        "wikipedia":{"status":wikipedia.get("status"),
                     "root":((wikipedia.get("collection") or {}).get("root") or {}).get("title"),
                     "safe_rows":len(wikipedia.get("chapters") or ()),
                     "cache_state":wikipedia.get("cache_state")},
        "projection":projection.coverage,
        "duplicate_keys":duplicate_keys,
        "duplicate_rows":len(duplicate_rows),
        "duplicate_borrowed_titles":sum(
            row.resolved_title.present and row.resolved_title.source != row.acquisition_provider
            for row in duplicate_rows
        ),
        "duplicate_borrowed_volumes":sum(
            row.effective_volume.present and row.effective_volume.source != row.acquisition_provider
            for row in duplicate_rows
        ),
        "cards":cards,"acquisition":acquisition,"wikipedia_payload":wikipedia,
    }


def compact(result):
    return {key:value for key,value in result.items()
            if key not in ("cards","acquisition","wikipedia_payload")}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--case",choices=("all","ippo","berserk"),default="all")
    parser.add_argument("--without-kitsu",action="store_true")
    args=parser.parse_args()
    output_dir=Path(r"C:\MangaNana-Dev\Test-Data")
    output_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    cache_path=output_dir/f"phase1d3a-qualification-{stamp}.sqlite3"
    report_path=output_dir/f"phase1d3a-qualification-{stamp}.json"
    sources=(MangaDexSource(),MangaPillSource(),WeebCentralSource())
    registry=SourceRegistry(sources)
    enrichment_registry=(EnrichmentRegistry((AniListAdapter(),))
                         if args.without_kitsu else DEFAULT_ENRICHMENT_REGISTRY)
    cache=SearchMetadataCache(cache_path)
    results=[]
    if args.case in ("all","ippo"):
        results.append(("ippo",qualify(
            "Hajime no Ippo",sources,registry,cache,enrichment_registry
        )))
    if args.case in ("all","berserk"):
        results.append(("berserk",qualify(
            "Berserk",sources,registry,cache,enrichment_registry
        )))
    cache.close()
    restarted=SearchMetadataCache(cache_path)
    for _name,result in results:
        cards=final_search_records(restarted.get_query_snapshot(result["query"]).value)
        result["cohort"]["restart"]=cohort_for(cards)
        context=context_for(next(row for row in cards if row.get("source_id") == "mangapill"))
        warm=ReferenceMetadataService(
            restarted,WikipediaPublicationAdapter(
                lambda _params: (_ for _ in ()).throw(AssertionError("restart cache missed"))
            ),NoBookwalker()
        ).lookup(context.reference_key,context.lookup_evidence())["wikipedia"]
        result["wikipedia"]["restart_cache_state"]=warm.get("cache_state")
        restart_projection=projection_for(
            result["acquisition"],warm,context.canonical_work_id,context.canonical_title
        )
        result["restart_projection"]=restart_projection.coverage
    restarted.close()

    by_name=dict(results)
    berserk=by_name.get("berserk")
    dex=(next((row for row in berserk["cards"] if row.get("source_id") == "mangadex"),None)
         if berserk else None)
    if dex and berserk:
        dex_inventory=inspect_source_inventory(registry.get("mangadex"),dex,"en","chapter")
        dex_rows=[dict(row,_source_id="mangadex") for row in dex_inventory.chapter_records]
        dex_projection=projection_for(
            dex_rows,berserk["wikipedia_payload"],berserk["canonical_work_id"],berserk["canonical_title"]
        )
        direct={"chapters":len(dex_rows),"projection":dex_projection.coverage}
    elif berserk:
        direct={"status":"unavailable","error":berserk["provider_errors"].get("mangadex","")}
    else:
        direct={"status":"not_requested"}
    report={
        "cache_path":str(cache_path),"contracts":{
            "query_snapshot":QUERY_SNAPSHOT_CONTRACT,"search_algorithm":SEARCH_ALGORITHM_VERSION,
            "provider_mapping":PROVIDER_MAPPING_CONTRACT,"wikipedia_parser":WikipediaPublicationAdapter.parser_version,
        },
        **{name:compact(result) for name,result in results},
        "berserk_direct_mangadex":direct,
    }
    report_path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    report["report_path"]=str(report_path)
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__ == "__main__":
    main()
