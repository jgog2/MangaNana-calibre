# MangaNana 0.13.0-dev - The Emperor
## Astra High Handoff: CBZ/PDF Import and PDF Export

### Purpose

Implement the first major Emperor feature set as one coherent External Book I/O expansion:

1. Import existing CBZ books.
2. Import existing PDF books.
3. Feed imported books into MangaNana's existing Book Customization pipeline.
4. Export finalized books as either CBZ or PDF.
5. Preserve the existing Volumes and Chapters workflows and their current behavior.

Additional manga sources are explicitly a later Emperor task and are not part of this pass.

This handoff intentionally resolves the product and technical research in advance so the implementation run can spend its effort on architecture, integration, edge cases, and validation rather than rediscovering requirements.

---

# 1. Baseline

Work on:

```text
branch: feature/emperor-expansion
Emperor start commit: 1dd5b73
version: 0.13.0-dev
codename: The Emperor
```

The supplied packaged baseline was inspected:

```text
MangaNana-Calibre-dev(3).zip
SHA-256: 667ae2d0a0ebf902217ea8e1e0040c1e9461118a3b233cdc2cd235b5fb44af17
size: 705,613 bytes
entries: 62
```

That ZIP is the finalized Empress package. The current Emperor branch differs at the milestone boundary only by the version/codename bump, so the packaged code is still representative of the implementation architecture.

The repository is authoritative for implementation and tests.

---

# 2. Important stale repository guidance

Before implementation, note that some historical project text is stale.

`AGENTS.md` still says things such as:

- current development branch is `dev`
- preserve `Choose Manga -> Download Settings -> Review`
- preserve the old orange visual language

The actual current application is:

```text
Choose Manga -> Book Customization -> Finalization
```

and the active branch is:

```text
feature/emperor-expansion
```

`ROADMAP.md` also contains older text describing Emperor primarily as hardening/reliability.

For this task, this handoff and the actual current implementation are authoritative where those stale lines conflict. Do not redesign the visual language in this task.

A separate lightweight documentation cleanup before the Astra run is preferred so the coding agent does not need to reconcile these stale instructions.

---

# 3. Product behavior already decided

## Stage 1 has three modes

The mode row in `Choose Manga` becomes:

```text
[ Volumes ]  [ Chapters ]  [ Import ]
```

Import is not a separate application workflow.

All three inputs converge into the same downstream stages:

```text
Volumes
Chapters
Imported CBZ/PDF
        |
        v
Book Customization
        |
        v
Finalization
```

Do not create a second customization pipeline.

## Import mode

When Import is selected:

- source search controls are hidden or disabled as appropriate
- direct-link controls are hidden
- provider search results are hidden
- a local import surface is shown
- supported inputs are `.cbz` and `.pdf`
- support Browse Files
- support drag and drop if it can be implemented cleanly without destabilizing the layout
- allow multiple files in one batch
- each input file is one independent output book
- never merge imported containers automatically

The imported inventory should use the existing Stage 1 visual language and selection controls where practical.

Suggested import surface:

```text
Import Existing Books

Drop CBZ or PDF files here
[ Browse Files ]

Imported Books
--------------------------------
[x] Volume 01.cbz   182 pages
[x] Volume 02.cbz   191 pages

[ Clear ]
```

Switching among Volumes, Chapters, and Import clears incompatible Stage 1 selection state and invalidates downstream products. It must not retain stale selected volumes, chapters, imported files, or finalization rows from another mode.

## Stage 2

`Book Customization` should remain visually and behaviorally the same.

Imported content must use the existing:

- portrait/original pages
- paired landscape
- reading direction
- processing presets
- brightness
- contrast
- gamma
- saturation
- sharpening
- grayscale
- output depth
- dithering
- Live eReader Preview
- Kobo screen simulation
- cover modes

Do not redesign or fork these systems.

## Stage 3

Add an Output Format control to `Book Creation & Metadata`:

```text
Output Format
[ CBZ ]  [ PDF ]
```

Default: CBZ.

PDF export must work for:

- source-downloaded Volumes
- source-downloaded Chapters
- imported CBZ
- imported PDF

Current CBZ-specific wording in Finalization should become dynamic or format-neutral.

Examples:

```text
Build Books from Volume Data
Save Each Chapter as Its Own Book
Selected volumes will be created as individual CBZ/PDF files.
```

The final action may remain mode-aware:

```text
Download & Add to Calibre
```

for source modes and:

```text
Process & Add to Calibre
```

for Import mode.

A single neutral label such as `Create & Add to Calibre` is also acceptable if it avoids duplicated UI state.

---

# 4. Existing architecture to reuse

The current final output pipeline in `DownloadWorker._download_group()` already has the correct reusable boundary.

Source acquisition currently creates ordered records shaped approximately like:

```python
{
    "blob": blob,
    "ext": ext,
    "size": size,
    "chapter_index": ...,
    "page_in_chapter": ...,
    "chapter_pages": ...,
}
```

It then uses:

```python
output_page_jobs(...)
render_output_page(...)
ordered_render(...)
final_workers(...)
```

This is the processing pipeline to preserve.

Current flow:

```text
source acquisition
-> normalized page records
-> output_page_jobs
-> render_output_page
-> ordered_render
-> CBZ ZIP writer
```

Target flow:

```text
source acquisition OR local import acquisition
-> normalized page records
-> output_page_jobs
-> render_output_page
-> ordered_render
-> selected output writer
   -> CBZ
   -> PDF
```

The difficult integration work belongs at the acquisition boundary and output-writer boundary.

Do not rewrite image processing, page pairing, screen simulation, or provider adapters.

---

# 5. Avoid full-book memory loading

This is a hard requirement.

A 200 to 300 page PDF or CBZ must not be represented as hundreds of complete page blobs or decoded PIL images in RAM at once.

Use disk-backed local records for final rendering.

A minimal compatible extension is:

```python
{
    "local_path": ".../source-00001.jpg",
    "ext": ".jpg",
    "size": (width, height),
    ...
}
```

Add a small shared helper used by page rendering to resolve a record from one of the existing or new storage forms:

```text
record.image      existing preview path
record.blob       existing downloaded final path
record.local_path new imported final path
```

Do not refactor the whole rendering layer around a new object hierarchy unless necessary.

The page-rendering contract should stay simple and source-independent.

---

# 6. Recommended new modules

Keep the new subsystem out of the already large `main.py` where practical.

Preferred modules:

```text
local_import.py
book_export.py
```

Naming can vary if a clearer project-consistent name emerges.

## `local_import.py`

Own:

- imported-book inspection
- CBZ member ordering
- ComicInfo parsing
- PDF metadata inspection
- PDF rasterization
- safe temporary staging
- local preview sample acquisition
- imported-book metadata model
- cleanup helpers

Suggested immutable model:

```python
@dataclass(frozen=True)
class ImportedBook:
    import_id: str
    path: str
    input_format: str
    title: str
    series: str
    author: str
    language: str
    number: str | None
    series_index: float | None
    page_count: int
    file_size: int
    cover_index: int | None
    warnings: tuple[str, ...]
```

Exact field names may change.

Do not load complete book contents during inspection.

## `book_export.py`

Own final writing and validation for:

```text
CBZ
PDF
```

It should consume already-rendered pages rather than perform source acquisition or image processing.

A function or small writer abstraction is acceptable:

```python
write_book(...)
write_cbz(...)
write_pdf(...)
```

The key property is that both the network worker and local import worker use the same final writer boundary.

---

# 7. CBZ import specification

Use Python stdlib `zipfile`.

Do not add an archive dependency.

## Inspection

Read:

- ordered image member list
- page count
- `ComicInfo.xml` if present
- metadata
- cover-page hint
- file size

Supported source page image formats should include at least:

```text
.jpg
.jpeg
.png
.webp
```

It is acceptable to support additional formats already decodable by the current Pillow build if tests cover them.

Ignore:

- directories
- `ComicInfo.xml` as a page
- `__MACOSX`
- irrelevant dot/junk entries
- unrelated non-image files

## Page order

Do not rely on raw ZIP insertion order.

Use natural path ordering so examples behave like:

```text
1.jpg
2.jpg
10.jpg
```

Nested page directories must also work.

## Archive safety

Never call `extractall()` on user-controlled member paths.

For final processing, stage selected page members into MangaNana's own temporary directory using MangaNana-generated sequential filenames.

Do not reuse untrusted archive paths as filesystem destinations.

## ComicInfo

Parse at least:

```text
Title
Series
Writer
LanguageISO
Number
Volume
PageCount
Pages/Page
```

The ComicInfo v2.0 schema supports a `Pages` array whose `Page` entries contain an `Image` index and a `Type`, including `FrontCover`.

Use an explicit `FrontCover` entry as the preferred metadata-cover candidate.

If no explicit cover is present, the first ordered image is the fallback cover candidate.

Important:

**A cover candidate remains a reading page.**

Do not remove the first page or `FrontCover` page from the imported book merely because it is used as Calibre cover artwork.

This differs from MangaNana's downloaded source cover behavior, where the source cover is separate from the reading pages.

## Imported ComicInfo output

When exporting a processed imported book to CBZ:

- preserve useful valid original ComicInfo fields when practical
- replace MangaNana-controlled metadata fields with the finalized values
- update `PageCount`
- rebuild or remove stale `Pages` indices if processing/pairing changed page count/order
- never emit stale page-index metadata that points at the original page layout

Do not spend the entire implementation on perfect preservation of every obscure ComicInfo extension. Core correctness is more important.

---

# 8. PDF import specification

Do not add:

- PyMuPDF
- Ghostscript
- pypdf
- OCR libraries
- another bundled PDF renderer

Calibre already ships the Poppler tools required for this.

Calibre 7.26 exposes:

```python
from calibre.ebooks.metadata.pdf import get_tools
```

which provides the bundled `pdfinfo` and `pdftoppm` executable paths.

This same mechanism remains available in current Calibre.

Use Calibre's bundled tools rather than shipping binaries.

## PDF inspection

Use `pdfinfo` to obtain at least:

- page count
- title
- author
- encryption state

Fallbacks:

```text
Title: filename stem if missing, empty, or Unknown
Author: empty/Unknown is acceptable
Series: inferred conservatively from filename only if existing project utilities already provide a trustworthy rule; otherwise leave editable
```

Do not invent aggressive metadata inference.

## Encryption

For this first pass:

```text
encrypted/password-protected PDF -> clear unsupported error
```

Do not add password UI.

## Rasterization

PDF is treated as a fixed-layout visual document.

No:

- text reflow
- OCR
- text extraction workflow
- vector-preserving edits
- embedded-image extraction

Use:

```text
PDF_IMPORT_DPI = 300
```

as an internal constant, not a new user-facing control.

Poppler defaults to 150 DPI, so the DPI must be explicit.

Recommended final rasterization shape:

```text
pdftoppm
-cropbox
-r 300
-jpeg
-jpegopt quality=95,optimize=y
```

If a platform Poppler version needs slightly different jpegopt syntax, adapt safely.

For live preview, rasterize only the bounded preview page range.

For final processing, rasterize the complete selected PDF into MangaNana's temporary staging area, then use the same local-page record path as staged CBZ pages.

Use `subprocess.Popen` for long raster jobs so cancellation can terminate the process and cleanup can be guaranteed.

Do not leave child `pdftoppm` processes or temporary raster files after cancellation/failure.

---

# 9. Local import acquisition contract

Both imported formats should converge before Book Customization.

Conceptually:

```text
CBZ
 -> inspect archive
 -> safe staged images
 -> local page records

PDF
 -> inspect PDF
 -> Poppler raster staging
 -> local page records

local page records
 -> existing output_page_jobs
 -> existing rendering/processing pipeline
```

For an imported book with no chapter-boundary metadata, treat the container as one ordered book for pairing purposes.

Use:

```text
chapter_index = 1
page_in_chapter = 1..N
chapter_pages = N
```

Do not invent chapter boundaries.

---

# 10. Live Preview for imports

Do not modify `ProcessingPreviewWorker` unless a tiny source-neutral extension is needed.

It is already explicitly CPU-only and source-independent.

The current network `PairingPreviewWorker` acquires a bounded sample and emits a structure approximately like:

```python
{
    "volume": ...,
    "label": ...,
    "layout": ...,
    "records": tuple(records),
    "stats": ...,
    "source_pages": ...,
    "output_pages": ...,
}
```

Add a local/import preview acquisition worker that emits the same shape.

For CBZ:

- read only the bounded sample members
- normalize EXIF as current source pages do
- decode only the bounded sample

For PDF:

- rasterize only the bounded sample pages
- load them
- cleanup the sample temp files

Then hand the sample to the unchanged `ProcessingPreviewWorker`.

Preserve the existing 128 MiB decoded preview protection.

Changing processing sliders after an imported preview is acquired must not reread the CBZ or rerasterize the PDF. Reprocessing should remain local from the cached bounded sample.

---

# 11. Output format and writer architecture

Add persisted preference:

```python
prefs.defaults["output_format"] = "cbz"
```

Optionally persist only the last import directory:

```python
prefs.defaults["last_import_dir"] = ""
```

Do not persist imported file selections across sessions.

## CBZ writer

Move or wrap the existing ZIP-writing behavior without changing current output semantics.

Regression requirement:

Existing Volumes/Chapters with Output Format = CBZ should produce behavior equivalent to the current implementation.

Continue:

- sequential page filenames
- ZIP_STORED unless there is a strong measured reason to change
- ComicInfo
- atomic `.part` finalization
- current validation

## PDF writer

Use Qt `QPdfWriter`.

Reason:

- already available through Calibre's Qt stack
- available in the Calibre 7.26 support floor
- supports multipage streaming with `newPage()`
- supports custom page size
- avoids retaining every output page in memory
- introduces no external dependency

Use a fixed internal:

```text
PDF_OUTPUT_DPI = 300
```

For each already-rendered page with pixel dimensions `(w, h)`:

1. define a custom physical PDF page size corresponding to `w / 300` by `h / 300` inches, or equivalent points
2. use exact custom page sizing
3. use zero margins
4. paint the page image to the full page
5. do not crop
6. do not add padding beyond what MangaNana's page renderer already produced
7. call `newPage()` only between pages, never after the final page

Qt documents that page size/layout changes should be made before painting begins or immediately before `newPage()` for the next page.

Set:

```text
Title
Creator = MangaNana
```

where supported.

Do not unconditionally call newer Qt APIs such as `QPdfWriter.setAuthor()`, because that method was added after the older Qt versions used by the current Calibre support floor.

Write to `.part`, close the painter/writer, validate, then `os.replace()`.

## PDF validation

Use Calibre's bundled `pdfinfo`.

Require:

- file exists
- nonzero size
- readable by `pdfinfo`
- final PDF page count equals planned output page count

For paired landscape, the raster content entering the writer should already be 1680x1264 because that is guaranteed by the existing page-rendering path.

---

# 12. Metadata behavior for import batches

Multiple files are allowed, but do not clone one imported title onto every book.

Each imported container owns its detected:

```text
title
number/series index
cover candidate
page count
```

For a single imported book, the existing Title / Series / Author metadata fields can operate normally.

For multiple imported books:

- preserve each book's individual detected Title
- preserve each individual Number/series index
- Series and Author may be treated as batch-level overrides when explicitly applied
- Title must not become one global string applied to every imported item
- if necessary, disable the global Title field in multi-import mode and display a neutral `Multiple imported titles` state

Do not build a full metadata spreadsheet/editor in this pass.

If imported files clearly contain different Series values, do not silently normalize them to the first file's series.

The Final Outputs rows must show the actual per-book metadata that will be sent to Calibre.

---

# 13. Cover behavior for imported books

Current MangaNana downloaded covers are separate metadata covers and are excluded from reading pages.

Imported books are different.

For imports:

## Keep Existing Cover

- use ComicInfo `FrontCover` page if available
- otherwise use first page
- assign it as Calibre metadata cover
- keep the same page in the reading content

## Stamp Existing Cover

- render MangaNana's stamped metadata cover from the imported cover candidate
- do not remove or replace that page in reading content

## Generate Cover

- generate MangaNana's metadata cover using the existing cover renderer
- reading pages remain unchanged except for normal selected page processing

No cover mode should unexpectedly delete imported source pages.

---

# 14. Workflow state changes

`workflow_state.py` currently accepts only:

```text
volume
chapter
```

Extend mode handling to:

```text
volume
chapter
import
```

Do not fake imported books as a provider.

Import state should have explicit local inventory/selection semantics, either through the existing generic `loaded_inventory` / `inventory_selection` fields or a minimal dedicated imported field if that is clearer.

Requirements:

- entering Import clears provider discovery/results/selection
- entering Volume/Chapter clears imported selection
- mode changes invalidate downstream finalization
- stale asynchronous local inspection results cannot overwrite a newer import generation
- imported inventory selection uses stable import IDs
- local imports never require provider identity, URL, source, or download language

---

# 15. Signatures and invalidation

Current signatures are source-centric.

Import mode needs a stable source identity that does not require hashing entire files.

Suggested imported identity tuple per file:

```text
resolved path
file size
mtime_ns
```

plus an internal import ID.

Use selected import identities in the relevant:

```text
current_signature
live preview signature
finalization signature
```

Changing:

- selected imported books
- metadata
- layout
- processing
- cover mode
- output format

must invalidate the correct downstream products.

Changing only Output Format should invalidate/rebuild Final Outputs, but should not force CBZ rereading or PDF rerasterization for an already cached Live Preview sample.

---

# 16. Finalization planning

Do not force imported content through the network-oriented `PreviewWorker`.

Add a local finalization planner or `ImportPreviewWorker` that returns the same outer row schema expected by Final Outputs.

Imported rows should include at least:

```text
selected
title
author
series
volume/series_index
pages
status
input format
output format
import ID
local path
```

Current source rows should remain unchanged except for the new output-format awareness.

---

# 17. Final worker results and Calibre import

Current Calibre integration hardcodes:

```python
"CBZ"
```

in `add_format()` and `add_books()`.

Final worker results must include a format field.

Conceptually:

```python
{
    "path": "...",
    "format": "cbz" | "pdf",
    "title": "...",
    ...
}
```

Then:

```python
fmt = item["format"].upper()
```

and use that dynamically for:

```text
db.add_format
db.add_books
replacement handling
completion logging
```

Do not set a remote provider identifier for local imported books.

Imported books have no MangaDex/MangaPill/WeebCentral identity unless some future explicit provenance feature adds one.

The existing MangaNana Calibre tag behavior can remain.

---

# 18. Cancellation and cleanup

Treat this as part of the architecture, not polish.

Requirements:

- no network operations on GUI thread
- no PDF rasterization on GUI thread
- no heavy image processing on GUI thread
- local inspection that can block should use worker threads
- cancel active `pdftoppm`
- close ZIP handles
- close output writer/painter
- remove `.part`
- remove temporary raster/staged pages
- do not alter Calibre for an unfinished book
- do not leave partially written final books

Use the existing worker/cancellation conventions where possible.

---

# 19. Error behavior

Clear user-facing errors for:

```text
unsupported extension
invalid/corrupt CBZ
CBZ with no readable images
malformed ComicInfo
invalid/corrupt PDF
encrypted/password-protected PDF
PDF raster failure
insufficient temporary disk space
output writer failure
PDF validation failure
```

Malformed or absent metadata should generally fall back rather than reject an otherwise readable book.

A malformed `ComicInfo.xml` should not make a valid CBZ unreadable.

---

# 20. Explicit non-goals

Do not implement any of the following in this run:

- new manga sources
- source adapter redesign
- provider/search redesign
- CBR/RAR import
- 7z import
- EPUB import
- folder import
- password-protected PDF support
- OCR
- PDF text reflow
- PDF text extraction workflow
- vector-preserving PDF editing
- embedded-image extraction
- PDF import DPI UI
- PDF output DPI UI
- full per-file metadata spreadsheet/editor
- automatic merging of imported books
- automatic chapter-boundary inference
- screen-emulation changes
- dithering redesign
- image-processing redesign
- cover redesign
- Judgement UI redesign
- branding/rename work
- giant `main.py` rewrite
- packaging new PDF binaries
- commit/push/tag/release

---

# 21. Focused test requirements

## Workflow state

Test:

1. `change_mode("import")`.
2. Volume/Chapter -> Import clears source discovery and inventory.
3. Import -> Volume/Chapter clears imported selection.
4. stale async local inspection cannot win after a newer generation.
5. import selection invalidates finalization.
6. stage names remain `choose_manga`, `book_customization`, `finalization`.

## CBZ import

Test:

1. natural order `1.jpg, 2.jpg, 10.jpg`.
2. nested directories.
3. junk/non-image entries ignored.
4. no-image CBZ rejected.
5. malformed ComicInfo falls back.
6. metadata parsing.
7. explicit `FrontCover`.
8. fallback first-page cover.
9. cover candidate remains in reading sequence.
10. EXIF orientation normalization.
11. staged extraction cannot escape temp directory.

## PDF import

Test:

1. bundled Calibre Poppler discovery.
2. metadata/page count parsing.
3. filename-title fallback.
4. encrypted PDF rejection.
5. raster command explicitly uses 300 DPI.
6. bounded preview rasterization.
7. full final rasterization.
8. cancellation terminates subprocess and removes temp files.
9. failed raster cleans partial state.

Tests should mock subprocess where practical and use a tiny real PDF smoke fixture where the existing test environment permits it.

## Shared processing

Test imported pages through:

```text
portrait
paired landscape
processing settings
dithering
```

Verify imported page records use the same rendering functions as downloaded source records.

Do not create a parallel processing implementation.

## Export

CBZ regression:

1. current source CBZ behavior still passes existing tests.
2. sequential pages.
3. valid ComicInfo.
4. validation.
5. atomic finalization.

PDF:

1. two or more pages create exact expected page count.
2. portrait page dimensions preserve aspect.
3. landscape page dimensions preserve aspect.
4. no unexpected crop.
5. no trailing blank page.
6. writer cleanup on failure.
7. validation catches incorrect/corrupt output.

## Calibre

Mock/test:

```text
CBZ -> {"CBZ": path}
PDF -> {"PDF": path}
```

Replacement flow must also use the actual output format.

Local imported books must not call remote provider identifier parsing.

## UI/offscreen smoke

Verify:

- mode row contains Volumes / Chapters / Import
- Import surface appears
- source search surface is not active in Import
- Browse Files accepts multiple CBZ/PDF
- invalid extensions are rejected
- selection/clear/remove behavior
- Next gating
- Book Customization is unchanged
- import Live Preview works offline
- Output Format appears in Finalization
- CBZ is default
- choosing PDF updates Final Outputs/extensions
- output-format change does not reacquire live preview source pages

---

# 22. Full regression requirements

Run the complete existing test suite after focused tests.

Existing source workflows are regression-critical:

- MangaDex
- MangaPill
- WeebCentral
- search
- direct URL load
- volume mode
- chapter mode
- publication mapping
- cross-source fallback
- Live Preview
- page pairing
- all Empress processing
- screen emulation
- cover rendering
- Calibre add/replace
- packaging

Do not claim live provider behavior unless actually tested live.

---

# 23. Packaging

After tests pass:

- run syntax checks
- run `git diff --check`
- inspect changed files
- build fresh `MangaNana-Calibre-dev.zip`
- verify ZIP integrity
- confirm new import/export modules are included
- confirm no external PDF binaries were accidentally packaged
- report SHA-256
- report byte size
- report entry count
- report focused test results
- report full suite results
- report any behavior that could not be manually tested

Do not commit, push, tag, merge, or release unless explicitly instructed.

---

# 24. Implementation order best suited to Astra

Use one run, but work in internally coherent phases.

## Phase A: establish pure I/O boundaries

Implement and test:

```text
local_import.py
book_export.py
```

before major UI integration.

Focus on:

- CBZ parser
- ComicInfo
- PDF inspection
- PDF raster
- local staged records
- CBZ writer abstraction
- QPdfWriter
- output validation
- cancellation/cleanup

## Phase B: make rendering storage-neutral

Add only the minimal local-path record support needed for existing:

```text
output_page_jobs
render_output_page
ordered_render
```

Prove with tests that source records and imported records share the same renderer.

## Phase C: workflow/state and UI

Add:

```text
Import mode
import inventory
mode transitions
Browse/drop
Next gating
local Live Preview acquisition
```

Preserve Stage 2.

## Phase D: Finalization and Calibre

Add:

```text
Output Format
local finalization rows
dynamic CBZ/PDF results
dynamic Calibre format handling
mode-aware provenance
```

## Phase E: regressions and packaging

Run focused and full tests, then package.

Astra should spend its strongest reasoning on the integration seams, state invalidation, cancellation, memory bounds, format abstraction, and preserving regressions.

It should not spend its run researching UI direction, new sources, PDF engines, or alternative processing architectures.

---

# 25. Definition of done

This feature is complete when all of these are true:

```text
Volumes -> customize -> CBZ works as before
Volumes -> customize -> PDF works
Chapters -> customize -> CBZ works as before
Chapters -> customize -> PDF works
Import CBZ -> customize -> CBZ works
Import CBZ -> customize -> PDF works
Import PDF -> customize -> CBZ works
Import PDF -> customize -> PDF works
```

and:

```text
large books are disk-backed rather than fully resident in RAM
Live Preview remains bounded
screen simulation remains presentation-only
cover behavior is correct
cancellation cleans everything
Calibre receives the correct file format
existing source workflows remain green
```

---

# 26. Copy/paste Astra High prompt

Use the following prompt after the repository documentation conflicts have been cleaned up or explicitly acknowledged.

```text
You are implementing the first major 0.13.0-dev "The Emperor" feature set for MangaNana on branch feature/emperor-expansion.

Read the attached MangaNana Emperor Astra Import/Export Handoff completely before editing. Treat that handoff and the actual current implementation as authoritative where stale historical ROADMAP.md or AGENTS.md text conflicts with it.

Goal: implement CBZ import, PDF import, and PDF export as one coherent External Book I/O expansion.

The product decisions and technical research have already been made. Do not spend the run redesigning the workflow, evaluating unrelated PDF libraries, adding providers, or rebuilding image processing.

Critical architecture:

- Stage 1 modes become Volumes / Chapters / Import.
- Import accepts local CBZ/PDF and converges into the existing Book Customization and Finalization stages.
- Add Output Format CBZ/PDF in Finalization, default CBZ.
- Existing source downloads and local imports must converge on the same normalized page-record and page-rendering pipeline.
- Reuse output_page_jobs(), render_output_page(), ordered_render(), final_workers(), existing processing settings, pairing, cover rendering, and screen preview behavior.
- Do not create a second image-processing pipeline.
- Final imported books must be disk-backed, not full-book blobs/images in RAM.
- Use stdlib zipfile for CBZ.
- Use Calibre's bundled Poppler via calibre.ebooks.metadata.pdf.get_tools() for PDF inspection/rasterization.
- PDF import uses explicit 300 DPI fixed-layout rasterization.
- Reject encrypted/password-protected PDFs in this pass.
- Use QPdfWriter for streaming PDF export with exact custom page geometry, zero margins, and no trailing blank page.
- Do not depend on newer QPdfWriter APIs unavailable in older supported Qt versions.
- Current cover behavior remains metadata-cover-only. Imported FrontCover/first page may be reused as metadata cover but must remain in the imported reading-page sequence.
- No new manga sources in this task.
- No Judgement UI overhaul.
- No branding work.
- No CBR/7z/EPUB/folder import.
- No OCR/reflow.
- No external PDF dependency.
- No commit, push, tag, merge, or release.

Start by inspecting only the implementation areas named in the handoff and confirm the actual current boundaries. Do not produce a long research report before coding. Implement the pure import/export modules and tests first, then integrate storage-neutral records, workflow/UI, Finalization, and Calibre.

Preserve current Volumes/Chapters behavior exactly when Output Format is CBZ.

Use background workers for blocking local inspection/rasterization and preserve the existing cancellation model. A cancelled or failed job must leave no child pdftoppm process, temp staging, .part output, or partial Calibre modification.

Add focused tests for all acceptance criteria in the handoff and run the complete suite. Then build a fresh development plugin ZIP and report:
- changed files
- architecture summary
- focused tests
- full suite result
- manual/offscreen smoke result
- untested limitations
- ZIP filename
- SHA-256
- byte size
- entry count

Do not stop after planning. Continue through implementation, tests, and packaging unless a genuinely external blocker makes implementation impossible.
```

---

# 27. Recommended pre-Astra housekeeping

Do this with a cheaper model or manually, not Astra High.

Update only stale project guidance before the implementation run:

`AGENTS.md`

```text
Current branch: feature/emperor-expansion
Current workflow: Choose Manga -> Book Customization -> Finalization
Emperor priority: local CBZ/PDF import and PDF export, then additional sources
Visual rule for Emperor I/O task: preserve current UI; no visual redesign
```

`ROADMAP.md`

Update the active milestone summary so Emperor reflects:

```text
0.13.x The Emperor
- CBZ import
- PDF import
- PDF export
- bring-your-own-manga processing
- additional sources after local I/O
- reliability/hardening for the expanded inputs/outputs
```

Do not rewrite historical Empress documentation.

This small cleanup prevents the expensive implementation model from spending context and reasoning on contradictory historical instructions.
