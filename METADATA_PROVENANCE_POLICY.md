# MangaNana Metadata Provenance Policy

## Status

This policy reflects the completed validation gates.

Current source status:

| Category | Source | Status |
|---|---|---|
| Acquisition | MangaDex | Active |
| Acquisition | MangaPill | Active |
| Acquisition | WeebCentral | Active |
| Work Enrichment | AniList | Active |
| Work Enrichment | Kitsu | Active |
| Publication Structure | Wikipedia | Validated with limitations |
| Publication Artwork/Catalog | BOOK☆WALKER | Validated with limitations |

Validated does not mean every field is trusted.

Each source may only supply fields that its gate actually proved safe.

---

## Acquisition Provenance

Only acquisition providers determine:

- where pages are downloaded from
- provider URL
- fallback state
- page availability
- available provider language

Reference sources never replace acquisition provenance.

`Source` in the UI always means actual acquisition source.

---

## Description

Priority:

1. BOOK☆WALKER when publication match is confident
2. AniList
3. Kitsu
4. Wikipedia fallback
5. provider
6. none

UI label:

`Description`

BOOK☆WALKER Description is approved for production use.

Long text must remain readable using bounded scrolling/progressive reveal rather than shrinking or clipping.

---

## Rating

Continue trusted existing AniList/Kitsu rating behavior.

BOOK☆WALKER rating is not approved as a replacement.

---

## Tags / Genres

Current production policy:

1. AniList/Kitsu trusted enrichment
2. normalize/dedupe according to existing behavior
3. preserve `MangaNana`

BOOK☆WALKER tags remain unproven for production-authoritative use.

Do not promote them yet.

Calibre:

```text
existing user tags
+ MangaNana
+ normalized trusted work-level tags
```

---

## Creator / Author

Priority:

1. trusted canonical AniList/Kitsu enrichment
2. provider creator
3. none

BOOK☆WALKER creator/publisher display text is visible but not yet proven strongly enough to replace canonical creator enrichment.

Never blindly title-case or reorder names.

---

## Chapter Title

Priority:

1. selected provider explicit title
2. compatible provider explicit title
3. validated Wikipedia title from a supported explicit publication pattern
4. unknown

Do not use unsupported Wikipedia layouts.

---

## Chapter -> Volume

Priority:

1. selected provider explicit mapping
2. compatible provider explicit mapping
3. validated Wikipedia explicit mapping
4. unknown

Never infer ranges.

Wikipedia mapping is valid only when produced by a supported fail-closed pattern.

---

## Selected Manga Artwork

After a confident BOOK☆WALKER publication match:

1. BOOK☆WALKER edition/series artwork
2. explicitly identified high-confidence provider artwork
3. provider display cover
4. placeholder

Before BOOK☆WALKER identity resolves, provider artwork may bootstrap the UI.

---

## Volume Cover

Priority:

1. exact BOOK☆WALKER UUID-backed volume cover
2. another explicitly identified exact volume cover
3. BOOK☆WALKER edition/series artwork
4. generic provider fallback
5. placeholder

A generic provider image must never be applied to all volumes merely because it exists.

An image is an exact volume cover only when tied to a resolved exact volume identity.

---

## Chapter Cover

Final CBZ:

1. explicit chapter artwork from a validated source
2. mapped exact volume cover
3. first downloaded chapter page
4. BOOK☆WALKER edition/series artwork
5. generic provider fallback
6. placeholder

Selection UI:

1. explicit chapter artwork from a validated source
2. mapped exact volume cover
3. BOOK☆WALKER edition/series artwork
4. provider display cover
5. placeholder

Do not fetch page 1 solely for UI decoration.

BOOK☆WALKER chapter artwork remains unproven and should not be treated as authoritative yet.

---

## Wikipedia Validation Rules

Current supported parser:

`graphic-novel-list-explicit-chapter-list-v1`

Required evidence:

- supported publication structure detected
- explicit volume grouping
- explicit chapter entries
- unambiguous main-series scope

Preserve:

- decimal chapter numbers
- ranges
- specials
- provenance

Do not:

- expand ambiguous ranges
- infer missing volume boundaries
- automatically join unsupported segmented chapter-list collections

Unsupported layouts return unknown.

---

## BOOK☆WALKER Validation Rules

Confident publication identity may use:

- canonical work evidence
- site-issued UUID
- canonical `de<UUID>` product URL
- stable numeric `series/<id>/list/` identity
- volume number
- creator/imprint display evidence
- edition/variant context

Exact volume artwork requires:

- resolved series/publication identity
- explicit volume number
- UUID-backed exact product/volume record
- edition compatibility

Ambiguous duplicates fail closed.

Promotional/bundle/related-work rows must not be promoted to exact volume records without compatible evidence.

---

## Conflict Resolution

When sources disagree:

1. choose according to field meaning/source authority
2. preserve trustworthy explicit provider structural data when already good
3. use Wikipedia only for supported explicit structure
4. use BOOK☆WALKER for publication identity/artwork/Description only where confidently matched
5. preserve acquisition provenance independently
6. if confidence is insufficient, do not merge

Examples:

- WeebCentral pages + Wikipedia chapter title: allowed
- WeebCentral pages + Wikipedia volume mapping: allowed
- WeebCentral pages + BOOK☆WALKER exact volume cover: allowed
- BOOK☆WALKER artwork must not change `Source`
- alternate-edition mappings/artwork must not cross incompatible editions

---

## Cache Separation

### Work Cache

May contain:

- canonical identity
- rating
- tags
- aliases
- canonical creators

### Provider Cache

May contain:

- provider title
- provider URL
- provider display cover
- provider-specific cover URL

### Wikipedia Cache

May contain:

- resolved page identity
- supported pattern identity
- chapter titles
- chapter-volume mapping
- volume list/order

Do not cache transient 429/network failures as valid empty results.

### BOOK☆WALKER Cache

May contain:

- series ID
- publication/edition identity
- product UUIDs
- exact volume identities
- edition/series artwork
- exact volume covers
- Description

Cache keys must include publication/edition/volume identity where applicable.

Do not cache ambiguous matches as successful matches.

---

## Preferences

After integration, add default-on independent toggles:

```text
Wikipedia Reference Metadata
BOOK☆WALKER Publication Metadata
```

Turning either off must not break acquisition.

---

## Core Principle

> Each source is trusted only for the fields its validation gate proved safe.
