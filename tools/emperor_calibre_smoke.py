"""Exercise real Qt/Poppler and the local workflow with an isolated test configuration."""
from io import BytesIO
from pathlib import Path
import os
import shutil
import sys
import tempfile
import types
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
test_data = Path('C:/MangaNana-Dev/Test-Data').resolve()
config = Path(os.environ['CALIBRE_CONFIG_DIRECTORY']).resolve()
assert test_data in config.parents
output = test_data / 'manganana-emperor-validation'; output.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = 'C:/MangaNana-Dev/Test-Downloads'
package = types.ModuleType('calibre_plugins.manganana'); package.__path__ = [str(root)]
sys.modules['calibre_plugins.manganana'] = package
from calibre_plugins.manganana import main
from calibre_plugins.manganana.book_export import write_book, validate_pdf
from calibre_plugins.manganana.local_import import inspect_book, staged_pages, run_tool, poppler_tools, import_plan
from calibre_plugins.manganana.import_workers import LocalBookWorker, LocalPreviewWorker
from qt.core import QApplication, QEventLoop, QFont, QFontDatabase, QIcon, QThread, QTimer, QWidget
from PIL import Image

app = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf'); app.setFont(QFont('Segoe UI', 10))
def forbidden(*args, **kwargs): raise AssertionError('External network forbidden in Emperor smoke.')
urllib.request.urlopen = forbidden

def art(size, color):
    out = BytesIO(); Image.new('RGB', size, color).save(out, 'PNG'); return out.getvalue()

images = [art((300, 600), 'red'), art((900, 300), 'blue'), art((450, 600), 'green')]
pdf = output / 'mixed-pages.pdf'
write_book(pdf, 'pdf', iter((i, ('.png', blob, 'INDIVIDUAL')) for i, blob in enumerate(images)), title='PDF Fixture')
assert validate_pdf(pdf, 3) == 3
prior_pdf = pdf.read_bytes()
def broken_pages():
    yield 0, ('.png', images[0], 'INDIVIDUAL')
    raise ValueError('Synthetic rendered-page failure')
try:
    write_book(pdf, 'pdf', broken_pages())
    raise AssertionError('Expected a writer failure')
except ValueError:
    pass
assert pdf.read_bytes() == prior_pdf and not Path(str(pdf)+'.part').exists()
info = run_tool([poppler_tools()[0], '-f', '1', '-l', '3', pdf])
print(info)
assert '72 x 144 pts' in info and '216 x 72 pts' in info and '108 x 144 pts' in info, info
pdf_book = inspect_book(pdf); assert pdf_book['title'] == 'PDF Fixture'
with staged_pages(pdf_book) as records:
    assert [r['size'] for r in records] == [(300, 600), (900, 300), (450, 600)]

cbz = output / 'local.cbz'
with zipfile.ZipFile(cbz, 'w') as archive:
    for i, blob in enumerate(images): archive.writestr(f'{i+1}.png', blob)
    archive.writestr('ComicInfo.xml', '<ComicInfo><Title>Local Title</Title><Series>Local Series</Series><Writer>Writer</Writer><Number>2.5</Number><Pages><Page Image="1" Type="FrontCover"/></Pages></ComicInfo>')
cbz_book = inspect_book(cbz)

def run(worker, signal='ready'):
    values = []; errors = []; loop = QEventLoop(); timer = QTimer(); timer.setSingleShot(True)
    getattr(worker, signal).connect(values.append); worker.failed.connect(errors.append)
    worker.finished.connect(loop.quit); timer.timeout.connect(loop.quit)
    timer.start(60000); worker.start(); loop.exec()
    assert timer.isActive(), 'Worker timeout'
    timer.stop(); worker.wait(); app.processEvents()
    assert not errors, errors
    assert len(values) == 1, values
    return values[0]

def cleanup(result):
    work = Path(result['workdir']).resolve()
    assert work.parent == Path(tempfile.tempdir).resolve()
    shutil.rmtree(work)

for book in (cbz_book, pdf_book):
    sample = run(LocalPreviewWorker(book, 'original_pages', 'rtl'))
    assert len(sample['records']) == 3 and all('image' in r for r in sample['records'])
    for fmt in ('cbz', 'pdf'):
        for layout in ('original_pages', 'paired_landscape'):
            for mode in ('keep', 'stamp', 'generate'):
                rows = import_plan([book], output_format=fmt)
                worker = LocalBookWorker(rows, main.ProcessingSettings(), layout, 'rtl', fmt, mode, True, True)
                result = run(worker, 'finished_ok')
                try:
                    item = result['files'][0]; assert item['format'] == fmt and item['title'] == book['title']
                    assert result['pages'] == 3 and Path(item['cover_path']).exists()
                    if fmt == 'pdf': assert validate_pdf(item['path']) > 0
                    else:
                        with zipfile.ZipFile(item['path']) as archive:
                            assert archive.testzip() is None
                            if layout == 'original_pages':
                                assert [archive.read(n) for n in archive.namelist() if n.endswith('.png')] == images if book['format'] == 'cbz' else True
                finally: cleanup(result)
print('LOCAL_MATRIX=PASS: CBZ/PDF input, CBZ/PDF output, both layouts, all cover modes')

class Source:
    source_id = 'fixture'; display_name = 'Synthetic'; capabilities = ()
    def fetch_binary(self, url, **kwargs):
        assert QThread.currentThread() != app.thread()
        return images[int(url)]
    def get_page_manifest(self, *args, **kwargs): return {'full': ['0', '1', '2']}
    def get_volume_covers(self, *args): return {}
    def get_chapters(self, *args):
        return [dict(id='fixture', chapter='2.5', volume=1., pages=3, _source_id='fixture')]
    def parse_manga_ref(self, url): return 'fixture'

source = Source()
for kind in ('native', 'volume', 'chapter', 'standalone'):
    for fmt in ('cbz', 'pdf'):
        for layout in ('original_pages', 'paired_landscape'):
            chapter = source.get_chapters()[0]
            group = dict(kind=kind, volume=1. if kind == 'volume' else None, identifier='2.5', chapters=[chapter])
            worker = main.DownloadWorker(source, 'fixture', 'Source Title', 'Writer', 'Series', 'en', None, None,
                                          False, True, (), page_layout=layout, output_format=fmt,
                                          chapter_output_groups=None if kind == 'native' else [group])
            result = run(worker, 'finished_ok')
            try:
                assert not result['failures'], result['failures']
                item = result['files'][0]
                assert Path(item['path']).suffix == '.'+fmt and item['format'] == fmt
                if fmt == 'pdf': assert validate_pdf(item['path']) == 3
                else: assert main._validate_cbz_output(item['path'], layout) == 3
            finally: cleanup(result)
print('SOURCE_MATRIX=PASS: native/grouped volumes, chapters, standalone; both formats/layouts')

gui = QWidget(); gui.current_db = types.SimpleNamespace(new_api=object(), library_path='C:/MangaNana-Dev/Test-Library')
dialog = main.MangaNanaDialog(gui, QIcon()); dialog.show(); app.processEvents()
dialog._set_workflow_mode('import')
assert not dialog.preview_btn.isEnabled() and dialog.import_panel.isVisible()
dialog._inspect_import_paths([str(cbz), str(pdf)])
assert not dialog.preview_btn.isEnabled()
loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec(); app.processEvents()
assert len(dialog._import_books) == 2, dialog.import_status.text()
dialog._select_imports(False); assert not dialog.preview_btn.isEnabled()
dialog._select_imports(True)
assert not dialog.title.isEnabled() and dialog.title.text() == 'Multiple imported titles'
assert dialog.preview_btn.isEnabled()
dialog._advance_stage(); assert dialog.workflow_state.stage == 'book_customization'
assert not dialog._live_preview_samples
dialog.open_pairing_preview()
loop = QEventLoop(); QTimer.singleShot(1500, loop.quit); loop.exec(); app.processEvents()
assert dialog._live_preview_samples and not dialog.pairing_preview_worker
sample = next(iter(dialog._live_preview_samples.values()))
brightness = dialog._processing_controls['brightness'][0]
brightness.setValue(110 if brightness.value() != 110 else 120)
loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec()
assert next(iter(dialog._live_preview_samples.values())) is sample
dialog._advance_stage()
loop = QEventLoop(); QTimer.singleShot(1000, loop.quit); loop.exec(); app.processEvents()
assert dialog.preview_table.rowCount() == 2 and dialog.download_btn.isEnabled()
assert [r['series'] for r in dialog.preview_data['rows']] == ['Local Series', '']
dialog.preview_data['rows'][1]['selected'] = False
dialog.series.setText('Explicit Series'); dialog._import_edited_fields.add('series'); dialog.apply_metadata()
assert [r['series'] for r in dialog.preview_data['rows']] == ['Explicit Series', 'Explicit Series']
assert [r['title'] for r in dialog.preview_data['rows']] == ['Local Title', 'PDF Fixture']
assert not dialog.preview_data['rows'][1]['selected'], 'Metadata application must preserve inclusion choices'
key = dialog._live_preview_signature_value()
dialog.output_format.setCurrentIndex(dialog.output_format.findData('pdf'))
assert key == dialog._live_preview_signature_value() and not dialog.download_btn.isEnabled()
assert next(iter(dialog._live_preview_samples.values())) is sample
dialog.continue_preview(); loop = QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
dialog._set_download_ui_locked(True); assert not dialog.output_format.isEnabled() and not dialog.import_mode_btn.isEnabled()
dialog._set_download_ui_locked(False); assert not dialog.title.isEnabled()
dialog.resize(1400, 940); app.processEvents(); dialog.grab().save(str(output / 'finalization.png'))
dialog._set_stage('choose_manga'); dialog._set_workflow_mode('chapter')
assert not dialog._import_books and not dialog._selected_import_ids and not dialog.import_panel.isVisible()
dialog._set_workflow_mode('import'); dialog._inspect_import_paths([str(cbz), str(pdf)])
dialog._set_workflow_mode('volume')
loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec(); app.processEvents()
assert not dialog._import_books, 'Late import inspection must not repopulate a source mode'
dialog._set_workflow_mode('import'); dialog._import_books=[cbz_book, pdf_book]
dialog._selected_import_ids={cbz_book['id']}; dialog._remove_imports()
assert dialog._import_books == [pdf_book] and not dialog._selected_import_ids
dialog.close(); app.processEvents()
print('IMPORT_UI=PASS: modes, independent titles, stage gating, format invalidation, locking, cleanup')

# Exercise actual Calibre add_books/add_format in the dedicated development library.
from calibre.db.legacy import LibraryDatabase
import uuid
library_path = Path('C:/MangaNana-Dev/Test-Library').resolve()
assert str(library_path).casefold() == 'c:\\manganana-dev\\test-library'
library = LibraryDatabase(str(library_path)); db = library.new_api
before_ids = set(db.all_book_ids()); created_ids = set(); fixture_titles = set()
original_pref = main.prefs['show_completion_summary']; main.prefs['show_completion_summary'] = False
gui2 = QWidget(); gui2.current_db = library
dialog2 = main.MangaNanaDialog(gui2, QIcon())
try:
    for fmt in ('cbz', 'pdf'):
        unique = 'Emperor automated smoke ' + uuid.uuid4().hex
        fixture_titles.add(unique)
        rows = import_plan([cbz_book], {'title': unique, 'series': 'Emperor Smoke'})
        result = run(LocalBookWorker(rows, main.ProcessingSettings(), 'original_pages', 'rtl', fmt, 'generate', True, True), 'finished_ok')
        dialog2.on_downloaded(result)
        current = set(db.all_book_ids()) - before_ids
        matching = [bid for bid in current if db.field_for('title', bid) == unique]
        assert len(matching) == 1, matching
        created_ids.update(matching)
        bid = matching[0]
        assert fmt.upper() in db.formats(bid)
        assert db.field_for('series', bid) == 'Emperor Smoke'
        assert db.field_for('series_index', bid) == 2.5
        assert db.field_for('authors', bid) == ('Writer',)
        assert not db.field_for('identifiers', bid), 'Local books must have no provider identifier'
        assert db.cover(bid), 'Metadata cover must reach Calibre'
        other = 'pdf' if fmt == 'cbz' else 'cbz'
        replacement = dict(path=str(pdf if other == 'pdf' else cbz), volume=2.5, title=unique,
                           format=other, cover_path=None)
        dialog2._replace_existing_book(bid, replacement, 'Writer', 'Emperor Smoke', 'en')
        assert set(db.formats(bid)) == {'PDF', 'CBZ'}
finally:
    # Delete only this run's newly created fixture books; retain all pre-existing test data.
    created_ids.update(bid for bid in set(db.all_book_ids()) - before_ids if db.field_for('title', bid) in fixture_titles)
    if created_ids: db.remove_books(created_ids, permanent=True)
    assert set(db.all_book_ids()) == before_ids
    dialog2.close(); app.processEvents(); library.close()
    main.prefs['show_completion_summary'] = original_pref
print('CALIBRE_TEST_LIBRARY=PASS: CBZ/PDF import, metadata, cover, no source IDs, format-aware replacement; fixture books removed')
print('No external network or normal-library writes. Samples:', output)
