"""Native Choose Manga layout and reusable presentation components.

No acquisition, publication or navigation authority lives in this module.
"""
from types import MethodType
from qt.core import (Qt, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QSplitter, QStackedLayout, QSizePolicy, QFont,
    QFontDatabase, QFontInfo, QFrame, QEvent, QObject, QSize, QTimer, QColor, QIcon, QMenu,
    QApplication, QAbstractItemView, QScrollArea, QFontMetrics, QProgressBar,
    QStyle, QStyleOptionButton, QLayout, QRect, QPoint)
from calibre_plugins.manganana.presentation.non_modal_window import PluginDialog as QDialog
from calibre_plugins.manganana.presentation.mangaanka_widgets import PreviewGridScroll
from calibre_plugins.manganana.presentation.choose_manga_resources import asset_root
from calibre_plugins.manganana.presentation.interface_scale import set_presentation_style

FONT_ROOT = asset_root() / 'assets/ui/fonts'
_font_family = None


class PreviewFlowLayout(QLayout):
    """Pack completed page tiles at their natural size, in output order."""
    def __init__(self, parent):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(8, 8, 8, 8)
        self.setSpacing(12)

    def addWidget(self, widget, *_grid_position):
        # Retain the controller's grid-shaped API; positioning belongs here.
        super().addWidget(widget)

    def addItem(self, item):
        self.items.append(item)
        self.invalidate()

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        if 0 <= index < len(self.items):
            item = self.items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), False)

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.sizeHint())
        margins = self.contentsMargins()
        return size + QSize(margins.left()+margins.right(), margins.top()+margins.bottom())

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, True)

    def _arrange(self, rect, place):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self.items:
            size = item.sizeHint()
            if row_height and x+size.width() > area.x()+area.width():
                x = area.x(); y += row_height+self.spacing(); row_height = 0
            if place:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width()+self.spacing()
            row_height = max(row_height, size.height())
        return y+row_height-rect.y()+margins.bottom()


class PreviewFlowScroll(PreviewGridScroll):
    """Keep page heights independent of the viewport's available height."""
    def reflow(self):
        body = self.widget()
        if body is not None and body.layout() is not None:
            flow = body.layout()
            body.setMinimumHeight(flow.heightForWidth(self.viewport().width()))
            flow.setGeometry(body.rect())
            body.updateGeometry()
            self.updateGeometry()


def review_font():
    global _font_family
    if _font_family is None:
        families = []
        for name in ('Regular', 'SemiBold', 'Bold'):
            # Older Windows Qt rejects otherwise valid fonts at long extracted
            # profile paths. Load the exact bundled bytes through Qt instead.
            identity = QFontDatabase.addApplicationFontFromData((FONT_ROOT / f'Geist-{name}.ttf').read_bytes())
            if identity < 0:
                raise RuntimeError('Bundled Geist font could not be loaded: ' + name)
            families.extend(QFontDatabase.applicationFontFamilies(identity))
        _font_family = next((name for name in families if name == 'Geist'), families[0])
    font = QFont(_font_family)
    font.setFamilies([_font_family, 'Yu Gothic UI', 'Microsoft YaHei UI', 'Segoe UI', 'sans-serif'])
    font.setPixelSize(15)
    return font


STYLE = '''
QDialog { background:#030A0F; color:#edf0f5; }
QWidget { font-family:'Geist','Yu Gothic UI','Microsoft YaHei UI','Segoe UI'; font-size:15px; }
QFrame#ankaHeader { background:#0c1118; border:0; border-radius:0; }
QWidget#reviewSearch { background:#111922; border:0; border-right:1px solid #303945; border-radius:0; }
QWidget#reviewInventory { background:#030A0F; border:0; border-radius:0; }
QWidget#selectedMangaCard { background:transparent; border:0; }
QLabel { background:transparent; color:#edf0f5; }
QPushButton { color:#edf0f5; background:#1a2430; border:1px solid #354151;
 border-radius:12px; padding:7px 14px; min-height:18px; font-size:14px; }
QPushButton:hover { background:#253242; border-color:#647488; }
QPushButton:focus { border:2px solid #30d8cf; }
QPushButton:disabled { color:#73808d; background:#111923; border-color:#25303c; }
QPushButton#primaryAction { color:#03100f; background:#20d4bd; border:1px solid #6eeee0; font-weight:600; }
QPushButton#primaryAction:disabled { background:#173e3b; color:#789a95; border-color:#2b514c; }
QLineEdit, QComboBox { background:#1a2430; color:#eef2f7; border:1px solid #3c495a;
 border-radius:12px; padding:7px 12px; selection-background-color:#235057; }
QLineEdit:focus, QComboBox:focus { border-color:#30d8cf; }
QListWidget { background:transparent; border:0; outline:0; }
QListWidget::item { border:0; padding:0; background:transparent; }
QListWidget::item:selected { background:transparent; }
QPushButton#providerFilter { background:#141e29; border:1px solid #354151;
 border-radius:13px; padding:7px 8px; font-size:13px; }
QPushButton#providerFilter:checked { background:#15333d; border-color:#36c6d1; }
QPushButton#modeChoice { border:0; border-radius:14px; background:#1c2734; padding:6px 12px; }
QPushButton#modeChoice:checked { background:#d2dae3; color:#101720; }
QLabel#ankaStep { color:#c9d1de; background:transparent; border:0; padding:9px 16px; font-size:15px; }
QLabel#ankaStep[active="true"] { color:#ffffff; background:#253342; border-radius:18px;
 border-bottom:2px solid #20d4bd; font-weight:600; }
QFrame#ankaFooter { background:#111922; border:0; border-radius:0; }
QScrollBar:horizontal { background:#0b1118; height:7px; border-radius:3px; }
QScrollBar::handle:horizontal { background:#465260; min-width:32px; border-radius:3px; }
QScrollBar:vertical { background:#111922; width:7px; border-radius:3px; }
QScrollBar::handle:vertical { background:#465260; min-height:32px; border-radius:3px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QSplitter::handle { background:#303945; width:3px; }
QWidget#volumeSkeleton { background:transparent; border:0; }
QFrame#skeletonTile { background:#131d28; border:1px solid #293544; border-radius:10px; }
QLabel#skeletonCover { background:#202c39; border:0; border-radius:6px; }
QLabel#skeletonLine { background:#293544; border:0; border-radius:4px; }
'''

TILE_STYLE = '''QFrame#reviewVolumeRow, QFrame#reviewVolumeRow[selected="false"] { background:#111b27; border:1px solid #334253; border-radius:10px; }
QFrame#reviewVolumeRow[selected="true"] { background:#10303b; border:2px solid #21d7d0; }
QFrame#reviewVolumeRow[keyboardFocus="true"] { border:2px solid #b4fff4; }'''
PICK_STYLE = '''QPushButton { background:#131e29; border:1px solid #8c9bad; border-radius:4px; padding:0; min-height:0; }
QPushButton:checked { background:#21d7c3; color:#08211e; border-color:#63eee0; }
QPushButton:focus { border:2px solid white; }'''


def badge_style(widget, rule):
    if not hasattr(widget,'_review_base_style'):
        widget._review_base_style=widget.styleSheet()
    set_presentation_style(widget,widget._review_base_style+' QPushButton {'+rule+'}')


def neutral_edition(widget):
    if widget.accessibleName().startswith('Edition:'):
        widget.setGraphicsEffect(None)
        widget._review_base_style='QPushButton {background:#242d38;color:#f3f4f6;border:1px solid #9ba5b1;border-radius:8px;}'
        widget.setStyleSheet(widget._review_base_style)


class CoverToggle(QObject):
    """A click selects; a drag never changes the stable controller key."""
    def __init__(self,row):
        super().__init__(row);self.row=row;self.press=None;self.dragged=False
    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton:
            self.row._selection_modifiers=event.modifiers()
            self.press=event.position();self.dragged=False;return True
        if event.type()==QEvent.Type.MouseMove and self.press is not None:
            self.dragged |= (event.position()-self.press).manhattanLength()>=QApplication.startDragDistance()
            return True
        if event.type()==QEvent.Type.MouseButtonRelease and event.button()==Qt.MouseButton.LeftButton and self.press is not None:
            click=not self.dragged and (event.position()-self.press).manhattanLength()<QApplication.startDragDistance()
            self.press=None
            try:
                if click and self.row.isEnabled():self.row.pick.click()
            finally:self.row._selection_modifiers=None
            return True
        return False


class InventorySkeleton(QWidget):
    """Decorative placeholders outside the controller's inventory model."""
    def __init__(self):
        super().__init__()
        self.setObjectName('volumeSkeleton')
        self.setAccessibleName('Loading selected inventory; selection unavailable')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(49,10,49,10)
        layout.setSpacing(20)
        self.tiles = []
        for _ in range(5):
            tile = QFrame(); tile.setObjectName('skeletonTile')
            column = QVBoxLayout(tile); column.setContentsMargins(12,12,12,12)
            cover = QLabel(); cover.setObjectName('skeletonCover')
            tile.cover = cover
            column.addWidget(cover,0,Qt.AlignmentFlag.AlignHCenter)
            for width in (85,65):
                line = QLabel(); line.setObjectName('skeletonLine'); line.setFixedSize(width,12)
                column.addWidget(line)
            layout.addWidget(tile)
            self.tiles.append(tile)
        layout.addStretch(1)


def listing_chapter_count(info):
    """Only an explicit count reported for this source listing is displayable.

    Qualification, publication metadata and resolved acquisition counts are
    deliberately excluded. Current adapters do not supply a listing count.
    """
    for key in ('source_chapter_count', 'reported_chapter_count'):
        value = info.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


class ResultTitle(QObject):
    """Elide the existing plain-text label without changing result identity."""
    def __init__(self, label, text):
        super().__init__(label)
        self.label, self.text = label, text
        label.setWordWrap(False)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        label.setFixedHeight(23)
        label.setToolTip(text)
        label.setMaximumWidth(QFontMetrics(label.font()).horizontalAdvance(text) + 2)
        label.installEventFilter(self)
        self.elide()

    def elide(self):
        self.label.setText(QFontMetrics(self.label.font()).elidedText(
            self.text, Qt.TextElideMode.ElideRight, max(0, self.label.width())))

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.FontChange):
            self.elide()
        return False


class VolumeCarousel(QObject):
    """Dialog-local input routing; original item IDs and selection stay authoritative."""
    _active = False
    _registered = False
    def __init__(self, dialog, host):
        super().__init__(host)
        self.d, self.view = dialog, dialog.volume_list
        self.remainder = 0.0
        layout = QHBoxLayout(host); layout.setContentsMargins(0,0,0,0); layout.setSpacing(5)
        self.left, self.right = QPushButton('‹'), QPushButton('›')
        for button, label in ((self.left,'Previous volumes'),(self.right,'Next volumes')):
            button.setAccessibleName(label); button.setToolTip(label)
            button.setAutoDefault(False); button.setFixedWidth(32)
            button.setStyleSheet('QPushButton {padding:0; font-size:25px; border-radius:16px;}')
        layout.addWidget(self.left); layout.addWidget(self.view,1); layout.addWidget(self.right)
        self.left.clicked.connect(lambda:self.move(-1))
        self.right.clicked.connect(lambda:self.move(1))
        self.view.horizontalScrollBar().valueChanged.connect(self.sync)
        self.view.horizontalScrollBar().rangeChanged.connect(self.sync)
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.timeout.connect(self.focus_item)
        self.view.currentItemChanged.connect(self.schedule_focus)
        # Installed after the existing page filter, so horizontal gestures are
        # consumed here even at either boundary and cannot reach the outer page.
        QApplication.instance().installEventFilter(self)
        self._registered = self._active = True
        dialog.finished.connect(self.detach)

    def detach(self, *_):
        """Unregister before Qt children or cyclic-GC Python state disappear."""
        self._active = False
        from PyQt6 import sip
        app = QApplication.instance()
        if self._registered and app is not None and not sip.isdeleted(self):
            app.removeEventFilter(self)
        self._registered = False
        timer = getattr(self, '_focus_timer', None)
        if timer is not None and not sip.isdeleted(timer):
            timer.stop()

    def __del__(self):
        # QObject destruction can deliver application events during tp_clear.
        # Python finalizers run before cyclic GC clears instance dictionaries.
        self.detach()

    def schedule_focus(self, *_):
        if self._active:
            self._focus_timer.start(0)

    def sync(self, *_):
        if not self._active:
            return
        bar = self.view.horizontalScrollBar()
        horizontal = self.d.workflow_mode in ('volume','chapter')
        self.left.setVisible(horizontal); self.right.setVisible(horizontal)
        self.left.setEnabled(horizontal and bar.value()>bar.minimum())
        self.right.setEnabled(horizontal and bar.value()<bar.maximum())

    def move(self, direction):
        if not self._active:
            return
        bar=self.view.horizontalScrollBar()
        bar.setValue(bar.value()+direction*max(1,int(self.view.viewport().width()*.8)))

    def item_for(self, widget):
        for i in range(self.view.count()):
            item=self.view.item(i); row=self.view.itemWidget(item)
            if row is not None and (row is widget or row.isAncestorOf(widget)):
                return item
        return None

    def focus_item(self, reveal=False):
        """Refresh the focus ring; only explicit keyboard navigation scrolls."""
        if not self._active:
            return
        current=self.view.currentItem()
        for i in range(self.view.count()):
            item=self.view.item(i); row=self.view.itemWidget(item)
            if row is not None:
                focused=QApplication.focusWidget()
                row.setProperty('keyboardFocus',item is current and
                    (focused is self.view or focused is row or (focused is not None and row.isAncestorOf(focused))))
                row.style().unpolish(row); row.style().polish(row)
        # Disabling a boundary arrow transfers focus back to the list. That
        # focus refresh must not undo the user's scroll to the boundary.
        if reveal and current is not None:
            self.view.scrollToItem(current,QAbstractItemView.ScrollHint.EnsureVisible)

    def eventFilter(self, watched, event):
        kind=event.type()
        if not self._active or kind not in (QEvent.Type.Wheel, QEvent.Type.FocusIn,
                QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            return False
        if (self.d.workflow_mode not in ('volume','chapter') or not isinstance(watched,QWidget)
                or (watched is not self.view and not self.view.isAncestorOf(watched))):
            return False
        if kind != QEvent.Type.Wheel and watched in (
                self.view.horizontalScrollBar(),self.view.verticalScrollBar()):
            # Native sliders own their drag, focus and keyboard input. Routing
            # their press through card focus would queue EnsureVisible for the
            # old current item and undo the user's scrollbar position.
            return False
        if kind == QEvent.Type.Wheel:
            pixel=event.pixelDelta(); delta=pixel if not pixel.isNull() else event.angleDelta()
            shifted=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if not delta.isNull():
                amount=delta.x() if abs(delta.x())>abs(delta.y()) else delta.y()
                self.remainder += -amount if not pixel.isNull() else -amount/120*max(48,self.view.horizontalScrollBar().singleStep()*3)
                step=round(self.remainder); self.remainder-=step
                bar=self.view.horizontalScrollBar(); bar.setValue(bar.value()+step)
                event.accept(); return True
            return False
        if kind in (QEvent.Type.FocusIn,QEvent.Type.MouseButtonPress):
            item=self.item_for(watched)
            if item is not None:self.view.setCurrentItem(item)
            self.schedule_focus()
        if kind == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Home,Qt.Key.Key_End):
            count=self.view.count()
            if count and self.view.isEnabled():
                index=self.view.currentRow()
                target=(0 if event.key()==Qt.Key.Key_Home else count-1 if event.key()==Qt.Key.Key_End
                    else max(0,min(count-1,index+(-1 if event.key()==Qt.Key.Key_Left else 1))))
                self.view.setCurrentRow(target); self.view.setFocus()
                self.focus_item(reveal=True)
                bar=self.view.horizontalScrollBar()
                if event.key()==Qt.Key.Key_Home:bar.setValue(bar.minimum())
                elif event.key()==Qt.Key.Key_End:bar.setValue(bar.maximum())
            event.accept(); return True
        return False


class FidelityLayout:
    def __init__(self, dialog):
        self.d = d = dialog
        self.font = review_font()
        d.setFont(self.font)
        d.setStyleSheet(d.styleSheet() + STYLE)
        self.font_resolved = QFontInfo(self.font).family()
        d.anka_shell.layout.setContentsMargins(0,0,0,0)
        d.anka_shell.layout.setSpacing(0)
        d.header.grid.setContentsMargins(14,7,14,7)
        d.header.icon_label.setFixedSize(38,38)
        d.header.icon_label.setPixmap(d.header.app_icon.pixmap(38,38))
        d.header.name_label.setStyleSheet('font-family:Geist;font-size:25px;font-weight:700;')
        d.header.version.hide()
        d.settings_button = QPushButton('⚙  Settings')
        d.settings_button.setAutoDefault(False)
        d.settings_button.clicked.connect(self.settings)
        d.header.grid.addWidget(d.settings_button,0,2,Qt.AlignmentFlag.AlignRight)
        self._discovery()
        self._hero()
        self._inventory()
        self._footer()
        d.anka_shell.workspace.verticalScrollBar().setValue(0)
        d.anka_shell.workspace.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.resize()

    def _discovery(self):
        d = self.d
        left = d._discovery_layout.itemAt(0).widget()
        right = d._source_selected_page
        self.search_pane = left
        left.setMinimumWidth(290); left.setMaximumWidth(16777215)
        right.setMinimumWidth(420)
        d._discovery_layout.removeWidget(left); d._discovery_layout.removeWidget(right)
        d.discovery_splitter = QSplitter(Qt.Orientation.Horizontal)
        d.discovery_splitter.setChildrenCollapsible(False)
        d.discovery_splitter.setHandleWidth(3)
        self.right_workspace = QWidget()
        self.right_workspace.setMinimumWidth(420)
        self.right_stack = QStackedLayout(self.right_workspace)
        self.right_stack.setContentsMargins(0,0,0,0)
        self.right_stack.addWidget(right)
        d.discovery_splitter.addWidget(left); d.discovery_splitter.addWidget(self.right_workspace)
        d.discovery_splitter.setSizes([455,1205])
        d.discovery_splitter.setStretchFactor(0,0); d.discovery_splitter.setStretchFactor(1,1)
        d._discovery_layout.addWidget(d.discovery_splitter)
        d._discovery_layout.setAlignment(Qt.AlignmentFlag(0))
        d._source_selected_page.layout().setAlignment(Qt.AlignmentFlag(0))
        d.discovery_splitter.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        left.layout().setContentsMargins(14,20,12,0)
        left.layout().setSpacing(0)
        left.layout().itemAt(0).widget().hide()
        top=d._search_top_panel.layout()
        self.mode_host=QFrame();self.mode_host.setObjectName('acquisitionSegments')
        segments=QHBoxLayout(self.mode_host);segments.setContentsMargins(2,2,2,2);segments.setSpacing(0)
        for button in (d.volume_mode_btn,d.chapter_mode_btn):
            d._mode_row.removeWidget(button);button.setParent(self.mode_host)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            button.setAccessibleName(button.text()+' acquisition mode')
            segments.addWidget(button,1)
        left.layout().insertWidget(1,self.mode_host)
        top.setContentsMargins(0,12,0,8);top.setSpacing(8)
        d.mode_helper.hide()
        d.search_box.setMinimumHeight(24)
        # Let Qt include the current font, padding and focus frame in its hint.
        d.search_btn.setSizePolicy(QSizePolicy.Policy.Minimum,QSizePolicy.Policy.Fixed)
        # The native QLineEdit clear action owns its geometry and text reserve.
        # Shared QToolButton padding must not alter that private style control.
        d.search_box.setStyleSheet(d.search_box.styleSheet()+'''
QLineEdit QToolButton {padding:0; margin:0; min-height:0; min-width:0;
 border:0; border-radius:0; background:transparent;}
''')
        self.settings_window = QDialog(d)
        self.settings_window.setWindowTitle('MangaAnkā · Settings and diagnostics')
        self.settings_window.setFont(self.font)
        outer=QVBoxLayout(self.settings_window);outer.setContentsMargins(16,16,16,16)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        body=QWidget();settings=QVBoxLayout(body);settings.setContentsMargins(4,4,14,4)
        scroll.setWidget(body);outer.addWidget(scroll,1)
        d.discovery_options.setParent(self.settings_window)
        settings.addWidget(QLabel('Discovery · acquisition language and direct links'))
        settings.addWidget(d.discovery_options)
        d.discovery_options.show()
        d.options_button.hide()
        d.source_status_host.setParent(self.settings_window)
        settings.addWidget(QLabel('Provider status and retry'))
        settings.addWidget(d.source_status_host)
        d.source_status_host.show()
        d._discovery_search_layout.setSpacing(10)
        header = d.search_results_label.parentWidget()
        header.setMinimumHeight(30)
        d.search_results_label.setStyleSheet('font-size:16px;font-weight:600;')
        self.results_count = QLabel(''); header.layout().addWidget(self.results_count)
        d.search_results.setMinimumHeight(80); d.search_results.setSpacing(0)
        d.search_results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.paging_host = d.show_more_btn.parentWidget()
        self.paging_host.setMinimumHeight(38)
        self.paging_host.layout().setContentsMargins(0,3,0,5)
        self.paging_summary = QLabel('All loaded results')
        self.paging_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.paging_summary.setStyleSheet('font-size:13px;color:#a5b0bf;')
        self.paging_host.layout().addWidget(self.paging_summary)
        d.show_more_btn.installEventFilter(d)
        # Preserve Import's existing panel and all of its controls.
        settings.addWidget(QLabel('Hero rendering · Static hero enables reduced motion'))
        d.animation_rate.parentWidget().layout().removeWidget(d.animation_rate)
        d.render_scale.parentWidget().layout().removeWidget(d.render_scale)
        settings.addWidget(d.animation_rate); settings.addWidget(d.render_scale)
        settings.addWidget(QLabel('Utilities'))
        for button in (d.preferences_btn,d.sources_btn,d.about_btn,d.google_books_key_btn):
            button.setParent(self.settings_window); settings.addWidget(button)
        close = QPushButton('Done'); close.clicked.connect(self.settings_window.hide); outer.addWidget(close)
        self.settings_window.resize(590,650)
        self.settings_window.hide()

    def settings(self):
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _hero(self):
        d = self.d
        layout = d._source_selected_page.layout()
        # Secondary toolbar has moved to Settings.
        layout.itemAt(2).widget().hide()
        d._selected_top_panel.layout().setContentsMargins(30,24,18,24)
        d._hero_row.setSpacing(30)
        d._hero_text_layout.setSpacing(9)
        d.selected_aliases.hide()
        d.hero_facts.hide()
        d.selected_author.hide()
        self.facts = QWidget(); grid = QGridLayout(self.facts)
        grid.setContentsMargins(0,12,0,0); grid.setHorizontalSpacing(28); grid.setVerticalSpacing(3)
        self.fact_values = []
        for i,title in enumerate(('Author / artist','Status','Release')):
            label = QLabel(title); label.setStyleSheet('font-size:14px;color:#aeb8c7;')
            value = QLabel(); value.setWordWrap(True); value.setStyleSheet('font-size:14px;')
            value.setTextFormat(Qt.TextFormat.PlainText)
            grid.addWidget(label,0,i); grid.addWidget(value,1,i)
            self.fact_values.append(value)
        d._hero_text_layout.insertWidget(d._hero_text_layout.count()-1,self.facts)
        self.details_button = QPushButton('Full synopsis and details…')
        self.details_button.setAutoDefault(False)
        self.details_button.clicked.connect(self.details)
        d._hero_text_layout.insertWidget(d._hero_text_layout.count()-1,self.details_button,0,Qt.AlignmentFlag.AlignLeft)
        d.selected_synopsis.setContentsMargins(0,0,12,0)
        d.selected_synopsis_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        d.selected_synopsis_scroll.setMinimumHeight(46)
        d.selected_synopsis_scroll.setMaximumHeight(72)
        for label in d.stat_labels:
            label.setStyleSheet('background:rgba(15,23,33,225);border:1px solid #3a4757;border-radius:13px;padding:12px;color:#edf1f7;font-size:14px;')
        d.hero_stats.setFixedWidth(175)
        d.selected_cover.setStyleSheet('background:#0c151e;border:1px solid #47596c;border-radius:7px;')

    def details(self):
        from calibre_plugins.manganana.metadata.description_text import normalize_description
        d=self.d;view=QDialog(d);view.setWindowTitle('Selected work · full synopsis and metadata')
        layout=QVBoxLayout(view);scroll=QScrollArea();scroll.setWidgetResizable(True)
        text=QLabel();text.setTextFormat(Qt.TextFormat.PlainText);text.setWordWrap(True)
        text.setContentsMargins(12,12,20,12)
        md=getattr(d,'_immediate_info',None) or d.loaded_metadata or {}
        text.setText('\n\n'.join(f'{label}: {normalize_description(md[key])}' for label,key in
            (('Title','title'),('Author','author'),('Artist','artist'),('Status','status'),
             ('Release','year'),('Description','description')) if md.get(key)))
        if md.get('tags'):
            text.setText(text.text()+'\n\nGenres: '+', '.join(str(tag)for tag in md['tags']))
        scroll.setWidget(text);layout.addWidget(scroll,1)
        close=QPushButton('Done');close.clicked.connect(view.accept);layout.addWidget(close)
        view.resize(640,480);view.exec()


    def _inventory(self):
        d = self.d
        layout = d._source_selected_page.layout()
        self.inventory_header = d.select_all_btn.parentWidget()
        self.inventory_header.setFixedHeight(58)
        self.inventory_header.layout().setContentsMargins(28,6,18,6)
        d.inventory_heading.setStyleSheet('font-size:24px;font-weight:600;')
        d.volume_count_label.setStyleSheet('font-size:13px;color:#c2ccda;')
        self.inventory_more=QPushButton('More')
        menu=QMenu(self.inventory_more)
        menu.addAction('Select Range…',d._choose_range)
        menu.addAction('Clear selection',d.clear_volume_btn.click)
        menu.addSeparator()
        menu.addAction('Sort ascending',lambda:d.inventory_order.setCurrentIndex(0))
        menu.addAction('Sort descending',lambda:d.inventory_order.setCurrentIndex(1))
        self.inventory_more.setMenu(menu)
        self.inventory_header.layout().addWidget(self.inventory_more)
        self.sort_button=QPushButton();self.sort_button.setAutoDefault(False)
        self.sort_button.clicked.connect(lambda:d.inventory_order.setCurrentIndex(1-d.inventory_order.currentIndex()))
        d.inventory_order.currentIndexChanged.connect(self.sort_direction)
        self.inventory_header.layout().addWidget(self.sort_button);self.sort_direction()
        d.inventory_order.hide();d.volume_count_label.hide()
        header_position=layout.indexOf(self.inventory_header)
        layout.removeWidget(self.inventory_header)
        self.inventory_header_host=QWidget()
        self.header_stack=QStackedLayout(self.inventory_header_host)
        self.header_stack.setContentsMargins(0,0,0,0)
        self.header_stack.addWidget(self.inventory_header)
        layout.insertWidget(header_position,self.inventory_header_host)
        layout.removeWidget(d.volume_list)
        d.inventory_stack_host = QWidget()
        d.inventory_stack = QStackedLayout(d.inventory_stack_host)
        d.inventory_stack.setContentsMargins(0,0,0,0)
        self.skeleton = InventorySkeleton()
        self.loading_page = QWidget()
        pending = QVBoxLayout(self.loading_page);pending.setContentsMargins(0,0,0,0)
        self.loading_header=QWidget()
        banner=QVBoxLayout(self.loading_header);banner.setContentsMargins(28,2,18,2);banner.setSpacing(2)
        activity = QHBoxLayout()
        self.spinner = QProgressBar();self.spinner.setRange(0,0);self.spinner.setTextVisible(False)
        self.spinner.setFixedSize(56,12);self.spinner.setAccessibleName('Inventory request in progress')
        activity.addWidget(self.spinner)
        self.loading_title = QLabel();self.loading_title.setStyleSheet('font-size:18px;font-weight:600;')
        activity.addWidget(self.loading_title,1);banner.addLayout(activity)
        self.loading_detail = QLabel();self.loading_detail.setWordWrap(False)
        self.loading_detail.setStyleSheet('font-size:13px;color:#c1cad8;')
        banner.addWidget(self.loading_detail)
        self.header_stack.addWidget(self.loading_header)
        pending.addWidget(self.skeleton,0,Qt.AlignmentFlag.AlignVCenter)
        self.carousel_host = QWidget()
        self.carousel = VolumeCarousel(d,self.carousel_host)
        d.inventory_stack.addWidget(self.carousel_host)
        d.inventory_stack.addWidget(self.loading_page)
        self.empty_gallery=QLabel('Select a search result to see available books.')
        self.empty_gallery.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_gallery.setProperty('ankaRole','empty')
        self.empty_gallery.setWordWrap(True)
        self.message_page = QWidget();message=QVBoxLayout(self.message_page)
        message.addStretch();message.addWidget(self.empty_gallery)
        self.retry_button=QPushButton('Retry inventory');self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(d._retry_inventory)
        message.addWidget(self.retry_button,0,Qt.AlignmentFlag.AlignHCenter);message.addStretch()
        d.inventory_stack.addWidget(self.message_page)
        position = layout.indexOf(self.inventory_header_host)+1
        layout.insertWidget(position,d.inventory_stack_host,1)
        d.inventory_stack_host.setContentsMargins(12,0,12,10)
        d.inventory_stack_host.setMinimumHeight(180)
        d.volume_list.setStyleSheet('QListWidget {background:transparent;border:0;border-radius:0;padding:2px;}')
        d.volume_list.setSpacing(10)
        d.range_hint.hide()  # Same selected-key summary remains in the fixed bar.
        # Remove old trailing stretch; the bounded carousel owns surplus height.
        for i in reversed(range(layout.count())):
            if layout.itemAt(i).spacerItem():
                layout.takeAt(i)
        layout.setSpacing(0)
        self.loading = False
        self.inventory_state = 'idle'
        self.set_state('idle')

    def _footer(self):
        d = self.d
        d.footer.stack.setContentsMargins(16,14,16,14)
        d.footer.stack.setSpacing(0)
        activity = d.log.parentWidget()
        d.footer.stack.removeWidget(activity)
        d.log.setParent(d.footer)
        self.log_popup = QDialog(d)
        self.log_popup.setWindowTitle('MangaAnkā · Activity Log')
        log_layout = QVBoxLayout(self.log_popup)
        log_layout.addWidget(d.log)
        log_actions=QHBoxLayout()
        for title,callback in (('Copy Log',d.copy_log),('Save Log',d.save_log)):
            button=QPushButton(title);button.clicked.connect(callback);log_actions.addWidget(button)
        log_layout.addLayout(log_actions)
        d.log.setMaximumHeight(16777215); d.log.show()
        self.log_popup.resize(850,360)
        # Original log model/copy/save remain intact; expansion uses a separate bounded view.
        d.log_toggle_btn.clicked.disconnect()
        d.log_toggle_btn.clicked.connect(self.show_log)
        d.log_toggle_btn.setText('☷   Activity Log  ›')
        d.log_toggle_btn.setStyleSheet('font-size:14px;')
        bar = QWidget(); row = QHBoxLayout(bar); row.setContentsMargins(0,0,0,0); row.setSpacing(12)
        row.addWidget(d.log_toggle_btn)
        # Progress shares the fixed status slot instead of inserting another
        # footer row when asynchronous search/download work starts or settles.
        d.footer.stack.removeWidget(d.progress_card)
        self.status_host=QWidget();self.status_host.setMinimumHeight(38)
        self.status_stack=QStackedLayout(self.status_host);self.status_stack.setContentsMargins(0,0,0,0)
        self.status_stack.addWidget(d.activity_status);self.status_stack.addWidget(d.progress_card)
        d.progress_card.layout().setContentsMargins(0,0,0,0);d.progress_card.layout().setSpacing(0)
        d.progress_card.setStyleSheet('background:transparent;border:0;')
        for widget in (d.search_progress,d.progress):widget.setFixedHeight(5)
        for widget in (d.search_progress_text,d.progress_text):
            widget.setStyleSheet('font-size:12px;');widget.setMinimumWidth(0)
            widget.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        row.addWidget(self.status_host,1)
        for button in (d.copy_log_btn,d.save_log_btn,d.back_btn,d.cancel_btn,d.preview_btn,d.download_btn):
            row.addWidget(button)
        d.footer.stack.addWidget(bar)
        d.footer.utilities.hide(); d.footer.navigation.hide()
        activity.hide()
        d.workflow_hint.hide()
        d.activity_status.setStyleSheet('color:#c2ccda;font-size:14px;background:transparent;border:0;')
        d.log_toggle_btn.show(); d.activity_status.show(); d.copy_log_btn.show(); d.save_log_btn.show()
        self.progress()

    def progress(self):
        d=self.d
        active=d._work_progress_active or (d._search_progress_active and d.workflow_state.stage=='choose_manga')
        self.status_stack.setCurrentWidget(d.progress_card if active else d.activity_status)

    def show_log(self):
        self.log_popup.show(); self.log_popup.raise_()

    def results(self):
        from calibre_plugins.manganana.app.main import ProviderBadgeWidget
        d=self.d;visible=0
        for i in range(d.search_results.count()):
            item=d.search_results.item(i);row=d.search_results.itemWidget(item);visible+=not item.isHidden()
            if row is None:continue
            item.setSizeHint(QSize(0,68));row.setMinimumHeight(66)
            row.layout().setContentsMargins(8,3,8,3)
            row.setStyleSheet('QFrame#reviewResultRow {background:transparent;border:0;border-bottom:1px solid #293440;border-radius:0;}'
                'QFrame#reviewResultRow:hover {background:#1b2935;}'
                'QFrame#reviewResultRow[selected="true"] {background:#253c44;border:0;border-left:2px solid #20d4bd;border-bottom:1px solid #354151;border-radius:0;}')
            row.title_label.setStyleSheet('font-size:15px;font-weight:500;')
            row.author_label.hide();row.rating_label.hide();row.cover.setFixedSize(38,54)
            for badge in row.findChildren(ProviderBadgeWidget):
                neutral_edition(badge);badge_style(badge,'font-size:11px;font-weight:500;padding:2px 5px;min-height:14px;')
            if hasattr(row,'inventory_label'):row.inventory_label.hide()
            info=item.data(Qt.ItemDataRole.UserRole) or {}
            if not hasattr(row,'_result_title'):
                # Keep the original badges, click targets and result model.
                badges=row.findChildren(ProviderBadgeWidget)
                while row.details.count():
                    entry=row.details.takeAt(0)
                    if entry.widget():entry.widget().hide()
                row.title_line=QWidget();title=QHBoxLayout(row.title_line)
                row.title_line.setFixedHeight(23)
                title.setContentsMargins(0,0,0,0);title.setSpacing(5)
                title.addWidget(row.title_label,1);row.title_label.show()
                row.count_line=QWidget();second=QHBoxLayout(row.count_line)
                second.setContentsMargins(0,0,0,0);second.setSpacing(6)
                row.chapter_count_label=QLabel();row.chapter_count_label.setStyleSheet('font-size:12px;color:#aeb8c7;')
                row.chapter_count_label.setWordWrap(False);second.addWidget(row.chapter_count_label)
                for badge in badges:
                    target=second if badge.accessibleName().startswith('Edition:') else title
                    target.addWidget(badge);badge.show()
                    badge.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Fixed)
                title.addStretch(0);second.addStretch(1)
                row.details.addWidget(row.title_line);row.details.addWidget(row.count_line)
                row.details.setSpacing(3)
                # Leave room below the centred title for count/edition details
                # while keeping the cover and the full provider chip aligned.
                row.details.setContentsMargins(0,16,0,0)
                row.layout().setAlignment(row.details,Qt.AlignmentFlag.AlignVCenter)
                row._result_title=ResultTitle(row.title_label,row._base_title)
            count=listing_chapter_count(info)
            row.chapter_count_label.setText(f'{count} chapters' if count is not None else '')
            row.chapter_count_label.setVisible(count is not None)
            row.count_line.setVisible(count is not None or any(
                b.accessibleName().startswith('Edition:') for b in row.count_line.findChildren(ProviderBadgeWidget)))
        self.results_count.setText(f'{visible} results')
        self.paging_summary.setVisible(not d.show_more_btn.isVisible())


    def metadata(self, md):
        from calibre_plugins.manganana.app.main import ProviderBadgeWidget
        d = self.d
        for label,key in zip(self.fact_values,('author','status','year')):
            value = str(md.get(key) or '')
            if key == 'author' and md.get('artist') and md.get('artist') != md.get('author'):
                value += '\n' + str(md['artist'])
            label.setText(value or '—')
        d.selected_author.hide(); d.hero_facts.hide(); d.selected_aliases.hide()
        d.selected_inventory_summary.hide()
        self.empty_state(md)
        wide=d._source_selected_page.width()>=900 and d.height()>=850
        d.selected_title.setStyleSheet('font-size:'+('38' if wide else '26')+'px;font-weight:700;color:#ffffff;')
        d.native_title.setStyleSheet('font-size:24px;color:#f0f3f8;')
        d.selected_synopsis.setStyleSheet('font-size:15px;color:#edf0f5;')
        d.selected_inventory_summary.setStyleSheet('font-size:15px;font-weight:500;')
        d.selected_tags.setStyleSheet('font-size:13px;color:#b3c0cf;')
        for badge in d.selected_source_host.findChildren(ProviderBadgeWidget):
            badge_style(badge,'font-size:15px;font-weight:600;padding:4px 9px;border-radius:12px;')

    def begin(self, info):
        d = self.d
        d._immediate_info = dict(info)
        d.selected_title.setText(str(info.get('title') or 'Untitled'))
        d.selected_author.setText(str(info.get('author') or ''))
        from calibre_plugins.manganana.metadata.description_text import normalize_description
        d.selected_synopsis.setText(normalize_description(info.get('description') or info.get('work_description')))
        d.selected_synopsis_scroll.setVisible(bool(d.selected_synopsis.text()))
        d.native_title.clear(); d.native_title.hide()
        self.metadata(info)
        d._set_hero_stats(('—\nVolumes found','—\nChapters found',
            str(info.get('language') or d.language.currentText())+'\nDownload language'))
        self.set_loading(True)

    def set_loading(self,loading):
        if loading:self.set_state('loading')
        else:self.sync_inventory()

    def set_state(self,state,detail=''):
        if state not in ('idle','loading','ready','empty','error'):raise ValueError(state)
        changed=self.inventory_state!=state
        self.inventory_state=state;self.loading=state=='loading';d=self.d
        d.inventory_stack_host.setProperty('inventoryState',state)
        noun='chapters' if d.workflow_mode=='chapter' else 'volumes'
        self.loading_title.setText(f'Loading {noun}…')
        self.loading_detail.setText(detail or 'Reading the selected source listing and resolving its downloadable inventory.')
        self.header_stack.setCurrentWidget(self.loading_header if state=='loading' else self.inventory_header)
        self.empty_gallery.setText(detail or {'idle':'Select a search result to see available books.',
            'empty':f'No downloadable {noun} were found for this source and language.',
            'error':f'Could not load {noun}. Retry or choose another search result.'}.get(state,''))
        self.retry_button.setVisible(state=='error')
        d.inventory_stack.setCurrentWidget(self.loading_page if state=='loading' else
            self.carousel_host if state=='ready' else self.message_page)
        if state in ('idle','loading','empty','error') and d.workflow_mode!='import':d.preview_btn.setEnabled(False)
        self.controls(state=='ready')
        if changed and d.loaded_metadata and state in ('loading','ready','empty','error'):
            d._refresh_hero()

    def sync_inventory(self):
        d=self.d
        if d.workflow_mode=='import':return
        from calibre_plugins.manganana.app.main import VolumeRowWidget
        has_rows=any(isinstance(d.volume_list.itemWidget(d.volume_list.item(i)),VolumeRowWidget) for i in range(d.volume_list.count()))
        workflow=d.workflow_state
        acquisition=getattr(workflow,'chapter_acquisition_state' if d.workflow_mode=='chapter' else 'volume_acquisition_state','idle')
        if acquisition=='terminal_failure':self.set_state('error',getattr(d,'_chapter_acquisition_error','') or 'The selected source could not resolve its inventory. Retry or select another result.')
        elif d._volume_plan_loading or d._volume_resolution_pending():self.set_state('loading')
        elif d.workflow_mode=='chapter' and d.loaded_metadata and not workflow.chapter_presentation_frozen:self.set_state('loading','Resolving downloadable chapters and publication structure.')
        elif has_rows:self.set_state('ready')
        elif acquisition=='ready':self.set_state('empty')
        elif getattr(d,'_immediate_info',None) or d.load_btn.text()=='Loading...':self.set_state('loading')
        elif self.inventory_state!='error':self.set_state('idle')


    def inventory(self):
        from calibre_plugins.manganana.app.main import VolumeRowWidget
        d = self.d
        horizontal = d.workflow_mode in ('volume','chapter')
        self.carousel.sync()
        # Fixed grid dimensions keep placeholder replacement from resizing the workspace.
        compact = d.height() < 850 or d._source_selected_page.width() < 900
        cover_width,cover_height = (54,76) if d.height()<550 else (72,100) if d.height()<680 else (108,150) if compact else (156,218)
        # A Calibre-hosted modal can be constrained by the screen work area at
        # high DPI. Fit the complete strip to the actual workspace, preserving
        # the cover aspect ratio rather than relying only on window breakpoints.
        margins=d.inventory_stack_host.contentsMargins()
        available=(d.anka_shell.workspace.viewport().height()-d.hero.height()
                   -self.inventory_header_host.height()-margins.top()-margins.bottom())
        if available>0:
            fitted_height=max(76,min(cover_height,available-62-32))
            cover_width=round(cover_width*fitted_height/cover_height)
            cover_height=fitted_height
        self.cover_size=(cover_width,cover_height)
        tile_width,tile_height = max(110,cover_width+26),cover_height+62
        self.tile_size = QSize(tile_width,tile_height)
        # Bound the strip to its items and native scroll bar. Surplus workspace
        # stays outside the gallery rather than separating covers from the bar.
        d.volume_list.setFixedHeight(tile_height+32 if horizontal else 120)
        d.volume_list.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.skeleton.setFixedHeight(tile_height+32)
        for tile in self.skeleton.tiles:
            tile.setFixedSize(tile_width,tile_height)
            tile.cover.setFixedSize(cover_width,cover_height)
            tile.layout().setContentsMargins(12,8,12,8)
        for i in range(d.volume_list.count()):
            item=d.volume_list.item(i); row=d.volume_list.itemWidget(item)
            if not horizontal or not isinstance(row,VolumeRowWidget):
                continue
            item.setSizeHint(self.tile_size)
            row.setFixedSize(tile_width,tile_height)
            row.cover_host.setFixedHeight(cover_height)
            row.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
            row.layout().setStretch(row.layout().indexOf(row.title),0)
            item.setData(Qt.ItemDataRole.ForegroundRole,QColor(0,0,0,0))
            row.cover.setFixedSize(cover_width,cover_height)
            if getattr(row,'_fidelity_cover_size',None)!=self.cover_size:
                row._fidelity_cover_size=self.cover_size
                url=(item.data(Qt.ItemDataRole.UserRole) or {}).get('cover_url')
                if url and url in d._image_cache:
                    pix=d._pix_for_url(url,cover_width,cover_height)
                    if pix is not None:row.set_cover(pix)
            row.setStyleSheet(TILE_STYLE)
            row.pick.setStyleSheet(PICK_STYLE)
            row.title.setStyleSheet('font-size:14px;font-weight:500;');row.title.setFixedHeight(20);row.title.setToolTip(row.title.text())
            row.title.setWordWrap(False)
            if not hasattr(row,'_fidelity_title'):row._fidelity_title=row.title.text()
            row.title.setToolTip(row._fidelity_title)
            row.title.setText(QFontMetrics(row.title.font()).elidedText(row._fidelity_title,Qt.TextElideMode.ElideRight,tile_width-18))
            row.membership.setStyleSheet('font-size:12px;color:#c1cad8;');row.membership.setFixedHeight(18);row.membership.setWordWrap(False)
            if not hasattr(row,'_fidelity_toggle'):
                row._fidelity_toggle=CoverToggle(row)
                row.cover.installEventFilter(row._fidelity_toggle)
                row.installEventFilter(row._fidelity_toggle)
                row.toggled.connect(lambda _checked,r=row: self.restyle_tile(r))
                original=row.set_checked
                def checked(instance,value,emit_signal=False,_original=original):
                    _original(value,emit_signal=emit_signal)
                    self.restyle_tile(instance)
                row.set_checked=MethodType(checked,row)
            self.restyle_tile(row)
        self.sync_inventory()

    def restyle_tile(self,row):
        # The original widget updates its own stylesheet after each toggle.
        row.setStyleSheet(TILE_STYLE); row.pick.setStyleSheet(PICK_STYLE)
        row.style().unpolish(row); row.style().polish(row)

    def resize(self):
        d = self.d
        if not hasattr(d,'inventory_stack'):
            return
        # Focus borders may be wider than normal borders. Reserve the largest
        # native style requirement rather than letting keyboard focus clip text.
        option=QStyleOptionButton();d.search_btn.initStyleOption(option)
        content=QSize(option.fontMetrics.horizontalAdvance(d.search_btn.text()),option.fontMetrics.height())
        required=d.search_btn.sizeHint()
        for focus in (False,True):
            option.state &= ~QStyle.StateFlag.State_HasFocus
            if focus:option.state |= QStyle.StateFlag.State_HasFocus
            required=required.expandedTo(d.search_btn.style().sizeFromContents(
                QStyle.ContentsType.CT_PushButton,option,content,d.search_btn))
        d.search_btn.setMinimumSize(required)
        # Fit both panes to the workspace. Other workflow stages retain native scrolling.
        target = d.anka_shell.workspace.viewport().size()
        d._choose_stage_panel.setMinimumHeight(0)
        d._choose_stage_panel.setMaximumHeight(16777215)
        d._choose_stage_panel.setMinimumHeight(target.height())
        d.anka_shell.workspace.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if getattr(self,'_window_width',None)!=d.width():
            self._window_width=d.width()
            if d.width()<1300:
                left=max(290,round(d.width()*.28))
                d.discovery_splitter.setSizes([left,max(420,d.width()-left-15)])
        wide = d._source_selected_page.width() >= 900 and d.height() >= 850
        dense=d.height()<680
        tiny=d.height()<550
        d.hero.setFixedHeight(390 if wide else 170 if tiny else 195 if dense else 290)
        d.selected_cover.setFixedSize(230,310) if wide else d.selected_cover.setFixedSize(78 if tiny else 90,109 if tiny else 126)
        d._hero_text_layout.setSpacing(4 if not wide else 5)
        d._selected_top_panel.layout().setSpacing(4)
        d.native_title.setStyleSheet('font-size:'+('18' if dense else '24')+'px;color:#f0f3f8;')
        d.selected_title.setWordWrap(not dense)
        d.selected_title.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        d.selected_inventory_summary.hide()
        d.selected_synopsis_scroll.setVisible(bool(d.selected_synopsis.text()) and not dense)
        d.inventory_stack_host.setMinimumHeight(130 if tiny else 155 if dense else 180)
        self.inventory_header.setFixedHeight(44 if dense else 58)
        self.inventory_header_host.setFixedHeight(44 if dense else 58)
        self.inventory_header.layout().setContentsMargins(14 if dense else 28,4,14 if dense else 18,4)
        d.inventory_heading.setStyleSheet('font-size:'+('19' if dense else '24')+'px;font-weight:600;')
        d.copy_log_btn.setVisible(not dense);d.save_log_btn.setVisible(not dense)
        for key,label in d.stage_labels.items():
            titles={'choose_manga':'1 Choose Manga','book_customization':'2 Customize','finalization':'3 Finalize'}
            full={'choose_manga':'1 Choose Manga','book_customization':'2 Book Customization','finalization':'3 Finalization'}
            label.setText((titles if d.width()<1100 else full)[key])
            label.setStyleSheet('font-size:14px;padding:8px 9px;' if d.width()<1100 else '')
        d.header.name_label.setStyleSheet('font-family:Geist;font-size:'+('22' if d.width()<1100 else '25')+'px;font-weight:700;')
        d.header._reflow()
        d._hero_text_layout.removeWidget(d.hero_stats)
        d._hero_row.removeWidget(d.hero_stats)
        d._selected_top_panel.layout().removeWidget(d.hero_stats)
        d.hero_stats.setMinimumWidth(175 if wide else 0)
        d.hero_stats.setMaximumWidth(175 if wide else 16777215)
        d.hero_stats.layout().setDirection(QHBoxLayout.Direction.TopToBottom if wide else QHBoxLayout.Direction.LeftToRight)
        if wide:
            d._hero_row.addWidget(d.hero_stats,0,Qt.AlignmentFlag.AlignVCenter)
        else:
            d._selected_top_panel.layout().addWidget(d.hero_stats)
        for label in d.stat_labels:
            label.setStyleSheet('background:rgba(15,23,33,225);border:1px solid #3a4757;border-radius:10px;padding:'
                +('4px;font-size:12px;' if not wide else '12px;font-size:14px;')+'color:#edf1f7;')
        d._hero_row.setSpacing(30 if wide else 14)
        d._selected_top_panel.layout().setContentsMargins(30 if wide else 12,24 if wide else 6,18,24 if wide else 6)
        d.selected_synopsis_scroll.setMaximumHeight(72 if wide else 46)
        self.facts.setVisible(wide)
        self.details_button.setVisible(bool(getattr(d,"_immediate_info",None) or d.loaded_metadata))
        self.details_button.setStyleSheet('font-size:13px;padding:3px 7px;min-height:16px;' if not wide else '')
        d.selected_title.setStyleSheet('font-size:'+('38' if wide else '22' if dense else '26')+'px;font-weight:700;color:#ffffff;')
        from calibre_plugins.manganana.app.main import ProviderBadgeWidget
        for badge in d.selected_source_host.findChildren(ProviderBadgeWidget):
            badge_style(badge,'font-size:'+('12px;padding:2px 6px;' if dense else '15px;padding:4px 9px;'))
        url=d._selected_cover_url or getattr(d,'_pending_search_cover_url','')
        if url and url in d._image_cache:
            pix=d._pix_for_url(url,d.selected_cover.width(),d.selected_cover.height())
            if pix is not None:d.selected_cover.setPixmap(pix)
        d.selected_tags.setVisible(bool(d.selected_tags.text()) and wide)
        for i,tile in enumerate(self.skeleton.tiles):
            tile.setVisible(i < (5 if wide else 3))
        self.inventory()
        self.empty_state(getattr(d,"_immediate_info",None) or d.loaded_metadata or {})

    @staticmethod
    def presentation_style():
        return STYLE+"""
QFrame#acquisitionSegments {background:#1a2430;border:1px solid #354151;border-radius:9px;}
QPushButton#modeChoice {background:transparent;border:1px solid transparent;border-radius:6px;padding:6px 3px;min-height:20px;font-size:14px;}
QPushButton#modeChoice:checked {background:#d2dae3;color:#101720;border-color:#d2dae3;}
QPushButton#modeChoice:focus {border-color:#20d4bd;}
QWidget#selectedMangaCard {background:transparent;border:0;}
"""

    def mode(self):
        d=self.d;local=d.workflow_mode=='import'
        if getattr(self,'_presentation_local',None) == local:
            self.set_loading(False)
            return
        self._presentation_local=local
        if hasattr(d,'import_mode_btn') and d.import_mode_btn.parentWidget() is not self.mode_host:
            button=d.import_mode_btn;d._mode_row.removeWidget(button);button.setParent(self.mode_host)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            button.setAccessibleName('Import acquisition mode');self.mode_host.layout().addWidget(button,1)
        self.mode_host.show();d._search_label.hide();d.mode_helper.hide();d.options_button.hide()
        d.discovery_options.show();d._search_top_panel.setVisible(not local)
        if hasattr(d,'import_panel'):
            self.prepare_import()
            self.right_workspace.show()
            self.right_stack.setCurrentWidget(self.import_details_page if local else d._source_selected_page)
            d._source_selected_page.setVisible(not local)
            self.import_details_page.setVisible(local)
            # The controller aligns Import to the top; the shared splitter owns
            # the full workspace height in every acquisition mode.
            d._discovery_layout.setAlignment(Qt.AlignmentFlag(0))
            self.search_pane.layout().setAlignment(Qt.AlignmentFlag(0))
            d._discovery_search_layout.setAlignment(Qt.AlignmentFlag(0))
            self.import_details()
        self.search_pane.setMaximumWidth(16777215)
        self.resize();self.set_loading(False)

    def prepare_import(self):
        d=self.d
        if hasattr(self,'import_details_page'):return
        from calibre_plugins.manganana.presentation.import_overview import ImportOverview
        self.import_details_page=QWidget();column=QVBoxLayout(self.import_details_page)
        column.setContentsMargins(30,24,30,24);column.setSpacing(16)
        self.import_heading=heading=QLabel('Import');heading.setStyleSheet('font-size:28px;font-weight:600;')
        heading.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        column.addWidget(heading)
        self.import_summary=QLabel();self.import_summary.setWordWrap(True);column.addWidget(self.import_summary)
        self.import_overview=ImportOverview();column.addWidget(self.import_overview,1)
        self.right_stack.addWidget(self.import_details_page)
        layout=d.import_panel.layout();actions=layout.itemAt(2).layout()
        for button in (d.import_browse_btn,d.import_select_btn,d.import_clear_btn,d.import_remove_btn):actions.removeWidget(button)
        layout.insertWidget(2,d.import_browse_btn)
        for button in (d.import_select_btn,d.import_clear_btn,d.import_remove_btn):
            button.setStyleSheet('''QPushButton {font-size:12px;padding:3px 4px;background:transparent;border:1px solid transparent;}
QPushButton:hover {background:#293b3b;border-color:#66B7A8;}
QPushButton:focus {border-color:#66B7A8;}
QPushButton:disabled {color:#73818a;}''');actions.addWidget(button)
        layout.setContentsMargins(8,8,8,4);layout.setSpacing(6);actions.setSpacing(4)
        d.import_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def import_details(self):
        if not hasattr(self,'import_details_page'):return
        d=self.d;books=d._selected_import_books()
        inspecting=d._import_inspection is not None
        self.import_summary.setText(d._import_inspection_message if inspecting else
            f'{len(books)} '+('book' if len(books)==1 else 'books')+f' selected · {sum(b["pages"] for b in books)} pages' if books else 'No books selected.')
        self.import_overview.set_books(d._import_books,d._selected_import_ids)

    def sort_direction(self,*_):
        descending=bool(self.d.inventory_order.currentData())
        name='Descending' if descending else 'Ascending'
        self.sort_button.setText(name)
        self.sort_button.setIcon(QIcon(str(asset_root()/('assets/ui/icons/sort-'+name.lower()+'.svg'))))
        self.sort_button.setIconSize(QSize(18,18))
        self.sort_button.setAccessibleName('Sort '+name.lower()+'; activate to reverse')
        self.sort_button.setToolTip(self.sort_button.accessibleName())

    def controls(self,available):
        d=self.d;dense=d.height()<680;volume=d.workflow_mode=='volume'
        d.inventory_order.hide();d.volume_count_label.hide()
        d.select_all_btn.setVisible(available);d.clear_volume_btn.setVisible(available and not dense)
        d.range_button.setVisible(available and volume and not dense)
        self.sort_button.setVisible(available and volume and not dense)
        self.inventory_more.setVisible(available and dense)

    def empty_state(self,md):
        d=self.d;selected=bool(md)
        if not selected:
            d.selected_title.setText('Search')
        else:
            title=str(md.get('title') or 'Untitled')
            d.selected_title.setToolTip(title);d.selected_title.setWordWrap(False)
            d.selected_title.setText(QFontMetrics(d.selected_title.font()).elidedText(title,Qt.TextElideMode.ElideRight,max(100,d.selected_title.width())))
        if not hasattr(self,'empty_instruction'):
            self.empty_instruction=QLabel('Choose Volumes or Chapters, then search your enabled manga sources.\nUse Import for local CBZ and PDF books.')
            self.empty_instruction.setWordWrap(True);self.empty_instruction.setStyleSheet('font-size:15px;color:#c1cad8;')
            d._hero_text_layout.insertWidget(2,self.empty_instruction)
        self.empty_instruction.hide()
        d.selected_cover.setVisible(selected);d.selected_source_host.setVisible(selected)
        d.edition_badge_host.setVisible(selected);d.hero_stats.setVisible(selected)
        d.selected_inventory_summary.hide();d.selected_author.hide();d.hero_facts.hide()
        d.native_title.setVisible(selected and bool(d.native_title.text()))
        d.selected_synopsis_scroll.setVisible(selected and bool(d.selected_synopsis.text()) and d.height()>=680)
        d.selected_tags.setVisible(selected and bool(d.selected_tags.text()) and d._source_selected_page.width()>=900 and d.height()>=850)
        self.facts.setVisible(selected and d._source_selected_page.width()>=900 and d.height()>=850)
        self.details_button.setVisible(selected)
        if not selected and not self.loading:self.set_loading(False)
