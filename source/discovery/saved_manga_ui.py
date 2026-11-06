"""Dialog-owned bookmarks presentation; reuse exact-provider controller input."""
from qt.core import (QObject, QToolButton, QLabel, QHBoxLayout, QListWidgetItem, QTimer, Qt,
    QWidget, QSize, QSizePolicy, QFontMetricsF, QPainter, QPainterPath, QPen, QColor, QEvent)
from math import ceil
from calibre.constants import config_dir
from calibre_plugins.manganana.discovery.saved_manga import FavoritesStore

HEART_COLOR = '#ED1E45'


class HeroHeart(QToolButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setFixedSize(32, 32)
        self.setStyleSheet('QToolButton,QToolButton:checked {background:transparent;border:0;padding:0;}'
            'QToolButton:focus {border:1px solid #ED1E45;border-radius:6px;}')

    def sizeHint(self):
        return QSize(32,32)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(HEART_COLOR),1.8))
        painter.setBrush(QColor(HEART_COLOR) if self.isChecked() else Qt.BrushStyle.NoBrush)
        painter.translate(4,4)
        path=QPainterPath();path.moveTo(12,21)
        path.cubicTo(-5,10,3,-2,12,6)
        path.cubicTo(21,-2,29,10,12,21)
        path.closeSubpath();painter.drawPath(path)


class HeroTitleRow(QWidget):
    """Use natural title width, shrinking through the existing elision logic."""
    _active=False
    _syncing=False
    def __init__(self, dialog, heart):
        super().__init__()
        self.dialog=dialog
        self.heart=heart
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Maximum,QSizePolicy.Policy.Fixed)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0);row.setSpacing(8)
        row.addWidget(dialog.selected_title,1)
        row.addWidget(heart,0,Qt.AlignmentFlag.AlignVCenter)
        self._active=True
        dialog.selected_title.installEventFilter(self)

    def sizeHint(self):
        if not self._active:
            return QSize(0,0)
        title=self.dialog.selected_title
        text=self.dialog.fidelity.title_field.text
        margins=title.contentsMargins()
        width=ceil(QFontMetricsF(title.font()).horizontalAdvance(text))+margins.left()+margins.right()
        extra=self.heart.width()+self.layout().spacing() if not self.heart.isHidden() else 0
        height=title.fontMetrics().height()+margins.top()+margins.bottom()
        return QSize(width+extra,max(height,self.heart.height() if extra else 0))

    def minimumSizeHint(self):
        return QSize(0,self.sizeHint().height())

    def sync_metrics(self):
        if not self._active or self._syncing or self.dialog._closing:return
        self._syncing=True
        try:
            title=self.dialog.selected_title
            margins=title.contentsMargins()
            height=title.fontMetrics().height()+margins.top()+margins.bottom()
            if title.height()!=height or title.minimumHeight()!=height:
                title.setFixedHeight(height)
            self.updateGeometry()
            # Only the small title/heart flow participates in this transaction.
            # QLabel's cached sizeHint may still describe the loading style.
            parent=self.parentWidget()
            if parent is not None and parent.layout() is not None:parent.layout().activate()
            self.layout().activate()
        finally:
            self._syncing=False

    def eventFilter(self,watched,event):
        if self._active and event.type()==QEvent.Type.FontChange:self.sync_metrics()
        return False


class SavedManga(QObject):
    active = False
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.store = FavoritesStore(config_dir)
        self.search_records = []
        self.showing = False
        self.active = True
        self.selection_item = None
        self.last_error = ''
        self.hero_heart=HeroHeart(dialog)
        hero_layout=dialog._hero_text_layout
        position=hero_layout.indexOf(dialog.selected_title)
        hero_layout.removeWidget(dialog.selected_title)
        self.title_row=HeroTitleRow(dialog,self.hero_heart)
        hero_layout.insertWidget(position,self.title_row,0,Qt.AlignmentFlag.AlignLeft)
        self.hero_heart.clicked.connect(self.toggle_selected)
        self.update_selected()
        self.search_button = QToolButton(dialog)
        self.search_button.setText('Search Results')
        self.saved_button = QToolButton(dialog)
        self.saved_button.setText('Bookmarks')
        self.saved_button.setAccessibleName('Bookmarks')
        for button in (self.search_button, self.saved_button):
            button.setCheckable(True)
            button.setStyleSheet('QToolButton {padding:5px 9px;border:1px solid #34443f;border-radius:7px;}'
                'QToolButton:checked {background:#29453f;color:#66B7A8;}')
            button.ensurePolished()
            button.setMinimumWidth(button.sizeHint().width())
        self.search_button.setChecked(True)
        dialog.fidelity.prefer_row.addWidget(self.search_button)
        dialog.fidelity.prefer_row.addWidget(self.saved_button)
        # The splitter has an explicit minimum that predates this compact row.
        # Propagate its native layout requirement so it cannot compress labels
        # or overlap the preference switch, including fractional DPI scales.
        pane = dialog.fidelity.search_pane
        pane.setMinimumWidth(max(pane.minimumWidth(), pane.minimumSizeHint().width()))
        # The two view buttons now serve as the discovery heading. Preserve
        # the old grouping actions behind Search Results' context menu.
        self.results_header=dialog.search_results_label.parentWidget()
        self.results_header.hide()
        self.results_header.setParent(dialog.fidelity.parking)
        self.search_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search_button.customContextMenuRequested.connect(self.search_display_menu)
        self.search_button.setToolTip('Search Results · right-click for Grouped or Flat display')
        self.search_button.setAccessibleDescription('Show search results. Open the context menu for Grouped or Flat display.')
        host = dialog.discovery_view.parentWidget().layout()
        def containing(layout):
            if layout.indexOf(dialog.discovery_view) >= 0:
                return layout
            for index in range(layout.count()):
                child=layout.itemAt(index).layout()
                found=containing(child) if child is not None else None
                if found is not None:
                    return found
            return None
        host = containing(host) or host
        position = host.indexOf(dialog.discovery_view)
        self.message = QLabel(dialog)
        self.message.setWordWrap(True)
        self.message.setStyleSheet('color:#acbdb7;padding:8px;')
        host.insertWidget(position, self.message)
        self.message.hide()
        self.search_button.clicked.connect(self.show_search)
        self.saved_button.clicked.connect(self.show_saved)
        self.error_timer = QTimer(self)
        self.error_timer.setInterval(500)
        self.error_timer.timeout.connect(self.check_error)
        self.error_timer.start()
        dialog.finished.connect(self.detach)

    def check_error(self):
        if self.active and self.store.error and self.store.error != self.last_error:
            self.last_error = self.store.error
            self.message.setText(self.store.error)
            recent=getattr(self.dialog,'recent_searches',None)
            self.message.setVisible(self.dialog.workflow_mode!='import' and not (recent and recent.home))
            self.dialog.add_log(self.store.error)

    def publish(self, records):
        self.search_records = [dict(r) for r in records]
        self.selection_item = None  # the hidden controller store was just reset
        self.refresh()

    def show_search(self, *_):
        recent = getattr(self.dialog, 'recent_searches', None)
        if recent is not None:
            # Navigation is not a search submission. Empty results from an
            # executed query still belong to Results; an unsubmitted field
            # or a query cleared with X belongs to the recent-search home.
            recent.home = not bool(self.dialog.workflow_state.executed_query)
        self.showing = False
        self.refresh()
        if recent is not None:
            recent.sync()

    def show_saved(self, *_):
        if hasattr(self.dialog,'recent_searches'):self.dialog.recent_searches.show_results()
        self.showing = True
        self.refresh()

    def search_display_menu(self, position):
        if not self.active or self.dialog._closing:
            return
        menu=self.dialog.discovery_mode.menu()
        menu.exec(self.search_button.mapToGlobal(position if position.x()>=0 else self.search_button.rect().bottomLeft()))

    def refresh(self):
        if not self.active or self.dialog._closing:
            return
        d = self.dialog
        self.search_button.setChecked(not self.showing)
        self.saved_button.setChecked(self.showing)
        d.discovery_view.saved_mode = self.showing
        d.discovery_view.setAccessibleName('Bookmarked manga' if self.showing else 'Manga discovery results')
        d.discovery_mode.setEnabled(not self.showing)
        d.discovery_view.setRootIsDecorated(d.discovery_view.grouped and not self.showing)
        rows = list(self.store.records.values()) if self.showing else self.search_records
        d.discovery_view.set_records(rows)
        d.search_results_label.setText('Saved Manga' if self.showing else 'Search Results')
        d.show_more_btn.setVisible(not self.showing and any(d._search_has_more.values()))
        message = self.store.warning if self.showing else ''
        if self.showing and not rows:
            message = message or 'No bookmarked manga. Select a provider listing and use the heart beside its title.'
        self.message.setText(message)
        self.message.setVisible(bool(message) and d.workflow_mode!='import')
        d._discovery_count()
        self.update_selected()

    def update_selected(self):
        if not self.active:
            return
        from calibre_plugins.manganana.discovery.saved_manga import clean_record
        row=clean_record(self.dialog.workflow_state.selected_provider_record)
        visible=bool(row) and self.dialog.workflow_mode in ('volume','chapter')
        self.hero_heart.setVisible(visible)
        if row:
            saved=self.store.contains(row)
            self.hero_heart.setChecked(saved)
            action='Remove from Saved Manga' if saved else 'Save Manga'
            description=f"{action}: {row['title']} · {row.get('source_name') or row['source_id']}"
            self.hero_heart.setToolTip(description)
            self.hero_heart.setAccessibleName(description)
        self.title_row.sync_metrics()

    def toggle_selected(self, *_):
        if not self.active or self.dialog._closing:
            return
        row=self.dialog.workflow_state.selected_provider_record
        if row:
            self.toggle(row)

    def toggle(self, row):
        if not self.active or self.dialog._closing:
            return
        try:
            from calibre_plugins.manganana.app.main import SOURCE_REGISTRY
            source = SOURCE_REGISTRY.get(row.get('source_id'))
            if not self.store.contains(row) and (source is None or source.parse_manga_ref(row.get('url') or '') is None):
                raise ValueError('This listing has no supported provider URL')
            self.store.toggle(row)
            if self.showing:
                self.refresh()
            else:
                # A heart changes no grouping, rank or thumbnail visibility.
                # Repaint existing nodes instead of regrouping a large search
                # model or scheduling another thumbnail batch.
                from calibre_plugins.manganana.discovery.discovery_groups import provider_key
                model=self.dialog.discovery_view.model()
                index=model.provider_index(provider_key(row))
                if index.isValid():
                    model.dataChanged.emit(index,index,[])
                self.dialog.discovery_view.viewport().update()
        except ValueError as exc:
            self.message.setText(str(exc))
            self.message.show()
        self.update_selected()

    def open(self, row):
        if not self.active or self.dialog._closing:
            return
        if self.dialog.workflow_mode not in ('volume', 'chapter'):
            return
        from calibre_plugins.manganana.app.main import SOURCE_REGISTRY
        source = SOURCE_REGISTRY.get(row.get('source_id'))
        ref = source.parse_manga_ref(row.get('url') or '') if source else None
        expected = str(row.get('id') or '')
        compatible = str(ref) == expected
        if row.get('source_id') in ('mangadex', 'weebcentral'):
            compatible = str(ref).casefold() == expected.casefold()
        if ref is None or not compatible:
            self.message.setText('This saved listing is unavailable or its provider identity has changed. Remove it or try again later.')
            self.message.show()
            return
        # A persisted bookmark cannot serialize a live resolution object. The
        # provider-local branch validates metadata/inventory afresh and reuses
        # eligible controller caches. Never reconstruct a cross-source fallback.
        info = dict(row, resolution_state='provider_local', _favorite_exact=True)
        from PyQt6 import sip
        if self.selection_item is not None and not sip.isdeleted(self.selection_item):
            index = self.dialog.search_results.row(self.selection_item)
            if index >= 0:
                self.dialog.search_results.takeItem(index)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, info)
        self.dialog.search_results.addItem(item)
        self.selection_item = item
        self.dialog.use_search_result(item)

    def detach(self, *_):
        if not self.active:
            return
        self.active = False
        self.title_row._active=False
        self.dialog.selected_title.removeEventFilter(self.title_row)
        from PyQt6 import sip
        if not sip.isdeleted(self.error_timer):
            self.error_timer.stop()
        self.store.close()

    def __del__(self):
        store = getattr(self, 'store', None)
        if store is not None:
            store.close()

