# Reference Metadata Prototype Report

Date: 2026-09-01  
Scope: isolated, Calibre-independent prototype only. No MangaNana workflow/UI
integration was performed.

## Method

- Wikipedia: normal MediaWiki search and parse endpoints, exact normalized
  title/alias matching only.
- BOOK☆WALKER: normal public catalog-search requests, exact normalized
  catalog-title/alias matching only.
- No browser automation, authentication workarounds, or extra acquisition
  provider requests were used.
- Live probe stopped after Wikipedia returned HTTP 429 during the bounded
  control matrix. The result is a reliability finding, not retried scraping.

## Control Matrix

### Death Note

#### Wikipedia

- Match: confident; unique exact title match (`Death Note`).
- Chapter-title coverage: 0 structured rows from the current conservative
  wikitext parser.
- Chapter-to-volume coverage: 0; no range inference was attempted.
- Volume coverage: 0 parsed volumes.
- Specials/ambiguities: none attached.
- Parsing/reliability: title match took 4 requests / 1.28s. The matching page
  did not yield the expected uniquely identifiable chapter-list link under the
  bounded parser.

#### BOOK☆WALKER

- Match: no match; normal public search responses did not expose one unique
  exact catalog title/alias to the strict parser.
- Edition / exact volume covers / chapter artwork / Description / tags /
  creators: unavailable because no safe publication match was made.
- Parsing/reliability: 2 requests / 2.88s, normal HTTP response, but no safe
  structured catalog match.

### Attack on Titan

#### Wikipedia

- Match: confident; unique exact title match (`Attack on Titan`).
- Chapter-title and chapter-to-volume coverage: 0.
- Volume coverage: 0.
- Specials/ambiguities: none attached.
- Parsing/reliability: 4 requests / 0.97s; same chapter-list discovery gap as
  Death Note.

#### BOOK☆WALKER

- Match: no match under strict catalog matching.
- Edition / covers / chapter artwork / Description / tags / creators:
  unavailable without a safe match.
- Parsing/reliability: 2 requests / 2.59s.

### JoJolion

#### Wikipedia

- Match: confident; unique exact title match (`JoJolion`).
- Chapter-title coverage: 0 before subsequent API requests were rate-limited.
- Chapter-to-volume and volume coverage: unavailable; the later requests
  returned HTTP 429.
- Parsing/reliability: 4 requests / 0.53s. Rate limiting prevents treating the
  current normal-request prototype as reliable.

#### BOOK☆WALKER

- Match: no match under strict catalog matching.
- Edition / covers / chapter artwork / Description / tags / creators:
  unavailable without a safe match.
- Parsing/reliability: 2 requests / 2.58s.

### One Piece

#### Wikipedia

- Match and all structure coverage: unavailable; the first API request in the
  large-title control returned HTTP 429.
- Parsing/reliability: 1 request / 0.08s. This prevents a meaningful
  pagination or scale measurement.

#### BOOK☆WALKER

- Match: no match under strict catalog matching.
- Edition / covers / chapter artwork / Description / tags / creators:
  unavailable without a safe match.
- Parsing/reliability: 2 requests / 2.78s.

## Prototype Findings

- Wikipedia can provide a conservative exact work-title match, but this pass
  did not prove reliable structured chapter or chapter-to-volume extraction.
  The current wikitext parser intentionally refuses to derive mappings from
  headings/ranges, and live API rate limiting interrupted the matrix.
- BOOK☆WALKER normal requests were reachable, but the bounded public search
  surface did not provide a unique exact publication record that the prototype
  could safely attach. No generic artwork was promoted to a volume cover.
- No source produced enough evidence to claim exact BOOK☆WALKER volume-cover,
  Description, tag, or creator coverage.

## Performance and Cache Findings

- Observed request cost before stopping: Wikipedia 1–4 requests/title;
  BOOK☆WALKER 2 requests/title; roughly 0.5–2.9 seconds/title.
- One Piece could not be assessed for pagination or scale because Wikipedia
  rate-limited the first request.
- The prototype cache keys separate source, publication ID, artifact kind,
  edition identity, and volume identity. Empty/failure values are not cached.
- A production investigation would need polite persistent caching, rate-limit
  backoff, and captured real-page fixtures before any integration; it must not
  cache exact volume artwork under a work-only key.

## Blockers and Fragility

- Wikipedia’s publication-structure tables are not proven to be uniform enough
  for the conservative generic parser; current coverage is zero.
- Wikipedia returned HTTP 429 during a very small sequential matrix, so normal
  requests are not yet proven reliable without a documented rate-limit policy.
- BOOK☆WALKER’s public search HTML does not currently yield a stable unique
  publication record using this bounded parser. Expanding to browser automation
  or broad scraping would exceed the prototype gate.

## Recommendation

**DO NOT PROCEED** to normal MangaNana integration from this prototype.

The sources remain candidates for a later, separately scoped discovery effort,
but the gate did not establish safe publication matching or useful structured
coverage for either source.

## Wikipedia Salvage Gate

Date: 2026-09-01  
Scope: bounded Wikipedia-only publication-structure validation. This section
does not change the earlier BOOK☆WALKER finding or integrate any source.

### Supported Parser Pattern

`graphic-novel-list-explicit-chapter-list-v1` accepts only a MediaWiki
`Graphic novel list` template with an explicit numeric `VolumeNumber` and an
explicit `ChapterListCol*` value. It supports either a nested `Numbered list`
with an explicit start value or numbered bullet entries. It records the source
page, pattern identity, and explicit extraction confidence on each row.

The parser takes a deliberately narrow main-series scope when a page contains
an explicit subsection whose normalized heading exactly matches the matched
work title; sister-series/spin-off subsections are then excluded. Otherwise it
does not invent a section boundary. Ranges remain ranges, decimals stay as
strings, and `Special N` stays a special rather than being mapped as a normal
chapter. It never derives chapter-to-volume assignments arithmetically.

### Four-title Coverage Summary

| Control | Matched page | Publication-structure page | Result |
| --- | --- | --- | --- |
| Death Note | `Death Note` | `List of Death Note chapters` | Dedicated page verified through MediaWiki search. It uses `Graphic novel list` volume blocks with `Numbered list` chapter/title entries, providing explicit numbered chapter titles and volume membership. The inspected page extends beyond the provider’s limited Ch. 1–10 data. |
| Attack on Titan | `Attack on Titan` | `List of Attack on Titan chapters` | Dedicated page verified through MediaWiki search. It uses the same explicit template family. The page contains separately headed manga/spin-off material; the exact main-series-heading boundary is the supported way to avoid attaching those rows to the main work. |
| JoJolion | `JoJolion` | `JoJolion` (main article, `Chapters`) | Main-page `Graphic novel list` blocks provide explicit volume and title entries. Source entries such as `2–5` are preserved as ranges and not expanded; alternate-column duplicate chapter numbering is retained first-wins without title-based guessing. |
| One Piece | `One Piece` | segmented `List(s) of One Piece chapters …` pages | MediaWiki search verified several chapter-list segment pages, including `List of One Piece chapters (1–186)`, which uses the supported template family. The prototype intentionally does not automatically aggregate multiple similarly named pages, so it returns unsupported rather than silently selecting or joining a large paginated collection. |

For the first three controls, chapter-title and chapter-to-volume coverage are
present only where the template explicitly supplies those fields; volume order
is the explicit template order. Death Note and Attack on Titan do not require
title-specific parser logic. JoJolion’s range representation is an ambiguity
that is preserved instead of normalized into invented individual mappings.
One Piece has no automatic all-series coverage yet, but its segmented layout
does not require repeated parsing of thousands of rows to establish the safe
failure mode.

### Requests, Rate Limits, and Cache

- Exact work matching is one MediaWiki search request. A main-page wikitext
  fetch is one more; dedicated chapter-list discovery and fetch add at most two
  more. A successful selected structure page is then reused in memory for its
  chapter and volume reads.
- Earlier paced inspection (two seconds between requests) reached the four
  controls and verified the pages/structures above. This gate’s final live
  control invocation received HTTP 429 on its very first request, and stopped
  immediately. No retries or traffic escalation were performed.
- Use a polite identifiable User-Agent, persistent cache keys based on the
  resolved page identity, and backoff/retry outside this prototype. Cache only
  nonempty successful structure data; transient HTTP/rate-limit failures must
  not be cached as an empty successful result.

### Known Limitations

- Only one explicit template family is supported. Ordinary prose, ambiguous
  tables, and unverified chapter-list names fail closed.
- Dedicated-list discovery requires one unique related MediaWiki search result;
  it deliberately refuses an ambiguous collection.
- One Piece pagination is deliberately unimplemented. A future, separately
  gated design would need an explicit verified collection/page-manifest model,
  not name-based segment guessing.
- Wikipedia remains rate-sensitive; persistent cache-backed use is required
  before considering normal production traffic.

### Recommendation

**PROCEED WITH LIMITATIONS.** The narrowly supported template structure yields
safe, useful explicit publication data for multiple controls without
title-specific rules, while unsupported and paginated layouts remain safely
unavailable. This is a source-validation result only, not authorization for
MangaNana integration.

## BOOK☆WALKER Identity Salvage Gate

Date: 2026-09-01  
Scope: bounded BOOK☆WALKER-only identity/catalog validation. No MangaNana
workflow or UI integration was performed.

### Stable Identifier Strategy

The ordinary Japanese public search page renders catalog cards with a UUID in
both `data-uuid` and a canonical `https://bookwalker.jp/de<UUID>/` product URL.
The confirmed product page provides a canonical URL, an explicit numbered
volume title, creator/imprint text, description, and a linked
`/series/<numeric-id>/list/` collection. The prototype uses the series-list ID
as the publication/edition identity and retains the UUID as the exact volume
record identity. It does not derive an identifier from a display slug.

An identity is confident only after one edition-compatible result card is
confirmed by its canonical product URL, explicit numeric volume, and exactly
one series-list ID. Cards with an explicit limited-free/trial marker are not
used. If the series list has more than one non-promotional record for the same
volume number, that volume fails closed instead of being selected by order.

### Four-title Identity and Volume Summary

| Control | Confirmed product UUID → series ID | Edition/identity result | Volume result |
| --- | --- | --- | --- |
| Death Note | `de4409c605-3eef-4287-a68d-650cc59a6e7e` → `series/13024` | `DEATH NOTE モノクロ版 1`; explicit monochrome edition. Separate color result is exposed and remains a different edition candidate. | Series page reported 12 records; UUID-backed normal volume rows and per-card covers are available without pagination. |
| Attack on Titan | `de14b19b62-e6d8-4419-acdd-620be6c3fcd3` → `series/4214` | `進撃の巨人（1）`; creator/imprint and distinct Before the Fall, omnibus, Full color, novel, and bilingual search cards provide explicit disambiguation signals. | Series page reported 51 catalog records, including limited-free variants. Normal UUID-backed volume rows are usable only after duplicate/promotion filtering. |
| JoJolion | `dee73c05f1-dd5c-46c1-8569-0c0002db3870` → `series/13018` | `ジョジョの奇妙な冒険 第8部 ジョジョリオン 1`; explicitly distinct from Part 8 color edition and other JoJo works. | Series page reported 27 UUID-backed records, with a single page and no observed pagination. |
| One Piece | `debfec8cda-fee8-4554-92a7-ec744c390d8a` → `series/13002` | `ONE PIECE モノクロ版 1`; explicit monochrome record, separated from color, episode A, starter, magazine, school, and remix results. | Series page reported 118 records, 60 on the first page, with pagination. A representative normal volume (`115`) was explicitly UUID-backed; no full-catalog crawl was performed. |

No title-specific matching rules were added. Edition selection uses explicit
catalog labels (for example monochrome or color) plus supplied canonical title
or alias evidence; no fuzzy attachment is allowed. Titles without a compatible
alias or explicit edition signal return ambiguous/no match.

### Metadata Findings

The confirmed product pages exposed a canonical title, volume number,
creator/imprint display text, an ordinary description meta field, JSON-LD
blocks, and a product-specific Open Graph image. The series-list cards expose
category tags and a product-associated image URL. The prototype represents a
series-list image as an exact volume cover only when it is in the same card as
the UUID-backed resolved volume record; generic series art is not promoted.

Description retrieval is useful for the confirmed volume product. Catalog-card
category tags are visible, but product-page tag normalization and a stable
publisher/creator parser were not proven consistently enough to recommend them
as production tag/creator authority yet. No explicit chapter artwork was
established.

### Requests and Cache

- Minimum identity confirmation: one compatible search page plus one product
  page (two requests), assuming the canonical identity includes a usable
  Japanese or catalog-title alias. Trying aliases may add bounded requests.
- One series-list request yields representative exact volume IDs and covers.
  One Piece needs page-aware bounded continuation for full inventory, not a
  repeated crawl; persistent cache is therefore essential.
- Cache successful data by source, `series/<id>`, edition identity, artifact
  type, and exact UUID/volume number. Do not cache ambiguous matches or
  transient failures as successful empty data.

### Known Limitations

- The public catalog is Japanese-market data; English-only identity evidence is
  insufficient when no catalog-title alias is available.
- Search results mix related works, editions, bundles, and promotional records.
  The prototype rejects rather than ranks unresolved candidates.
- Series lists can contain promotional duplicates and pagination. The current
  isolated parser does not automatically traverse paginated lists.
- Category tags, creator/publisher parsing, and chapter-artwork coverage need
  separate field-validation gates before production precedence.

### Recommendation

**PROCEED WITH LIMITATIONS.** Stable publication/edition and exact volume UUID
identity are safely demonstrable for multiple controls through bounded public
requests. Promote only this identity/exact-volume capability for a future
integration gate; do not yet promote BOOK☆WALKER as a general tag, creator, or
chapter-artwork source.
