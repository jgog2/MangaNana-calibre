"""Real Qt checks for incremental, idempotent scaling and retired subtrees."""
import importlib.util
from pathlib import Path
import sys,types,unittest
from qt.core import QApplication,QDialog,QWidget,QLabel,QFontInfo,QEvent,QObject
from PyQt6 import sip

ROOT=Path(__file__).resolve().parents[1]
package=types.ModuleType('scroll_scale_test');package.__path__=[str(ROOT)]
config=types.ModuleType('scroll_scale_test.config');config.prefs={}
sys.modules[package.__name__]=package;sys.modules[config.__name__]=config
spec=importlib.util.spec_from_file_location('scroll_scale_test.interface_scale',ROOT/'presentation/interface_scale.py')
scale=importlib.util.module_from_spec(spec);spec.loader.exec_module(scale)
scale.prefs=config.prefs

class FontEvents(QObject):
    def __init__(self,parent):super().__init__(parent);self.count=0
    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.FontChange:self.count+=1
        return False

class ScalingTests(unittest.TestCase):
    def setUp(self):
        self.app=QApplication.instance() or QApplication([])
        self.d=QDialog();self.d.setStyleSheet('QWidget {font-size:15px;}')
        self.label=QLabel('Stable hero',self.d);self.label.setStyleSheet('font-size:34px;')
        config.prefs.update(interface_scale_mode='manual',interface_scale_percent=85)
        self.scale=scale.InterfaceScale(self.d);self.scale.apply();self.app.processEvents()
    def tearDown(self):
        self.scale.detach();self.d.deleteLater();self.app.processEvents()
    def test_new_cards_cannot_rescale_existing_title(self):
        observer=FontEvents(self.label);self.label.installEventFilter(observer)
        base=QFontInfo(self.label.font()).pixelSize()
        for n in range(25):
            row=QWidget(self.d);label=QLabel('Chapter '+str(n),row)
            label.setStyleSheet('font-size:14px;');self.scale.apply_tree(row)
            self.app.processEvents()
            self.assertEqual(QFontInfo(label.font()).pixelSize(),12)
            self.assertEqual(QFontInfo(self.label.font()).pixelSize(),base)
        self.assertEqual(observer.count,0)
    def test_factor_never_compounds(self):
        for percent,expected in ((85,29),(100,34),(115,39),(85,29)):
            self.scale.percent=percent;self.scale.screen_changed();self.scale.apply()
            for _ in range(8):self.scale.apply_tree(self.d);self.app.processEvents()
            self.assertEqual(QFontInfo(self.label.font()).pixelSize(),expected)
    def test_changed_base_rule_is_scaled_once(self):
        self.label.setStyleSheet('font-size:26px;');self.app.processEvents();self.scale.apply()
        self.assertEqual(QFontInfo(self.label.font()).pixelSize(),22)
        before=self.label.styleSheet()
        self.scale.apply_tree(self.label);self.assertEqual(before,self.label.styleSheet())
    def test_retired_pending_widget_is_safe(self):
        row=QWidget(self.d);self.scale.pending.add(row);sip.delete(row)
        self.scale.apply();self.assertTrue(self.scale.active)
    def test_detach_is_terminal_and_clears_work(self):
        self.label.setStyleSheet('font-size:22px;');self.scale.detach()
        self.scale.apply_tree(self.d);self.scale.apply();self.app.processEvents()
        self.assertFalse(self.scale.timer.isActive());self.assertFalse(self.scale.pending)
        self.assertEqual(self.label.styleSheet(),'font-size:22px;')
    def test_preview_retains_its_explicit_font(self):
        preview=QWidget(self.d);preview.setProperty('interfaceScalePreview',True)
        label=QLabel('Preview',preview);label.setStyleSheet('font-size:20px;')
        self.scale.apply_tree(preview);self.assertEqual(label.styleSheet(),'font-size:20px;')

class CarouselRoutingTests(unittest.TestCase):
    def setUp(self):
        import ast
        import qt.core as q
        self.q=q;self.app=q.QApplication.instance() or q.QApplication([])
        tree=ast.parse((ROOT/'presentation/choose_manga_design.py').read_text(encoding='utf8'))
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='VolumeCarousel')
        ns={name:getattr(q,name) for name in ('QObject','QTimer','QHBoxLayout','QPushButton','QApplication','QWidget','Qt','QEvent','QAbstractItemView')}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'production VolumeCarousel','exec'),ns)
        self.d=q.QDialog();self.d.workflow_mode='chapter';self.d.resize(650,240)
        host=q.QWidget(self.d);host.setGeometry(0,0,650,240)
        self.view=self.d.volume_list=q.QListWidget(self.d)
        self.view.setFlow(q.QListView.Flow.LeftToRight);self.view.setWrapping(False)
        self.view.setHorizontalScrollMode(q.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setVerticalScrollBarPolicy(q.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for n in range(30):
            item=q.QListWidgetItem(str(n));item.setSizeHint(q.QSize(132,200));self.view.addItem(item)
        self.carousel=ns['VolumeCarousel'](self.d,host)
        self.d.show();self.view.setCurrentRow(0);self.app.processEvents();self.app.processEvents()
        self.bar=self.view.horizontalScrollBar()
    def tearDown(self):
        self.carousel.detach();self.d.close();self.d.deleteLater();self.app.processEvents()
    def test_scrollbar_drag_after_keyboard_does_not_restore_current_item(self):
        q=self.q
        self.bar.setValue(self.bar.maximum());self.app.processEvents()
        opt=q.QStyleOptionSlider();self.bar.initStyleOption(opt)
        grip=self.bar.style().subControlRect(q.QStyle.ComplexControl.CC_ScrollBar,opt,q.QStyle.SubControl.SC_ScrollBarSlider,self.bar)
        start=grip.center();end=q.QPoint(self.bar.width()//2,start.y())
        for kind,pos,buttons in ((q.QEvent.Type.MouseButtonPress,start,q.Qt.MouseButton.LeftButton),(q.QEvent.Type.MouseMove,end,q.Qt.MouseButton.LeftButton),(q.QEvent.Type.MouseButtonRelease,end,q.Qt.MouseButton.NoButton)):
            self.app.sendEvent(self.bar,q.QMouseEvent(kind,q.QPointF(pos),q.QPointF(self.bar.mapToGlobal(pos)),q.Qt.MouseButton.NoButton if kind==q.QEvent.Type.MouseMove else q.Qt.MouseButton.LeftButton,buttons,q.Qt.KeyboardModifier.NoModifier))
        requested=self.bar.value();self.assertGreater(requested,0)
        self.app.processEvents();self.app.processEvents()
        self.assertEqual(self.bar.value(),requested);self.assertEqual(self.view.currentRow(),0)
    def test_scrollbar_keys_remain_native_slider_input(self):
        q=self.q
        self.app.sendEvent(self.bar,q.QKeyEvent(q.QEvent.Type.KeyPress,q.Qt.Key.Key_End,q.Qt.KeyboardModifier.NoModifier))
        self.app.processEvents()
        self.assertEqual(self.bar.value(),self.bar.maximum());self.assertEqual(self.view.currentRow(),0)

    def _click_arrow(self, button):
        button.setFocus(self.q.Qt.FocusReason.MouseFocusReason)
        button.click()
        self.app.processEvents();self.app.processEvents()

    def test_arrow_boundaries_survive_disabled_button_focus_transfer(self):
        for mode in ('volume','chapter'):
            self.d.workflow_mode=mode
            for side in ('left','right'):
                with self.subTest(mode=mode,side=side):
                    self.view.setCurrentRow(15);self.view.setFocus()
                    self.app.processEvents();self.app.processEvents()
                    self.bar.setValue(1 if side=='left' else self.bar.maximum()-1)
                    current=self.view.currentItem()
                    self._click_arrow(getattr(self.carousel,side))
                    boundary=self.bar.minimum() if side=='left' else self.bar.maximum()
                    self.assertEqual(self.bar.value(),boundary)
                    self.assertIs(self.view.currentItem(),current)
                    self.assertFalse(getattr(self.carousel,side).isEnabled())

    def test_pending_focus_refresh_cannot_undo_arrow_scroll(self):
        self.view.setCurrentRow(15)
        self.bar.setValue(1)
        self._click_arrow(self.carousel.left)
        self.assertEqual(self.bar.value(),self.bar.minimum())
        self.assertEqual(self.view.currentRow(),15)

    def test_card_keyboard_navigation_reveals_current_after_arrow_browsing(self):
        q=self.q
        self.view.setCurrentRow(15);self.app.processEvents();self.app.processEvents()
        self.bar.setValue(1);self._click_arrow(self.carousel.left)
        for key,target in ((q.Qt.Key.Key_Right,16),(q.Qt.Key.Key_Left,15),
                           (q.Qt.Key.Key_Home,0),(q.Qt.Key.Key_End,29)):
            self.app.sendEvent(self.view,q.QKeyEvent(q.QEvent.Type.KeyPress,key,q.Qt.KeyboardModifier.NoModifier))
            self.app.processEvents();self.app.processEvents()
            self.assertEqual(self.view.currentRow(),target)
            self.assertTrue(self.view.viewport().rect().intersects(self.view.visualItemRect(self.view.currentItem())))
        self.assertEqual(self.bar.value(),self.bar.maximum())

if __name__=='__main__':unittest.main()
