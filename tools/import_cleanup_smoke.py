"""Focused Import polish checks with real Qt/Poppler and no library/network writes."""
from io import BytesIO
from pathlib import Path
import os
import sys
import tempfile
import threading
import types
from unittest.mock import patch
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
test_data = Path('C:/MangaNana-Dev/Test-Data').resolve()
assert test_data in Path(os.environ['CALIBRE_CONFIG_DIRECTORY']).resolve().parents
output = test_data / 'manganana-import-cleanup'; output.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = 'C:/MangaNana-Dev/Test-Downloads'
package = types.ModuleType('calibre_plugins.manganana'); package.__path__ = [str(root)]
sys.modules['calibre_plugins.manganana'] = package
from calibre_plugins.manganana import main, import_workers, local_import
from calibre_plugins.manganana.book_export import write_book
from qt.core import QApplication, QCheckBox, QEventLoop, QFont, QFontDatabase, QIcon, QPoint, QTimer, QWidget
from PIL import Image

app = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf'); app.setFont(QFont('Segoe UI', 10))
def forbidden(*args, **kwargs): raise AssertionError('Network access forbidden in Import cleanup smoke.')
urllib.request.urlopen = forbidden

def wait_until(condition):
    if condition(): return
    loop = QEventLoop(); poll = QTimer(); timeout = QTimer(); timeout.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if condition() else None)
    timeout.timeout.connect(loop.quit); poll.start(10); timeout.start(30000); loop.exec()
    poll.stop(); timeout.stop(); assert condition(), 'Timed out'; app.processEvents()

blob = BytesIO(); Image.new('RGB', (300, 600), 'orange').save(blob, 'PNG'); art = blob.getvalue()
pdf = output / 'preview.pdf'
write_book(pdf, 'pdf', iter((i, ('.png', art, 'INDIVIDUAL')) for i in range(3)), title='PDF Preview')
book = local_import.inspect_book(pdf)
messages = []
records = local_import.preview_records(book, log=messages.append)
assert all(r['size'] == (100, 200) for r in records)
with local_import.staged_pages(book) as final:
    assert all(r['size'] == (300, 600) for r in final)
assert any('100 DPI' in m and '300 DPI' in m for m in messages)
print('PDF_PREVIEW=PASS: 100 DPI sample, unchanged 300 DPI final pages')

cbz = output / 'numbered.cbz'
with zipfile.ZipFile(cbz, 'w') as archive:
    archive.writestr('1.png', art)
    archive.writestr('ComicInfo.xml', '<ComicInfo><Title>Numbered</Title><Number>2</Number></ComicInfo>')

class Database:
    def all_book_ids(self): return ()
    def add_books(self, books, **kwargs): return [1], []

gui = QWidget(); gui.current_db = types.SimpleNamespace(new_api=Database(), library_path='C:/MangaNana-Dev/Test-Library')

def selected_panel_height(sequence):
    probe = main.MangaNanaDialog(gui, QIcon())
    probe.show(); probe.resize(1400, 940); app.processEvents()
    for mode in sequence:
        probe._set_workflow_mode(mode); app.processEvents()
    height = probe._selected_top_panel.height()
    probe.close(); app.processEvents()
    return height

direct_heights = {
    'volume': selected_panel_height(('volume',)),
    'chapter': selected_panel_height(('chapter',)),
}
for sequence in (
        ('volume', 'chapter'), ('chapter', 'volume'),
        ('volume', 'chapter', 'volume'), ('chapter', 'volume', 'chapter')):
    assert selected_panel_height(sequence) == direct_heights[sequence[-1]], sequence
print('MODE_GEOMETRY=PASS: Selected Manga matches direct-mode geometry after every switch sequence')

dialog = main.MangaNanaDialog(gui, QIcon())
dialog.show(); app.processEvents(); dialog.resize(1400, 940); app.processEvents()
dialog._set_workflow_mode('volume'); app.processEvents()
original_y = dialog.volume_mode_btn.mapTo(dialog, QPoint(0, 0)).y()
original_height = dialog._search_top_panel.height()
dialog._set_workflow_mode('import'); app.processEvents()
import_y = dialog.import_mode_btn.mapTo(dialog, QPoint(0, 0)).y()
assert import_y < 220, import_y
assert dialog.import_table.width() > dialog.width() * .75, 'Import inventory should use the available width'
assert dialog.import_table.height() > 300, 'Import inventory should expand below the compact mode controls'
assert dialog._search_top_panel.maximumHeight() == 16777215
assert not dialog.search_results.isVisible() and not dialog.url.isVisible()
assert not dialog.pad.isVisible()
dialog.grab().save(str(output / 'import-layout.png'))
dialog._set_workflow_mode('volume'); app.processEvents()
assert dialog.volume_mode_btn.mapTo(dialog, QPoint(0, 0)).y() == original_y
assert dialog._search_top_panel.height() == original_height
assert dialog.search_results.isVisible() and dialog.url.isVisible()
assert dialog.covers.text() == 'Use source volume cover in Calibre metadata'
assert 'imported' not in dialog.cover_mode_note.text()
dialog._set_workflow_mode('chapter'); app.processEvents()
assert dialog.covers.text() == 'Use series cover in Calibre metadata'
assert dialog.pad.text() == 'Zero-pad chapter numbers (Recommended)'
dialog._set_workflow_mode('import')
print('LAYOUT=PASS: Import controls at top; source geometry and cover wording restored')

# Hold inspection to check the pending state before ready is delivered.
release = threading.Event(); inspect = import_workers.inspect_book
def held_inspection(*args, **kwargs):
    assert release.wait(10)
    return inspect(*args, **kwargs)
with patch.object(import_workers, 'inspect_book', side_effect=held_inspection):
    dialog._inspect_import_paths([str(pdf)])
    assert dialog.import_status.text() == 'Inspecting 1 file…'
    assert 'Inspecting' in dialog.workflow_hint.text()
    assert dialog.import_table.rowCount() == 0 and not dialog.preview_btn.isEnabled()
    app.processEvents(); dialog.grab().save(str(output / 'inspection.png'))
    release.set(); wait_until(lambda: dialog._import_inspection is None)
assert dialog.import_table.rowCount() == 1 and dialog.import_status.text() == '1 imported book.'
selector_host = dialog.import_table.cellWidget(0, 0)
selector = selector_host.findChild(QCheckBox)
assert selector is not None and selector.isChecked()
assert selector.objectName() == 'importUseCheckbox'
assert '#FF6740' in selector.styleSheet() and 'border-radius:2px' in selector.styleSheet()
assert 'standardbutton-apply-16.png' in selector.styleSheet()
assert selector_host.layout().itemAt(0).alignment() == Qt.AlignmentFlag.AlignCenter
assert dialog.import_table.columnWidth(0) == 40
selector.click(); assert not dialog._selected_import_ids
selector.click(); assert dialog._selected_import_ids
dialog.grab().save(str(output / 'import-selector.png'))
assert dialog.preview_btn.isEnabled()
dialog.cover_mode.setCurrentIndex(dialog.cover_mode.findData('generate'))
assert dialog.pad.isHidden(), 'An unnumbered PDF has no cover number to pad'
dialog._inspect_import_paths([str(cbz)]); wait_until(lambda: dialog._import_inspection is None)
assert dialog.import_status.text() == '2 imported books.'
assert not dialog.pad.isHidden(), 'Numbered generated covers retain padding'
dialog.cover_mode.setCurrentIndex(dialog.cover_mode.findData('keep'))
assert dialog.pad.isHidden(), 'Keep cover does not use number padding'
dialog._selected_import_ids = {b['id'] for b in dialog._import_books if b['format'] == 'pdf'}
dialog._remove_imports(); assert dialog.import_status.text() == '1 imported book.'
dialog._select_imports(True); dialog._remove_imports(); assert dialog.import_status.text() == 'No imported books.'
print('INSPECTION_AND_CONTROLS=PASS: loading, ready count, removal, singular/plural, meaningful padding only')

main.prefs['show_completion_summary'] = False
dialog._set_applied_metadata('Title', 'Author', 'Series')
for mode in ('import', 'volume'):
    dialog.workflow_mode = mode; dialog.log.clear()
    dialog.current_source = types.SimpleNamespace(parse_manga_ref=lambda _: 'fixture')
    dialog.preview_data = {'selected_estimated_bytes': 2000000}
    dialog.on_downloaded(dict(files=[dict(path=str(cbz), volume=None, title='Title', format='cbz',
                                         kind='import' if mode == 'import' else 'volume')],
                              pages=3, final_bytes=1000000, elapsed=1))
    text = '\n'.join(dialog.log.item(i).text() for i in range(dialog.log.count()))
    assert '1 book in Calibre' in text and 'book(s)' not in text, text
    if mode == 'import':
        assert 'Output size:' in text and 'Books skipped:' in text
        assert 'Download size' not in text and 'Existing volumes' not in text
    else:
        assert 'Download size:' in text and 'Existing volumes skipped:' in text
dialog.close(); app.processEvents()
print('COMPLETION_WORDING=PASS: local processing terms and provider download terms')
print('No network or Calibre library writes. Screenshots:', output)
