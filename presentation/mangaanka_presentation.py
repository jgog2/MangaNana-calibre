"""Shared modern design tokens; scoped to plugin windows, never QApplication."""
import re
from qt.core import (QWidget,QDialog,QApplication,QEvent,QObject,QTimer)
from calibre_plugins.manganana.presentation.choose_manga_resources import asset_root

UI_ACCENT = '#66B7A8'
TOKENS={'background':'#030A0F','surface':'#111922','raised':'#1a2430',
    'text':'#edf0f5','muted':'#aeb8c7','border':'#354151','accent':UI_ACCENT,
    'spacing':(4,8,12,16,24,32),'radius':8}

def shared_style():
    arrow=(asset_root()/'assets/ui/icons/chevron-down.svg').as_posix()
    return '''
QDialog, QWidget#mangananaShell {background:#030A0F;color:#edf0f5;}
QWidget {font-family:'Geist','Yu Gothic UI','Microsoft YaHei UI','Segoe UI';font-size:14px;color:#edf0f5;}
QLabel {background:transparent;}
QFrame#card, QGroupBox, QFrame[ankaRole="panel"], QWidget#customizationSection {
 background:#111922;border:1px solid #303945;border-radius:8px;}
QFrame#ankaHeader, QFrame#ankaFooter {border:0;border-top:0;border-bottom:0;border-radius:0;}
QFrame#finalizationPanel {background:#111922;border:0;border-radius:0;}
QTableWidget#finalOutputs, QTableWidget#finalOutputs QHeaderView {
 border:0;border-radius:0;padding:0;}
QWidget#selectedMangaCard, QFrame[ankaRole="nested"], QFrame#sourceManagerRow {
 background:#111922;border:1px solid #303945;border-radius:8px;}
QGroupBox {margin-top:18px;padding:16px 12px 12px;font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 5px;}
QPushButton, QToolButton {background:#1a2430;color:#edf0f5;border:1px solid #354151;border-radius:8px;padding:6px 10px;min-height:18px;}
QPushButton:hover, QToolButton:hover {background:#253242;border-color:#647488;}
QPushButton:focus, QToolButton:focus {border:1px solid #30d8cf;}
QPushButton#primaryAction, QPushButton[ankaRole="primary"] {background:#20d4bd;color:#03100f;border:1px solid #6eeee0;font-weight:600;}
QPushButton:disabled, QToolButton:disabled, QPushButton#primaryAction:disabled,
QPushButton[ankaRole="primary"]:disabled {background:#17212a;color:#73808d;border-color:#303945;}
QPushButton#processingChoice:checked,QPushButton#layoutChoice:checked,QPushButton[ankaRole="segment"]:checked {
 background:#31424c;color:#ffffff;border-color:#84939e;}
QLineEdit,QComboBox,QAbstractSpinBox,QTextEdit,QPlainTextEdit {background:#0d151e;color:#edf0f5;border:1px solid #354151;border-radius:8px;padding:6px;selection-background-color:#235057;}
QLineEdit:focus,QComboBox:focus,QAbstractSpinBox:focus,QTextEdit:focus,QPlainTextEdit:focus {border-color:#30d8cf;}
QComboBox {padding-right:28px;}
QComboBox::drop-down {width:24px;border:0;}
QComboBox::down-arrow {image:url("ARROW");width:12px;height:12px;}
QComboBox QAbstractItemView {background:#111922;color:#edf0f5;selection-background-color:#31424c;border:1px solid #354151;}
QCheckBox,QRadioButton {spacing:8px;padding:2px;border:1px solid transparent;}
QCheckBox:focus,QRadioButton:focus {border-color:#30d8cf;}
QCheckBox::indicator,QRadioButton::indicator {width:16px;height:16px;background:#0d151e;border:1px solid #84939e;}
QCheckBox::indicator {border-radius:4px;}
QCheckBox::indicator:checked,QRadioButton::indicator:checked {background:#20d4bd;border-color:#6eeee0;}
QRadioButton::indicator {border-radius:9px;}
QScrollArea,QStackedWidget,QWidget#previewOverview,QWidget#previewBody,QWidget#previewDetail {background:transparent;border:0;}
QAbstractItemView {background:#0b121a;alternate-background-color:#111922;color:#edf0f5;border:1px solid #303945;border-radius:6px;selection-background-color:#253c44;}
QHeaderView::section {background:#1a2430;color:#edf0f5;border:0;border-bottom:1px solid #354151;padding:8px 6px;}
QTableWidget {gridline-color:#303945;}
QTableCornerButton::section {background:#1a2430;border:0;}
QScrollBar:vertical {background:#0b1118;width:9px;}
QScrollBar:horizontal {background:#0b1118;height:7px;}
QScrollBar::handle {background:#52606e;min-width:24px;min-height:24px;border:0;border-radius:3px;}
QScrollBar::add-line,QScrollBar::sub-line {width:0;height:0;}
QScrollBar::add-page,QScrollBar::sub-page {background:transparent;}
QProgressBar {background:#0b1118;border:0;border-radius:3px;min-height:5px;}
QProgressBar::chunk {background:#20d4bd;border-radius:3px;}
QLabel[ankaRole="empty"] {background:transparent;color:#aeb8c7;border:0;padding:12px;}
QLabel[ankaRole="status"],QLabel[ankaRole="ready"] {background:#1a2430;border:1px solid #354151;color:#edf0f5;border-radius:6px;padding:4px 8px;}
QSlider::groove:horizontal {height:4px;background:#41484b;border-radius:2px;}
QSlider::sub-page:horizontal {background:ACCENT;border-radius:2px;}
QSlider::handle:horizontal {background:#dfe5e5;border:0;width:14px;margin:-5px 0;border-radius:7px;}
'''.replace('ARROW',arrow).replace('ACCENT',UI_ACCENT).replace('#20d4bd',UI_ACCENT).replace('#30d8cf',UI_ACCENT).replace('#6eeee0',UI_ACCENT).replace('color:#03100f','color:#102421')

def _neutral_local(style):
    colors={'#08131d':'#030A0F','#10253a':'#111922','#1c3a52':'#1a2430',
        '#285a58':'#354151','#242a46':'#1a2430','#3e7c72':'#52606e','#66b7a8':UI_ACCENT,
        '#17191b':'#111922','#eef3f1':'#edf0f5','#aab8bd':'#aeb8c7'}
    style=re.sub(r'#[0-9a-fA-F]{6}',lambda m:colors.get(m[0].lower(),m[0]),style)
    return style.replace('Segoe UI','Geist')

def apply_presentation(window):
    from calibre_plugins.manganana.presentation.choose_manga_design import review_font
    window.setFont(review_font())
    window.setStyleSheet(_neutral_local(window.styleSheet())+shared_style())
    for widget in window.findChildren(QWidget):
        # Provider palettes carry source identity, not application decoration.
        if widget.__class__.__name__=='ProviderBadgeWidget':continue
        style=widget.styleSheet()
        if style:widget.setStyleSheet(_neutral_local(style))
    window.setProperty('mangaankaPresentation',True)
    if window.__class__.__name__ == 'PreferencesDialog':
        from calibre_plugins.manganana.presentation.choose_manga_polish import polish_preferences
        polish_preferences(window)
    elif window.property('seafoamSettings'):
        from calibre_plugins.manganana.presentation.choose_manga_polish import SETTINGS_STYLE
        window.setStyleSheet(window.styleSheet()+SETTINGS_STYLE)

def fit_dialog(dialog):
    screen=dialog.screen()
    if screen:
        space=screen.availableGeometry().adjusted(20,35,-20,-35)
        dialog.resize(min(dialog.width(),space.width()),min(dialog.height(),space.height()))
        dialog.move(max(space.left(),min(dialog.x(),space.right()-dialog.width())),
                    max(space.top(),min(dialog.y(),space.bottom()-dialog.height())))

class PresentationScope(QObject):
    """Lazy plugin dialogs inherit the same tokens, including inline legacy rules."""
    _active=False
    _registered=False
    def __init__(self,dialog):
        super().__init__(dialog);self.dialog=dialog
        import weakref
        self._pending=weakref.WeakSet()
        self._fit_timer=QTimer(self);self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_pending)
        QApplication.instance().installEventFilter(self)
        self._registered=self._active=True
        dialog.finished.connect(self.detach)

    def detach(self,*_):
        self._active=False
        from PyQt6 import sip
        app=QApplication.instance()
        if self._registered and app is not None and not sip.isdeleted(self):
            app.removeEventFilter(self)
        self._registered=False
        timer=getattr(self,'_fit_timer',None)
        if timer is not None and not sip.isdeleted(timer):timer.stop()
        pending=getattr(self,'_pending',None)
        if pending is not None:pending.clear()

    def __del__(self):
        self.detach()

    def _fit_pending(self):
        if not self._active:return
        from PyQt6 import sip
        pending=list(self._pending);self._pending.clear()
        for dialog in pending:
            if not sip.isdeleted(dialog) and dialog.isVisible():fit_dialog(dialog)

    def eventFilter(self,watched,event):
        if not self._active:return False
        if (event.type()==QEvent.Type.Show and isinstance(watched,QDialog) and watched is not self.dialog
                and not watched.property('mangaankaNativeFileDialog')):
            ancestor=watched.parentWidget()
            while ancestor is not None and ancestor is not self.dialog:ancestor=ancestor.parentWidget()
            if ancestor is self.dialog and not watched.property('mangaankaPresentation'):
                apply_presentation(watched)
                self._pending.add(watched);self._fit_timer.start(0)
        return False
