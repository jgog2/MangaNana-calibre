# MangaNana UX Philosophy

> **Status:** Governing UX philosophy for MangaNana  
> **Current redesign milestone:** `0.11.0-dev — The High Priestess`

This document defines the product-level user experience principles that govern MangaNana.

It is intentionally **not** a pixel-perfect implementation specification. Its purpose is to explain how MangaNana should behave, how workflows should be staged, where controls belong, and how the interface should respond to user actions.

Future implementation prompts, contributors, and coding agents should read this document before modifying user-facing behavior.

> **If an implementation prompt conflicts with this document, the prompt must explicitly identify and justify the intended UX philosophy change. Otherwise, this document governs.**

---

# 1. Product Goal

MangaNana should make a technically complicated manga acquisition and preparation workflow feel simple, predictable, transparent, and user-controlled.

Under the hood, MangaNana may need to handle:

- multiple content providers
- provider-specific adapters
- search normalization
- metadata enrichment
- alternate editions
- language availability
- chapter and volume inventories
- cross-source fallback
- caching
- page downloads
- page pairing
- image processing
- CBZ creation
- ComicInfo metadata
- Calibre import
- eReader optimization

The user should **not** need to understand most of that complexity.

The interface should expose only the information required to make a meaningful decision at the moment that decision becomes relevant.

The user should always understand:

1. what MangaNana is doing,
2. what MangaNana is waiting for,
3. what source or manga record is currently selected,
4. what will happen when they press the next button,
5. what network activity they explicitly initiated,
6. and what files MangaNana ultimately intends to create.

---

# 2. Core UX Principles

## 2.1 User actions must have predictable consequences

A control should do what the user naturally expects it to do.

Examples:

- Typing into Search does not search.
- Pressing **Search** or Enter searches.
- Toggling **Prefer Colored** does not unexpectedly start a network request.
- Clicking a search result selects that exact result.
- Pressing **Next** advances the workflow.
- Pressing **Back** returns to the prior stage without unnecessarily destroying work.
- Entering Review does not automatically download preview pages.

Unexpected background behavior should be avoided unless it is harmless, clearly communicated, and directly related to an explicit action.

---

## 2.2 Network activity should correspond to obvious user actions

MangaNana should avoid hidden network requests caused by unrelated preference changes.

Normal network-triggering actions include:

- Search
- Load Direct Link
- selecting a provider record and loading its inventory
- Show More Results
- Retry Source
- Enable Live Preview
- Refresh Preview
- Download & Add to Calibre

The user should not need to wonder why MangaNana suddenly started contacting providers.

---

## 2.3 Ranking should primarily change order, not existence

MangaNana should favor **high recall** in visible search results.

A mediocre or weakly related result appearing lower in a scrollable results list is a minor inconvenience.

The result the user actually wanted being silently discarded is a search failure.

Therefore:

> **Prefer false positives over false negatives in visible search results.**

Search intelligence should mainly help organize results rather than decide that valid provider results are unworthy of being shown.

---

## 2.4 Uncertainty should result in less merging, not disappearance

If MangaNana is uncertain whether two provider records represent the same canonical work or edition, both should remain visible.

Do not hide one simply because MangaNana cannot confidently reconcile them.

This principle applies especially to:

- alternate editions
- fan-colored releases
- official colored releases
- Color-ban releases
- differently romanized titles
- provider metadata inconsistencies
- franchise titles with long shared prefixes

Canonical identity remains useful internally, but uncertainty should not erase user choice.

---

## 2.5 Provider records remain independently selectable

Visible search results represent **provider-local records**.

These are legitimate independent user choices:

- JoJolion — MangaDex
- JoJolion — MangaPill
- JoJolion — WeebCentral
- JoJolion Color-ban — MangaDex
- JoJolion Fan-Colored — MangaDex

Cross-provider visual deduplication should not collapse them into a single result.

Same-provider exact duplicate IDs may be deduplicated.

The provider record selected by the user should remain authoritative throughout the workflow.

---

## 2.6 Avoid modal interruptions whenever possible

The user should be able to continue working even if one provider or optional feature fails.

Prefer:

- inline error messages
- red failure pills
- retry icons
- contextual status text
- Activity Log explanations

over blocking modal dialogs.

A provider failure should not freeze the entire search workflow.

A preview failure should not block downloading.

---

## 2.7 Persistent defaults and current-job choices are different

**Preferences** should contain persistent defaults.

The three-stage workflow should contain decisions for the current job.

Examples:

Persistent:
- default reading direction
- default destination
- source configuration
- general application preferences

Current job:
- selected manga
- Volumes vs Chapters
- Download Language
- selected volumes/chapters
- layout
- Chapter Output mode
- cover behavior
- current processing settings

Do not turn workflow pages into a second Preferences dialog.

---

## 2.8 Context-sensitive controls should appear only when relevant

The interface should not show users a large wall of disabled or irrelevant controls.

Examples:

- Volume mode does not need Chapter Output controls.
- Chapter Output controls appear only for Chapter mode.
- Zero-pad chapter numbering should only appear where chapter-file naming needs it.
- Manual grouping controls appear only when Manual Grouping is selected.
- Image-processing controls belong with the live visual preview.
- Controls with no effect in the current layout should be disabled or hidden.

The goal is to reduce cognitive load.

---

# 3. Primary Workflow

MangaNana should use three clear stages:

## Choose Manga / Output Setup / Review

The current stage is shown in **MangaNana orange**.

The other two stages remain white.

Example:

`Choose Manga / Output Setup / Review`

If the user is on Stage 1:

- **Choose Manga** = orange
- Output Setup = white
- Review = white

The stage labels should initially be **non-clickable**.

Navigation happens using Back and Next so users cannot jump into downstream stages that have invalid or incomplete upstream state.

---

# 4. Global Layout Philosophy

The High Priestess interface uses a static two-panel layout inspired by the proportions of an open book.

The "book" concept is a **visual motif only**.

There should be:

- two major side-by-side work areas
- roughly page-like proportions
- a narrow fixed center gutter/separator
- no page-turn animation
- no folding-page effect
- no unusual navigation behavior

The UI should remain a normal desktop application.

The central gutter provides identity and visual organization without dictating interaction.

---

# 5. Global Shell

The overall shell remains structurally consistent across all three stages.

## Header

Contains:

- MangaNana logo/title
- version/build identifier
- stage header:
  - Choose Manga
  - Output Setup
  - Review

## Main body

Two primary side-by-side panels separated by the visual center gutter.

Each major pane should be able to scroll independently if necessary.

The UI should remain usable when resized.

Controls should never overlap or clip at the minimum supported window size.

---

# 6. Activity Log and Progress

The detailed Activity Log remains an important MangaNana diagnostic feature, but it should not permanently consume a large portion of the interface.

Normal idle presentation should be compact.

Example:

`✓ 27 volumes loaded from MangaDex                         Activity Log ▴`

The user can expand the Activity Log when desired.

During long-running operations, such as Download & Add to Calibre, the log and progress information may become more prominent automatically.

The full detailed logging system should remain available.

This is a presentation change, not a reduction in diagnostics.

---

# 7. Bottom Navigation

## Stage 1: Choose Manga

No Back button.

Bottom navigation:

- Preferences
- Manga Sources
- About
- Next: Output Setup →

There is no separate Close or Cancel button for closing the plugin window.

The normal operating-system window close control is sufficient.

---

## Stage 2: Output Setup

Bottom navigation:

- ← Back
- Preferences
- Manga Sources
- About
- Next: Review →

---

## Stage 3: Review

Bottom navigation:

- ← Back
- Preferences
- Manga Sources
- About
- Download & Add to Calibre

---

# 8. Stage 1 — Choose Manga

## 8.1 Purpose

Stage 1 answers:

> **What exact manga/source do I want, and which chapters or volumes do I want?**

This stage contains both discovery and content selection.

---

# 9. Stage 1 Layout

## Left upper area — Discovery controls

Contains:

### Search
- query field
- Search button

### Mode
- Volumes
- Chapters

### Download Language
- language selector

### Prefer Colored
- checkbox/toggle

### Direct Link
- provider URL input
- Load button

---

## Left lower area — Search Results

A large scrollable result list.

The interface should deliberately allow many provider-specific records to remain visible.

Initial search target:

> **Up to approximately 20 results per enabled provider where supported.**

With three enabled providers, the combined list may therefore contain many results.

That is acceptable.

The best results should rank first.

---

## Right upper area — Selected Manga

Shows detailed information for the exact currently selected provider record.

Examples:

- larger proportional cover
- title
- author
- source pill
- edition/type pill
- language
- inventory summary
- status when available
- useful alternate title metadata when already known

Do not perform expensive extra requests merely to decorate this panel.

---

## Right lower area — Inventory

Shows either:

- Volumes
- Chapters

for the exact selected provider record.

Contains:

- compact proportional thumbnails where available
- title/number
- MangaNana orange circular selection controls
- Select All
- Clear
- optional secondary range shortcut if useful

---

# 10. Search Execution

Typing does not search.

Only an explicit action executes discovery:

- Search button
- Enter key while Search has focus

Search never automatically selects the first result.

After results appear, nothing is selected until the user clicks a result.

---

# 11. Pending Query vs Executed Query

The text currently visible in the search field is not automatically the active search.

MangaNana must distinguish:

- **pending query text**
- **last executed query**

Example:

1. User searches `One Piece`.
2. Results for One Piece appear.
3. User edits the field to `JoJolion`.
4. User does not press Search.

The visible results are still the One Piece results.

The result pane may explicitly say:

> Results for "One Piece"

Toggling preferences must not execute the pending JoJolion query.

---

# 12. Search Philosophy

Search should be intentionally permissive.

Conceptual pipeline:

```text
Explicit Search
    ↓
Search every enabled provider concurrently
    ↓
Wait for provider terminal states
    ↓
Normalize provider-local records
    ↓
Remove only clearly invalid records
    ↓
Rank
    ↓
Display generously
```

Do not use a pipeline where MangaNana must first prove canonical identity, edition identity, or strong relevance before the user is allowed to see a provider result.

---

# 13. Search Admission

A provider-returned result should normally survive to the visible result set.

A result may be removed if:

- it is an exact duplicate provider record
- it violates deliberate adult-content policy
- it violates deliberate doujinshi policy
- it lacks enough provider identity to ever load
- the provider response is malformed beyond usable recovery

The following should generally **not** remove a result:

- mediocre relevance score
- low popularity
- uncertain canonical identity
- uncertain edition classification
- another provider having a better copy
- enrichment failure
- incomplete metadata
- Prefer Colored being disabled
- lack of already-loaded inventory

These factors may influence ranking or labels.

---

# 14. Search Ranking

Use understandable relevance tiers rather than aggressive visibility thresholds.

Conceptual order:

## Tier 1
Normalized exact title or trusted alias match.

## Tier 2
Full normalized query phrase contained in title/alias.

## Tier 3
All meaningful query tokens represented.

## Tier 4
Partial but plausible token/phrase relationship.

## Tier 5
Provider returned the candidate, but local relevance appears weak.

Tier 5 may rank low, but it should not automatically disappear.

Within a comparable relevance tier, ranking may consider:

- explicit edition intent
- Prefer Colored
- provider result order
- useful completeness signals
- deterministic tie-breaking

Popularity and external enrichment should be subordinate.

---

# 15. Search Text Normalization

Before relevance comparison, normalize:

- Unicode
- case
- punctuation
- hyphens
- apostrophes
- repeated whitespace

For search identity purposes:

`One-Punch Man`

and:

`One Punch Man`

should be treated as equivalent text.

---

# 16. External Enrichment

AniList/Kitsu enrichment must not be required for provider results to appear.

Content-provider search results define discovery.

Enrichment may provide:

- author
- aliases
- canonical metadata
- ratings
- work identity
- edition hints

But enrichment should not become an admission gate.

Search should not unnecessarily wait for external enrichment if the provider results are already ready for display.

Late enrichment must not unexpectedly remove visible results.

---

# 17. Search Display Barrier

Search results should not progressively reshuffle while providers are still completing.

Cold search behavior:

1. start all enabled provider searches concurrently
2. wait for each provider to:
   - succeed
   - fail
   - timeout
   - cancel
3. normalize/rank returned provider records
4. render the combined result set once

While waiting, show a neutral state such as:

> Searching sources…

Provider response speed must not determine ranking.

---

# 18. Search Result Deduplication

Do **not** visually deduplicate across providers.

These remain separate results:

- JoJolion — MangaDex
- JoJolion — MangaPill
- JoJolion — WeebCentral

Likewise, different provider-local editions remain separate.

Deduplicate only when the same provider returns the same immutable provider record ID/URL more than once.

Same normalized title alone is not enough to deduplicate.

---

# 19. Search Result Cards

Search result cards should be compact enough to show approximately 6–8 results vertically at the intended default window size.

Typical card contents:

- small proportional cover
- title
- author if already known
- MangaNana source pill
- MangaNana edition/type pill when known
- language if already known

Do not trigger expensive inventory loads merely to show extra card metadata.

Search-result covers:

- preserve original aspect ratio
- scale down proportionally
- never stretch
- never crop merely to fill a fixed rectangle
- use a fixed maximum height
- allow width to follow image ratio

Visual hierarchy:

1. Selected Manga cover — largest
2. Search result cover — medium-small
3. Volume/chapter thumbnail — smallest

---

# 20. Result Selection

Search never auto-selects.

When the user clicks a search result:

1. that exact card becomes active/highlighted
2. the Selected Manga panel updates
3. MangaNana loads inventory for that exact provider record
4. the right inventory pane shows a loading state
5. chapters/volumes populate when ready

No second Select button is required.

Clicking the card is the explicit selection action.

---

# 21. Provider Record Authority

A selected result establishes an authoritative provider-local identity.

At minimum preserve:

- provider
- provider item ID
- provider URL/reference
- edition identity when known

That identity should survive through:

```text
selection
→ inventory
→ selected chapters/volumes
→ Output Setup
→ Review
→ download
→ metadata
```

Do not perform a title re-search after selection.

Do not silently swap between separate records on the same provider merely because titles are similar.

---

# 22. Rapid Selection / Async Safety

If the user clicks MangaDex JoJolion and then quickly clicks MangaPill JoJolion before the first inventory request completes, the late MangaDex response must never populate the MangaPill selection.

Use explicit generation/load guards.

This same principle applies to:

- searches
- Show More
- inventory loads
- direct links
- preview downloads
- retry operations

Late asynchronous responses must not overwrite newer user intent.

---

# 23. Mode Behavior

Volumes and Chapters are different discovery contexts.

Changing:

- Volumes → Chapters
- Chapters → Volumes

should immediately:

- clear Search Results
- clear selected manga
- clear inventory
- clear inventory selections
- clear old source-status state
- invalidate downstream output plans

But preserve the current query text.

Do **not** automatically re-search.

Show a lightweight status message such as:

> Mode changed to Chapters. Search again to find chapter-compatible results.

This helps users understand that Volumes and Chapters are treated differently.

---

# 24. Download Language

Download Language belongs on Stage 1 because language affects the usable inventory the user is selecting.

It should not be hidden on Output Setup.

Language behavior should remain transparent and provider-aware.

Do not silently fabricate language.

Provider adapters own their language contracts.

---

# 25. Prefer Colored

Prefer Colored is a ranking preference.

It should never initiate a first search.

Before Search:

1. user types query
2. user toggles Prefer Colored
3. no network request occurs

After results exist, Prefer Colored may locally rerank the currently available result set without triggering a provider search.

Explicit query intent remains stronger than the preference.

Example:

`JoJolion color`

should strongly favor relevant colored editions even if Prefer Colored is otherwise disabled.

Standard editions may still remain visible.

---

# 26. Show More Results

One simple combined button:

> Show More Results

When pressed:

1. ask every provider that reports additional availability for its next bounded result page
2. wait for those requested providers to finish/fail/timeout
3. append newly discovered provider records
4. rerank the combined visible list
5. preserve all already visible results

Do not use separate More buttons for every provider unless future usability testing proves necessary.

---

# 27. Source Search Status

The Search Results area should visibly communicate provider state using MangaNana pill language.

Examples:

- healthy/completed provider = normal pill
- searching provider = subtle loading indicator
- failed provider = red source pill with a small retry-arrow affordance

A failed provider should not produce a blocking popup.

Hover/tooltip may explain:

> WeebCentral search failed. Click to retry.

Clicking the failed pill retries only that source.

Successful results from other providers remain usable during the retry.

---

# 28. Source Manager Behavior

Manga Sources remains accessible through the bottom navigation/footer.

No separate source checkbox row is required on Stage 1.

If sources change while results already exist:

## Disabling a source
- hide its current cards locally
- do not perform network search
- if the currently selected result belongs to that source, clear the active selection and inventory
- preserve results from still-enabled sources

## Enabling a source
- do not automatically search
- preserve current results
- show a lightweight notice:

> Sources changed. Search again to include newly enabled sources.

The next explicit Search uses the new source configuration.

---

# 29. Direct Link

Direct Link bypasses normal discovery.

When the user loads a recognized MangaDex/MangaPill/WeebCentral URL:

1. resolve the exact provider record
2. create a temporary provider result card in the normal Search Results area
3. automatically select that temporary card
4. populate the Selected Manga panel
5. load the appropriate inventory

The direct-link workflow should visually use the same selection/inventory model as search.

Do not populate the right side with an invisible or unexplained source record.

---

# 30. Automatic Fallback

Automatic provider fallback remains allowed to minimize interruptions.

If a selected source later fails and MangaNana has a sufficiently compatible fallback source:

- fallback may occur automatically
- no blocking popup is required
- the Activity Log must clearly explain what happened
- the visible selected source/provider should update so the UI does not claim pages are coming from a source that is no longer being used

Example Activity Log:

```text
[MangaDex] Chapter request failed.
Falling back to MangaPill...
[MangaPill] Continuing download.
```

Fallback must preserve work/edition compatibility requirements.

Fallback must not treat merely belonging to the same franchise as sufficient equivalence.

---

# 31. Selection State

Changing the selected search result changes the active job source.

Search/result comparison should be easy.

If practical within the current session, selections may be remembered by:

- provider record
- mode
- language

However, only one provider record is the active job at a time.

The UI must make the active result visually unambiguous.

---

# 32. Stage 1 Next

Button label:

> Next: Output Setup →

Enabled only when:

- an exact provider record is selected
- its inventory loaded successfully
- at least one chapter or volume is selected

If disabled, show a clear reason.

Example:

> Select at least one volume to continue.

Do not leave disabled navigation unexplained.

---

# 33. Stage 2 — Output Setup

## 33.1 Purpose

Stage 2 answers:

> **How should MangaNana organize and format the selected content?**

Provider discovery is finished.

Search controls do not belong here.

Provider selection does not belong here.

Visual image tuning does not belong here.

---

# 34. Stage 2 Layout

The two sides should be conceptually divided:

## Left page
### Reading & Layout

## Right page
### Book Creation & Metadata

---

# 35. Reading & Layout

Current controls include:

### Output Layout
- Portrait — Individual Pages
- Landscape — Paired Pages

### Reading Direction
- Right to Left
- Left to Right where supported

Future room may be reserved for:

- reader/device profiles
- structural page rules
- nonvisual pairing behavior

Do **not** put visual adjustment controls here.

Contrast, saturation, brightness, gamma, sharpening, dithering, scaling/cropping, and similar visual processing controls belong with the live preview on Stage 3.

---

# 36. Book Creation — Volume Mode

If the user selected Volume mode on Stage 1:

Do not show Chapter Output controls.

The user already selected real provider volumes.

The page should explain the current plan simply:

> Selected volumes will be created as individual CBZ files.

Then show relevant:

- naming
- metadata
- destination
- cover behavior

Do not clutter Volume mode with Chapter-only settings.

---

# 37. Book Creation — Chapter Mode

If Stage 1 used Chapter mode, show:

## Chapter Output

- Build CBZs from Volume Data
- Manually Group Chapters into Volumes
- Save Each Chapter as Its Own CBZ

### Build CBZs from Volume Data

Enabled only when complete trustworthy explicit chapter-to-volume evidence exists for the selected chapters.

Never infer volume boundaries using:

- total chapter count
- total volume count
- averages
- neighboring chapter numbers
- synthetic grouping assumptions

If volume data is unavailable:

- disable the option
- state why

Example:

> Volume data unavailable for this selection.

Then default to:

> Save Each Chapter as Its Own CBZ

---

# 38. Manual Grouping

Manual Grouping remains a focused editor/dialog rather than permanently occupying Stage 2.

Expected capabilities:

- selected chapters shown in canonical order
- Ctrl/Shift multi-selection
- assign selected chapters to a volume
- reassign
- clear assignment
- preserve decimal/special chapter numbering where supported
- cannot finalize until every selected chapter is assigned

After confirmation, Stage 2 should show a concise summary:

> Manual Groups  
> 3 volumes created from 17 chapters  
> [Edit Groups]

---

# 39. Naming

Only display naming controls relevant to the current output mode.

Examples:

- Zero-pad chapter numbers appears for individual chapter CBZ output where appropriate.
- Generated volume naming options appear for generated-volume workflows.

Do not display irrelevant naming controls merely because they exist somewhere in MangaNana.

---

# 40. Metadata

Output-specific metadata controls belong on Stage 2.

Possible controls:

- output title / Alternate Title selection
- series metadata behavior
- ComicInfo writing
- Calibre metadata behavior
- cover source

Alternate Title affects the output title.

It must not change:

- canonical identity
- provider
- selected edition
- inventory
- search result identity

---

# 41. Covers

Cover source selection belongs on Stage 2 because it is a book-output decision.

Current behavior may include:

- source/series cover

Future options may include:

- custom cover
- MangaNana-generated cover
- chapter-range markings
- MangaNana generated-volume badge/watermark

Do not expose fake controls for unimplemented features.

Reserve logical space and architecture for them.

Visual tuning of generated covers may later be integrated with Stage 3 preview.

---

# 42. Volume Cover Parity

Generated volumes built from trusted explicit volume data should use the same volume-cover resolution path as native Volume mode whenever equivalent provider volume-cover metadata is available.

Rules:

- preserve volume-specific covers when available
- distinct generated volumes must not accidentally share the same cover
- do not borrow a cover merely because another provider supplied structural volume evidence
- do not retain stale previous-volume/edition covers
- use existing fallback behavior when no authentic volume-specific cover exists
- metadata cover remains excluded from manga reading pages

---

# 43. Calibre Destination

The current destination should remain visible on Stage 2, but compact.

Example:

```text
Destination
C:\...\MangaNana-Test-Library          [Browse]
```

The default destination may come from Preferences.

The destination should not dominate the page.

---

# 44. Stage 2 Next

Button label:

> Next: Review →

Pressing it is the exact Review transition.

It should:

1. validate the current configuration
2. validate manual grouping where applicable
3. build the explicit output plan
4. prepare output metadata
5. populate Stage 3

There should no longer be a separate Review button.

Navigation itself performs the transition.

---

# 45. Stage 3 — Review

## 45.1 Purpose

Stage 3 answers:

> **What exactly will MangaNana create?**

The left side is factual output review.

The right side is optional visual preview/tuning.

---

# 46. Stage 3 Left Page — Final Outputs

Review should display **planned books**, not raw selected chapters.

Each planned output may show:

- inclusion control
- cover
- title
- volume/chapter range
- provider
- author
- series/volume
- page count when known
- estimated size when known
- status
- warnings

This same representation works for:

- native provider volumes
- automatically detected/generated volumes
- manually grouped volumes
- individual chapter CBZs

---

# 47. Review Inclusion vs Focus

Review rows have two separate concepts:

## Inclusion
Should this output actually be created?

Use the existing MangaNana circular Use/selection control.

## Focus
Which planned output is currently being inspected or previewed?

Use row highlight/focus styling.

Clicking a row should not accidentally toggle its inclusion state.

---

# 48. Review Summary

At the bottom of the Review list, show a concise summary when available.

Example:

```text
3 books
183 pages
~147 MB
```

If MangaNana detects an existing Calibre volume or potential update, show useful status before execution where possible.

Warnings belong here.

Example:

> ⚠ No volume-specific cover available

---

# 49. Live eReader Preview

The right side of Stage 3 is reserved for:

> Live eReader Preview

Preview is **OFF by default**.

Entering Stage 3 must not download preview pages.

Initial state:

```text
Live eReader Preview

Preview is optional.

MangaNana can download a small sample of pages so you can
see how the final output will look on your reader.

[ Enable Live Preview ]

No preview is required to continue.
```

---

# 50. Preview Network Behavior

Preview is explicit and bounded.

Pressing:

> Enable Live Preview

may start a small sample-page download.

The user can skip preview completely and still use:

> Download & Add to Calibre

Preview failure must never block the normal download workflow.

---

# 51. Preview Sample Reuse

After the preview sample downloads:

- reuse the same sample when sliders/settings change
- do not redownload for every visual adjustment
- keep sample download deliberately bounded

If the user changes to another planned book that has no preview sample:

Do not silently download another sample.

Show:

> Preview sample has not been loaded for this item.  
> [Load Preview Sample]

Network activity remains user-controlled.

---

# 52. Existing Pairing Preview

The current Pairing Preview functionality should become the initial implementation foundation for the Stage 3 Live eReader Preview.

High Priestess should reorganize existing preview behavior into this location.

Future visual processing controls can expand the same workspace.

---

# 53. Future Visual Processing Controls

Future controls belong beside/below the live preview because the user needs immediate visual feedback.

Potential controls include:

- contrast
- brightness
- saturation
- gamma
- sharpening
- dithering
- scaling
- crop
- margins

Do not place these on Stage 2.

High Priestess should reserve logical space for them but should not create nonfunctional placeholder controls.

---

# 54. Preview Fidelity

The preview should use the same underlying processing pipeline as final CBZ generation whenever possible.

Avoid a separate approximate preview algorithm.

Conceptually:

```text
Original page
    ↓
MangaNana processing configuration
    ├── Preview renderer
    └── Final CBZ renderer
```

The user should be able to trust the preview.

---

# 55. Preview Invalidation

If the user goes Back and changes settings that invalidate the preview:

- do not automatically redownload
- mark preview as out of date
- offer explicit refresh

Example:

> Preview settings changed.  
> [Refresh Preview]

---

# 56. Visual Processing Scope

Initial visual processing settings should normally apply to the whole current job rather than silently creating per-volume hidden overrides.

The UI should communicate the scope.

Example:

> Processing settings apply to all selected outputs.

Per-book overrides may be considered later if justified.

---

# 57. Back Navigation

Back should preserve work aggressively.

## Stage 3 → Stage 2
Preserve:
- Review state
- Stage 2 settings
- processing settings
- selected outputs

If Stage 2 settings change, mark downstream Review state stale and rebuild it when the user advances again.

## Stage 2 → Stage 1
Preserve:
- search field
- executed search results
- selected provider record
- loaded inventory
- chapter/volume selections
- valid Stage 2 settings where still applicable

Do not treat Back as Start Over.

---

# 58. Downstream Invalidation

When an upstream decision materially changes, downstream plans become stale.

Examples:

- changing selected manga
- changing Mode
- changing selected chapters/volumes
- changing Chapter Output grouping
- changing output layout when it affects generated output

MangaNana should rebuild downstream state when the user next advances.

Do not destroy unrelated valid settings unnecessarily.

---

# 59. Error Philosophy

Errors should be local to the operation that failed.

Examples:

## Provider search failure

Show successful provider results normally.

Show failed provider as a red retryable source pill.

No blocking popup.

## No search results

Inline message:

> No results were returned for "xyz".  
> Try another title, alternate title, or Direct Link.

## Inventory unavailable

Example:

> MangaPill does not provide volume information for this title.

## Inventory load failure

Example:

> MangaDex could not load this title's chapters.  
> [Retry]

## Preview failure

Example:

> Preview sample could not be loaded.  
> [Retry Preview]

Download remains available.

---

# 60. Provider Adapter Philosophy

Each provider adapter owns translation from provider-specific behavior into MangaNana's normalized contract.

Shared search/UI code should not need to understand:

- MangaDex API quirks
- MangaPill HTML quirks
- WeebCentral markup quirks

Provider-specific assumptions belong at the adapter boundary.

The adapter contract should clearly distinguish:

- zero results
- zero chapters
- parse failure
- network failure
- malformed provider response

A parser failure should not silently become a believable "0 usable chapters" state when MangaNana can determine that parsing failed.

---

# 61. Language Contracts

Provider language semantics should be explicit.

If a provider has a stable content-language contract, the adapter may declare it.

Explicit provider-reported language metadata should remain authoritative where available.

Missing language must not be treated automatically as wrong language.

Do not fabricate language merely to satisfy preferred-language resolution.

---

# 62. Cache Philosophy

Cache useful provider facts, not MangaNana's past opinion that something was "not relevant enough."

Search cache should conceptually preserve:

- provider
- executed query
- provider page/offset
- normalized provider candidates
- pagination state
- fetch/version metadata

Then current ranking rules can operate over those cached candidates.

Avoid caching aggressively filtered "final answers" that permanently hide provider records.

Zero-result final snapshots should not become persistent reusable "nothing exists" conclusions if the provider may return different results later.

Inventory caches remain separate from search candidate caches.

---

# 63. Retry Philosophy

Alias or alternate-query retries should be bounded and provider-local.

Prefer retries for genuinely empty provider searches rather than merely "weak" ones.

A retry must:

- belong to one provider
- use the actual retry query
- preserve successful first-pass candidates
- preserve first-pass pagination state
- never overwrite another provider's state
- log provider/query accurately

Optional retry failure must not erase successful discovery.

---

# 64. Visual Design Philosophy

MangaNana should remain visually distinctive without sacrificing density or clarity.

Core visual principles:

- dark theme
- MangaNana orange as primary accent
- existing MangaNana source-pill design
- existing MangaNana edition/type pill language
- proportional cover artwork
- clear typography hierarchy
- dense but readable result/inventory rows
- restrained use of borders
- spacing and typography should provide structure
- center gutter provides the primary large-scale visual division
- selected states use MangaNana orange consistently

Do not replace existing MangaNana pill language with generic rectangular badges unless deliberately redesigned later.

---

# 65. Cover Aspect Ratio

All manga/volume/chapter artwork should preserve its native aspect ratio.

Never stretch covers.

Never crop simply to fill a fixed rectangle.

Use proportional scaling and appropriate maximum dimensions.

Visual hierarchy:

- Selected Manga cover = largest
- Search Result cover = medium-small
- Volume/Chapter thumbnail = smallest

---

# 66. Future-Proofing

High Priestess should deliberately leave architectural and spatial room for future features without prematurely implementing them.

Potential future additions include:

- device/reader profiles
- advanced live image processing
- custom covers
- MangaNana-generated covers
- volume/chapter-range cover markings
- eReader simulation improvements
- more sophisticated pairing visualization
- processing presets

Do not add empty placeholder controls for unimplemented features.

Reserve clean extension points instead.

---

# 67. Control Migration Rule

Before replacing the existing UI, every current interactive control and user-facing behavior must be inventoried and mapped to one of:

- Stage 1 — Choose Manga
- Stage 2 — Output Setup
- Stage 3 — Review
- Preferences
- Manga Sources
- intentional removal

Nothing should silently disappear because it was forgotten during the redesign.

The migration audit should include at minimum:

- Search
- Mode
- Direct Link
- Prefer Colored
- Download Language
- Alternate Title
- Volume/Chapter selection
- Select All / Clear
- Output Layout
- Reading Direction
- Chapter Output
- Manual Grouping
- Zero Padding
- cover behavior
- ComicInfo/metadata behavior
- Calibre destination
- Review Use controls
- Pairing Preview
- Activity Log
- Progress
- Copy Log
- Save Log
- cancellation behavior
- provider fallback
- source configuration

---

# 68. General Interaction Laws

These are hard UX rules:

1. **Search is explicit.**
2. **Preferences do not secretly initiate searches.**
3. **Search never auto-selects a result.**
4. **Provider results are shown generously.**
5. **Ranking primarily affects order, not existence.**
6. **No cross-provider visual deduplication.**
7. **The exact provider record clicked by the user becomes authoritative.**
8. **Mode changes create a new discovery context and clear old search state.**
9. **Mode changes preserve query text but never auto-search.**
10. **Prefer Colored never initiates provider search.**
11. **External enrichment is not required for provider results to appear.**
12. **Back preserves valid work.**
13. **Next validates the current stage and performs the transition.**
14. **Entering Review never initiates preview downloads.**
15. **Live Preview is explicit, optional, and bounded.**
16. **Provider failures should not block successful provider results.**
17. **Preview failure never blocks normal download.**
18. **Disabled actions explain why they are disabled.**
19. **Late async responses never overwrite newer user intent.**
20. **Network actions should always be understandable from the user's last deliberate action.**
21. **Provider-specific quirks stay inside provider adapters.**
22. **Future features receive extension points, not fake controls.**

---

# 69. Mental Model

A new user should be able to understand MangaNana without documentation.

The intended experience is:

```text
CHOOSE MANGA

Search "JoJolion"
    ↓
See MangaDex, MangaPill, WeebCentral, and edition-specific records
    ↓
Click the exact result wanted
    ↓
See that exact provider record's chapters or volumes
    ↓
Select desired content
    ↓
Next
```

```text
OUTPUT SETUP

Choose Portrait or Landscape
    ↓
Choose how selected content becomes books
    ↓
Confirm naming, metadata, destination, and cover behavior
    ↓
Next
```

```text
REVIEW

See the exact CBZ files MangaNana plans to create
    ↓
Optionally enable Live eReader Preview
    ↓
Optionally inspect/tune visual output
    ↓
Download & Add to Calibre
```

There should be very little hidden state.

MangaNana may remain sophisticated internally, but the interface should make the user's explicit choices visible and authoritative.

---

# 70. Guiding Principle

The Magician built the multi-source machinery.

The High Priestess should make that machinery understandable.

MangaNana should be clever **behind the interface**, not clever **instead of the user**.

The goal is:

> **Search broadly. Show generously. Rank intelligently. Preserve user choice. Make every important state visible.**
