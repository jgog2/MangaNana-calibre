# MangaUpdates Publication-Structure Validation Report

Date: 2026-09-01  
Scope: targeted API validation only. No MangaNana production code, UI,
Wikipedia behavior, acquisition provider, cache, ZIP, or integration changed.

## Decision

**DO NOT PROCEED.** MangaUpdates' public v1 API safely establishes work
identity and work metadata, but the validated surface does not expose a
historical per-series release collection containing both an explicit chapter
and an explicit volume. Without that primary evidence, MangaNana cannot
measure duplicate agreement, detect conflicts, compare mappings to Wikipedia,
or safely map any chapter to a volume.

The gate intentionally stopped here. It did not scrape MangaUpdates HTML,
automate a browser, crawl release pages, use account functionality, infer
boundaries, or query any third-party aggregator.

## API / Access Surface

Observed public keyless API base: `https://api.mangaupdates.com/v1`.

| Capability | Public API result | Structural suitability |
| --- | --- | --- |
| Series search | `POST /series/search` accepts `search`, `stype`, `perpage`; returns `total_hits`, pagination fields, and result records | Suitable for conservative candidate discovery only |
| Series detail | `GET /series/{series_id}` returns the stable numeric ID, titles/aliases, type, creators, related series, publication metadata, and `latest_chapter` | Suitable for work identity only |
| Historical release records by series | Not present in the validated detail record and no documented public endpoint was established | Unavailable; required evidence missing |
| Release record fields (chapter + volume + group/release/date) | Not available through the validated public series surface | Unavailable |
| Authentication | Search/detail worked anonymously; user-list/account endpoints are outside scope | No credential was used |
| Rate limit / retry policy | No official rate limit or retry policy was discoverable from the inspected public surface | Treat as undocumented; a future design would need conservative throttling and backoff |

The series detail response for Death Note contains no `releases` collection or
volume count. Its exposed `latest_chapter` is a work-level progress field, not
chapter-level publication evidence. A successful `OPTIONS /releases` response
did not declare a usable API method or schema. It is not evidence of a
documented historical-release API.

## Four-title Identity Results

| Control | MangaUpdates series ID | Evidence | Confidence / caveat |
| --- | ---: | --- | --- |
| Death Note | 3479935384 | Exact `Death Note`, type `Manga` | Confident |
| Attack on Titan | 23393951235 | Exact canonical alias `Shingeki no Kyojin`, type `Manga` | Confident after alias search; an English-title search was too broad to select safely |
| JoJolion | 49100542773 | `JoJo no Kimyou na Bouken Part 8: JoJolion`, type `Manga` | Confident Part 8 candidate; requires the full/Part 8 alias to avoid other JoJo works |
| One Piece | 55099564912 | Exact `One Piece`, type `Manga` | Confident |

Search result sets are extremely broad for several controls (Death Note: 3,464;
Attack on Titan: at least 10,000; One Piece: at least 10,000). A future
identity adapter would need exact canonical-title/alias and type checks, plus
creator/related-series evidence as applicable; it must never choose the first
result or use fuzzy similarity alone.

## Release Evidence and Consensus Model

No validated API response supplied release observations with both a chapter and
a volume. Consequently, for every control:

- release records examined: 0
- chapters with explicit volume evidence: 0
- single-evidence mappings: 0
- consensus mappings: 0
- conflicting mappings: 0
- earliest/latest mapped chapter: unknown
- group/release identity, release date, language, duplicate semantics: unknown

The appropriate conceptual resolver remains deliberately unused:

| Observation state | Result |
| --- | --- |
| No explicit chapter+volume observations | `no_evidence` / unknown |
| One explicit observation | `single_evidence`, not Wikipedia-equivalent |
| Multiple independent observations agreeing | `consensus` |
| Multiple explicit volume values | `conflict`, fail closed |

No volume was inferred from release ordering, dates, neighboring chapters,
ranges, work-level totals, or the `latest_chapter` field. Existing
`normalize_chapter_number` semantics would preserve normalized numeric labels
(`1`, `01`, `001` → `1`), retain decimals, and reject specials/ranges as normal
chapter identifiers if an evidence endpoint were later validated.

## Wikipedia Benchmark

| Control | Existing validated Wikipedia structure | MangaUpdates explicit mappings | Overlap / agreements / conflicts | Agreement |
| --- | --- | ---: | --- | --- |
| Death Note | 108 chapter rows, 12 volumes | 0 | 0 / 0 / 0 | N/A (no comparable mappings) |
| Attack on Titan | 139 explicit main-series rows | 0 | 0 / 0 / 0 | N/A (no comparable mappings) |
| JoJolion | Existing validated explicit structure, including preserved ranges/decimals | 0 | 0 / 0 / 0 | N/A (no comparable mappings) |

Zero overlap is not a negative agreement score; it is the absence of the
chapter-volume evidence required to run the trust test. Wikipedia remains the
only validated publication-structure source in the current baseline.

## One Piece Coverage

One Piece resolves safely to series ID 55099564912 and has a large result set,
but the validated API provides no bounded series-release history or chapter
filter. Therefore no early/mid/late range was requested and no release history
was crawled. Later-chapter coverage is **0 proven mappings**, so MangaUpdates
does not currently fill Wikipedia's intentionally unsupported segmented-list
gap.

## Operations and Future Cache Considerations

Bounded live cost for this gate: six public search requests, one series-detail
request, and one capability check. Search responses include `page` and
`per_page`, but neither yields per-series structural evidence. Persistent
caching could be practical for work identity only, keyed by MangaUpdates series
ID and canonical URL. It is not justified for structural mappings because no
such mappings were obtained.

If a later official endpoint is documented, its cache records must retain:
series ID, normalized chapter key, explicitly supplied volume, release ID,
group identity where available, release date/language, fetch time, and the
derived consensus/conflict state. Transient errors, ambiguous identities, and
conflicts must never be cached as a resolved volume mapping. A last-known-good
consensus would need invalidation on new conflict and periodic refresh for
ongoing works.

## MangaUpdates vs Wikipedia

Wikipedia is publication-oriented and already validated for one conservative,
explicit chapter-to-volume pattern. Its known limitations are segmented works
such as One Piece and rate-limit/cache sensitivity.

MangaUpdates' public API is better suited to work identity and broad community
metadata in this gate. It did not demonstrate the explicit chapter+volume
release evidence, duplicate provenance, conflict detection, or bounded
historical coverage needed to serve as a secondary structural source.

Recommendation: **D — not adopted as a publication-structure source.** A
future gate may be reopened only if MangaUpdates documents a public, bounded,
per-series historical-release endpoint with explicit chapter and volume fields
and enough provenance to measure duplicate independence.
