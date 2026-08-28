MangaNana Development Roadmap

MangaNana is a Calibre plugin for finding, downloading, preparing, and adding manga directly to a Calibre library without leaving Calibre.

The current goal is a strong Calibre-plugin release. Standalone MangaNana, local-library management, direct device sync, and other standalone-only systems are post-1.0 ideas and are not part of the current completion target.

The immediate priority is to preserve the working core while expanding MangaNana into a multi-source, volume-or-chapter workflow with optional image processing and eReader-oriented preview tools.

The primary user flow remains:

Source
→ Download Settings
→ Review
→ Download & Add to Calibre

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

Development builds should keep a visible build identity using the Git commit plus build timestamp.

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

three-stage book-style UI

optional Live Preview

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

Test Pairing Preview.

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

avoid stale Preview or Review state

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
├── MangaFireSource
├── SourceC
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

Provisional candidates:

MangaDex

MangaFire

MangaPill

WeebCentral remains a strong alternate candidate.

Final defaults should be selected after connector validation, inventory comparison, and stability testing.

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

Search for:
[ Volumes ] [ Chapters ]

There is no default.

This is a conscious per-search choice so results can be ranked and presented according to the desired output type.

Volume mode

show available volumes

select individual volumes

select ranges

Use Entire Series / Deselect All

create one CBZ per selected volume

preserve existing volume metadata behavior

Example:

Chainsaw Man (Official Colored) (Vol. 01)

Chapter mode

show a scrollable chapter list rather than hundreds of volume-style tiles

support chapter filtering/search

select individual chapters

select ranges

Select All / Deselect All

create one CBZ per selected chapter

Example:

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

volumes synthesized from chapter metadata when reliable

get_volumes() may legitimately return no useful volume structure while get_chapters() remains fully functional.

Chapter covers

Chapters often lack distinct cover art.

Potential options:

Chapter covers:
- Use source/series cover unchanged
- Add chapter-number badge when needed
- Always add chapter-number badge

A generated chapter-number cover must remain metadata/cover material only and must never enter the reading-page sequence or shift pairing parity.

Track 6: Multi-Source Search, Identity, Ranking, and Fallback

SourceCoordinator

The adapter understands one website.

The SourceCoordinator understands many.

Conceptually:

SourceCoordinator
├── parallel search
├── normalization
├── progressive results
├── failure isolation
├── deduplication
├── inventory comparison
├── provider ranking
└── fallback

Search behavior

Search only enabled sources.

Providers should run independently.

Do not wait for every provider before showing results.

MangaDex results arrive
→ display

MangaFire arrives later
→ merge/update

Source C fails
→ report non-blocking status

Canonical manga identity

The same edition available from multiple providers should normally appear as one result when confidence is sufficient.

Example:

JoJolion

Available from 3 selected sources

Matching signals, strongest first:

shared external/publication IDs

exact normalized titles

alternate titles

author

series/part information

fuzzy title matching as supporting evidence

False merges are worse than duplicate cards.

Editions remain distinct

Different editions must remain separately identifiable in results.

Examples:

official colored edition

normal B&W edition

omnibus/special edition

materially different translation/release when identifiable

A color edition and B&W edition must not be merged simply because the base title matches.

Provider ranking

The user chooses which sources are enabled.

Once selected, MangaNana makes ranking decisions automatically.

For Volume mode, prioritize approximately:

requested inventory completeness
→ requested language availability
→ source reliability/health
→ image/page availability
→ source priority/tie breakers

For Chapter mode, chapter completeness replaces volume completeness as the primary inventory signal.

If one source has the full requested catalog and another is partial, prefer the complete provider.

Mixed-source fallback

Mixed-source jobs are allowed and are a benefit of the architecture, but they should be conservative.

Preferred behavior:

satisfy the requested job from one strong source when possible

use another source when the preferred source is missing requested items

avoid unnecessary alternation between providers

preserve edition/language consistency

show source attribution in Review

Example:

Vol. 01-10  Source A
Vol. 11     Source B
Vol. 12-20  Source A

Language fallback

A source may advertise English metadata while no downloadable English pages remain.

MangaNana should:

distinguish advertised language metadata from usable downloadable inventory

avoid auto-selecting an unusable language

use another enabled source if it has the requested language

otherwise clearly explain that the requested language is unavailable

Unavailable language must never create a dead-end workflow.

Direct URLs

If a user pastes a direct title URL:

detect whether a registered connector owns the URL

route the title directly to that connector

a supported but disabled source may be used for that request without permanently enabling it

optionally offer Enable this source

If unsupported:

This website is not currently supported by this version of MangaNana. If you would like it considered as a future source, open a Source Request on GitHub.

Provide a direct source-request action when practical.

Track 7: Three-Stage Book-Style Interface

Goal

Keep MangaNana understandable as provider count and processing features grow.

The application becomes a three-stage, book-inspired workflow:

1. Source
2. Download Settings
3. Review

The book metaphor is visual/navigation structure, not a requirement for realistic page-turn interaction.

Back/Next controls must remain conventional and obvious.

A short optional transition animation may be used, but interaction must not depend on dragging a page corner or a realistic page curl.

Page 1: Source

Left page

Provider/search setup:

enabled source cards with local logos

source status only for sources that have been checked

Source Search / Add Source

Configure Sources

explicit Volumes or Chapters mode toggle

Right page

Manga and inventory selection:

title search

direct URL entry

merged manga results

Available from N selected sources

edition labels such as COLOR/B&W

volume grid in Volume mode

chapter list/filter in Chapter mode

Page 1 answers:

Where am I getting it from?
What am I getting?

Page 2: Download Settings

Contains output choices, not manga inventory selection.

Potential controls:

Portrait / Landscape

RTL / LTR reading direction

language where relevant

zero padding

cover behavior

output quality/resolution

processing preset

device/output profile

Page 2 answers:

How should MangaNana build it?

Page 3: Review + Optional Live Preview

Left page: Review

Show exactly what MangaNana is about to create:

title/edition

selected volumes or chapters

source attribution

language

output layout

file count

estimated pages

estimated size

fallback sources where used

Right page: Live Preview

The right page is reserved for optional preview/image-processing work.

The user must be able to download without loading preview assets.

Initial state may show:

Live Preview

[ Load Live Preview ]

Only after the user requests preview should MangaNana download representative preview pages.

Navigation validation

Next becomes available only when the current stage has enough valid information.

Page 1:

mode chosen

manga selected

usable inventory resolved

at least one volume/chapter selected

Page 2:

output settings valid

Page 3:

Download & Add available immediately

Live Preview optional

Responsive book layout

maintain stable left/right page proportions

center gutter provides subtle separation

optional subtle stacked-page detail at the outer edge

preserve MangaNana's modern dark visual language

avoid excessive skeuomorphism

scroll complex page contents internally rather than stretching controls indefinitely

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

Provide near-real-time visual feedback for layout and image-processing settings without forcing preview downloads on users who do not need them.

Optional loading

Opening Review must not automatically fetch preview pages.

Only Load Live Preview or equivalent explicit action begins preview acquisition.

Users familiar with their preferred settings may choose a preset and download immediately without previewing.

Representative sample

Target roughly 3-6 useful pages:

cover/first page

title/front matter

normal manga page

darker/heavily shaded page

spread if available

color page when relevant

Preview architecture

run network and rendering work outside GUI thread

download preview source pages once

cache preview pages for the session

reuse cached pages when controls change

debounce rapid control changes

cancel/invalidate obsolete renders

display only newest render result

avoid moving surrounding UI during rendering

Shared processing pipeline

Preview and final CBZ must use the same underlying processing functions.

Conceptually:

Source image
→ normalization/layout
→ MangaNana processing
→ dither/quantization
→ final output image

Preview may use reduced-size copies for responsiveness, but processing behavior should not drift from final output.

Comparison modes

Initial:

Processed

Original / Processed side by side

Potential later:

draggable before/after split

zoomed detail comparison

Track 10: Image Processing

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

Track 11: Dithering

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

Track 12: Processing Presets

Goal

Let users reuse known-good combinations without opening Live Preview every time.

Initial built-in presets:

Original

Manga B&W

Smooth Grayscale

Crisp eInk

Custom

Users should also be able to save their own presets containing combinations such as:

Contrast
Saturation
Gamma
Grayscale
Dithering algorithm
Dither strength
Resolution/output profile

Saved presets should be editable and removable.

A user who already knows the preset they prefer should be able to select it on Download Settings and proceed directly to download.

Track 13: eReader Screen Emulation

Goal

Let users estimate how processed manga may appear on a target display.

Screen emulation is preview-only.

It must never alter the final CBZ unless corresponding processing options are separately enabled.

Pipeline:

Final CBZ image
→ optional display simulation
→ Live Preview

Initial profiles:

No Emulation

Generic B&W eReader

Generic Color eReader

Kobo Libra Colour

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

Track 14: Review Panel Expansion

Review should answer:

What exactly is MangaNana about to create?

Potential entry:

JoJolion Vol. 04

Source: MangaDex
Fallback source: none
Language: English
Pages: 226
Processing: Manga B&W
Output: Landscape
Estimated size: ~93 MB

For mixed-source jobs, source attribution should remain visible but subtle.

For Chapter mode, Review should make file output unambiguous.

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

Source → Download Settings → Review

download/add to Calibre

cancellation

restart/stale-state behavior

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

ranges

Select All / Deselect All

generated chapter-number cover badges

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

opening Review does not fetch preview pages

Load Live Preview fetches only sample pages

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

Source

Download Settings

Review + Live Preview

Suggested Active Development Order

The current recommended sequence is:

Keep the current beta stable and merge validated fixes to dev.

Continue regression/core extraction.

Finish moving MangaDex behavior behind SourceAdapter.

Build SourceRegistry and connector metadata.

Implement/validate the second provider.

Implement/validate the third provider.

Build SourceCoordinator and progressive multi-source search.

Add conservative cross-source identity, inventory ranking, and fallback.

Add explicit Volume / Chapter search and output modes.

Build the three-stage book-style UI.

Add Source Search, Configure Sources, local provider logos, and lazy health states.

Add authentication/session framework as required by supported connectors.

Add MangaNana interface scaling.

Build optional Live Preview.

Add Contrast, Saturation, Gamma, Grayscale, and Resolution processing.

Add built-in and user processing presets.

Add Atkinson, Floyd-Steinberg, Bayer 4x4, and Bayer 8x8 dithering.

Add basic eReader preview/emulation.

Expand/validate the English/live connector catalog toward ~50 strong sources.

Run full beta/release qualification and permanent regression cases.

Perform the final orientation/pairing accuracy review.

Add the GitHub release update checker.

Complete README/search-discoverability/release messaging.

Cut the 1.0 release candidate when the active completion criteria are satisfied.

This order is a guide, not a reason to force an architectural change before it is ready. Multi-source behavior remains the largest integration risk.

Codex Implementation Sequence

Use scoped feature-branch prompts instead of one giant task.

Recommended prompt sequence:

finish MangaDex behind SourceAdapter

SourceRegistry

SourceCoordinator

second provider

third provider

multi-source identity/ranking/fallback

Volume/Chapter modes

three-stage book UI

optional Live Preview

image processing

dithering

eReader emulation

Preferences expansion

final regression pass

orientation/pairing accuracy pass

GitHub release update checker

Each Codex task should:

inspect existing behavior first

make the smallest architectural change that satisfies the task

preserve working UI/behavior unless intentionally changed

add/update relevant tests

run the relevant test suite

summarize changed files and test results

avoid committing unless explicitly requested

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

turning Review into a debugging screen

moving controls during asynchronous loading

unexplained technical terminology

silent edition merging when confidence is weak

The complexity belongs in the architecture.

The user experience should remain:

Find manga
→ choose Volumes or Chapters
→ choose what to download
→ choose how it should be built
→ review
→ download and add to Calibre
