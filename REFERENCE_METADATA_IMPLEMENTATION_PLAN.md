# MangaNana Reference Metadata Implementation Plan

## Status

The source-validation phase is complete enough to begin a narrow production integration.

Results:

### Wikipedia

Recommendation:

**PROCEED WITH LIMITATIONS**

Validated:

- confident work/page matching for multiple controls
- reusable explicit parser pattern
- chapter titles
- explicit chapter-to-volume mapping
- volume order/grouping
- decimal/range/special preservation
- fail-closed unsupported behavior

Current supported pattern:

`graphic-novel-list-explicit-chapter-list-v1`

Known limitations:

- One Piece-style segmented lists are not automatically aggregated
- unsupported layouts fail closed
- transient HTTP 429 responses require bounded use + persistent caching

### BOOK☆WALKER

Recommendation:

**PROCEED WITH LIMITATIONS**

Validated:

- stable site-issued UUID product identity
- canonical `de<UUID>` product URLs
- stable numeric `series/<id>/list/` publication identity
- edition/variant discrimination for the tested controls
- exact UUID-backed volume identity
- exact volume-cover association
- edition/series artwork
- Description

Not yet validated for production-authoritative use:

- tags
- creator replacement
- publisher replacement
- chapter artwork
- automatic traversal of large paginated series

---

## Immediate Next Step

Run a **narrow production integration pass**.

Do not add every possible reference feature at once.

Approved first integration scope:

1. run Wikipedia after a manga has been selected / canonical identity established
2. run BOOK☆WALKER after a manga has been selected / canonical identity established
3. persist successful reference metadata
4. apply safe Wikipedia chapter titles
5. apply safe Wikipedia chapter->volume mappings
6. apply BOOK☆WALKER edition/series artwork
7. apply BOOK☆WALKER exact UUID-backed volume covers
8. apply BOOK☆WALKER Description
9. preserve acquisition `Source`
10. fail closed and preserve existing behavior whenever reference matching fails

Explicitly out of scope for this first integration:

- BOOK☆WALKER tags
- BOOK☆WALKER creator replacement
- BOOK☆WALKER publisher replacement
- BOOK☆WALKER chapter artwork
- One Piece Wikipedia multi-page aggregation
- One Piece BOOK☆WALKER full catalog traversal
- broad source discovery
- image-processing features
- device simulation
- Empress work

---

## Production Reference Timing

Do not run reference lookups for every Search Results row.

Preferred flow:

```text
Search providers
-> user selects manga
-> canonical identity established
-> Wikipedia reference lookup
-> BOOK☆WALKER identity/reference lookup
-> cache
-> enrich selected inventory and final outputs
```

This reduces unnecessary requests and helps avoid Wikipedia rate limiting.

---

## Phase 1 — Integrate Wikipedia Structure

Use the existing validated prototype.

Requirements:

- preserve supported parser identity
- attach titles/mappings only when extraction confidence is valid
- fail closed on unsupported layouts
- never infer volume boundaries
- preserve decimal/special/range representations
- do not auto-aggregate unsupported One Piece segmented pages

Apply publication structure to:

- chapter inventory metadata
- volume-planning logic
- Final Outputs naming/grouping where existing architecture already consumes chapter metadata

Do not rewrite unrelated chapter workflow.

---

## Phase 2 — Integrate BOOK☆WALKER Identity + Artwork + Description

Use the validated identity chain:

```text
search
-> UUID
-> canonical product
-> series ID
-> exact volume identity
```

Approved fields:

- publication/edition identity
- edition/series artwork
- exact UUID-backed volume cover
- Description

Requirements:

- ambiguous publication matches fail closed
- promotional/duplicate/related-work rows are not accepted as exact volumes without compatible evidence
- exact volume artwork must remain tied to exact volume identity
- generic images must not be promoted to volume artwork
- acquisition Source remains unchanged

---

## Phase 3 — Shared Artwork Resolver

Use one shared resolver across Selected Manga, chapter/volume rows, Final Outputs, CBZ metadata, and Calibre metadata.

### Selected Manga

```text
BOOK☆WALKER edition/series artwork
-> high-confidence provider artwork
-> provider display cover
-> placeholder
```

### Volume Row / Volume CBZ

```text
BOOK☆WALKER exact UUID-backed volume cover
-> another explicitly identified exact volume cover
-> BOOK☆WALKER edition/series artwork
-> generic provider fallback
-> placeholder
```

### Chapter Selection UI

```text
validated explicit chapter artwork
-> exact mapped volume cover
-> BOOK☆WALKER edition/series artwork
-> provider display cover
-> placeholder
```

### Chapter CBZ

```text
validated explicit chapter artwork
-> exact mapped volume cover
-> first downloaded chapter page
-> BOOK☆WALKER edition/series artwork
-> generic provider fallback
-> placeholder
```

Final Outputs preview must match the final written cover.

---

## Phase 4 — Description UI

Production priority:

```text
BOOK☆WALKER
-> AniList
-> Kitsu
-> Wikipedia
-> provider
-> none
```

Selected Manga must:

- keep readable font size
- use a bounded Description region
- allow scrolling/progressive reveal
- never clip long BOOK☆WALKER descriptions
- never shrink Description text to unreadable size

Display label:

`Description`

---

## Phase 5 — Caching

Persist successful reference metadata.

### Wikipedia

Key by stable resolved page identity.

Cache:

- parser pattern
- chapter titles
- chapter-volume mappings
- volume order

Never cache transient 429/network failures as successful empty data.

### BOOK☆WALKER

Key by:

```text
series_id
edition identity
artifact type
UUID / exact volume identity
```

Cache:

- publication identity
- edition/series artwork
- exact volume covers
- Description

Rules:

- no exact volume cover under work-only keys
- no ambiguous match cached as success
- transient failures remain retryable
- failed artwork must not overwrite valid artwork
- later normal searches should recover without Clear Cache

---

## Phase 6 — Preferences

After the first integration is stable, add default-on toggles:

```text
Wikipedia Reference Metadata
BOOK☆WALKER Publication Metadata
```

Disabling either:

- disables that lookup
- preserves acquisition behavior
- does not erase already-good provider metadata
- does not change Source provenance

This may be done in the same integration pass only if it is localized and does not expand scope materially.

---

## Focused Acceptance Matrix

### Death Note

Verify:

- Wikipedia fills chapter titles beyond current provider coverage
- Wikipedia supplies explicit chapter->volume mapping
- BOOK☆WALKER publication identity resolves
- BOOK☆WALKER exact volume covers appear on mapped volume outputs
- BOOK☆WALKER Description appears readably
- acquisition provider remains Source

### Attack on Titan

Verify:

- main-series Wikipedia scope excludes spin-offs
- exact volume structure remains conservative
- BOOK☆WALKER avoids spin-offs/omnibus/color/promotional contamination
- exact volume artwork remains tied to exact volume identity

### JoJolion

Verify:

- existing good MangaDex structure is not made worse
- Wikipedia only fills/validates safe explicit fields
- BOOK☆WALKER matches Part 8 rather than other JoJo parts/editions
- exact volume artwork remains correct

### One Piece

Verify:

- unsupported Wikipedia segmented aggregation fails closed
- BOOK☆WALKER does not crawl the full paginated catalog unnecessarily
- a representative exact-volume identity path remains safe
- existing provider behavior continues when reference coverage is incomplete

---

## Focused Validation Strategy

During active integration:

- run only relevant reference/chapter/output/cache/UI tests
- compile touched modules
- build one dev ZIP only when the targeted integration is ready for manual testing

Do not run the full regression suite on every iteration.

Run the full suite only when High Priestess reaches release-qualification/freeze stage.

---

## Future Validation Work

Do not promote these BOOK☆WALKER fields until separately proven:

- tags
- creator replacement
- publisher replacement
- chapter artwork

Possible later work:

- BOOK☆WALKER tag validation gate
- One Piece-safe pagination/aggregation
- additional Wikipedia supported parser patterns
- secondary publication-structure fallback source

---

## Scope Boundary

This remains High Priestess reference-metadata integration.

It is not:

- image processing
- device simulation
- Empress presets
- generated cover design
- arbitrary image search
- acquisition-provider replacement
- broad workflow rewrite

---

## Core Rule

> Integrate only the fields that passed validation. Preserve existing behavior whenever a reference source cannot match safely.
