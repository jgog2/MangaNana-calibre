MangaNana Development Roadmap

MangaNana is a Calibre plugin for finding, downloading, preparing, and adding manga directly to a Calibre library without leaving Calibre.

The current goal is a strong Calibre-plugin 1.0 release. Standalone MangaNana, local-library management, direct device sync, and other standalone-only systems are post-1.0 ideas and are not part of the current completion target.

The current architecture already supports the multi-source MangaDex / MangaPill / WeebCentral foundation, provider-local search results, Volume/Chapter workflows, fallback, output planning, and existing Portrait/Landscape generation.

The immediate priority is **0.11.0-dev — The High Priestess**: repair and simplify the three-stage workflow so the existing machinery is clear, stable, and predictable before advanced image/output work begins.

The primary user flow is:

Choose Manga
→ Book Customization
→ Finalization
→ Download & Add to Calibre

Tarot Release Milestones

0.10.0-dev — The Magician — frozen/completed architecture milestone

The Magician established the major multi-source machinery and provider abstraction needed for the later UI and output work.

0.11.0-dev — The High Priestess — active

High Priestess is the clarity/workflow milestone.

Primary scope:

- three mutually exclusive stages: Choose Manga / Book Customization / Finalization
- repair stale/downstream stage resurrection and invalidation bugs
- compact discovery controls with substantially more Search Results space
- no default Volume/Chapter mode; before selection the UI remains generically Manga-oriented
- remove the Volume Range UI
- use compact Select All / Clear inventory actions
- remove explanatory hover-description text boxes/tooltips from ordinary workflow controls
- center the branding/stage header and the two-page gutter correctly
- compact idle progress/status/Activity Log presentation
- move Live eReader Preview to Book Customization
- allow bounded Live Preview in both Portrait and Landscape
- keep Live Preview optional and explicit
- move book-creation/output choices to Finalization
- add simple bulk-editable Title / Series / Author metadata
- keep language selection on Choose Manga, not Finalization
- preserve existing cover behavior without adding a new cover editor
- keep Final Outputs compact and retain page-count and estimated-size summaries
- fix Preferences group-title clipping and rename `Search_Metadata Cache` to `Search & Metadata Cache`
- keep Preferences OK/Cancel and improve spacing/focus styling
- change Calibre plugin author metadata to `jgog`
- change the Calibre plugin description to `Reading manga shouldn't turn into a damn IT project.`

0.12.x — The Empress — next

The Empress is the output/image refinement milestone.

Primary direction:

- advanced image-processing controls
- contrast, brightness, gamma, saturation, grayscale, sharpening, scaling/crop/margins where justified
- dithering and output-quality tuning
- large vertically scrollable processed-page preview workspace
- shared preview/final processing pipeline
- user-named reusable processing presets
- eReader Device Simulator
- generic and major-device simulator profiles
- refined device/output profiles
- later cover-generation/customization work where appropriate

0.13.x — The Emperor

Hardening, reliability, provider failure handling, large-series behavior, edge cases, performance, and platform stability.

0.14.x — Judgement

Feature freeze, release qualification, documentation, install/upgrade testing, beta feedback, and final regression work.

1.0 — The World

Stable complete Calibre-plugin release. The World should contain little or no major new feature work beyond what has already survived Judgement.

Current Development Principles

Current Development Principles

Stability first

Preserve working CBZ creation, metadata, covers, Portrait, Landscape, reading direction, and page-pairing behavior unless a change is intentional and tested.

Keep source, language, authentication, and network failures non-blocking.

No network work on the GUI thread.

No heavy image processing on the GUI thread.

Cancel or invalidate obsolete asynchronous jobs.

Cache thumbnails and preview source pages.

Lazy-load offscreen images and provider icons.

Avoid unnecessary API calls.

Bound caches by size.

One failed source must never freeze MangaNana.

One slow source must not prevent other sources from returning results.

New systems should be added through small, reversible changes where practical.

Add regression tests for bugs that have already occurred.

Branching and development

main remains public/stable.

dev remains the active integration branch.

Larger work uses feature branches from dev.

Public behavior should not change during internal refactors unless explicitly intended.

Development builds should use semantic versioning plus the active Tarot codename. Do not include timestamps in the visible MangaNana version/build identifier.

Normal development and Calibre testing should run non-elevated. Administrator sessions are for repair only.

Current 1.0 Scope

The active roadmap ends with the Calibre plugin.

Target features:

stable MangaDex baseline

expanded regression suite

MangaNana Core extraction

provider/connector architecture

large English-capable source catalog

multi-source search and ranking

explicit Volume or Chapter search/output modes

careful mixed-source fallback

three-stage book-style UI: Choose Manga / Book Customization / Finalization

optional Portrait/Landscape Live Preview

contrast, saturation, gamma, grayscale, and resolution processing

dithering

reusable processing presets

eReader preview/emulation

source authentication/configuration

configurable MangaNana UI scaling

final orientation/pairing accuracy review

GitHub release update checker

README/search-discoverability pass

release qualification and regression testing

Not part of the current 1.0 target:

standalone MangaNana

standalone local library

direct eReader transfer outside Calibre

standalone device synchronization

mobile/Android frontend

Track 0: Stabilize the Current Plugin

Goal

Maintain a dependable baseline while the new architecture is introduced.

Current focus

Continue beta testing across Windows and macOS.

Test multiple Calibre versions.

Test Windows display scaling at common DPI levels.

Test MangaNana interface scaling independently from OS scaling.

Test long manga series.

Test manga with only standalone or chapter-level releases.

Test missing covers.

Test unavailable preferred languages.

Test Portrait and Landscape workflows.

Test bounded Portrait and Landscape Live Preview.

Test cancellation and network failure paths.

Test direct source URLs.

Test existing books already present in Calibre.

Configuration resilience

The plugin should start safely when preferences are:

missing

partially populated

from an older version

malformed

unreadable due to a filesystem/ACL problem

A damaged or unreadable settings file should not make the entire plugin impossible to load.

Completion criteria

The plugin should:

remain responsive during search and download operations

recover cleanly from source/network errors

avoid stale Preview or Finalization state

avoid layout overlap at common DPI/UI scales

package valid CBZ files consistently

import completed books into Calibre reliably

preserve metadata and cover behavior

clean temporary data after cancellation or failure

provide useful Activity Log output

Track 1: Regression Testing and MangaNana Core Extraction

Phase 1A: Regression test foundation

Maintain and expand saved-fixture tests so core behavior does not depend on live websites.

Priority areas:

title localization

metadata normalization

volume normalization and numeric sorting

decimal volume/chapter handling

standalone chapter ordering

duplicate chapter handling

unavailable-language handling

download-plan generation

cover fallback

CBZ page ordering

page-pairing logic

direct URL routing

source failure isolation

auxiliary cover exclusion

EXIF normalization

preview/final processing consistency

Known regression cases should remain represented even when the final solution is deferred.

Phase 1B: Core extraction

Gradually move Calibre-independent logic out of main.py.

Target direction:

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

Early extraction targets:

localization helpers

volume/chapter normalization

chapter sorting

metadata normalization

CBZ naming

page pairing

image processing

source-independent download planning

Do not attempt a full rewrite. Move one logical group at a time and protect it with tests.

Track 2: Source Adapter Architecture

Goal

Remove MangaDex-specific assumptions from the rest of MangaNana and make adding another supported website primarily a connector task.

MangaDex remains the first implementation, but the architecture should assume dozens or hundreds of possible connectors.

Conceptually:

SourceAdapter
├── MangaDexSource
├── MangaPillSource
├── WeebCentralSource
├── SourceD
└── ...

Adapter responsibilities

Each source adapter owns the quirks of one provider:

URL recognition

search

metadata normalization

languages

volume inventory

chapter inventory

page discovery

image retrieval

covers

authentication requirements

provider-specific headers/tokens/cookies

pagination

rate-limit handling

source-specific errors

The rest of MangaNana should not need provider-specific if/elif logic.

Core adapter contract

Conceptually:

class SourceAdapter:
    source_id: str
    name: str
    languages: set[str]
    capabilities: set[str]
    adult: bool
    auth_type: str

    def matches_url(self, url):
        ...

    def search(self, query, mode):
        ...

    def get_manga(self, ref):
        ...

    def get_volumes(self, manga, language):
        ...

    def get_chapters(self, manga, language):
        ...

    def get_pages(self, chapter):
        ...

    def get_cover(self, item):
        ...

    def fetch_image(self, page):
        ...

    def check_health(self):
        ...

Methods and models may evolve, but the responsibilities should remain clear.

Source metadata

Each connector should declare locally:

stable source ID

display name

local source logo/icon

English support

additional supported languages

adult-content status

capabilities

authentication type

connector version

last verified/known compatibility metadata where useful

Provider logos should be stored locally when licensing/use permits and normalized to a consistent display size. Missing icons should use a safe generated fallback.

Proof of architecture

Before adding many connectors, MangaDex should operate cleanly through the adapter abstraction with no visible behavioral regressions.

Track 3: Source Registry, Source Catalog, and Provider UI

Goal

Support a HakuNeko/HaruNeko-style large provider catalog without forcing the user to look at or ping every source.

Supported versus enabled

MangaNana may ship with a large catalog of supported connectors.

Only a small subset is enabled for normal search.

Conceptually:

Supported Sources
├── Enabled
│   ├── MangaDex
│   ├── Source B
│   └── Source C
│
└── Available in Source Search
    ├── Source D
    ├── Source E
    ├── Source F
    └── ...

Removing a source from the active set disables it; it does not uninstall the connector.

The source remains discoverable through Source Search and can be re-enabled.

Initial catalog target

Research and maintain up to roughly 50 high-value connectors initially.

Prioritize:

English-capable sources

currently live sites

manga/manhwa/manhua sources

useful inventory

reasonably stable connector behavior

sites that complement rather than merely duplicate MangaDex

Do not include novel-only or anime-only connectors in the MangaNana catalog.

The architecture should scale beyond 50 connectors later without redesigning the UI.

Default enabled sources

Target three strong default sources.

Current default-enabled sources:

MangaDex

MangaPill

WeebCentral

Future default-source changes should be made only after connector validation, inventory comparison, and stability testing.

Adult sources

Adult content is hidden by default.

Preference:

Index 18+ sources: Off

When disabled:

adult-only connectors do not appear in Source Search

adult-only connectors are not queried

adult results from mixed/general sources should also be filtered when identifiable

direct URLs to adult-only connectors should explain that 18+ source indexing is disabled

When enabled:

adult connectors become discoverable

the user still chooses which adult sources to enable

enabling adult indexing does not automatically enable every adult source

Adult filtering therefore exists at both connector level and, where possible, title/result level.

Lazy health checks

Do not ping the full supported catalog.

Unselected sources should normally display:

Not checked

Only enabled/selected sources receive runtime health checks.

Health state should be cached and should consider recent reliability, not just one ping.

Possible states:

Excellent
Good
Degraded
Unreachable
Login required
Session expired
Not checked

"Strength" means connector health/reliability, not manga inventory or image quality.

Configure Sources

Page 1 should include a Configure Sources action.

Persistent source configuration may include:

enabled/disabled state

sign in/sign out

authentication status

API key/token fields when required by that connector

test connection

clear saved session/cookies

source-specific options

optional source-language restrictions

last known health/reliability

connector version/last verified details under Advanced

Ordinary manga searches should not require opening this screen.

Track 4: Authentication and Source Configuration

Goal

Allow providers with authentication requirements to work without making users log in every session.

Connector-defined authentication

A connector may declare:

no authentication

username/password session

token

API key

OAuth/account authorization

other provider-specific requirements

Authentication UI should be centralized through Configure Sources while each connector defines what fields/actions it needs.

Persistence and security

Where technically possible:

save authenticated sessions securely

reuse valid sessions between Calibre/MangaNana launches

detect expired sessions

isolate authentication failure to the affected source

never write credentials, tokens, cookies, or authorization headers to the Activity Log

redact secrets from error reporting

avoid storing raw secrets in ordinary MangaNana JSON preferences where a safer local mechanism is practical

Track 5: Volume and Chapter Search / Output Modes

Goal

Support manga organized by volumes, chapters, or both.

MangaNana must not require reliable volume metadata just to download a title.

Explicit search mode

Before each search, the user deliberately chooses:

Mode:
[ Volumes ] [ Chapters ]

There is no default.

Before either option is selected, the workflow should remain generically Manga-oriented and must not pretend the user is already in a Volume or Chapter context.

Changing modes clears the old discovery context and selections but preserves the typed query. It does not automatically search.

Volume mode

show available volumes

select individual volumes directly

compact Select All / Clear actions

create one CBZ per selected native volume

preserve existing volume metadata/cover behavior

Do not require a separate Volume Range UI.

Example:

Chainsaw Man (Official Colored) (Vol. 01)

Chapter mode

show a scrollable chapter list

select individual chapters directly

compact Select All / Clear actions

allow downstream Chapter Output strategies during Finalization:

Build CBZs from trusted Volume Data

Manually Group Chapters into Volumes

Save Each Chapter as Its Own CBZ

Do not require a separate chapter range-selector UI.

Example individual output:

Chainsaw Man (Official Colored) (Ch. 01)

Chapter files should use the same Calibre series structure as volume files so a chapter-based reader can keep the entire series ordered consistently.

Internal model

Do not force every title into volumes.

Conceptually:

Manga
↓
Edition
↓
Language
↓
Volume / Chapter Structure
├── Volumes → Chapters → Pages
└── Chapters → Pages

A source may expose:

volumes and chapters

chapters only

volumes synthesized from chapter metadata only when complete, trustworthy explicit mapping exists

get_volumes() may legitimately return no useful volume structure while get_chapters() remains fully functional.

Chapter covers

Chapters often lack distinct cover art.

High Priestess preserves current cover fallback behavior.

Future cover-label/generation controls are not required for High Priestess and may be developed in later milestones.

A generated chapter-number cover, if implemented later, must remain metadata/cover material only and must never enter the reading-page sequence or shift pairing parity.

Track 6: Multi-Source Search, Identity, Ranking, and Fallback

SourceCoordinator

The adapter understands one website.

The SourceCoordinator understands many.

Conceptually:

SourceCoordinator
├── parallel search
├── provider-terminal display barrier
├── provider-local result normalization
├── permissive ranking
├── failure isolation
├── same-provider exact-ID deduplication
├── inventory resolution
└── conservative fallback

Search behavior

Search only enabled sources.

Providers run independently and concurrently.

Initial combined rendering waits for every requested content provider to reach a terminal state:

succeed
fail
timeout
cancel

Then MangaNana ranks and renders the combined provider-local result set once.

Provider response speed must not determine visible ranking.

External enrichment such as AniList/Kitsu is not part of the provider display barrier and must not delay provider-result rendering.

Late enrichment may attach safe metadata, but it must not remove, reorder, or provider-replace already visible search results.

Provider-local result authority

Do not visually merge or deduplicate across providers.

These are separate selectable records:

JoJolion — MangaDex
JoJolion — MangaPill
JoJolion — WeebCentral

Different editions from one or several providers also remain distinct.

Same-provider duplicate immutable IDs/URLs may be deduplicated.

Canonical identity remains useful internally for aliases, compatibility checks, fallback, and metadata, but uncertainty should result in less merging rather than hidden provider choices.

Search admission and ranking

Provider-returned candidates should generally remain visible unless clearly invalid or deliberately filtered by policy.

Ranking primarily changes order, not existence.

Prioritize:

normalized exact/alias relationship
→ phrase/token relevance
→ explicit edition intent
→ Prefer Colored where relevant
→ deterministic provider-local/order signals

Popularity/enrichment signals are subordinate.

Fallback

Automatic provider fallback remains allowed when the selected source cannot provide usable content and a sufficiently compatible source can.

Fallback should:

preserve work/edition/language safety

avoid unnecessary source alternation

remain transparent in visible source state and Activity Log

never treat merely sharing a franchise as sufficient equivalence

Language fallback

A source may advertise English metadata while no downloadable English pages remain.

MangaNana should:

distinguish advertised language metadata from usable downloadable inventory

avoid auto-selecting an unusable language

use another compatible enabled source if it has the requested language

otherwise clearly explain that the requested language is unavailable

Unavailable language must never create a dead-end workflow.

Direct URLs

If a user pastes a direct title URL:

detect whether a registered connector owns the URL

route the title directly to that connector

create/select a visible temporary provider result card in the normal results model

load the exact provider inventory

A supported but disabled source may be used for that direct request without permanently enabling it.

If unsupported, explain that the website is not currently supported and point users toward the source-request path where practical.

Track 7: Three-Stage Book-Style Interface

Goal

Keep MangaNana understandable as provider count and output capabilities grow.

The High Priestess application uses three mutually exclusive, book-inspired stages:

1. Choose Manga
2. Book Customization
3. Finalization

The book metaphor is visual structure only.

Back/Next controls remain conventional.

Do not use page curls, drag gestures, or realistic page-turn interaction.

The two primary panes should remain roughly equal width with a narrow centered gutter.

The MangaNana logo/title and stage navigation share the same horizontal center axis. The independently right-aligned version string must not displace that center.

Stage 1: Choose Manga

Left page:

compact discovery controls

Mode: Volumes / Chapters with no default

Download Language

Prefer Colored

Direct Link

large scrollable Search Results area capable of showing roughly 6-8 compact result cards at normal window size

Right page:

Selected Manga summary

proportional cover

clear structured metadata such as author, source/edition pills, explicit rating where cheaply available

chapter/volume inventory

compact Select All / Clear

selection count

No Volume Range UI.

Before a mode is selected, mode-specific areas use generic Manga wording instead of claiming Volumes or Chapters.

Stage 1 answers:

Which exact manga/provider record do I want?

Which chapters or volumes do I want?

Stage 2: Book Customization

Left page: Reading & Layout

Portrait — Individual Pages

Landscape — Paired Pages

RTL / LTR reading direction

Right page: Live eReader Preview

Preview is optional and OFF by default.

Entering Book Customization does not fetch preview pages.

Enable Live Preview is the explicit network action.

High Priestess preview supports both:

bounded individual-page Portrait preview

bounded paired-page Landscape preview

High Priestess does not implement the Empress processing workstation, named presets, or eReader Device Simulator.

Stage 2 answers:

How should this manga be presented for reading?

Stage 3: Finalization

Left page: Book Creation & Metadata

Chapter Output strategy when Chapter mode requires it

Manual Grouping entry/summary where relevant

relevant naming controls such as zero padding

bulk-editable Title

bulk-editable Series

bulk-editable Author

Calibre destination

existing cover behavior

Do not add language editing here.

Do not add a new per-output metadata editor or cover editor during High Priestess.

Right page: Final Outputs

Show the planned books MangaNana will create.

Keep useful aggregate information such as:

file/output count

estimated pages

estimated size

layout

language

The existing compact output table/list is acceptable; decorative cover thumbnails are not required.

Stage 3 answers:

How should these books be packaged and identified?

What exactly will MangaNana create?

Stage isolation

Only one stage body may exist visibly at a time.

Going Back must completely hide downstream containers.

Changing upstream selection/layout may mark downstream state stale, but must never rebuild/show Finalization automatically.

This regression requires explicit automated coverage.

Activity Log and progress

Idle presentation should remain compact.

Do not leave completed full-width progress bars permanently visible.

Search status belongs to Choose Manga.

Preview status belongs to Book Customization.

Final output/download status belongs to Finalization.

Detailed Activity Log, Copy Log, and Save Log remain available when expanded.

Hover descriptions

Remove the custom explanatory hover-description/text-box system from ordinary workflow controls.

Do not rely on tooltips to explain basic fields or buttons.

Use clear labels, inline helper text where necessary, disabled-state reasons, contextual status, or Activity Log messages instead.

Navigation validation

Stage 1 requires:

mode chosen

manga selected

usable inventory resolved

at least one volume/chapter selected

Stage 2 requires:

valid reading/layout settings

Preview is never required.

Stage 3:

Download & Add to Calibre becomes available when the final output configuration is valid.

Responsive book layout

maintain stable left/right proportions

keep the center gutter subtle and truly centered

preserve MangaNana's modern dark visual language

avoid excessive orange outlining on inactive controls

scroll complex pane contents internally rather than stretching controls indefinitely

avoid overlap/clipping at supported window sizes

Track 8: Interface Scaling

Goal

Allow users to adjust MangaNana independently from OS display scaling.

Preferences:

Interface Scale:
Auto
50%
75%
90%
100%
110%
125%
150%
175%
200%

Default may be Auto or 100% depending on implementation behavior.

Requirements:

scale fonts, icons, margins, buttons, and layout consistently

preserve book/spread proportions

enforce minimum usable control sizes

persist the preference

remain independent from Windows/macOS DPI scaling

avoid clipped controls at supported scales

Release testing should cover representative combinations of OS scaling and MangaNana scaling.

Track 9: Live Preview Engine

Goal

Provide visual feedback for output/layout and later image-processing settings without forcing preview downloads on users who do not need them.

High Priestess baseline

Live eReader Preview lives on the right side of Book Customization.

It is optional and OFF by default.

Opening Book Customization must not automatically fetch preview pages.

Only Enable Live Preview or an equivalent explicit action begins preview acquisition.

The bounded High Priestess implementation must render inside the Stage 2 preview pane rather than opening a separate preview window.

It must support:

Portrait — individual page preview

Landscape — paired page preview

The old historical Pairing Preview limitation must not make Portrait preview unavailable.

Run network/rendering work outside the GUI thread.

Cancel or invalidate obsolete preview jobs.

Do not allow late preview responses to overwrite newer user intent.

Preview failure never blocks Finalization/download.

The Empress expansion

0.12.x — The Empress turns this same Stage 2 workspace into the advanced processing preview environment.

Planned Empress behavior:

download a small representative set of source pages explicitly

cache/reuse source samples for the session

display processed preview pages at a useful large size

support a vertically scrollable preview workspace

reuse source samples while image controls change

debounce rapid processing changes

render only the newest state

share processing functions with final CBZ output

Named presets and the eReader Device Simulator are Empress features, not High Priestess features.

Shared processing pipeline

Preview and final CBZ should converge on the same underlying processing functions.

Conceptually:

Source image
→ normalization/layout
→ MangaNana processing
→ dither/quantization
→ final output image

Preview may use performance-conscious representations where necessary, but processing behavior should not intentionally drift from final output.

Potential comparison modes can be evaluated during Empress and later milestones rather than being required for High Priestess.

Track 10: Image Processing — The Empress

Goal

Allow users to optimize manga for an eReader without requiring an external image editor.

Default:

Original

MangaNana should not intentionally alter source artwork unless the user requests processing.

Initial controls

Contrast

Saturation

Gamma

Grayscale

Resolution scaling

Dithering

Potential later controls:

brightness

sharpening

black point

white point

JPEG quality

noise reduction

Do not expose every advanced control in the default interface.

Processing order

The order must be deliberate and tested.

Initial direction:

Decode
→ EXIF/orientation normalization
→ layout/resize to target dimensions
→ color/grayscale conversion
→ gamma/contrast/saturation adjustments
→ palette/bit-depth quantization where applicable
→ dithering
→ encode

Dithering should normally occur after resizing so later resampling does not destroy the dither pattern or create additional moiré.

Track 11: Dithering — The Empress

Goal

Improve grayscale and limited-color output on eReader displays while preserving manga line art and screentones.

Initial visible algorithms

None

Atkinson

Floyd-Steinberg

Bayer 4x4

Bayer 8x8

Backend/experimental candidates

Sierra Lite

Burkes

Stucki

Jarvis-Judice-Ninke

Blue noise

Do not expose every experimental algorithm in the normal UI unless testing shows a clear benefit.

Dither strength

Custom processing should support a Dither Strength control where the algorithm permits a meaningful implementation.

Evaluation pages

Test against:

clean B&W line art

dense screentones

grayscale shading

gradients

dark pages

detailed backgrounds

full-color manga

Watch specifically for:

moiré

destroyed screentones

lost line detail

crushed blacks

blown highlights

excessive noise

preview/final inconsistencies

Open-source research references

Study conceptually:

Kindle Comic Converter, for manga/eReader processing workflow

DitherSpace, for live dither controls and preview UX

Dithering Studio, for broad algorithm comparison

Didder, for algorithm/reference implementation ideas

Cyotek Dithering, for visual comparison examples

Reuse ideas and algorithms only in ways compatible with applicable licenses. MangaNana should keep its own processing architecture.

Track 12: Processing Presets — The Empress

Goal

Let users reuse known-good combinations without opening Live Preview every time.

Initial built-in presets:

Original

Manga B&W

Smooth Grayscale

Crisp eInk

Custom

Users should also be able to save and name their own presets containing combinations such as:

Contrast
Saturation
Gamma
Grayscale
Dithering algorithm
Dither strength
Resolution/output profile

Saved presets should be editable and removable.

A user who already knows the preset they prefer should be able to select it on Book Customization and proceed without loading preview pages.

Track 13: eReader Device Simulator — The Empress

Goal

Let users estimate how processed manga may appear on a target display by applying a preview-only simulation layer over the Live eReader Preview workspace.

The eReader Device Simulator is preview-only.

Its control should live at the top of the Live eReader Preview workspace so the user can enable/select a simulator profile without creating a separate preview system.

It must never alter the final CBZ unless corresponding processing options are separately enabled.

Pipeline:

Final CBZ image
→ optional display simulation
→ Live Preview

Initial profile direction:

No Simulation

Generic B&W eReader

Generic Color eReader

Kobo Libra Colour

Additional major Kobo/Kindle profiles may be added after their approximation rules are researched and validated.

Potential simulation characteristics:

reduced saturation

grayscale response

approximate e-ink contrast

approximate color-gamut reduction

mild display tint

reduced apparent sharpness

resolution/pixel-density approximation

Device-specific profiles must be clearly described as approximations.

Appearance varies with firmware, front-light settings, ambient lighting, calibration, and individual panels.

Track 14: Finalization Panel Expansion

Goal

Make the last stage answer:

How should these books be packaged and identified?

What exactly is MangaNana about to create?

High Priestess baseline

Left page:

Chapter Output strategy where relevant

Manual Grouping where relevant

relevant naming options

bulk Title

bulk Series

bulk Author

destination

existing cover behavior

Bulk metadata edits apply to the current job rather than forcing users to edit each planned output individually.

Language remains a Choose Manga decision.

Do not add a High Priestess cover editor.

Right page: Final Outputs

Potential entry:

JoJolion Vol. 04

Source: MangaDex
Language: English
Pages: 226
Output: Landscape
Estimated size: ~93 MB

Keep source attribution subtle but accurate.

Keep aggregate page count and estimated-size information.

For Chapter mode, Final Outputs should make file output unambiguous.

Example:

JoJolion (Ch. 037).cbz
JoJolion (Ch. 038).cbz
JoJolion (Ch. 039).cbz

3 CBZ files

Track 15: Provider Validation and Connector Expansion

Goal

Grow the connector catalog carefully rather than blindly porting every HakuNeko provider.

Initial research strategy

Use HaruNeko/HakuNeko as a connector-pattern reference.

Study:

source abstraction

connector registry/discovery

URL validation

manga lookup

chapter enumeration

image URL extraction

authentication handling

error handling

rate limiting

shared connector helpers/decorators

source-specific quirks

Do not:

import the entire HakuNeko architecture

couple MangaNana to HakuNeko's runtime/UI

import anime/novel functionality

blindly port every connector

sacrifice MangaNana's simpler Calibre workflow

Validation criteria

Before calling a connector production-ready, verify:

Can reach source
Can search
Can resolve a title
Can enumerate volumes and/or chapters
Can resolve pages
Can retrieve an image
Can fail without blocking other sources

Maintain connector fixtures where practical and limited live smoke tests for actual site compatibility.

Initial candidate pool

Research up to roughly 50 English/live providers.

High-priority candidates currently include:

MangaDex

MangaFire

MangaPill

WeebCentral

MangaKatana

MangaTown

MangaFreak

MangaFox

MangaHere

MangaBat

MangaKakalot

MangaNato

MangaGo

ManhwaTop

ManhuaPlus

S2Manga

Toonily

AsuraScans/AsuraToons

FlameComics

HiveScans

other validated English-capable HaruNeko connectors

Official/licensed services should be treated as a separate connector class because access rules, authentication, subscriptions, and download restrictions may differ significantly.

Examples:

MANGA Plus

VIZ Shonen Jump

Manga UP! Global

Comikey

WEBTOON

Tapas

Tappytoon

Toomics

A connector being technically representable does not automatically mean MangaNana should support downloading from it. Access rules must be evaluated per service.

Track 16: Release Qualification and Beta Testing

Maintain a repeatable release qualification checklist instead of relying on random manual tests.

Core workflow

Test:

title search

direct URL

Volume mode

Chapter mode

Choose Manga → Book Customization → Finalization

download/add to Calibre

cancellation

restart/stale-state behavior

stage isolation after Back navigation

changing Stage 1 selection after visiting Finalization does not resurrect downstream panels

changing Portrait/Landscape after visiting Finalization does not resurrect downstream panels

Finalization rebuild occurs only on explicit forward navigation

no explanatory hover-description boxes on ordinary workflow controls

Portrait Live Preview works without switching to Landscape

Volume edge cases

one volume

very long series

decimal volumes

missing volume numbers

missing covers

standalone chapters

already-present Calibre volumes

incomplete source inventory

Chapter edge cases

chapter-only titles

hundreds of chapters

decimal/special chapters

named/unnamed chapters

missing chapter covers

direct individual selections

Select All / Clear

Chapter Output grouping

Multi-source cases

same manga on one source

same edition on several sources

different editions across sources

full inventory on one source

partial inventory on another

complementary gaps

slow provider

dead provider

mixed-source fallback

Language cases

English available

English advertised but pages unavailable

requested language absent

another source has requested language

fallback works without dead-end UI

Provider UI

defaults

disable/re-enable

Source Search

provider logos

missing-logo fallback

lazy health checks

cached health

Configure Sources

supported disabled direct URL

unsupported direct URL

source request action

Authentication

initial login

persistence

restart

expiration

logout

bad credentials

revoked token

failure isolation

secret redaction

CBZ integrity

valid archive

page order

metadata

title

series

series index

author

cover

no auxiliary/helper files in reading sequence

no duplicate/missing pages

cleanup after completion/failure

Preview/processing

preview remains optional

opening Book Customization does not fetch preview pages

Enable Live Preview fetches only bounded sample pages

session cache works

rapid controls do not freeze UI

preview and final output use same processing pipeline

presets work without preview

Dithering

Test line art, screentones, gradients, dark pages, detailed pages, and color pages against all visible algorithms.

Platform/UI

At minimum:

Windows

macOS

current Calibre

one older supported Calibre version

representative OS DPI scales

representative MangaNana UI scales

Track 17: Permanent Regression Cases

Keep concrete edge cases represented in automated or repeatable smoke tests.

Required cases include:

advertised-but-undownloadable English inventory

complete source preferred over partial source

gap-only mixed-source fallback

color and B&W editions remain distinct

Volume versus Chapter mode

chapter-only source

provider failure isolation

supported/disabled/unsupported direct URL behavior

expired authentication

adult-source filtering

disabled sources are not health-pinged

chapter cover fallback does not change reading-page order

auxiliary cover exclusion

Live Preview optionality

Portrait and Landscape preview availability

stage-container mutual exclusion

upstream changes mark downstream state stale without showing/rebuilding it

preview/final processing consistency

deterministic dithering where expected

screentone/moiré samples

UI scaling

known JoJolion orientation case

The JoJolion case should remain a regression reference even though the final orientation solution is intentionally deferred.

Track 18: Final Page Orientation and Pairing Accuracy Pass

Goal

Revisit difficult orientation and pairing edge cases after the major 1.0 feature work is complete.

This pass occurs near the end of the active roadmap, before the release update checker.

Focus

re-evaluate EXIF-based orientation handling

compare full-quality and data-saver source images

do not assume EXIF alone always represents intended page presentation

distinguish genuine spreads from sideways portrait pages

verify Preview and final CBZ behavior

test known JoJolion sideways-page cases

avoid dimension-only or edge-based rotation heuristics

preserve legitimate landscape artwork/spreads

maintain reading-direction and pairing parity

add regression tests for newly confirmed fixes

Completion criteria

known sideways-page cases render correctly

genuine spreads are not incorrectly rotated

Preview and final output use consistent orientation rules

the fix is not overfitted to one manga/page

auxiliary covers cannot affect pairing parity

Track 19: GitHub Release Update Checker

Goal

Let users know when a newer MangaNana plugin release is available.

Behavior

On MangaNana startup:

open MangaNana
→ consult cached update state
→ if check is due, query GitHub Releases in background
→ compare versions
→ notify only if a newer applicable release exists

Requirements:

never block startup

cache checks, approximately 12-24 hours

proper semantic version comparison

default to stable releases

optionally support a prerelease channel

show a non-blocking update notice

provide a link to the GitHub Release

initial implementation does not auto-install updates

network errors/rate limits/malformed responses silently fail or log a low-level message

development builds should not incorrectly nag about stable releases

Preferences:

Check for MangaNana updates automatically
Update channel: Stable / Prerelease
[ Check Now ]

Track 20: README, Search Discoverability, and Release Messaging

Product positioning

Primary message:

MangaNana is a Calibre plugin that lets you find, download, prepare, and add manga to your Calibre library without leaving Calibre.

The main appeal is downloading and adding manga within one Calibre workflow.

Secondary message:

MangaNana can also handle volume/chapter output, metadata, covers, page layout, image processing, and eReader-oriented optimization before adding the files to the library.

Search/discoverability language

Use natural language around real user queries without keyword stuffing.

Important phrases/topics include:

Calibre manga plugin

manga downloader for Calibre

download manga directly into Calibre

add manga to Calibre automatically

MangaDex Calibre plugin

multi-source manga downloader

manga volume downloader

manga chapter downloader

download manga as CBZ

manga to CBZ

manga metadata for Calibre

manga covers in Calibre

manga for Kobo

manga for Kindle

manga downloader for eReader

manga for e-ink / color e-ink

manga page pairing

manga dithering / grayscale optimization

Use these naturally in descriptions and examples.

Search-oriented FAQ

README should answer questions such as:

How can I download manga directly into Calibre?

Is there a MangaDex plugin for Calibre?

Can Calibre download manga chapters?

Can I download complete manga volumes with Calibre?

How do I put manga on a Kobo using Calibre?

Can MangaNana search more than one manga source?

The goal is explicit, accurate language that helps both people and retrieval/recommendation systems understand when MangaNana is relevant.

GitHub metadata

Maintain an accurate repository description and topics such as:

calibre
calibre-plugin
manga
manga-downloader
mangadex
cbz
ereader
kobo
kindle
eink
comic-downloader

Do not claim unsupported functionality for discoverability.

README screenshots

Once the new UI is stable, use three primary screenshots:

Choose Manga

Book Customization + Live eReader Preview

Finalization + Final Outputs

Suggested Active Development Order

The current recommended sequence is:

Finish the High Priestess repair/polish pass without committing until manual qualification succeeds.

Re-run automated regression tests, compile checks, packaging validation, and Calibre installation after the repair.

Manually qualify:

Choose Manga search/discovery

Volume and Chapter mode

Back/Next state preservation

stage isolation

Portrait and Landscape output

Portrait and Landscape Live Preview

Chapter Output strategies

bulk Title / Series / Author metadata

Final Outputs page/size summaries

download/add to Calibre

Preferences and Source Manager

Once High Priestess is stable, freeze the milestone.

Then begin 0.12.x — The Empress:

advanced image processing

large scrollable processed preview

dithering

named processing presets

eReader Device Simulator and profiles

device/output tuning

After Empress:

0.13.x — The Emperor — hardening/reliability

0.14.x — Judgement — feature freeze/release qualification

1.0 — The World — stable release

Provider/catalog expansion, interface scaling, update checking, orientation/pairing accuracy, and documentation work should be scheduled where they best fit these milestones without destabilizing the active release.

Codex Implementation Sequence

Use scoped feature-branch prompts rather than one giant task.

Current prompt sequence:

High Priestess consolidated UI/state repair

High Priestess regression/manual qualification fixes

High Priestess packaging/finalization

Empress preview/processing foundation

Empress image processing and dithering

Empress named presets

Empress eReader Device Simulator

Emperor reliability/hardening

Judgement release qualification

World 1.0 release preparation

Each Codex task should:

inspect existing behavior first

read UX_PHILOSOPHY.md before user-facing changes

make the smallest architectural change that satisfies the task

preserve working behavior unless intentionally changed

add/update relevant tests

run the relevant test suite

summarize changed files and test results

avoid committing, pushing, tagging, or releasing unless explicitly requested

Post-1.0 / Inactive Long-Term Ideas

These are retained as future ideas but are outside the current roadmap completion target.

Potential later directions:

standalone MangaNana frontend

standalone local manga library/database

direct eReader transfer without Calibre

library/device synchronization

new-volume monitoring for a standalone library

smart per-page monochrome detection

adaptive page processing

advanced manual pairing editor

metadata reconciliation

richer provenance/history

automatic device-based profile selection

These should not delay completion of the Calibre plugin roadmap.

UI Design Principles

The default experience should remain simple even if MangaNana supports many sources.

Prefer:

one obvious next action

progressive disclosure

clear defaults where a default is appropriate

explicit choice where user intent matters, such as Volume versus Chapter search

stable geometry

optional advanced controls

provider complexity hidden until needed

readable and recoverable errors

source attribution without forcing manual source management

optional preview rather than mandatory preview downloads

Avoid:

exposing hundreds of providers at once

pinging disabled sources

making users understand provider implementation details

mixing volume and chapter selectors in the same visible state

turning Finalization into a debugging screen

moving controls during asynchronous loading

unexplained technical terminology

silent edition merging when confidence is weak

The complexity belongs in the architecture.

The user experience should remain:

Choose Manga
→ choose Volumes or Chapters
→ choose what to download
→ customize reading/layout and optionally preview
→ finalize book creation and bulk metadata
→ verify Final Outputs
→ download and add to Calibre
