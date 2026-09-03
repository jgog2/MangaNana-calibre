# MangaBaka Publication / Artwork Validation Report

Date: 2026-09-01  
Scope: bounded source-validation only. No MangaNana workflow, UI, worker,
runtime, cache, packaging, or provider-precedence integration was changed.

## Surface and Method

MangaBaka documents a public JSON HTTP API at `https://api.mangabaka.org/`.
This gate used only that API: `GET /v1/series/search` and one bounded
`GET /v1/series/{id}` detail check. No HTML scraping, browser automation,
authentication, retries, bulk database download, or third-party-provider
request was used.

The v1 response identifies itself as `x-api-stability: stable`. Its published
documentation nevertheless says the schema is not yet version-1.0 stable and
may change additively. The v2 endpoint exposed a different, beta schema, so it
is not used by the isolated prototype or this recommendation.

MangaBaka documents 30 uncached searches/minute and 180 uncached default
GETs/minute, with CDN caching (`cf-cache-status`) and a documented one-day to
seven-day individual-series refresh cadence. The probe remained well below
those limits. The API documentation also requires attribution to MangaBaka and
its underlying providers; any later product proposal must first establish
license/attribution compatibility.

## Stable Identity and Cross-ID Findings

The stable v1 surface provides a numeric MangaBaka series ID, canonical URL,
primary/native/romanized/secondary titles, type, author/artist, publisher,
and a `source` object containing provider IDs. The latter is useful as
*reported identity evidence only*: this gate did not follow, read, or evaluate
any linked provider, and specifically did not research MangaUpdates.

| Control | Exact selected v1 work | Numeric ID | Volume count | Identity confidence |
| --- | --- | ---: | ---: | --- |
| Death Note | `DEATH NOTE` | 1824 | 12 | Confident exact work title |
| Attack on Titan | `ATTACK ON TITAN` | 4024 | 34 | Confident exact work title |
| JoJolion | `JoJo no Kimyou na Bouken: JoJolion` | 1406 | 27 | Confident only with the Part 8/full-title alias; bare `JoJolion` returned no result in the bounded v2 exploratory check |
| One Piece | `ONE PIECE` | 377 | 115 | Confident exact work title |

Search result sets were large (148, 169, 615, and 599 respectively), so a
future implementation must preserve strict exact-title/alias + type checks and
return ambiguous/no-match when those checks do not select exactly one work. It
must not rank related titles, novels, side stories, or edition variants by
display order.

## Publication Structure and Artwork Findings

MangaBaka v1 provides only a *work-level* `final_volume` count. It does not
expose a volume-record list, edition/translation record, per-volume stable ID,
or release/edition language mapping in the checked surface. Therefore it
cannot prove a specific selected volume or distinguish publisher/translation
variants for MangaNana finalization.

The API returns one generic work cover (`cover.raw.url` and derivatives). It
does not state that this is a particular volume, provide front/back roles,
artwork language, edition, volume number, or a separate generic-versus-volume
artwork type. No request ordering was used to infer any of those fields.

- Exact per-volume cover retrieval: unavailable; fail closed.
- Volume/edition language: unavailable; fail closed.
- Front/back cover distinction: unavailable; fail closed.
- Generic work cover: available only as `work_level`, never promoted to a
  selected-volume cover.
- Multi-volume sample: all four controls expose only the numeric count, not a
  list to sample.
- One Piece scale: the selected work reports 115 volumes, but there is no
  volume pagination endpoint in the validated schema. Search pagination exists
  and reports a `next` URL; it is unrelated to a publication inventory.

## Description, Tags, and Metadata Quality

The detail record has a nonempty description and rich structured tag objects
(`name`, hierarchy, spoiler/genre flags, content rating, and weight). It also
has authors, artists, publishers, title aliases, publication dates, and source
IDs. This is useful work-level metadata.

However, description language is not declared by a dedicated field, and the
description itself may quote an upstream source. Tags and descriptions are
therefore not suitable to override explicit provider metadata without a later
provenance and attribution design. The prototype returns their stated values
only; it infers neither language nor trust priority.

## Cache and Failure Rules

Useful persistent-cache keys would include API version, MangaBaka numeric
series ID, resolved canonical URL, artifact kind, and fetch timestamp. Cache
only successful nonempty JSON with the documented schema marker; do not cache
429s, malformed JSON, absent optional fields, or ambiguous identity matches as
successful empty data. Revalidate after the source's stated 1–7-day refresh
window and retain a last-known-good record only as stale fallback with its age
visible to diagnostics.

The supplied isolated prototype is intentionally Calibre-independent and has
fixture coverage for stable IDs/aliases, cross IDs, ambiguity, Attack on Titan
aliasing, JoJolion Part 8 identity, missing optional fields, malformed detail
fail-closed behavior, generic-versus-volume artwork separation, and search
pagination non-following. It contains no production call site.

## Comparison with BOOK☆WALKER

| Capability | MangaBaka stable v1 | Existing BOOK☆WALKER prototype |
| --- | --- | --- |
| Work identity / aliases | Strong numeric work identity and aliases | Strong only after strict catalog/product confirmation |
| Edition / publication identity | No edition record | Confirmed catalog/series identity when unambiguous |
| Exact volume records and covers | Not exposed | UUID-backed records and exact per-card covers when unique |
| Work description and tags | Rich work-level fields, language/provenance caveats | Product description; tags not yet production-authoritative |
| Large inventory | Count only; no volume API | Pagination known but deliberately bounded/unimplemented |

## Recommendation

**Direct MangaBaka vs BOOK☆WALKER: B — companion metadata candidate only.**
MangaBaka is stronger for generic work identity, aliases, descriptions, and
tags, but it cannot replace BOOK☆WALKER for publication-edition identity or
exact volume-cover retrieval.

**Overall gate: DO NOT PROCEED to production integration.** The source is a
promising future work-metadata companion, but the required publication and
artwork evidence is absent. A later, separately authorized integration gate
would need attribution/license approval, schema-version fixtures, explicit
metadata precedence, persistent cache policy, and a strict policy that its
work-level cover never becomes a selected-volume cover.
