"""Synchronous scale ownership and idempotent responsive layout contracts."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from qt.core import QApplication,QDialog,QLabel,QFontInfo,QObject,QEvent,QSize,QVBoxLayout
from calibre_plugins.manganana.discovery.saved_manga_ui import HeroTitleRow,HeroHeart
from calibre_plugins.manganana.presentation.interface_scale import InterfaceScale,set_presentation_style
from calibre_plugins.manganana.presentation.choose_manga_reference import ReferenceFidelityLayout
from calibre_plugins.manganana.app.settings.config import prefs


class Events(QObject):
    def __init__(self,parent):super().__init__(parent);self.fonts=0;self.styles=0
    def eventFilter(self,watched,event):
        self.fonts+=event.type()==QEvent.Type.FontChange
        self.styles+=event.type()==QEvent.Type.StyleChange
        return False


class LayoutStabilityTests(unittest.TestCase):
    def test_explicit_style_is_scaled_before_return_without_compounding(self):
        app=QApplication.instance() or QApplication([])
        saved={k:prefs.get(k) for k in ('interface_scale_mode','interface_scale_percent')}
        d=QDialog();label=QLabel('Stable',d)
        try:
            prefs['interface_scale_mode']='manual';prefs['interface_scale_percent']=85
            d.interface_scaling=InterfaceScale(d)
            d.show();label.ensurePolished();app.processEvents()
            set_presentation_style(label,'font-size:32px;')
            self.assertEqual(QFontInfo(label.font()).pixelSize(),27)
            observer=Events(label);label.installEventFilter(observer)
            for _ in range(20):
                set_presentation_style(label,'font-size:32px;')
                d.interface_scaling.apply_tree(label)
                self.assertEqual(QFontInfo(label.font()).pixelSize(),27)
            self.assertEqual(observer.fonts,0);self.assertEqual(observer.styles,0)
            app.processEvents()
            self.assertEqual(QFontInfo(label.font()).pixelSize(),27)
        finally:
            d.interface_scaling.detach();d.deleteLater();app.processEvents()
            for key,value in saved.items():prefs[key]=value

    def test_boundary_inputs_are_idempotent_and_hidden_stages_do_not_reflow(self):
        class Boundary:
            def width(self):return 1200
            def height(self):return 700
        d=Boundary();d.inventory_stack=object();d.workflow_state=SimpleNamespace(stage='choose_manga')
        d.anka_shell=SimpleNamespace(workspace=SimpleNamespace(viewport=lambda:Boundary()))
        d.property=lambda name:1.
        owner=SimpleNamespace(d=d,right_workspace=Boundary(),_resize_discovery=Mock())
        for _ in range(20):ReferenceFidelityLayout.resize(owner)
        owner._resize_discovery.assert_called_once()
        d.workflow_state.stage='finalization';owner._layout_key=None
        ReferenceFidelityLayout.resize(owner)
        owner._resize_discovery.assert_called_once()

    def test_boundary_reentry_does_not_recurse(self):
        d=SimpleNamespace(inventory_stack=object())
        owner=SimpleNamespace(d=d,_arranging=True)
        ReferenceFidelityLayout.resize(owner)
        self.assertTrue(owner._arranging)

    def test_title_row_uses_current_metrics_even_when_label_hint_is_stale(self):
        class StaleLabel(QLabel):
            def sizeHint(self):return QSize(51,19)
        app=QApplication.instance() or QApplication([])
        d=QDialog();d._closing=False
        d.selected_title=StaleLabel('Berserk',d)
        d.fidelity=SimpleNamespace(title_field=SimpleNamespace(text='Berserk'))
        layout=QVBoxLayout(d);heart=HeroHeart(d);row=HeroTitleRow(d,heart);layout.addWidget(row)
        try:
            d.show();app.processEvents()
            d.selected_title.setStyleSheet('font-size:32px;')
            d.selected_title.ensurePolished();row.sync_metrics();app.processEvents()
            height=d.selected_title.fontMetrics().height()
            self.assertGreater(height,19)
            self.assertGreaterEqual(row.sizeHint().height(),height)
            self.assertEqual(d.selected_title.height(),height)
            self.assertEqual(d.selected_title.y(),0)
            row._active=False
            d.selected_title.removeEventFilter(row)
            d.selected_title.setStyleSheet('font-size:18px;')
            self.assertEqual(row.sizeHint(),QSize(0,0))
        finally:
            row._active=False;d.selected_title.removeEventFilter(row)
            d.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
