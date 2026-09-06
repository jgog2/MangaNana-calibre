"""Run with calibre-debug -e, isolated CALIBRE_CONFIG_DIRECTORY, offscreen Qt.

Exercises the real dialog/Qt workers using synthetic pages and a fake library.
No provider or user library is contacted. Not part of the plain-Python suite.
"""
import os
from pathlib import Path
import sys
import types
import urllib.request

root=Path(__file__).resolve().parents[1]
assert os.environ.get('CALIBRE_CONFIG_DIRECTORY'), 'Use an isolated configuration.'
assert Path(os.environ['CALIBRE_CONFIG_DIRECTORY']).resolve().parent == root
if os.environ.get('MANGANANA_QT_PACKAGED')=='1':
    from calibre.customize.ui import initialized_plugins
    assert any(plugin.name=='MangaNana' for plugin in initialized_plugins())
else:
    package=types.ModuleType('calibre_plugins.manganana'); package.__path__=[str(root)]
    sys.modules['calibre_plugins.manganana']=package

from qt.core import QApplication, QIcon, QWidget, QEventLoop, QTimer, QFontDatabase, QFont, QToolButton, QPushButton, QEvent, Qt, QSize, QPointF, QPoint, QMouseEvent, QWheelEvent
from PIL import Image
from calibre_plugins.manganana.main import LeftShiftIconButton, MangaNanaDialog
from calibre_plugins.manganana.image_processing import ProcessingSettings, apply_processing
from calibre_plugins.manganana.processing_presets import BUILTIN_PRESETS_BY_ID
from calibre_plugins.manganana import native_dithering
if os.environ.get('MANGANANA_QT_PACKAGED')=='1':
    assert '.zip' in sys.modules['calibre_plugins.manganana.main'].__file__.lower()

expected_backend=os.environ.get('MANGANANA_SMOKE_EXPECT_BACKEND','native')
if expected_backend=='portable':
    def unavailable_native_resource(): raise FileNotFoundError('Synthetic missing DLL control')
    native_dithering._resource_bytes=unavailable_native_resource

app=QApplication([])
network_calls=[]
def forbidden_network(*args,**kwargs):
    network_calls.append(True)
    raise AssertionError('Qt processing/detail smoke must never use the network')
urllib.request.urlopen=forbidden_network
font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
if font.is_file():
    QFontDatabase.addApplicationFont(str(font)); app.setFont(QFont('Segoe UI',10))
gui=QWidget()
gui.current_db=types.SimpleNamespace(new_api=object(),library_path='Isolated synthetic library')
dialog=MangaNanaDialog(gui,QIcon())
dialog.show(); app.processEvents()
print('OPENING_CLIENT=',dialog.width(),dialog.height())
print('OPENING_FRAME=',dialog.frameGeometry().width(),dialog.frameGeometry().height())
print('AVAILABLE=',dialog.screen().availableGeometry().width(),dialog.screen().availableGeometry().height())
dialog._set_stage('book_customization')
assert [dialog.screen_emulation.itemText(i) for i in range(dialog.screen_emulation.count())]==[
    'Off','Kobo Libra Colour']
assert dialog.screen_emulation.currentData()=='none'
assert dialog._screen_emulation_id=='none'
assert dialog.processing_preset.currentText()=='Original'
assert [dialog.processing_preset.itemText(i) for i in range(dialog.processing_preset.count())]==[
    'Original','B&W Manga','High Contrast B&W','Soft Grayscale','Color Enhancement','Custom']
assert dialog.portrait_btn.iconSize()==QSize(38,28)
assert dialog.landscape_btn.iconSize()==QSize(36,36)
assert isinstance(dialog.portrait_btn,QPushButton)
assert not isinstance(dialog.portrait_btn,LeftShiftIconButton)
assert isinstance(dialog.landscape_btn,LeftShiftIconButton)
assert dialog.landscape_btn._icon_left_shift==5
assert dialog.landscape_btn.text()=='LANDSCAPE\nPaired Pages'
dialog.landscape_btn.setChecked(True)
QApplication.sendEvent(dialog.landscape_btn,QEvent(QEvent.Type.Enter))
dialog.landscape_btn.grab()
QApplication.sendEvent(dialog.landscape_btn,QEvent(QEvent.Type.Leave))
transition_count=0
original_invalidate=dialog.invalidate_preview
def count_invalidation():
    global transition_count
    transition_count+=1; original_invalidate()
dialog.invalidate_preview=count_invalidation
dialog.processing_preset.setCurrentIndex(dialog.processing_preset.findData('bw_manga'))
assert dialog.processing==BUILTIN_PRESETS_BY_ID['bw_manga'].settings and transition_count==1
assert dialog.processing_preset.currentText()=='B&W Manga'
dialog._processing_controls['contrast'][0].setValue(120)
assert dialog.processing_preset.currentText()=='Custom'
dialog._prompt_processing_preset_name=lambda *args:'B&W Manga Test 2'
dialog._save_processing_preset()
assert dialog.processing_preset.findData('user:B&W Manga Test 2')>=0
assert [dialog.processing_preset.itemText(i) for i in range(dialog.processing_preset.count())]==[
    'Original','B&W Manga','High Contrast B&W','Soft Grayscale','Color Enhancement',
    'MY PRESETS','B&W Manga Test 2','Custom']
dialog._processing_controls['contrast'][0].setValue(115)
assert dialog.processing_preset.currentText()=='B&W Manga'
dialog._reset_processing()
assert dialog.processing==BUILTIN_PRESETS_BY_ID['original'].settings and transition_count==4
dialog.processing_preset.setCurrentIndex(dialog.processing_preset.findData('color_enhancement'))
assert dialog.processing.saturation==1.25 and dialog._processing_controls['saturation'][0].value()==125
dialog._reset_processing()
dialog._update_processing_preset('B&W Manga Test 2')
dialog._prompt_processing_preset_name=lambda *args:'B&W Manga Tuned'
dialog._rename_processing_preset('B&W Manga Test 2')
assert dialog.processing_preset.findData('user:B&W Manga Tuned')>=0
assert list(dialog._processing_controls)==['brightness','contrast','gamma','saturation','sharpness']
assert not hasattr(dialog,'resolution')
for name,low,high in (('brightness',25,200),('contrast',50,200),('gamma',50,250),('saturation',20,300),('sharpness',0,200)):
    slider,label=dialog._processing_controls[name]
    assert (slider.minimum(),slider.maximum(),slider.singleStep(),slider.pageStep(),slider.value())==(low,high,5,5,100)
    assert label.text()==('1.00' if name=='gamma' else '100%')
for tick,gamma,pixel in ((50,.5,64),(100,1.,128),(200,2.,181)):
    dialog._processing_controls['gamma'][0].setValue(tick)
    assert dialog.processing.gamma==gamma
    assert apply_processing(Image.new('L',(1,1),128),dialog.processing).getpixel((0,0))==pixel
dialog._reset_processing()
print('REAL_QT_GAMMA_0.5_1.0_2.0=64_128_181')
app.processEvents()
dialog.grab().save(str(root/'dist'/'empress-small-screen-smoke.png'))
for name,(slider,label) in dialog._processing_controls.items():
    slider.setValue(125)
    assert label.text() == ('1.25' if name=='gamma' else '125%')
assert dialog.workflow_state.preview_state=='off'
assert not dialog._processing_pending
assert dialog.processing==ProcessingSettings(1.25,1.25,1.25,brightness=1.25,sharpness=1.25)

def wait_render():
    for _attempt in range(6):
        loop=QEventLoop(); timeout=QTimer(); timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit); timeout.start(60000)
        worker=dialog._processing_worker
        if worker is not None:
            worker.finished.connect(loop.quit)
            if worker.isRunning(): loop.exec()
        app.processEvents()
        assert timeout.isActive(), 'Local render timed out'
        timeout.stop()
        if dialog._processing_worker is None and not dialog._processing_pending:
            return
    raise AssertionError('Local render did not settle to newest state')

for layout in ('original_pages','paired_landscape'):
    dialog._choose_layout(layout)
    key=dialog._live_preview_signature_value()
    image=Image.new('RGB',(160,240),(90,120,160))
    images=(image,Image.new('RGB',image.size,(160,100,90)),Image.new('RGB',image.size,(90,160,100)))
    sample={'layout':layout,'records':tuple({'image':im,'size':im.size,'ext':'.png'} for im in images),
            'stats':{'individuals':3},'source_pages':3}
    dialog._live_preview_samples={key:sample}; dialog._active_preview_sample_key=key
    dialog._live_preview_stale=False; dialog.workflow_state.mark_preview_ready()
    dialog._schedule_processing_render(immediate=True)
    wait_render()
    assert dialog.live_preview_grid.count()==(2 if layout=='paired_landscape' else 3)
    overview_images=dialog._overview_images
    overview_bytes={number:image.constBits().asstring(image.sizeInBytes())
                    for number,image in overview_images.items()}
    generation=dialog._render_ownership.generation
    final_signature=dialog.current_signature(); live_signature=dialog._live_preview_signature_value()
    dialog.workflow_state.set_finalization_plan(('screen-emulation-firewall',))
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('kobo_libra_colour'))
    assert dialog._render_ownership.generation==generation
    assert dialog._processing_worker is None and not dialog._processing_pending
    assert dialog._overview_images is overview_images
    assert overview_bytes=={number:image.constBits().asstring(image.sizeInBytes())
                            for number,image in dialog._overview_images.items()}
    assert dialog.current_signature()==final_signature
    assert dialog._live_preview_signature_value()==live_signature
    assert not dialog.workflow_state.finalization_stale
    assert dialog.workflow_state.finalization_plan==('screen-emulation-firewall',)
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('none'))
    assert dialog._render_ownership.generation==generation
    button=dialog.live_preview_grid.itemAt(0).widget().findChild(QToolButton)
    expected=(1680,1264) if layout=='paired_landscape' else image.size
    assert f'{expected[0]} × {expected[1]}' in button.text()
    button.click()
    assert dialog._detail_viewer.surface.image is dialog._overview_images[1]
    assert dialog._detail_viewer._provisional
    assert dialog._detail_viewer.surface.width()>1 and dialog._detail_viewer.surface.height()>1
    wait_render()
    viewer=dialog._detail_viewer
    assert not viewer.isWindow()
    assert dialog.live_preview_stack.currentWidget() is viewer
    assert viewer.window() is dialog
    assert viewer.surface.image is not None
    assert (viewer.surface.image.width(),viewer.surface.image.height())==expected
    assert viewer.aspect_host._aspect_ratio is None
    assert viewer.scroll.geometry()==viewer.aspect_host.contentsRect()
    viewer.zoom.setCurrentIndex(viewer.zoom.findData(None)); app.processEvents()
    off_scroll_geometry=viewer.scroll.geometry()
    normal_processing=dialog.processing
    normal_signature=dialog.current_signature(); normal_live_signature=dialog._live_preview_signature_value()
    outer_size=dialog.size(); preview_card_geometry=dialog.live_preview_stack.parentWidget().geometry()
    network_before=len(network_calls)
    dialog.workflow_state.set_finalization_plan(('screen-emulation-firewall',))
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('kobo_libra_colour'))
    assert viewer.surface.image is None, 'Off -> Kobo must clear the raw page immediately'
    assert viewer.surface.emulated and viewer._emulation_id=='kobo_libra_colour'
    assert dialog.processing==normal_processing
    assert dialog.current_signature()==normal_signature
    assert dialog._live_preview_signature_value()==normal_live_signature
    assert not dialog.workflow_state.finalization_stale
    assert dialog.workflow_state.finalization_plan==('screen-emulation-firewall',)
    assert len(network_calls)==network_before
    wait_render()
    screen=(1680,1264) if layout=='paired_landscape' else (1264,1680)
    assert (viewer.surface.image.width(),viewer.surface.image.height())==screen
    assert viewer.aspect_host._aspect_ratio is None
    assert viewer.scroll.geometry()==viewer.aspect_host.contentsRect()==off_scroll_geometry
    assert dialog.size()==outer_size and dialog.live_preview_stack.parentWidget().geometry()==preview_card_geometry
    viewer.zoom.setCurrentIndex(viewer.zoom.findData(None)); app.processEvents()
    assert viewer.surface.width()<=viewer.scroll.viewport().width()
    assert viewer.surface.height()<=viewer.scroll.viewport().height()
    viewport=viewer.scroll.viewport().size()
    fit_factor=min(1.,viewport.width()/screen[0],viewport.height()/screen[1])
    expected_fit=QSize(max(1,round(screen[0]*fit_factor)),max(1,round(screen[1]*fit_factor)))
    assert viewer.surface.size()==expected_fit
    fitted_size=viewer.surface.size()
    viewer.set_emulation('none',layout); viewer._apply_zoom(); app.processEvents()
    assert viewer.surface.size()==fitted_size
    viewer.set_emulation('kobo_libra_colour',layout); viewer._apply_zoom(); app.processEvents()
    assert viewer.surface.size()==fitted_size
    dialog._schedule_processing_render(immediate=True); wait_render()
    assert viewer.surface.size()==fitted_size, 'Repeated refresh must not accumulate Fit shrink'
    resize_generation=dialog._render_ownership.generation
    fit_dialog_size=dialog.size()
    dialog.resize(fit_dialog_size.width()+120,fit_dialog_size.height()+80); app.processEvents()
    grown_viewport=viewer.scroll.viewport().size()
    grown_factor=min(1.,grown_viewport.width()/screen[0],grown_viewport.height()/screen[1])
    assert viewer.surface.size()==QSize(max(1,round(screen[0]*grown_factor)),
                                       max(1,round(screen[1]*grown_factor)))
    dialog.resize(fit_dialog_size); app.processEvents()
    assert viewer.surface.size()==fitted_size
    assert dialog._render_ownership.generation==resize_generation
    viewer.grab().save(str(root/'dist'/f'empress-kobo-{layout}-smoke.png'))
    viewer.zoom.setCurrentIndex(viewer.zoom.findData(1.0)); app.processEvents()
    assert viewer.zoom.currentText()=='100% Device Pixels'
    assert viewer.surface.size()==QSize(*screen)
    device_menu=viewer.zoom_menu()
    assert '100% Device Pixels' in [action.text() for action in device_menu.actions()]
    device_menu.deleteLater()
    viewer.zoom.setCurrentIndex(viewer.zoom.findData(2.0)); app.processEvents()
    assert viewer.surface.size()==QSize(screen[0]*2,screen[1]*2)
    assert not viewer.surface.smooth_scaling()
    assert viewer.scroll.horizontalScrollBar().maximum()>0 or viewer.scroll.verticalScrollBar().maximum()>0
    dialog._reset_processing(); assert dialog._screen_emulation_id=='kobo_libra_colour'
    dialog._flush_processing_render(); wait_render()
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('none'))
    assert viewer.surface.image is None, 'Kobo -> Off must clear the emulated framebuffer immediately'
    assert not viewer.surface.emulated and viewer._emulation_id=='none'
    wait_render()
    assert (viewer.surface.image.width(),viewer.surface.image.height())==expected
    assert viewer.aspect_host._aspect_ratio is None
    assert viewer.zoom.itemText(viewer.zoom.findData(1.0))=='100%'
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('kobo_libra_colour'))
    first_profile_worker=dialog._processing_worker
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('none'))
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('kobo_libra_colour'))
    assert first_profile_worker.isInterruptionRequested()
    assert viewer.surface.image is None and viewer.surface.emulated
    wait_render()
    assert dialog._screen_emulation_id=='kobo_libra_colour'
    assert (viewer.surface.image.width(),viewer.surface.image.height())==screen
    emulated_framebuffer=viewer.surface.image
    emulated_bits=emulated_framebuffer.constBits().asstring(emulated_framebuffer.sizeInBytes())
    emulated_generation=dialog._render_ownership.generation
    emulated_network_before=len(network_calls)
    for index in range(viewer.zoom.count()):
        viewer.zoom.setCurrentIndex(index); app.processEvents()
    emulated_menu=viewer.zoom_menu()
    emulated_menu.actions()[-1].trigger(); app.processEvents()
    emulated_menu.actions()[-2].trigger(); app.processEvents()
    emulated_menu.deleteLater()
    emulated_wheel=QWheelEvent(
        QPointF(20,20),QPointF(20,20),QPoint(),QPoint(0,-120),
        Qt.MouseButton.NoButton,Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,False)
    QApplication.sendEvent(viewer.surface,emulated_wheel); app.processEvents()
    viewer.zoom.setCurrentIndex(viewer.zoom.findData(2.0)); app.processEvents()
    for bar in (viewer.scroll.horizontalScrollBar(),viewer.scroll.verticalScrollBar()):
        bar.setValue(bar.maximum()//2)
    emulated_pan=QMouseEvent(
        QEvent.Type.MouseButtonPress,QPointF(100,100),QPointF(100,100),
        Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewer.surface,emulated_pan)
    emulated_pan=QMouseEvent(
        QEvent.Type.MouseMove,QPointF(70,70),QPointF(70,70),
        Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewer.surface,emulated_pan)
    emulated_pan=QMouseEvent(
        QEvent.Type.MouseButtonRelease,QPointF(70,70),QPointF(70,70),
        Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(viewer.surface,emulated_pan); app.processEvents()
    assert viewer.surface.image is emulated_framebuffer
    assert emulated_bits==viewer.surface.image.constBits().asstring(viewer.surface.image.sizeInBytes())
    assert dialog._render_ownership.generation==emulated_generation
    assert dialog._processing_worker is None and not dialog._processing_pending
    assert len(network_calls)==emulated_network_before
    dialog.screen_emulation.setCurrentIndex(dialog.screen_emulation.findData('none'))
    wait_render()
    viewer.pages.setCurrentIndex(1)
    assert viewer.surface.image is dialog._overview_images[2] and viewer._provisional
    wait_render()
    assert dialog._detail_page==2 and viewer.surface.image is not None
    generation=dialog._render_ownership.generation
    framebuffer=viewer.surface.image
    framebuffer_bits=framebuffer.constBits().asstring(framebuffer.sizeInBytes())
    network_before=len(network_calls)
    for index in range(viewer.zoom.count()):
        viewer.zoom.setCurrentIndex(index); app.processEvents()
        if viewer.zoom.currentData()==1.0:
            assert viewer.surface.size()==viewer.surface.image.size()
    assert dialog._render_ownership.generation==generation, 'Zoom must not trigger rendering'
    assert dialog._processing_worker is None and not dialog._processing_pending
    assert viewer.surface.image is framebuffer
    assert framebuffer_bits==viewer.surface.image.constBits().asstring(viewer.surface.image.sizeInBytes())
    assert len(network_calls)==network_before
    assert [viewer.zoom.itemData(i) for i in range(viewer.zoom.count())]==[None,.25,.5,.75,1.,1.25,1.5,2.]
    menu=viewer.zoom_menu()
    assert [a.text() for a in menu.actions() if not a.isSeparator()]==[
        'Fit to Preview','25%','50%','75%','100% Actual Pixels','125%','150%','200%','Zoom In','Zoom Out']
    assert menu.actions()[8].isChecked()  # 200% plus separator
    menu.actions()[-1].trigger(); assert viewer.zoom.currentData()==1.5
    menu.actions()[-2].trigger(); assert viewer.zoom.currentData()==2.
    menu.deleteLater()
    wheel=QWheelEvent(QPointF(20,20),QPointF(20,20),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.ControlModifier,Qt.ScrollPhase.NoScrollPhase,False)
    QApplication.sendEvent(viewer.surface,wheel); assert viewer.zoom.currentData()==1.5
    viewer.zoom.setCurrentIndex(7); app.processEvents()
    for bar in (viewer.scroll.horizontalScrollBar(),viewer.scroll.verticalScrollBar()): bar.setValue(bar.maximum()//2)
    old_scroll=viewer.scroll.verticalScrollBar().value()
    for event_type,position,button,buttons in (
        (QEvent.Type.MouseButtonPress,100,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove,70,Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease,70,Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton)):
        event=QMouseEvent(event_type,QPointF(position,position),QPointF(position,position),button,buttons,Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(viewer.surface,event)
    if viewer.scroll.verticalScrollBar().maximum()>0:
        assert viewer.scroll.verticalScrollBar().value()==min(viewer.scroll.verticalScrollBar().maximum(),old_scroll+30)
    center=viewer.view_center()
    old_overview=dialog._overview_images
    for value in range(105,200,5):
        dialog._processing_controls['gamma'][0].setValue(value)
    dialog._flush_processing_render(); wait_render()
    assert dialog.processing.gamma==1.95
    assert dialog._overview_images is old_overview and dialog._overview_dirty
    assert dialog.workflow_state.preview_state=='ready'
    assert all(abs(a-b)<.02 for a,b in zip(center,viewer.view_center())), (center,viewer.view_center())
    saturation=dialog._processing_controls['saturation'][0]
    saturation.setValue(155)
    dialog.grayscale_on.click()
    assert not saturation.isEnabled() and dialog.processing.saturation==1.55
    center=viewer.view_center()
    dialog._processing_controls['brightness'][0].setValue(150)
    dialog._processing_controls['sharpness'][0].setValue(200)
    dialog._flush_processing_render(); wait_render()
    assert dialog.processing.grayscale and dialog.processing.brightness==1.5 and dialog.processing.sharpness==2
    assert dialog._overview_images is old_overview and dialog._overview_dirty
    assert (viewer.surface.image.width(),viewer.surface.image.height())==expected
    assert all(abs(a-b)<.02 for a,b in zip(center,viewer.view_center())), ('adjusted center',center,viewer.view_center())
    assert [dialog.output_depth.itemText(i) for i in range(dialog.output_depth.count())]==['Original','16 Gray Levels','8 Gray Levels','4 Gray Levels','2 Gray Levels']
    dialog.output_depth.setCurrentIndex(2)
    assert dialog.dithering.isEnabled() and not dialog.dither_strength.isEnabled()
    dialog.dithering.setCurrentIndex(2); dialog.dither_strength.setValue(200)
    assert dialog.dither_strength.isEnabled() and dialog.processing.dither_strength==2.
    dialog._flush_processing_render(); wait_render()
    assert dialog.processing.output_depth==8 and viewer.surface.image is not None
    dialog.grayscale_off.click()
    assert saturation.isEnabled() and saturation.value()==155
    assert dialog.output_depth.itemText(2)=='512 Colors'
    dialog.dithering.setCurrentIndex(0)  # Keep large color smoke bounded on portable Calibre.
    dialog._flush_processing_render(); wait_render()
    dialog._reset_processing(); dialog._flush_processing_render(); wait_render()
    assert dialog.processing.neutral
    assert dialog.output_depth.currentData()==0 and dialog.dithering.currentData()=='off' and dialog.dither_strength.value()==100
    assert (viewer.surface.image.width(),viewer.surface.image.height())==expected
    viewer.zoom.setCurrentIndex(4); app.processEvents()
    viewer.scroll.horizontalScrollBar().setValue(viewer.scroll.horizontalScrollBar().maximum())
    viewer.scroll.verticalScrollBar().setValue(viewer.scroll.verticalScrollBar().maximum())
    app.processEvents()
    viewer.grab().save(str(root/'dist'/'empress-detail-smoke.png'))
    viewer.back.click()
    assert dialog._processing_pending
    dialog._flush_processing_render(); wait_render()
    assert dialog._detail_viewer is None and dialog.live_preview_stack.currentIndex()==0
    assert dialog._overview_images is not old_overview and not dialog._overview_dirty

dialog.resize(1764,1068); app.processEvents()
left=dialog.reading_direction.parentWidget()
for widget in (dialog.reading_direction_label,dialog.reading_direction,dialog.processing_preset,
               dialog.dither_strength):
    assert widget.isVisible()
    top=widget.mapTo(left,QPoint(0,0)).y(); bottom=top+widget.height()
    assert top>=0 and bottom<=left.contentsRect().height(),(widget.accessibleName(),top,bottom,left.height())
assert dialog.reading_direction.height()>=dialog.reading_direction.sizeHint().height()
dialog.grab().save(str(root/'dist'/'empress-customization-smoke.png'))
for _slider,label in dialog._processing_controls.values():
    assert label.isVisible() and label.width() >= label.sizeHint().width()
dialog._open_preview_detail(1); wait_render()
dialog._processing_controls['gamma'][0].setValue(175); dialog._flush_processing_render()
dialog.close(); wait_render(); app.processEvents()
assert dialog._detail_viewer is None and dialog._detail_page is None
second=MangaNanaDialog(gui,QIcon())
assert second.processing.neutral, 'Processing must not persist across launches'
assert second.screen_emulation.currentData()=='none', 'eReader Sim must not persist across launches'
assert second.processing_preset.currentText()=='Original'
assert second.processing_preset.findData('user:B&W Manga Tuned')>=0
assert [second.processing_preset.itemText(i) for i in range(second.processing_preset.count())]==[
    'Original','B&W Manga','High Contrast B&W','Soft Grayscale','Color Enhancement',
    'MY PRESETS','B&W Manga Tuned','Custom']
assert not second.grayscale_on.isChecked() and not hasattr(second,'resolution')
assert second._processing_controls['brightness'][0].value()==second._processing_controls['sharpness'][0].value()==100
assert second._processing_controls['saturation'][0].maximum()==300
assert not hasattr(second,'_screen_emulation_frame_blobs')
second.screen_emulation.setCurrentIndex(second.screen_emulation.findData('kobo_libra_colour'))
assert second.screen_emulation.currentData()=='kobo_libra_colour'
assert second._screen_emulation_id=='kobo_libra_colour'
second.close(); app.processEvents()
print('EMPRESS_QT_SMOKE=PASS')
assert not network_calls
print('DETAIL_AND_ZOOM_NETWORK_CALLS=0')
assert native_dithering.backend_status().startswith(expected_backend), native_dithering.backend_status()
print('QT_BACKEND=',native_dithering.backend_status())
