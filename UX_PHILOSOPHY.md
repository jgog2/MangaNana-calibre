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
- Entering Book Customization does not automatically download preview pages.

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
- Future image-processing controls belong with the Live eReader Preview on Book Customization.
- Controls with no effect in the current layout should be disabled or hidden.

The goal is to reduce cognitive load.

---

## 2.9 Explanatory hover text is not part of the workflow

Ordinary controls should not display custom explanatory text boxes merely because the pointer is hovering over them.

This applies to buttons, fields, selectors, toggles, labels, pills, and similar workflow controls.

If something needs explanation, prefer:

- clearer wording
- concise inline helper text
- disabled-state reason text
- contextual status
- Activity Log detail

Do not make basic comprehension depend on discovering a tooltip.

---

# 3. Primary Workflow

MangaNana should use three clear stages:

## Choose Manga / Book Customization / Finalization

The current stage is shown in **MangaNana orange**.

The other two stages remain white.

Example:

`Choose Manga / Book Customization / Finalization`

If the user is on Stage 1:

- **Choose Manga** = orange
- Book Customization = white
- Finalization = white

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
  - Book Customization
  - Finalization

## Main body

Two primary side-by-side panels separated by the visual center gutter.

Each major pane should be able to scroll independently if necessary.

The UI should remain usable when resized.

Controls should never overlap or clip at the minimum supported window size.

## Preferences dialog

Preferences remains a conventional modal dialog with **OK** and **Cancel**.

High Priestess should correct current presentation defects:

- group-box headings must not be clipped by their borders
- rename `Search_Metadata Cache` to **Search & Metadata Cache**
- keep related helper text next to the setting it explains
- use balanced internal spacing
- avoid excessive orange borders that make ordinary fields resemble warnings/errors

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
- Next: Book Customization →

There is no separate Close or Cancel button for closing the plugin window.

The normal operating-system window close control is sufficient.

---

## Stage 2: Book Customization

Bottom navigation:

- ← Back
- Preferences
- Manga Sources
- About
- Next: Finalization →

---

## Stage 3: Finalization

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

Stage 1 should prioritize the two things the user is here to do: find the correct provider record and select the desired content.

## Left upper area — Compact discovery controls

Contains:

### Search
- query field
- Search button

### Mode
- Volumes
- Chapters
- neither selected by default

### Download Language
- language selector
- should look like a selector rather than an error/focused text field

### Prefer Colored
- compact MangaNana-styled checkbox/toggle

### Direct Link
- compact provider URL input
- Load button
- avoid repeated explanatory copy; one concise row is enough

The discovery area should be vertically compact so it does not starve Search Results.

## Left lower area — Search Results

A large scrollable result list.

The default window should show approximately **6–8 compact result cards vertically** where practical.

The interface should deliberately allow many provider-specific records to remain visible.

Initial search target:

> **Up to approximately 20 results per enabled provider where supported.**

With three enabled providers, the combined list may therefore contain many results.

That is acceptable.

The best results should rank first.

## Right upper area — Selected Manga

Use a compact but informative selected-record summary rather than a large mostly-empty panel.

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
- rating when already known, shown explicitly (for example `★ 8.4`) rather than appended to the title
- a small number of useful tags or a short synopsis when already available cheaply
- useful alternate title metadata when already known

Do not perform expensive extra requests merely to decorate this panel.

## Right lower area — Inventory

Before a mode is selected, use generic **Manga** wording and an instructional empty state rather than pretending the inventory is already Volumes or Chapters.

After mode selection, show either:

- Volumes
- Chapters

for the exact selected provider record.

Contains:

- compact proportional thumbnails where available
- title/number
- MangaNana orange circular selection controls
- compact **Select All**
- compact **Clear**
- selection count

Select All / Clear belong in or near the inventory header rather than as giant full-width buttons.

There is no separate Volume Range UI.

The inventory should receive most of the right-side vertical space.

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
- rating when already known, shown as secondary metadata such as `★ 8.4`, never as unexplained text appended to the title

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
→ Book Customization
→ Finalization
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

There is **no default mode**.

Before the user chooses either mode:

- neither **Volumes** nor **Chapters** should appear active
- inventory language should remain generic, using **Manga** rather than pretending a chapter or volume context already exists
- no mode-specific selection requirement should be shown

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

This helps users understand that Volumes and Chapters are intentionally separate discovery contexts.

---

# 24. Download Language

Download Language belongs on Stage 1 because language affects the usable inventory the user is selecting.

It should remain on Choose Manga and should not be duplicated on later stages.

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

The failure state and retry action must be understandable without relying on hover text. Use the pill state, retry affordance, concise inline status, or Activity Log.

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

> Next: Book Customization →

Enabled only when:

- a mode has been chosen
- an exact provider record is selected
- its inventory loaded successfully
- at least one chapter or volume is selected

If disabled, show only the first meaningful unmet prerequisite and make the wording mode-aware.

Examples:

> Choose Volumes or Chapters to begin.

> Search for and select a manga.

> Select at least one chapter to continue.

Do not bind this message to downstream Finalization inclusion state.

Do not leave disabled navigation unexplained.

---

# 33. Stage 2 — Book Customization

## 33.1 Purpose

Stage 2 answers:

> **How should the selected manga be presented for reading?**

Provider discovery and inventory selection are finished.

Search controls do not belong here.

Provider selection does not belong here.

The High Priestess version keeps this stage deliberately focused: reading/layout choices on the left and an optional Live eReader Preview on the right.

Advanced image-processing controls are reserved for **0.12.x — The Empress**.

---

# 34. Stage 2 Layout

The two sides are:

## Left page
### Reading & Layout

## Right page
### Live eReader Preview

The two panes should remain roughly equal in width with a narrow, visually centered gutter.

---

# 35. Reading & Layout

Current High Priestess controls include:

### Output Layout
- Portrait — Individual Pages
- Landscape — Paired Pages

### Reading Direction
- Right to Left
- Left to Right where supported

Active choices should use MangaNana orange clearly.

Inactive choices should remain visually neutral rather than receiving the same orange emphasis.

Reading Direction must look like a choice control, not an editable text field.

Future Empress controls will extend this left page with image/output tuning such as contrast, brightness, gamma, saturation, sharpening, dithering, scaling, crop, margins, and reader/device-oriented settings.

Do not add nonfunctional placeholders for those controls during High Priestess.

---

# 36. High Priestess Live eReader Preview

The right page of Book Customization contains:

> Live eReader Preview

Preview is **OFF by default**.

Entering Book Customization must not download preview pages.

The preview is optional and must never be required to continue.

High Priestess should reuse and reorganize the existing preview machinery into this stage rather than attempting the full Empress preview workstation.

The High Priestess preview must support both output layouts:

- **Portrait** previews bounded individual pages.
- **Landscape** previews bounded paired-page output.

Portrait preview must not be disabled merely because the historical Pairing Preview was originally designed around landscape pairing.

The preview must render inside the Stage 2 preview pane. High Priestess should not open a separate preview window.

The preview area belongs inside the Stage 2 page rather than as a separate workflow stage.

---

# 37. Preview Network Behavior

Preview network activity is explicit and bounded.

Pressing:

> Enable Live Preview

may begin a small sample-page download.

No preview download occurs merely because:

- the user entered Book Customization
- the user changed Portrait/Landscape
- the user changed Reading Direction
- the user returned with Back

Preview failure must never block the normal workflow.

---

# 38. Preview Reuse and Invalidation

After a preview sample downloads:

- keep the sample deliberately bounded
- reuse already-downloaded sample material when practical
- invalidate obsolete render work when the user's settings change
- never allow late preview work to overwrite newer user intent

If upstream content selection changes materially, mark the preview stale rather than silently downloading new pages.

Offer an explicit refresh/reload action when a new sample is required.

---

# 39. High Priestess / Empress Preview Boundary

High Priestess establishes the correct workflow location and supports bounded Portrait and Landscape preview.

The following are **not High Priestess scope** and belong to **0.12.x — The Empress**:

- the large vertically scrollable processed-page preview workstation
- advanced image-adjustment sliders
- named user presets
- preset save/load/update/delete behavior
- eReader Device Simulator
- device-specific simulator profiles
- sophisticated display overlays
- advanced processing comparison modes

High Priestess should leave clean extension points for these features without implementing fake controls.

---

# 40. Stage 2 Next

Button label:

> Next: Finalization →

Pressing it should:

1. validate the current reading/layout configuration
2. preserve any valid optional preview state
3. invalidate stale downstream output plans when necessary
4. enter Finalization

Preview does not need to be enabled or loaded.

Navigation itself performs the transition.

---

# 41. Stage 3 — Finalization

## 41.1 Purpose

Stage 3 answers:

> **How should MangaNana package and identify the books, and what exactly will it create?**

The left side contains book-creation choices and bulk metadata.

The right side contains Final Outputs.

This is the last stage before Download & Add to Calibre.

---

# 42. Stage 3 Left Page — Book Creation & Metadata

The left page contains only controls needed to finalize the current job.

Depending on mode, this may include:

- Chapter Output strategy
- Manual Grouping entry/summary
- naming controls such as zero padding where relevant
- bulk metadata fields
- current Calibre destination
- existing implemented cover behavior

Do not turn this page into a general Preferences screen.

---

# 43. Book Creation — Volume Mode

If the user selected Volume mode on Stage 1:

Do not show Chapter Output controls.

The selected provider volumes already define the output structure.

Explain the plan simply:

> Selected volumes will be created as individual CBZ files.

Preserve the existing volume metadata and volume-cover behavior.

---

# 44. Book Creation — Chapter Mode

If Stage 1 used Chapter mode, show:

## Chapter Output

- Build CBZs from Volume Data
- Manually Group Chapters into Volumes
- Save Each Chapter as Its Own CBZ

### Build CBZs from Volume Data

Enable only when complete trustworthy explicit chapter-to-volume evidence exists for the selected chapters.

Never infer volume boundaries using:

- total chapter count
- total volume count
- averages
- neighboring chapter numbers
- synthetic grouping assumptions

If volume data is unavailable:

- disable the option
- state why
- default to **Save Each Chapter as Its Own CBZ**

---

# 45. Manual Grouping

Manual Grouping remains a focused editor/dialog rather than permanently occupying the stage.

Expected capabilities:

- selected chapters shown in canonical order
- Ctrl/Shift multi-selection
- assign selected chapters to a volume
- reassign
- clear assignment
- preserve decimal/special chapter numbering where supported
- cannot finalize until every selected chapter is assigned

After confirmation, Finalization should show a concise summary and an **Edit Groups** action.

---

# 46. Bulk Metadata

High Priestess exposes three editable metadata fields:

- **Title**
- **Series**
- **Author**

These fields are auto-populated from MangaNana's resolved metadata and apply **in bulk to the entire current job**.

The user should not have to edit every planned volume/chapter output individually.

Do not add a language editor here. Download Language remains a Stage 1 inventory decision.

Do not add a new per-output metadata editor during High Priestess.

Metadata edits must not alter:

- provider identity
- selected edition
- inventory
- search result identity
- downloaded language

---

# 47. Covers

High Priestess should preserve the already-working cover behavior and volume-cover parity.

Do not add a new cover editor during this repair pass.

Future cover work belongs to later milestones and may include:

- custom cover selection
- MangaNana-generated covers
- chapter/volume labeling
- chapter-range markings
- generated-volume badges/watermarks

Do not expose fake controls for unimplemented cover features.

---

# 48. Volume Cover Parity

Generated volumes built from trusted explicit volume data should use the same volume-cover resolution path as native Volume mode whenever equivalent provider volume-cover metadata is available.

Rules:

- preserve volume-specific covers when available
- distinct generated volumes must not accidentally share the same cover
- do not borrow a cover merely because another provider supplied structural volume evidence
- do not retain stale previous-volume/edition covers
- use existing fallback behavior when no authentic volume-specific cover exists
- metadata cover remains excluded from manga reading pages

---

# 49. Calibre Destination

The current destination remains visible on Finalization, but compact.

Example:

```text
Destination
C:\...\MangaNana-Test-Library          [Browse]
```

The default destination may come from Preferences.

The destination should not dominate the page.

---

# 50. Stage 3 Right Page — Final Outputs

Final Outputs displays **planned books**, not raw selected chapters.

Each planned output may show:

- inclusion control
- type
- title
- provider/source
- page count when known
- estimated size when known
- status
- warnings where useful

The existing compact table/list approach is acceptable.

Do not add decorative cover thumbnails to Final Outputs merely for decoration.

This representation must work for:

- native provider volumes
- automatically generated volumes
- manually grouped volumes
- individual chapter CBZs

---

# 51. Final Output Inclusion

Inclusion answers:

> **Should this planned output actually be created?**

Use the existing MangaNana circular selection language consistently.

A row's inclusion state must not be confused with unrelated upstream chapter/volume selection state.

If row focus/highlight exists, clicking a row should not accidentally toggle inclusion.

---

# 52. Final Output Summary

Keep the concise aggregate information above or near Final Outputs.

Important information includes:

- number of planned books
- total page count when known
- estimated total size when known
- output layout
- language

Examples:

```text
1 volume • 139 pages • ~61.1 MB
Landscape paired pages • English
```

```text
4 volumes • 391 pages • ~385 MB
```

Page count and estimated size are useful decision information and should not be removed during simplification.

---

# 53. Final Download Action

The primary action is:

> Download & Add to Calibre

It belongs on Finalization and should use strong MangaNana-orange primary-action styling.

A separate permanent message repeating that the job is ready is unnecessary when the enabled primary action already communicates readiness.

---

# 54. Stage Isolation

The three stage bodies must be mutually exclusive.

At any moment, the main work area contains exactly one of:

- Stage 1 — Choose Manga
- Stage 2 — Book Customization
- Stage 3 — Finalization

Returning Back must completely hide downstream stage containers.

Upstream changes may mark downstream state stale, but they must never:

- show downstream panels
- rebuild Finalization automatically
- display downstream-ready messages
- trigger preview downloads
- cause a third or fourth work column to appear

Only explicit Next navigation may enter or rebuild the next stage.

---

# 55. High Priestess Status/Progress Discipline

Search status belongs to Choose Manga.

Preview status belongs to Book Customization.

Final output/download status belongs to Finalization.

Do not leave completed full-width progress bars permanently visible.

At idle, status and Activity Log presentation should remain compact.

Detailed logs, Copy Log, and Save Log remain available when the log is expanded.

---

# 56. Empress Handoff

**0.12.x — The Empress** expands the Book Customization workspace rather than inventing a new workflow.

Its intended direction includes:

- advanced image processing
- large scrollable processed-page preview
- reusable named processing presets
- eReader Device Simulator and profiles
- device/display-oriented tuning
- refined scaling/dithering behavior
- later cover-generation/customization work where appropriate

High Priestess should make these additions easy later without implementing them early.

---

# 57. Back Navigation

Back should preserve valid work aggressively.

## Stage 3 → Stage 2
Preserve:
- Finalization configuration
- bulk Title/Series/Author edits where still valid
- Chapter Output/manual grouping state where still valid
- inclusion state where still valid
- Book Customization settings
- optional preview state where still valid

If Book Customization settings change, mark downstream Finalization/output-plan state stale and rebuild it only when the user advances again.

## Stage 2 → Stage 1
Preserve:
- search field
- executed search results
- selected provider record
- loaded inventory
- chapter/volume selections
- valid Book Customization settings where still applicable

Do not treat Back as Start Over.

Back navigation must never cause downstream panels to remain visible on the upstream stage.

---

# 58. Downstream Invalidation

When an upstream decision materially changes, downstream plans become stale.

Examples:

- changing selected manga
- changing Mode
- changing selected chapters/volumes
- changing output layout
- changing reading direction when it affects output

MangaNana should rebuild downstream state only when the user next advances to the affected stage.

An upstream change must **not** call a downstream prepare/show routine merely because old Finalization state exists.

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
- selected/active states use MangaNana orange consistently
- inactive controls remain visually neutral

The branding and stage-navigation composition should share the same true horizontal center axis.

The version/build string may remain right-aligned, but it must not push the branding or stage navigation off center.

The two main work panes should be roughly equal width.

The narrow center gutter must sit on the window's center axis and read as a visual separator rather than a heavy splitter or scrollbar.

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

High Priestess should deliberately leave architectural and spatial room for **0.12.x — The Empress** without prematurely implementing it.

Empress-oriented additions include:

- advanced live image processing
- large scrollable preview inspection
- custom named processing presets
- eReader Device Simulator
- generic and device-specific simulator profiles
- device/reader output profiles
- custom covers
- MangaNana-generated covers
- volume/chapter-range cover markings
- more sophisticated processing and pairing visualization

Do not add empty placeholder controls for unimplemented features.

Reserve clean extension points instead.

---

# 67. Control Migration Rule

During the High Priestess repair, every current interactive control and user-facing behavior must be inventoried and mapped to one of:

- Stage 1 — Choose Manga
- Stage 2 — Book Customization
- Stage 3 — Finalization
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
- Volume/Chapter selection
- Select All / Clear
- Output Layout
- Reading Direction
- Live eReader Preview
- Chapter Output
- Manual Grouping
- Zero Padding
- bulk Title / Series / Author metadata
- existing cover behavior
- ComicInfo/metadata behavior
- Calibre destination
- Final Outputs inclusion controls
- Activity Log
- Progress
- Copy Log
- Save Log
- cancellation behavior
- provider fallback
- source configuration

Intentional removals include:

- the Volume Range UI
- giant full-width Select All / Use Entire Series controls in favor of compact **Select All / Clear**
- the ordinary-control hover-description/help-tooltip system

No ordinary field, button, selector, toggle, label, or pill should require a custom explanatory hover text box. Use clear labels, concise inline helper text where genuinely necessary, disabled-state reasons, contextual status, or the Activity Log instead.

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
8. **Mode has no default; before selection the interface remains generically Manga-oriented.**
9. **Mode changes create a new discovery context and clear old search state.**
10. **Mode changes preserve query text but never auto-search.**
11. **Prefer Colored never initiates provider search.**
12. **External enrichment is not required for provider results to appear.**
13. **Back preserves valid work.**
14. **Next validates the current stage and performs the transition.**
15. **Entering Book Customization never initiates preview downloads.**
16. **Live Preview is explicit, optional, bounded, and available in both Portrait and Landscape.**
17. **Provider failures should not block successful provider results.**
18. **Preview failure never blocks normal download.**
19. **Disabled actions explain why they are disabled.**
20. **Late async responses never overwrite newer user intent.**
21. **Network actions should always be understandable from the user's last deliberate action.**
22. **Provider-specific quirks stay inside provider adapters.**
23. **The three stage bodies are mutually exclusive; downstream UI never resurrects on an upstream stage.**
24. **Ordinary controls do not use explanatory hover-description text boxes.**
25. **Future Empress features receive extension points, not fake High Priestess controls.**

---

# 69. Mental Model

A new user should be able to understand MangaNana without documentation.

The intended experience is:

```text
CHOOSE MANGA

Choose Volumes or Chapters
    ↓
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
BOOK CUSTOMIZATION

Choose Portrait or Landscape
    ↓
Choose reading direction
    ↓
Optionally enable bounded Live eReader Preview
    ↓
Preview either individual Portrait pages or paired Landscape output
    ↓
Next
```

```text
FINALIZATION

Choose Chapter Output/grouping behavior when relevant
    ↓
Review or edit bulk Title / Series / Author metadata
    ↓
Confirm destination and existing output behavior
    ↓
See Final Outputs, page count, and estimated size
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
