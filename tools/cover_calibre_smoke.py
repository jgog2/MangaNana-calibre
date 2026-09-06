"""Run with calibre-debug -e and isolated config under Test-Data; no library I/O."""
from io import BytesIO
from pathlib import Path
import os
import sys
import tempfile
import types
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
test_data = Path('C:/MangaNana-Dev/Test-Data').resolve()
config = Path(os.environ['CALIBRE_CONFIG_DIRECTORY']).resolve()
assert test_data in config.parents, 'Use a test-only Calibre configuration.'
output = test_data / 'manganana-cover-validation'
output.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = 'C:/MangaNana-Dev/Test-Downloads'
package = types.ModuleType('calibre_plugins.manganana'); package.__path__ = [str(root)]
sys.modules['calibre_plugins.manganana'] = package
from calibre_plugins.manganana import main
from calibre_plugins.manganana.cover_rendering import render_cover
from qt.core import QApplication, QDialog, QEventLoop, QFont, QFontDatabase, QIcon, QThread, QTimer, QWidget
from PIL import Image

app = QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
app.setFont(QFont('Segoe UI',10))
def forbidden(*args, **kwargs): raise AssertionError('External network forbidden in cover smoke.')
urllib.request.urlopen = forbidden

buffer = BytesIO(); Image.new('RGB', (740, 1200), (45, 90, 160)).save(buffer, 'PNG')
art = buffer.getvalue()

class Source:
    source_id = 'mangadex'; display_name = 'Synthetic'; capabilities = ()
    def __init__(self): self.cover_fetches = 0
    def fetch_binary(self, url, **kwargs):
        assert QThread.currentThread() != app.thread(), 'Fetch must be off GUI thread.'
        self.cover_fetches += int(url == 'cover.png')
        return art
    def get_page_manifest(self, *args, **kwargs): return {'full':['page.png']}
    def get_volume_covers(self, *args): return {16.: 'cover.png'}


def run(worker, signal='ready'):
    values = []; errors = []; loop = QEventLoop(); timer = QTimer(); timer.setSingleShot(True)
    getattr(worker, signal).connect(values.append); worker.failed.connect(errors.append)
    worker.finished.connect(loop.quit); timer.timeout.connect(loop.quit)
    timer.start(30000); worker.start(); loop.exec()
    assert timer.isActive(), 'Worker timeout'
    timer.stop(); worker.wait(); app.processEvents()
    assert not errors, errors
    assert len(values) == 1
    return values[0]


source = Source()
# Execute the real grouped output path, including chapter->volume grouping.
for kind, number in (('volume',16),('chapter',103),('standalone',None)):
    archives = []
    for mode in ('keep','stamp','generate'):
        chapter = dict(id='fixture',chapter='103',pages=1,_source_id='fixture')
        group = dict(kind=kind,volume=number if kind=='volume' else None,
                     identifier=str(number or ''),chapters=[chapter])
        worker = main.DownloadWorker(source,'fixture','Chainsaw Man (Official Colored)','Author',
            'Chainsaw Man','en',None,None,True,True,(),cover_mode=mode,
            main_cover_url='cover.png',volume_covers={16.:'cover.png'},chapter_output_groups=[group])
        result = run(worker,'finished_ok')
        try:
            assert not result['failures'], result['failures']
            item = result['files'][0]
            with zipfile.ZipFile(item['path']) as archive:
                archives.append({name:archive.read(name) for name in archive.namelist()})
            cover = Path(item['cover_path']).read_bytes()
            expected = render_cover(art,mode=mode,title='Chainsaw Man (Official Colored)',
                series='Chainsaw Man',output_kind=kind,volume=number if kind=='volume' else None,
                chapter_number='103' if kind=='chapter' else None)
            assert cover == expected
            (output / f'{mode}-{kind}.png').write_bytes(cover)
        finally:
            # Validate the exact temporary root before recursive cleanup.
            work = Path(result['workdir']).resolve()
            assert work.parent == Path(tempfile.tempdir).resolve()
            import shutil
            shutil.rmtree(work)
    assert archives[0] == archives[1] == archives[2]

gui = QWidget(); gui.current_db = types.SimpleNamespace(
    new_api=object(),library_path='C:/MangaNana-Dev/Test-Library')
dialog = main.MangaNanaDialog(gui,QIcon())
dialog.current_source = source
dialog.workflow_mode = 'volume'; dialog.current_manga_url = 'fixture'
dialog.loaded_metadata = {'title':'Chainsaw Man (Official Colored)'}
dialog._set_applied_metadata('Chainsaw Man (Official Colored)','Author','Chainsaw Man')
dialog._selected_volumes = {16.}; dialog._download_language_valid = True
dialog._loaded_covers = {16.:'cover.png'}; dialog._main_cover_url = 'cover.png'
dialog._set_stage('finalization'); dialog.setMaximumSize(2000,1400); dialog.resize(1400,940)
dialog.show(); app.processEvents()
assert [dialog.cover_mode.itemText(i) for i in range(3)] == [name for name,_ in main.COVER_MODES]

for mode in ('stamp','generate'):
    previous = dialog.current_signature()
    dialog.cover_mode.setCurrentIndex(dialog.cover_mode.findData(mode)); app.processEvents()
    assert previous != dialog.current_signature()
    assert not dialog.covers.isEnabled()
    assert not dialog.download_btn.isEnabled(), 'Changing cover mode must invalidate review.'
    chapter = dict(id='fixture',chapter='103',pages=1,_source_id='fixture')
    group = dict(kind='volume',volume=16.,identifier='16',chapters=[chapter])
    worker = main.PreviewWorker(source,'fixture','Chainsaw Man (Official Colored)','Author',
        'Chainsaw Man','en',None,None,True,(),chapter_output_plan=[group])
    data = run(worker)
    dialog.on_preview_ready(data,build_signature=dialog.current_signature())
    assert dialog.preview_table.rowCount() == 1
    assert not dialog.workflow_state.finalization_stale
    preview_errors=[]; ticks=[0]
    timer=QTimer(); timer.setInterval(25)
    def close_when_ready():
        ticks[0]+=1
        if dialog.preview_data['rows'][0].get('cover_thumbnail') or ticks[0] > 800:
            if ticks[0] > 800: preview_errors.append('Cover preview timed out')
            for child in dialog.findChildren(QDialog):
                if child.windowTitle() == 'Cover Preview': child.reject()
    timer.timeout.connect(close_when_ready); timer.start()
    dialog._show_cover_preview(); timer.stop(); app.processEvents()
    assert not preview_errors
    assert dialog.preview_data['rows'][0].get('cover_thumbnail')
    assert ticks[0] > 0, 'GUI event loop should stay responsive during preview.'
    dialog._set_download_ui_locked(True)
    assert not dialog.cover_mode.isEnabled() and not dialog.cover_preview_btn.isEnabled()
    dialog._set_download_ui_locked(False)
    assert dialog.cover_mode.isEnabled() and not dialog.covers.isEnabled()

dialog.resize(1400,940); app.processEvents()
dialog.grab().save(str(output / 'finalization.png'))
dialog.close(); app.processEvents()
print('COVER_QT_SMOKE=PASS: both modes, grouped volumes/chapters/standalone, preview, locking, CBZ isolation')
print('No external network or Calibre library writes. Visual samples:', output)
