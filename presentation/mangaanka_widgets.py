"""Shared MangaAnkā shell widgets. Navigation remains owned by the dialog."""
from calibre_plugins.manganana.common.plugin_paths import plugin_root
from pathlib import Path

from qt.core import (QCheckBox, QComboBox, QColor, QFrame, QGridLayout, QHBoxLayout,
                     QLabel, QIcon, QPainter, QPen, QPointF, QPixmap, QScrollArea,
                     QSizePolicy, QStyle, QStyleOptionButton, QStyleOptionComboBox,
                     Qt, QVBoxLayout, QWidget, QPushButton, QBoxLayout, QStackedWidget, QLayout,
                     QApplication, QObject, QEvent, QAbstractScrollArea, QAbstractSpinBox, QSlider,
                     QSize, QWheelEvent, pyqtSignal)

from calibre_plugins.manganana.version_info import SEMANTIC_VERSION, CODENAME
from calibre_plugins.manganana.presentation.mangaanka_theme import (
    BRIGHT_SEAFOAM,
    DEEP_OCEAN,
    MIST_GRAY,
    OFF_WHITE,
    DISABLED_TEXT,
)

APP_ICON_RESOURCE = 'images/mangaanka-app-icon.png'
STAGES = (('choose_manga', 'Choose Manga'),
          ('book_customization', 'Book Customization'),
          ('finalization', 'Finalization'))


def selection_icon(pixmap):
    """Keep line icons readable on the seafoam fill of a checked segment."""
    icon = QIcon(pixmap)
    checked = pixmap.copy()
    painter = QPainter(checked)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(checked.rect(), QColor(DEEP_OCEAN))
    painter.end()
    icon.addPixmap(checked, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(checked, QIcon.Mode.Active, QIcon.State.On)
    return icon


class MangaAnkaCheckBox(QCheckBox):
    """QSS square indicator with a scale-independent two-stroke checkmark.

    Qt owns labels, focus, hit testing, keyboard input, tristate and signals.
    Only the check glyph is painted to avoid platform icon/color dependencies.
    """
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.checkState() == Qt.CheckState.Unchecked:
            return
        option = QStyleOptionButton(); self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(DEEP_OCEAN if self.isEnabled() else MIST_GRAY), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); painter.setPen(pen)
        def point(x, y): return QPointF(rect.x() + rect.width()*x, rect.y() + rect.height()*y)
        if self.checkState() == Qt.CheckState.PartiallyChecked:
            painter.drawLine(point(.25, .5), point(.75, .5))
        else:
            painter.drawLine(point(.23, .5), point(.43, .7))
            painter.drawLine(point(.43, .7), point(.78, .28))
        painter.end()


class MangaAnkaComboBox(QComboBox):
    """Normal combo box with a readable, layout-positioned dropdown chevron."""
    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionComboBox(); self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                          QStyle.SubControl.SC_ComboBoxArrow, self)
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(OFF_WHITE if self.isEnabled() else DISABLED_TEXT), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); painter.setPen(pen)
        x, y = rect.center().x(), rect.center().y()
        painter.drawLine(QPointF(x-4, y-2), QPointF(x, y+2))
        painter.drawLine(QPointF(x, y+2), QPointF(x+4, y-2))
        painter.end()


def app_icon():
    """Calibre injects get_resources for ZIP modules; source runs use the handoff.

    The build maps the original asset to APP_ICON_RESOURCE without a repository
    duplicate. Never fall back to the unrelated Calibre action icon.
    """
    try:
        raw = get_resources(APP_ICON_RESOURCE)
    except NameError:
        raw = (plugin_root() / 'docs/ui/mangaanka-app-icon.png').read_bytes()
    pixmap = QPixmap()
    if not pixmap.loadFromData(raw, 'PNG'):
        raise RuntimeError('The packaged MangaAnkā app icon could not be loaded.')
    return QIcon(pixmap)


class WorkflowStepper(QWidget):
    """Accessible navigation requests; the dialog owns stage validation."""
    stage_requested = pyqtSignal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName('Workflow stages')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.labels = {}
        step_style='''
QPushButton#ankaStep {color:#d2d9df;background:#1a2428;border:1px solid #354541;
 border-radius:18px;padding:8px 18px;font-size:13px;font-weight:600;}
QPushButton#ankaStep:hover {background:#293b3b;border-color:#66B7A8;}
QPushButton#ankaStep:focus {border:1px solid #a2eadc;background:#293b3b;}
QPushButton#ankaStep[active="true"] {color:#102421;background:#66B7A8;}
QPushButton#ankaStep[active="true"]:hover {background:#80c9bb;}
QPushButton#ankaStep:disabled {color:#73818a;background:transparent;}
'''
        for number, (key, title) in enumerate(STAGES, 1):
            label = QPushButton(f'{number}  {title}')
            label.setObjectName('ankaStep')
            label.setStyleSheet(step_style)
            label.setAutoDefault(False)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            label.setToolTip(f'Go to {title}' + (' — select content first' if number > 1 else ''))
            label.clicked.connect(lambda checked=False, stage=key: self.stage_requested.emit(stage))
            self.labels[key] = label
            layout.addWidget(label)
        self.set_active('choose_manga')

    def set_active(self, stage):
        if stage not in self.labels:
            raise ValueError(f'Unknown stage: {stage}')
        self.active_stage = stage
        for key, label in self.labels.items():
            active = key == stage
            label.setProperty('active', active)
            label.setAccessibleName(label.text() + (' — current stage' if active else ''))
            label.style().unpolish(label)
            label.style().polish(label)
            label.update()


class MangaAnkaHeader(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('ankaHeader')
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 8)
        self.grid.setHorizontalSpacing(24)
        self.brand = QWidget()
        brand_row = QHBoxLayout(self.brand)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(12)
        self.app_icon = app_icon()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(self.app_icon.pixmap(48, 48))
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setAccessibleName('MangaAnkā app icon')
        brand_row.addWidget(self.icon_label)
        text = QVBoxLayout(); text.setSpacing(0)
        self.name_label = QLabel(f'Manga<span style="color:{BRIGHT_SEAFOAM};">Ankā</span>')
        self.name_label.setTextFormat(Qt.TextFormat.RichText)
        self.name_label.setAccessibleName('MangaAnkā')
        self.name_label.setObjectName('ankaName')
        self.subtitle = QLabel('From jgog'); self.subtitle.setObjectName('ankaSubtitle')
        text.addWidget(self.name_label); text.addWidget(self.subtitle)
        brand_row.addLayout(text)
        self.stepper = WorkflowStepper()
        self.version = QLabel(f'v{SEMANTIC_VERSION}\n{CODENAME}')
        self.version.setObjectName('ankaVersion')
        self.version.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.grid.addWidget(self.brand, 0, 0, Qt.AlignmentFlag.AlignLeft)
        self.grid.addWidget(self.version, 0, 2, Qt.AlignmentFlag.AlignRight)
        # Equal outer columns anchor the stepper to the window's center, not
        # the leftover space between unequal branding and version labels.
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(2, 1)
        self._compact = None
        self._reflow()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def _reflow(self):
        wing = max(self.brand.sizeHint().width(), self.version.sizeHint().width())
        self.grid.setColumnMinimumWidth(0, wing)
        self.grid.setColumnMinimumWidth(2, wing)
        required = 2 * wing + self.stepper.sizeHint().width() + 2 * self.grid.horizontalSpacing()
        compact = self.width() < required
        if compact == self._compact:
            return
        self._compact = compact
        self.grid.removeWidget(self.stepper)
        if compact:
            self.grid.addWidget(self.stepper, 1, 0, 1, 3, Qt.AlignmentFlag.AlignCenter)
        else:
            self.grid.addWidget(self.stepper, 0, 1, Qt.AlignmentFlag.AlignCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()


class MangaAnkaFooter(QFrame):
    """Hosts existing action widgets; never creates or connects workflow actions."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('ankaFooter')
        self.stack = QVBoxLayout(self)
        self.stack.setContentsMargins(0, 8, 0, 0)
        self.stack.setSpacing(8)
        self.actions = QGridLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(8)
        self._compact = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def set_actions(self, utilities, navigation):
        self.utilities = QWidget(); utility_row = QHBoxLayout(self.utilities)
        self.navigation = QWidget(); navigation_row = QHBoxLayout(self.navigation)
        for row, buttons in ((utility_row, utilities), (navigation_row, navigation)):
            row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
            for button in buttons:
                row.addWidget(button)
        self.stack.addLayout(self.actions)
        self._reflow()

    def _reflow(self):
        if not hasattr(self, 'utilities'):
            return
        required = self.utilities.sizeHint().width() + self.navigation.sizeHint().width() + 16
        compact = self.width() < required
        if compact == self._compact:
            return
        self._compact = compact
        self.actions.removeWidget(self.utilities); self.actions.removeWidget(self.navigation)
        self.actions.addWidget(self.utilities, 0, 0, Qt.AlignmentFlag.AlignLeft)
        self.actions.addWidget(self.navigation, 1 if compact else 0, 0 if compact else 1,
                               Qt.AlignmentFlag.AlignRight)
        self.actions.setColumnStretch(0, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()


class MangaAnkaShell:
    """Layout owner with persistent chrome and a bounded scrolling work area."""
    def __init__(self, dialog):
        self.layout = QVBoxLayout(dialog)
        self.layout.setContentsMargins(16, 12, 16, 12)
        self.layout.setSpacing(8)
        self.header = MangaAnkaHeader()
        self.layout.addWidget(self.header)
        self.workspace = QScrollArea()
        self.workspace.setObjectName('ankaWorkspace')
        self.workspace.setWidgetResizable(True)
        self.workspace.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout.addWidget(self.workspace, 1)
        self.footer = MangaAnkaFooter()
        self.layout.addWidget(self.footer)

    def set_workspace(self, widget):
        self.workspace.setWidget(widget)


class ElidedSummary(QLabel):
    """One-line secondary text whose contents never set the panel's width."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ''
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f'color:{MIST_GRAY}; background:transparent;')

    def set_summary(self, text):
        text = ' '.join(text.split())
        self.full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self._elide()

    def setText(self, text):
        self.set_summary(str(text))

    def minimumSizeHint(self):
        margins = self.contentsMargins()
        return QSize(0, self.fontMetrics().height() + margins.top() + margins.bottom() + 4)

    def sizeHint(self):
        return self.minimumSizeHint()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight,
                                                 max(0, self.contentsRect().width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._elide(); self.updateGeometry()


class CollapsibleSection(QWidget):
    """A section in the outer page flow, without an independent scroll viewport."""
    def __init__(self, title, expanded=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.setObjectName('customizationSection')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self); layout.setContentsMargins(10, 6, 10, 8)
        self.header = QPushButton(); self.header.setObjectName('sectionHeader')
        self.header.setCheckable(True); self.header.setChecked(expanded)
        self.body = QWidget()
        self.content = QVBoxLayout(self.body); self.content.setContentsMargins(0, 4, 0, 10)
        self.content.setSpacing(7)
        self.summary = ElidedSummary()
        layout.setSpacing(4)
        layout.addWidget(self.header); layout.addWidget(self.summary); layout.addWidget(self.body)
        self.header.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded):
        # ASCII markers also work when Qt's offscreen font catalog lacks arrows.
        self.header.setText(('-  ' if expanded else '+  ') + self.title.replace('&', '&&'))
        self.header.setAccessibleName(self.title + (' expanded' if expanded else ' collapsed'))
        self.body.setVisible(expanded)
        self.summary.setVisible(not expanded)
        self.updateGeometry()


class ResponsiveColumns(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        # A horizontal layout's summed minimum must not prevent the resize
        # event that switches it to a vertical layout (notably loaded preview).
        self.columns.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.columns.setContentsMargins(0, 0, 0, 0); self.columns.setSpacing(10)
        self.stacked = False

    def panel_widths(self):
        widths = []
        for i in range(self.columns.count()):
            widget = self.columns.itemAt(i).widget()
            if widget is None or widget.isHidden():
                continue
            policy = widget.sizePolicy().horizontalPolicy()
            hint = widget.sizeHint() if policy == QSizePolicy.Policy.Fixed else widget.minimumSizeHint()
            widths.append(max(0, widget.minimumWidth(), hint.width()))
        return widths

    def required_two_column_width(self):
        widths = self.panel_widths()
        margins = self.columns.contentsMargins()
        return sum(widths) + max(0, len(widths)-1)*self.columns.spacing() + margins.left() + margins.right()

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        margins = self.columns.contentsMargins()
        size.setWidth(max(self.panel_widths(), default=0) + margins.left() + margins.right())
        return size

    def reflow(self):
        stacked = self.width() < self.required_two_column_width()
        if stacked != self.stacked:
            self.stacked = stacked
            self.columns.setDirection(QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight)
            self.updateGeometry()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest:
            self.reflow()
        return result

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


class PreviewGridScroll(QScrollArea):
    """Reflow existing thumbnails without acquiring or processing images."""
    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        body = self.widget()
        if body is not None and body.layout() is not None:
            grid = body.layout(); margins = grid.contentsMargins()
            width = max((grid.itemAt(i).widget().minimumSizeHint().width() for i in range(grid.count())), default=0)
            size.setWidth(max(size.width(), width+margins.left()+margins.right()+2*self.frameWidth()+
                              self.verticalScrollBar().sizeHint().width()))
        return size

    def reflow(self):
        body = self.widget()
        if body is None or body.layout() is None:
            return
        grid = body.layout()
        cells = [grid.itemAt(i).widget() for i in range(grid.count())]
        if not cells:
            return
        margins = grid.contentsMargins()
        required = 2*max(cell.minimumSizeHint().width() for cell in cells) + grid.horizontalSpacing()
        columns = 2 if self.viewport().width()-margins.left()-margins.right() >= required else 1
        for cell in cells:
            grid.removeWidget(cell)
        for index, cell in enumerate(cells):
            grid.addWidget(cell, index//columns, index%columns)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


class CurrentStageStack(QStackedWidget):
    """Hidden stages must not impose their combined minimum on the active page."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget is not None else super().minimumSizeHint()

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget is not None else super().sizeHint()

    def heightForWidth(self, width):
        # QStackedLayout otherwise includes hidden stages when measuring
        # wrapped content, making the preview inherit discovery's page height.
        widget = self.currentWidget()
        if widget is not None:
            return widget.heightForWidth(width) if widget.hasHeightForWidth() else widget.sizeHint().height()
        return super().heightForWidth(width)


class PageWheelFilter(QObject):
    """Dialog-scoped wheel safety and nested-scroll handoff, including lazy views.

    Qt owns all scrolling and gesture accumulation. Only target selection is
    ours; forwarding retains the native event fields, not computed increments.
    Popup lists retain Qt's native selection/scroll behavior. Keyboard, clicking,
    dragging and explicit Ctrl-wheel preview zoom are left to their widgets.
    """
    _active = False
    _registered = False
    def __init__(self, dialog, workspace):
        super().__init__(dialog)
        self.dialog = dialog
        self.workspace = workspace
        self._forwarding = False
        QApplication.instance().installEventFilter(self)
        self._registered = self._active = True
        dialog.finished.connect(self.detach)

    def detach(self, *_):
        self._active = False
        from PyQt6 import sip
        app = QApplication.instance()
        if self._registered and app is not None and not sip.isdeleted(self):
            app.removeEventFilter(self)
        self._registered = False

    def __del__(self):
        self.detach()

    def eventFilter(self, watched, event):
        if not self._active or event.type() != QEvent.Type.Wheel or self._forwarding or not isinstance(watched, QWidget):
            return False
        if not self.dialog.isAncestorOf(watched):
            return False
        if watched.window().windowType() == Qt.WindowType.Popup:
            return False
        node = watched
        areas = []
        sensitive = False
        while node is not None and node is not self.dialog:
            if isinstance(node, QComboBox) and node.view().isVisible():
                return False
            sensitive |= isinstance(node, (QComboBox, QSlider, QAbstractSpinBox))
            if isinstance(node, QAbstractScrollArea):
                areas.append(node)
            node = node.parentWidget()
        if not areas and not sensitive:
            return False
        if not sensitive and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        # Activity Log is in the fixed footer, not a child of the workspace.
        # At its boundaries the page is still the natural scroll destination.
        if self.workspace not in areas:
            areas.append(self.workspace)
        pixel = event.pixelDelta()
        delta = pixel if not pixel.isNull() else event.angleDelta()
        horizontal = abs(delta.x()) > abs(delta.y())
        amount = delta.x() if horizontal else delta.y()
        for area in areas:
            bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
            if (amount > 0 and bar.value() <= bar.minimum()) or (amount < 0 and bar.value() >= bar.maximum()):
                continue
            if area is areas[0] and not sensitive and watched in (area, area.viewport(), bar):
                return False  # Original event, native inner/outer scrolling.
            target = area.viewport()
            forwarded = QWheelEvent(target.mapFromGlobal(event.globalPosition()), event.globalPosition(),
                                    event.pixelDelta(), event.angleDelta(), event.buttons(), event.modifiers(),
                                    event.phase(), event.inverted(),
                                    event.source() if hasattr(event, 'source') else Qt.MouseEventSource.MouseEventNotSynthesized,
                                    event.pointingDevice())
            if hasattr(forwarded, 'setTimestamp'):
                forwarded.setTimestamp(event.timestamp())
            self._forwarding = True
            try:
                QApplication.sendEvent(target, forwarded)
            finally:
                self._forwarding = False
            event.accept()
            return True
        event.accept()
        return True
