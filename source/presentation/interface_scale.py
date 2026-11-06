"""Plugin-local text scaling; Qt continues to own device-pixel-ratio scaling."""
import re
import weakref
from qt.core import QObject, QWidget, QTimer, QEvent
from calibre_plugins.manganana.app.settings.config import prefs


def scale_factor(mode, percent, available):
    if mode == 'manual':
        try:
            return max(.85, min(1.15, int(percent) / 100))
        except (TypeError, ValueError):
            return 1.
    width, height = available
    return .9 if width < 1200 or height < 700 else 1.


def set_presentation_style(widget, style):
    """Publish a canonical style through its window's scale owner before paint."""
    owner = widget.window()
    scaling = getattr(owner, 'interface_scaling', None)
    if scaling is not None and scaling.active:
        scaling.set_style(widget, style)
    elif widget.styleSheet() != style:
        widget.setStyleSheet(style)


class InterfaceScale(QObject):
    active = False

    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = weakref.ref(dialog)
        self.active = True
        self.mode = prefs.get('interface_scale_mode', 'auto')
        self.percent = prefs.get('interface_scale_percent', 100)
        self.factor = 1.
        self.styles = weakref.WeakKeyDictionary()
        self.pending = weakref.WeakSet()
        self._full = True
        self._applying = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.apply)
        dialog.finished.connect(self.detach)
        dialog.destroyed.connect(self.detach)
        self.screen_changed()
        # Resolve initial text metrics before the window's opening layout.
        self.timer.stop()
        self.apply()

    def screen_changed(self):
        if not self.active:
            return
        dialog = self._dialog()
        if dialog is None:
            return
        screen = dialog.screen()
        area = screen.availableGeometry() if screen else dialog.rect()
        factor = scale_factor(self.mode, self.percent, (area.width(), area.height()))
        self._full |= factor != self.factor
        self.factor = factor
        dialog.setProperty('interfaceScaleFactor', self.factor)
        if self._full:self.timer.start(0)

    def eventFilter(self, watched, event):
        if self.active and not self._applying and event.type() in (QEvent.Type.ChildAdded, QEvent.Type.StyleChange):
            # ChildAdded can arrive before a QWidget subclass is constructed.
            # Defer that subtree, rather than restyling the entire dialog for
            # each visible card. Our own style changes cannot enqueue a pass.
            self.pending.add(watched)
            self.timer.start(0)
        return False

    def apply(self):
        if not self.active:
            return
        roots=[self._dialog()] if self._full else list(self.pending)
        self.pending.clear()
        self._full=False
        for root in roots:
            self.apply_tree(root)

    def apply_tree(self, root):
        """Finish a newly arranged subtree before its first painted frame."""
        if not self.active or self._applying or root is None:
            return
        from PyQt6 import sip
        dialog = self._dialog()
        if dialog is None or sip.isdeleted(dialog) or sip.isdeleted(root):
            return
        self._applying=True
        try:
            self._apply_widgets(dialog, [root, *root.findChildren(QWidget)])
        finally:
            self._applying=False

    def _apply_widgets(self, dialog, widgets):
        from PyQt6 import sip
        for widget in widgets:
            if sip.isdeleted(widget):
                continue
            ancestor = widget
            preview = False
            while ancestor is not None and ancestor is not dialog:
                if ancestor.property('interfaceScalePreview'):
                    preview = True
                    break
                ancestor = ancestor.parentWidget()
            if preview:
                continue
            current = widget.styleSheet()
            previous = self.styles.get(widget)
            base = previous[0] if previous and current == previous[1] else current
            self.set_style(widget, base)

    def set_style(self, widget, base):
        scaled = re.sub(r'(font-size\s*:\s*)(\d+(?:\.\d+)?)px',
            lambda m: m[1] + f'{max(10, float(m[2])*self.factor):g}px', base)
        if widget not in self.styles:
            widget.installEventFilter(self)
        self.styles[widget] = (base, scaled)
        if widget.styleSheet() != scaled:
            previous = self._applying
            self._applying = True
            try:
                widget.setStyleSheet(scaled)
            finally:
                self._applying = previous

    def detach(self, *_):
        if not self.active:
            return
        self.active = False
        from PyQt6 import sip
        if not sip.isdeleted(self.timer):
            self.timer.stop()
        for widget in list(self.styles):
            if not sip.isdeleted(widget):
                widget.removeEventFilter(self)
        self.styles.clear()
        self.pending.clear()


def add_display_settings(dialog, layout, form_card):
    from qt.core import QComboBox, QSpinBox, QLabel, QPushButton, QFrame, QVBoxLayout
    form = form_card('Interface', layout)
    dialog.interface_scale_mode = QComboBox()
    dialog.interface_scale_mode.addItem('Auto', 'auto')
    dialog.interface_scale_mode.addItem('Manual', 'manual')
    dialog.interface_scale_mode.setCurrentIndex(1 if prefs.get('interface_scale_mode') == 'manual' else 0)
    dialog.interface_scale_percent = QSpinBox()
    dialog.interface_scale_percent.setRange(85, 115)
    dialog.interface_scale_percent.setSingleStep(5)
    dialog.interface_scale_percent.setSuffix('%')
    dialog.interface_scale_percent.setValue(int(prefs.get('interface_scale_percent', 100)))
    form.addRow('Text & control scale', dialog.interface_scale_mode)
    form.addRow('Adjustment', dialog.interface_scale_percent)
    preview = QFrame(); preview.setProperty('interfaceScalePreview', True)
    preview.setObjectName('card'); column = QVBoxLayout(preview)
    title = QLabel('MangaAnkā'); body = QLabel('A preview of interface text')
    column.addWidget(title); column.addWidget(body)
    form.addRow('Preview', preview)
    note = QLabel('Changes apply when MangaAnkā is reopened. Auto adapts to the available screen; Windows DPI scaling remains automatic.')
    note.setWordWrap(True); form.addRow(note)
    reset = QPushButton('Reset to Auto')
    form.addRow(reset)

    def update(*_):
        mode = dialog.interface_scale_mode.currentData()
        percent = dialog.interface_scale_percent.value()
        prefs['interface_scale_mode'] = mode
        prefs['interface_scale_percent'] = percent
        dialog.interface_scale_percent.setEnabled(mode == 'manual')
        screen = dialog.screen().availableGeometry()
        factor = scale_factor(mode, percent, (screen.width(), screen.height()))
        title.setStyleSheet(f'font-size:{20*factor:g}px;font-weight:600;')
        body.setStyleSheet(f'font-size:{14*factor:g}px;')

    def defaults():
        dialog.interface_scale_percent.setValue(100)
        dialog.interface_scale_mode.setCurrentIndex(0)

    dialog.interface_scale_reset = reset
    dialog.interface_scale_note = note
    dialog.interface_scale_mode.currentIndexChanged.connect(update)
    dialog.interface_scale_percent.valueChanged.connect(update)
    reset.clicked.connect(defaults)
    update()
