# MangaNana Reference Metadata Architecture

## Status

**Architecture approved. Wikipedia and BOOK☆WALKER are validated with limitations for specific production roles.**

The validation gates established that MangaNana can safely use:

- **Wikipedia** for explicit publication structure when a supported layout is detected.
- **BOOK☆WALKER** for publication/edition identity, exact UUID-backed volume identity, exact volume covers, series/edition artwork, and Description.
- **AniList / Kitsu** remain the trusted sources for rating, tags, and canonical creator enrichment for now.
- **MangaDex / MangaPill / WeebCentral** remain acquisition sources and the truthful page-source provenance.

Core rule:

> The provider that supplies manga pages does not need to be the provider that supplies the best metadata or artwork.

MangaNana should preserve truthful acquisition provenance while using the best confidently matched metadata and artwork for the same work, edition, volume, or chapter.

---

## Source Roles

### 1. Acquisition Sources

Current sources:

- MangaDex
- MangaPill
- WeebCentral

Primary responsibilities:

- search downloadable manga
- expose languages, chapters, volumes, and page URLs
- download manga pages
- remain the truthful `Source` shown to the user

Acquisition providers are authoritative for pages, not automatically for publication artwork or bibliographic structure.

Provider covers are bootstrap/fallback artwork unless explicitly identified as the exact chapter/volume cover required.

---

### 2. Work Enrichment Sources

Current sources:

- AniList
- Kitsu

Primary responsibilities:

- canonical work identity
- aliases
- creators
- rating
- tags / genres
- Description fallback

These remain optional and non-blocking.

For now, AniList/Kitsu remain authoritative for:

- rating
- tags
- canonical creator enrichment

BOOK☆WALKER tags and creator/publisher metadata are not yet proven strongly enough to replace them.

---

### 3. Publication Structure Source

Validated with limitations:

- Wikipedia

Approved production responsibilities:

- chapter titles
- chapter-to-volume assignments
- volume order
- explicit publication grouping
- explicit special/side-story labeling where safely detectable

Current supported parser pattern:

`graphic-novel-list-explicit-chapter-list-v1`

This supports explicit volume blocks containing explicit numbered/bulleted chapter entries.

Wikipedia must fail closed when:

- the layout is unsupported
- chapter grouping is ambiguous
- a segmented collection would require unsafe aggregation
- explicit publication relationships are not present

Never infer chapter-to-volume boundaries arithmetically.

### Known Wikipedia limitations

- only the validated explicit publication pattern is currently supported
- One Piece-style segmented chapter-list pages are not automatically joined
- transient HTTP 429 responses can occur
- persistent page-identity caching is required for production use
- unsupported layouts must return unknown rather than guessing

---

### 4. Publication Artwork + Catalog Source

Validated with limitations:

- BOOK☆WALKER

Approved production responsibilities:

- publication/edition identity
- stable numeric series identity
- stable UUID-backed exact volume identity
- exact volume covers tied to resolved UUID-backed volume records
- series/edition artwork
- Description

Validated identity path:

```text
search result
-> site-issued UUID
-> canonical de<UUID> product URL
-> numeric series/<id>/list/ publication collection
-> exact volume record
```

BOOK☆WALKER must fail closed when:

- publication identity is ambiguous
- multiple normal volume records remain unresolved
- edition evidence conflicts
- a generic image is not explicitly tied to an exact publication/volume

### Not yet approved from BOOK☆WALKER

Do not treat these as production-authoritative yet:

- tags
- creator replacement
- publisher replacement
- chapter artwork
- automatic traversal of large paginated series such as One Piece

These may be validated later in separate focused work.

---

## Adapter Separation

### `SourceAdapter`

Acquisition:

```text
search()
get_manga()
get_languages()
get_volumes()
get_chapters()
get_pages()
get_cover()
```

### `WorkEnrichmentAdapter`

Work metadata:

```text
match_work()
get_description()
get_rating()
get_tags()
get_aliases()
get_creators()
```

### `PublicationMetadataAdapter`

Publication metadata:

```text
match_publication()
get_chapter_list()
get_chapter_volume_map()
get_volume_list()
get_volume_metadata()
get_volume_covers()
get_chapter_artwork()
get_description()
get_tags()
```

Specific sources implement only the fields they have actually proven safe.

---

## Production Reference Flow

Reference lookup should occur after the user has selected a manga / canonical identity is established.

Preferred flow:

```text
Acquisition search
-> user selects manga
-> canonical work identity established
-> Wikipedia publication lookup
-> BOOK☆WALKER publication lookup
-> cache successful reference results
-> enrich inventory / final outputs
```

Do not issue Wikipedia or BOOK☆WALKER reference requests for every search-result row.

This keeps request counts bounded and reduces rate-limit exposure.

---

## Provenance

Resolved metadata should preserve provenance internally where practical.

Example:

```text
page_source = WeebCentral
description_source = BOOK☆WALKER
chapter_title_source = Wikipedia
chapter_volume_source = Wikipedia
volume_cover_source = BOOK☆WALKER
rating_source = AniList
tags_source = AniList/Kitsu
```

---

## Artwork Authority

Artwork should conceptually preserve:

```text
source
type
publication/edition identity
volume number when applicable
stable record identity
confidence
```

Example:

```text
source: BOOK☆WALKER
type: volume
series_id: 13024
uuid: <site-issued UUID>
volume: 4
confidence: exact
```

Generic provider artwork must never silently propagate across every chapter or volume.

---

## Artwork Policy

Once a confident BOOK☆WALKER publication match exists, BOOK☆WALKER artwork becomes the preferred visual artwork throughout the workflow.

This applies to:

- Selected Manga
- chapter rows
- volume rows
- Final Outputs
- CBZ / Calibre metadata

Search-result rows may continue using provider artwork until a work is selected and BOOK☆WALKER identity has been resolved.

The provider pill still represents the actual acquisition source.

### Selected Manga

1. BOOK☆WALKER edition/series artwork
2. explicitly identified high-confidence provider artwork
3. provider display cover
4. placeholder

### Volume Selection / Volume Output

1. exact BOOK☆WALKER UUID-backed volume cover
2. another explicitly identified exact volume cover
3. BOOK☆WALKER edition/series artwork
4. generic provider cover as last-resort fallback
5. placeholder

### Chapter Selection Thumbnail

1. explicit chapter artwork from an already-validated source
2. exact mapped volume cover, preferably BOOK☆WALKER
3. BOOK☆WALKER edition/series artwork
4. provider display cover
5. placeholder

Do not fetch chapter page 1 solely to decorate the selection UI.

### Chapter CBZ Cover

1. explicit chapter artwork from an already-validated source
2. exact mapped volume cover, preferably BOOK☆WALKER
3. first page of the downloaded chapter
4. BOOK☆WALKER edition/series artwork
5. generic provider cover
6. placeholder

---

## Description Policy

Production priority:

1. BOOK☆WALKER Description when confidently matched
2. AniList
3. Kitsu
4. Wikipedia fallback
5. provider
6. none

Use one Description at a time.

BOOK☆WALKER descriptions can be long.

Selected Manga must:

- keep a readable font size
- use a bounded Description region
- support scrolling or progressive reveal
- never clip the Description
- never shrink text to an uncomfortably small size simply to make it fit

Display label:

`Description`

---

## Tag Policy

Current production priority:

1. AniList / Kitsu according to existing trusted enrichment behavior
2. provider fallback where already supported

BOOK☆WALKER tags are not yet production-authoritative.

Calibre metadata should preserve:

```text
existing user tags
+ MangaNana
+ normalized trusted tags
```

BOOK☆WALKER tags may be promoted later only after a separate focused validation gate.

---

## Chapter-to-Volume Policy

Priority:

1. trustworthy explicit selected-provider mapping
2. trustworthy explicit compatible-provider mapping
3. validated Wikipedia publication mapping
4. future validated publication reference
5. unknown

Never infer volume boundaries from chapter numbers alone.

For mixed selections:

- mapped chapters may form volume CBZs
- unmapped chapters remain standalone
- no selected chapter is dropped

---

## Matching Safety

### Wikipedia

Require:

- confident canonical work/page match
- validated supported structure pattern
- explicit publication grouping

Unsupported layouts fail closed.

### BOOK☆WALKER

Require:

- canonical work evidence
- UUID-backed product identity
- stable series ID
- edition compatibility
- explicit volume identity for exact-volume artwork

Do not attach a publication because it is merely the first search result.

Do not use fuzzy title similarity alone.

---

## Caching

Use persistent separated namespaces:

```text
work_enrichment/
publication_wikipedia/
publication_bookwalker/
provider_search/
provider_display_covers/
resolved_output_covers/
scaled_pixmaps/
```

### Wikipedia cache

Key successful publication structure by stable resolved page identity.

Do not cache transient 429/network failures as valid empty metadata.

### BOOK☆WALKER cache

Key by:

```text
source
series_id
edition identity
artifact type
UUID / volume identity where applicable
```

Do not cache ambiguous matches as success.

Do not store exact-volume artwork under work-only keys.

---

## Failure Behavior

Reference failure never blocks normal MangaNana use.

If Wikipedia fails:

- preserve provider structure
- leave genuinely unknown chapters standalone

If BOOK☆WALKER fails:

- use explicitly identified alternative artwork
- fall back gracefully

No modal is required.

---

## Core Principle

> Use only the fields each reference source has actually proven safe. Preserve acquisition provenance and fail closed whenever publication identity or structure is ambiguous.
