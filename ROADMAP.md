# MangaNana Development Roadmap

MangaNana is evolving from a Calibre plugin centered on MangaDex into a broader manga preparation, processing, library, and eReader workflow.

The immediate priority is stability. New systems should build on the current working plugin without weakening the existing Choose Manga → Download Settings → Review workflow.

---

# Current Development Principles

These rules apply across the project.

## Stability first

Before adding major systems:

- Fix remaining freezes and UI-thread blocking.
- Keep search and volume scrolling smooth.
- Keep source and language failures non-blocking.
- Preserve the current Choose Manga → Download Settings → Review workflow.
- Avoid expensive session restoration.
- Preserve current CBZ, metadata, cover, Portrait, Landscape, and page-pairing behavior.
- Keep network failures visible through the Activity Log.
- Avoid changing working behavior unless the change is intentional and tested.

## Performance rules

Project-wide rules:

- No network operations on the GUI thread.
- No heavy image processing on the GUI thread.
- Cancel or invalidate obsolete asynchronous jobs.
- Cache thumbnails.
- Cache preview source pages.
- Lazy-load offscreen images.
- Avoid unnecessary API calls.
- Preserve fixed widget geometry during asynchronous loading.
- Avoid persistent state that requires expensive reconstruction.
- Save preferences only when necessary.
- Bound caches by size.
- One failed source must never freeze the entire application.
- A slow source must not prevent other sources from returning results.

## Development rules

- `main` remains the public/stable branch.
- `dev` is the active integration branch.
- Larger work uses feature branches from `dev`.
- Changes should be small and reversible where practical.
- Regression tests should be added for bugs that have already occurred.
- New architecture should reduce coupling to Calibre where possible.
- Public behavior should not change during internal refactors unless explicitly intended.

---

# Track 0: Stabilize the Current Plugin

## Goal

Reach a point where the existing MangaDex-based Calibre plugin can serve as a dependable baseline for future development.

## Current focus

- Continue beta testing across Windows and macOS.
- Test multiple Calibre versions.
- Test Windows display scaling at 100%, 125%, and 150%.
- Test very long manga series.
- Test manga with only standalone chapters.
- Test titles with missing volume covers.
- Test titles with unavailable preferred languages.
- Test Portrait and Landscape workflows.
- Test Pairing Preview.
- Test cancellation and network failure paths.
- Test direct MangaDex URL loading.
- Test existing volumes already present in Calibre.

## Completion criteria

The current plugin should:

- remain responsive during search and download operations
- recover cleanly from source/network errors
- avoid stale Preview or Review state
- avoid layout overlap at common DPI settings
- package valid CBZ files consistently
- import completed books into Calibre reliably
- preserve metadata and cover behavior
- clean temporary data after cancellation or failure
- provide useful Activity Log output

---

# Track 1: Regression Testing and Core Extraction

This track should begin before major new features.

## Phase 1A: Regression Test Foundation

Expand the existing test suite gradually.

Priority tests:

- volume normalization
- numeric volume sorting
- standalone chapter ordering
- duplicate chapter handling
- language fallback
- title-language selection
- download-plan generation
- CBZ page ordering
- cover fallback
- page-pairing logic
- range selection behavior
- source failure handling

Use saved API fixtures wherever possible so tests do not depend on live MangaDex responses.

Example structure:

```text
tests/
├── test_volume_normalization.py
├── test_standalone_chapters.py
├── test_language_fallback.py
├── test_download_plan.py
├── test_pairing.py
├── test_cbz_order.py
└── fixtures/
```

## Phase 1B: MangaNana Core Extraction

Gradually move Calibre-independent logic out of `main.py`.

Potential modules:

```text
manganana_core/
├── models.py
├── metadata.py
├── volumes.py
├── chapters.py
├── covers.py
├── downloads.py
├── cbz.py
├── pairing.py
├── processing.py
├── preview.py
├── cache.py
└── sources/
```

Early extraction targets:

- localization helpers
- volume normalization
- chapter sorting
- metadata normalization
- CBZ naming
- page pairing
- image-processing functions

Do not attempt a full rewrite.

Move one logical group at a time and use regression tests to confirm identical behavior.

## Long-term objective

The Calibre plugin becomes one frontend using MangaNana Core.

Future standalone MangaNana uses the same core.

---

# Track 2: Live Preview Engine

## Goal

Create a persistent preview system that reacts to image-processing settings in near real time.

The Live Preview should make it possible to adjust image output without repeatedly downloading or rebuilding an entire volume.

## Representative preview sample

Load a small set of useful pages rather than an entire volume.

Potential sample:

- cover or first page
- title/front-matter page
- normal manga page
- darker or heavily shaded page
- spread if available
- color page when relevant

Target approximately 3 to 6 representative pages.

## Preview architecture

The preview worker should:

- run outside the GUI thread
- download source pages once
- cache source images
- reuse cached pages when sliders change
- debounce rapid control changes
- cancel or invalidate obsolete renders
- display only the newest render result
- avoid moving surrounding UI while rendering

A subtle status such as:

`Updating preview...`

is preferable to blocking the interface.

## Shared processing pipeline

Preview processing and final CBZ processing must use the same underlying functions.

Conceptually:

```text
Source Image
    ↓
MangaNana Processing Pipeline
    ↓
Final Output Image
```

Live Preview may use reduced-size cached source images for speed, but the processing logic itself should remain shared.

This prevents Preview behavior from drifting away from final output behavior.

## Comparison modes

Initial modes:

- Processed only
- Original / Processed side by side

Later:

- draggable before/after split
- zoomed detail comparison

---

# Track 3: Image Processing

## Goal

Allow users to optimize manga images for their preferred eReader without requiring external image-processing software.

Default behavior remains:

**Original**

MangaNana should not alter source artwork unless the user requests processing.

## Primary controls

Initial processing controls:

- Contrast
- Saturation
- Gamma
- Grayscale conversion
- Dithering
- Resolution scaling

Potential later controls:

- Brightness
- Sharpening
- Black-point adjustment
- White-point adjustment
- JPEG quality
- Noise reduction

Do not expose every advanced control in the default interface.

## Processing order

Define a stable internal processing pipeline early.

Possible order:

```text
Decode
↓
Color adjustments
↓
Grayscale conversion if enabled
↓
Contrast / Gamma
↓
Resize
↓
Sharpen
↓
Dithering
↓
Encode
```

The exact order should be tested and documented because output quality can change significantly depending on processing sequence.

---

# Track 4: Dithering

## Goal

Improve grayscale and limited-color output on eReader displays.

Candidate algorithms:

- None
- Floyd-Steinberg
- Atkinson
- Ordered/Bayer

The normal UI can expose friendly presets.

Advanced settings may expose the actual algorithm.

Potential presets:

- Original
- Smooth Grayscale
- High Detail B&W
- eReader Dithered
- Custom

Dithering must be evaluated carefully for manga screentones because aggressive algorithms can create moiré patterns or destroy intentional texture.

---

# Track 5: eReader Screen Emulation

## Goal

Let users estimate how processed manga may appear on the type of display they plan to use.

Screen emulation is preview-only.

It must never alter the final CBZ unless the corresponding image-processing settings are separately enabled.

## Pipeline distinction

Final file pipeline:

```text
Original Page
→ MangaNana Processing
→ Final CBZ Image
```

Preview pipeline:

```text
Final CBZ Image
→ eReader Display Simulation
→ Preview
```

This separation is important.

## Initial profiles

Potential profiles:

- No Emulation
- Generic Color eReader
- Generic B&W eReader
- Kobo Libra Colour

Device-specific profiles should be clearly described as approximations unless based on measured display characteristics.

## Potential simulation characteristics

- reduced saturation
- grayscale response
- e-ink contrast behavior
- approximate color gamut reduction
- mild display tint
- reduced apparent sharpness
- resolution / pixel density
- optional bezel framing

## Accuracy disclaimer

Device simulation should communicate that appearance varies with:

- firmware
- brightness/front-light settings
- ambient lighting
- device calibration
- individual display variation

---

# Track 6: Processing Profiles

## Goal

Allow users to save reusable manga-output configurations.

Example:

```text
My Color eReader

Layout: Landscape
Reading direction: Right-to-left
Saturation: +5
Contrast: +8
Gamma: 1.0
Dithering: None
Resolution: Device optimized
Display simulation: Generic Color eReader
```

Profiles may contain:

- layout
- image-processing settings
- resolution
- reading direction
- output quality
- device-emulation choice
- cover behavior

Potential later feature:

Automatically select a profile based on the connected eReader.

---

# Track 7: Source Adapter Architecture

This should happen before adding many new websites.

## Goal

Remove MangaDex-specific assumptions from the rest of MangaNana.

Create a common source interface.

Conceptually:

```python
class SourceAdapter:
    def search(self, query):
        ...

    def get_manga(self, source_id):
        ...

    def get_languages(self, source_id):
        ...

    def get_volumes(self, source_id, language):
        ...

    def get_chapters(self, source_id, language):
        ...

    def get_pages(self, chapter_id):
        ...

    def get_cover(self, source_id):
        ...
```

MangaDex becomes the first implementation:

```text
SourceAdapter
└── MangaDexSource
```

## Proof of architecture

Before adding a second source, MangaDex should function entirely through the adapter abstraction without visible behavioral regressions.

If MangaDex cannot cleanly operate through the abstraction, the interface needs improvement before more providers are added.

---

# Track 8: Source Manager

## Goal

Provide one place for users to enable, disable, configure, and prioritize manga sources.

Potential location:

**Preferences → Sources**

Example:

```text
Sources

✓ MangaDex         Ready
✓ Source B         Ready
○ Source C         Disabled
⚠ Source D         Login required
```

Each provider may expose:

- Enabled toggle
- Source name
- Priority
- Status
- Authentication status
- Test Connection
- Source-specific options

Potential later feature:

Drag-and-drop source priority.

---

# Track 9: Authentication and Source Configuration

Different providers may require different configuration.

Possible connector-defined fields:

- API key
- OAuth/account authorization
- token
- username
- endpoint URL
- no authentication

MangaNana should not expose a generic:

`Enter API key for website`

without a corresponding source adapter that understands how to use it.

## Security requirements

- Never write credentials to the Activity Log.
- Never commit credentials to Git.
- Store secrets using an appropriate local credential mechanism where practical.
- Redact authentication details in error reporting.

---

# Track 10: Second Source Proof of Concept

Before attempting broad multi-source support, add exactly one second provider.

The goal is architectural validation.

A second source should prove that:

- SourceAdapter works
- search can run independently per provider
- normalized metadata works
- language handling works
- volume/chapter discovery works
- source-specific failures remain isolated
- the existing UI does not become source-specific

Do not add many providers until this proof of concept works reliably.

---

# Track 11: Multi-Source Search

## Goal

One MangaNana search queries all enabled providers.

Conceptually:

```text
Search "JoJolion"

MangaDex       6 results
Source B       4 results
Source C       3 results

        ↓

Normalize

        ↓

Deduplicate

        ↓

Merged Search Results
```

## Requirements

Providers run independently.

If one provider times out or fails:

- results from working providers should still appear
- the failed source should report a non-blocking status
- the UI must remain responsive

## Progressive results

Do not wait for every provider before showing results.

For example:

```text
MangaDex results arrive
↓
Display immediately
↓
Source B results arrive later
↓
Merge into existing list
```

Per-provider timeout budgets should prevent a slow provider from delaying the entire search.

---

# Track 12: Cross-Source Manga Identity

## Goal

Represent the same manga available from multiple providers as one canonical MangaNana record.

Example:

```text
JoJolion

Available from:
- MangaDex
- Source B
- Source C
```

rather than showing three unrelated cards.

## Matching signals

Use strongest evidence first:

1. shared external IDs
2. publication IDs
3. exact normalized titles
4. alternate titles
5. author
6. series/part information
7. fuzzy matching as supporting evidence

## Confidence model

Internally:

- Exact
- Strong
- Possible

Only Exact and sufficiently Strong matches should merge automatically.

A false duplicate merge is worse than showing duplicate search results.

## User correction

Potential UI:

```text
These appear to be the same manga.

[ Merge ]
[ Keep Separate ]
```

Remember user decisions locally.

---

# Track 13: Source Selection

For a merged manga, MangaNana chooses a default provider according to:

- requested language
- source completeness
- source priority
- available volumes
- image quality
- source reliability
- preferred edition
- color vs monochrome release

Example:

```text
JoJolion
COLOR

Using: MangaDex
Also available: Source B, Source C
```

Users can override the automatic source choice.

---

# Track 14: Cross-Source Language Fallback

## Goal

Reduce language dead ends.

Example:

```text
English unavailable from MangaDex.
English available from Source B.
```

MangaNana can:

- automatically switch according to preferences
- visibly offer the alternate provider

Source and language fallback should remain understandable to the user.

---

# Track 15: Per-Volume Source Fallback

Advanced feature.

Example:

```text
Volume 1–11     MangaDex
Volume 12       Source B
Volume 13–20    MangaDex
```

MangaNana fills gaps from secondary providers.

Do not implement this until these systems are reliable:

- metadata normalization
- canonical manga identity
- chapter ordering
- duplicate detection
- page-quality handling
- source attribution
- source-specific licensing/availability rules

This is a later-stage feature.

---

# HakuNeko Research Track

HakuNeko is useful because it has already explored a large part of the connector problem.

Reference:

https://github.com/manga-download/hakuneko

## Study

Inspect:

- source abstractions
- connector discovery
- manga lookup
- chapter enumeration
- image URL extraction
- authentication handling
- error handling
- rate limiting
- source-specific quirks

## Reuse conceptually

Useful areas include:

- connector patterns
- parsing approaches
- known site-specific edge cases
- provider naming/mapping strategies
- source-specific request behavior

## Avoid

Do not:

- import the entire HakuNeko architecture
- couple MangaNana to HakuNeko's UI/runtime
- import unrelated anime functionality
- blindly port every connector
- sacrifice MangaNana's simpler workflow to match HakuNeko

MangaNana is a Python/Qt project with a different purpose.

Useful provider logic should be adapted into MangaNana's own SourceAdapter architecture.

## Provenance

Any adapted connector logic should be documented so future maintainers can identify its origin and understand why the implementation exists.

---

# Track 16: Review Panel Expansion

As source and processing capabilities grow, Review can expose more useful job information.

Potential entry:

```text
Volume 4

Source: MangaDex
Language: English
Pages: 226
Processing: Color eReader
Output: Landscape
Estimated size: ~93 MB
```

For jobs involving multiple providers, add a subtle Source column.

Avoid turning Review into a technical debugging screen.

The purpose remains:

**What exactly is MangaNana about to create?**

---

# Track 17: Standalone MangaNana

This is a major long-term goal.

## Goal

Build a modern standalone MangaNana application that can operate without Calibre.

The standalone should use MangaNana Core rather than duplicating the plugin implementation.

Conceptually:

```text
MangaNana Core
├── Calibre Plugin
└── Standalone Application
```

## Standalone workflow

Potential main workflow:

```text
Discover
→ Download
→ Library
→ Device
```

## Local library

The standalone will need its own persistent database.

SQLite is a likely choice.

Potential stored information:

- canonical manga ID
- source/provider IDs
- edition
- title
- alternate titles
- author
- language
- volume/chapter identity
- local CBZ path
- cover
- date downloaded
- processing profile
- output settings
- MangaNana version
- device sync status

Database schema changes must support safe migrations between MangaNana versions.

---

# Track 18: Standalone Library Dashboard

Potential library view:

```text
My Library

Steel Ball Run
24 / 24 volumes
Complete

JoJolion
21 / 27 volumes
6 available

The JOJOLands
5 downloaded
1 new volume available
```

Potential statuses:

- Complete
- Updates available
- Missing volumes
- Downloaded
- On device
- Not on device

This would turn MangaNana from a downloader into a manga collection manager.

---

# Track 19: Direct eReader Integration

## Goal

Allow the standalone application to transfer manga directly to a connected eReader without requiring Calibre.

Potential functionality:

- detect connected devices
- identify mount point
- display free storage
- transfer selected books
- remove MangaNana-managed books
- remember transferred files
- compare local library with device contents
- safely eject device

Example:

```text
Connected eReader
18.6 GB free

✓ Steel Ball Run Vol. 01
✓ Steel Ball Run Vol. 02
○ JoJolion Vol. 01
○ JoJolion Vol. 02

Selected size: 1.4 GB

[ Sync to eReader ]
```

Device support should be implemented through a device abstraction where practical.

---

# Track 20: Library and Device Synchronization

Potential future capabilities:

- show books only in local MangaNana library
- show books currently on device
- show books available from sources but missing locally
- identify new releases
- prioritize next unread volumes where supported
- estimate transfer storage before copying
- warn when selected files exceed available device storage

Actual reading-progress integration depends on what each device exposes reliably.

---

# Track 21: Update Checking

Once MangaNana maintains source identity, it can check previously downloaded series for updates.

Example:

```text
The JOJOLands

Local:
Volumes 1–5

Available:
Volumes 1–6

1 new volume available

[ Review Volume 6 ]
```

Update checks should be lightweight and opt-in.

Downloads should remain user-controlled.

---

# Track 22: Smart Page Processing

## Per-page monochrome detection

Analyze actual page chroma.

If an RGB image is effectively monochrome:

- optionally convert it to grayscale
- reduce output size
- preserve genuinely colored inserts

This should not be used as the primary method for labeling an entire manga B&W.

## Adaptive processing

Potential later capabilities:

- stronger contrast for unusually dark scans
- preserve already-clean pages
- preserve color inserts
- protect screentones
- detect blank pages
- detect duplicate pages
- detect suspiciously low-resolution pages
- detect corrupt images
- detect unusual aspect ratios

Automatic processing must remain conservative.

---

# Track 23: Advanced Page Pairing

The current landscape pairing system can eventually become more intelligent.

Potential improvements:

- original-spread recognition
- cover handling
- chapter-title-page recognition
- inserts
- advertisements
- supplemental pages
- parity analysis
- intentional isolated-page detection
- special handling for sideways pages

## Manual Pairing Editor

Possible later tool:

```text
Page 16 | Page 17
[ Pair ]

Page 18
[ Keep Single ]

Page 19 | Page 20
[ Pair ]
```

Users could override difficult pairing decisions before CBZ creation.

This is a later advanced feature.

---

# Track 24: Metadata Reconciliation

Compare source metadata against local library metadata.

Potential differences:

- title
- author
- series
- language
- edition
- publication status
- tags
- cover

Allow users to review differences before replacing local metadata.

This becomes especially valuable once multiple sources exist.

---

# Track 25: Download Provenance

Store internal provenance for created books where practical.

Potential information:

- MangaNana version
- source
- source manga ID
- source chapter IDs
- language
- creation date
- processing profile
- page layout
- cover source
- output settings

This helps future updates, troubleshooting, and migration between sources.

---

# Search Principles

These principles should remain even after multi-source support is added.

- lightweight initial results
- large readable covers
- preferred-language display titles
- Show More Results
- append instead of replacing
- preserve scroll position
- lazy-load covers
- cancel stale requests
- deduplicate by source ID
- deduplicate canonical manga carefully
- filter unavailable titles
- keep adult-content filtering configurable
- avoid blocking the entire interface on one source
- show results progressively

With multiple sources, Show More Results may become provider-aware internally while remaining one simple control for users.

---

# UI Design Principles

MangaNana should remain approachable even as functionality grows.

The default workflow should continue to feel like:

```text
Find manga
→ choose volumes
→ choose how it should look
→ review
→ download/add
```

Advanced systems should remain underneath that workflow.

## Avoid

- exposing provider implementation details unnecessarily
- overwhelming users with every image-processing control
- moving controls during asynchronous loading
- unexplained technical terminology
- making source selection mandatory when MangaNana can make a safe default choice
- turning the main window into a configuration dashboard

## Prefer

- clear defaults
- progressive disclosure
- optional advanced controls
- one obvious next action
- stable panel geometry
- consistent visual language
- readable error states
- recoverable failures

---

# Suggested Development Order

The current recommended sequence is:

1. Stabilize the current 0.9.x public beta.
2. Expand regression tests.
3. Begin MangaNana Core extraction.
4. Move MangaDex behind SourceAdapter.
5. Build the Live Preview Engine.
6. Add Contrast, Saturation, Gamma, and Grayscale.
7. Add Dithering.
8. Add basic processing presets.
9. Add eReader display emulation.
10. Expand processing profiles.
11. Build Source Manager.
12. Study HakuNeko connectors in detail.
13. Add one second source as proof of concept.
14. Implement multi-source search.
15. Add canonical manga identity and duplicate merging.
16. Add cross-source language fallback.
17. Add additional sources gradually.
18. Add per-volume source fallback later.
19. Continue extracting MangaNana Core.
20. Build standalone local library.
21. Build standalone MangaNana frontend.
22. Add direct eReader transfer.
23. Add library/device synchronization.
24. Add update checking.
25. Expand smart processing and pairing only after the foundation is stable.

---

# Long-Term Product Direction

The Calibre plugin remains valuable and should continue to be supported.

Long term, MangaNana may become a broader manga-focused application:

```text
MangaNana

Discover manga across supported sources
↓
Choose editions and volumes
↓
Optimize pages for an eReader
↓
Review output
↓
Build reader-ready CBZ files
↓
Store in MangaNana or Calibre
↓
Transfer directly to an eReader
↓
Track missing and newly available volumes
```

The Calibre plugin and standalone application should share the same underlying MangaNana Core wherever possible.

The complexity belongs in the architecture.

The user experience should remain simple.
