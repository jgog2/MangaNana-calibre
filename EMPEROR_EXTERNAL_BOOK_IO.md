# External Book I/O — 0.13.0-dev

Choose **Import** on Choose Manga and browse one or more CBZ/PDF files. Select the
books to process, continue through Book Customization, and choose CBZ or PDF in
Finalization. Each input container remains an independent book. Source Volumes and
Chapters also support both output formats. CBZ is the default; the selected format
is saved separately from processing preferences.

For one imported book, Title, Series and Author are editable. For multiple books,
Title displays “Multiple imported titles”; each book retains its own title and
number. Series and Author change across the batch only when those fields are
explicitly edited and Apply Metadata is pressed. Final Output inclusion survives
metadata application. Imported files do not receive provider identifiers.

An imported ComicInfo FrontCover (or the first reading page) supplies the optional
metadata cover. That page always stays in the reading sequence, including Stamp
Existing Cover and Generate Cover. The generated/stamped metadata cover never
replaces a reading page. Single-book cover previews run off the GUI thread.

## Implementation boundaries

- `local_import.py`: stdlib ZIP inspection, natural member ordering, bounded
  ComicInfo parsing, owned sequential staging files, EXIF normalization, stable
  file identities, bundled Poppler inspection/rasterization, cancellation.
- `import_workers.py`: background inspection, local Finalization planning,
  bounded preview acquisition, cover previews and disk-backed final acquisition.
- `import_workflow.py`: import inventory and selections, generation guards,
  independent batch metadata and connections to the existing three stages.
- `main.py`: minimal `image`/`blob`/`local_path` loader at the shared renderer
  boundary; source and import workers use `output_page_jobs`, `render_output_page`,
  `ordered_render` and `final_workers`. Calibre add/replace uses the actual format.
- `book_export.py`: shared streaming CBZ/PDF writers, `.part` cleanup and atomic
  publication. CBZ keeps ZIP_STORED, sequential filenames and ComicInfo. Imported
  ComicInfo keeps useful metadata, updates controlled fields/PageCount and removes
  stale page mappings after pairing.

PDF input uses Calibre's `get_tools()` and `pdftoppm -cropbox -r 300 -jpeg
-jpegopt quality=95,optimize=y`. Encrypted PDFs are rejected. No downloaded tools
or additional PDF library are required. Output uses QPdfWriter with custom page
dimensions at 300 DPI, zero margins and page breaks only between rendered pages.
Bundled pdfinfo checks that each output is readable and has the exact page count
before publication. PDF embeds Title and Creator; Calibre receives Author, Series,
series index, language and the separate metadata cover.

Full imported books remain disk-backed. PDF Live Preview rasterizes at 100 DPI;
final PDF import remains at 300 DPI. Preview caches at most 14 decoded source
pages and enforces the existing 128 MiB ceiling. Oversized samples are logged and
skipped; later eligible pages are tried, and safe samples are retained. Only a
sample with no safe pages reports the memory-limit failure. Processing changes reuse that
sample; output-format changes do not invalidate or reacquire it. File changes
require removing/rebrowsing the input. Failed or cancelled local jobs discard
staging and prepared outputs before Calibre import.

Screen emulation and all processing mathematics are unchanged. The production
Kobo Libra Colour CFA strength remains **0.10**.

## Validation

Run pure tests with Python unittest discovery. The focused I/O tests are in
`tests/test_local_import_export.py`; existing cover, screen-emulation, Empress
pipeline and page-rendering suites cover preservation of the shared renderer.

`tools/emperor_calibre_smoke.py` runs with calibre-debug and QT_QPA_PLATFORM=offscreen.
Set CALIBRE_CONFIG_DIRECTORY to a directory inside `C:/MangaNana-Dev/Test-Data`.
The smoke script uses real Qt/Poppler, synthetic source acquisition, fixtures under
Test-Data/Test-Downloads, and actual add/replace calls in
`C:/MangaNana-Dev/Test-Library`. It removes only its own temporary library books.
It forbids external network access. It is a development validation tool, not part
of the plugin ZIP.

## Scope and limits

Browse supports CBZ/PDF; drag-and-drop was left out of this pass. No encrypted
PDFs, CBR/RAR/7z, EPUB, folders, OCR or reflow. PDF input is rasterized at fixed
300 DPI, so original PDF text/vector content is not retained. Preview uses the
first selected imported book. Local imports use Calibre's duplicate classification
without automatically replacing books based on inferred local numbering.

Qualification uses tiny real PDF fixtures and synthetic source pages. Live
provider availability, older supported Calibre/Qt versions, a physical Kobo and
large real-world PDF stress loads need separate manual qualification.
