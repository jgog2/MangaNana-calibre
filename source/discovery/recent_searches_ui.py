"""Bounded local search history, cached artwork and search-home navigation."""
import base64
from qt.core import (QObject, QWidget, QStackedWidget, QVBoxLayout, QPushButton,
    QLabel, QListWidget, QListWidgetItem, QMenu, Qt, QSize, QIcon, QPixmap,
    QToolButton, QBuffer, QIODevice, QColor)
from calibre_plugins.manganana.app.settings.config import prefs


def query_key(query):
    return ' '.join(str(query).split()).casefold()


def clean_recent_searches(values):
    if not isinstance(values, (list, tuple)):
        return []
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str):
            continue
        query = value.strip()
        key = query_key(query)
        if not query or len(query) > 256 or key in seen:
            continue
        result.append(query)
        seen.add(key)
        if len(result) == 20:
            break
    return result


class RecentSearches(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.d = dialog
        self.home = True
        self.queries = clean_recent_searches(prefs.get('recent_searches', []))
        raw = prefs.get('recent_search_artwork', {})
        self.artwork = dict(raw) if isinstance(raw, dict) else {}
        self.capture = None
        self.warning = ''
        self.stack = QStackedWidget()
        dialog.discovery_view.parentWidget().layout().replaceWidget(dialog.discovery_view, self.stack)
        self.stack.addWidget(dialog.discovery_view)
        self.page = QWidget()
        column = QVBoxLayout(self.page)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(8)
        title = QLabel('Recent searches')
        title.setStyleSheet('font-size:14px;font-weight:600;')
        column.addWidget(title)
        self.empty = QLabel('Your recent searches will appear here.')
        self.empty.setWordWrap(True)
        column.addWidget(self.empty)
        self.list = QListWidget()
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setIconSize(QSize(36, 50))
        self.list.setUniformItemSizes(True)
        self.list.setAccessibleName('Recent searches')
        self.list.setStyleSheet('''QListWidget::item {padding:7px 10px;border-bottom:1px solid #26353b;}
            QListWidget::item:hover {background:#203832;}
            QListWidget::item:selected {background:#29453f;border-radius:0;}
            QListWidget::item:focus {border:1px solid #66B7A8;}''')
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        self.list.itemClicked.connect(self.run_item)
        self.list.itemActivated.connect(self.run_item)
        column.addWidget(self.list, 1)
        self.stack.addWidget(self.page)
        self.clear_button = QPushButton('Clear recent searches')
        self.clear_button.setAutoDefault(False)
        self.clear_button.clicked.connect(self.clear)
        dialog.fidelity.paging_host.layout().addWidget(self.clear_button)
        # Keep Qt's native clear icon, hit target, text margins and DPI sizing.
        for button in dialog.search_box.findChildren(QToolButton):
            button.clicked.connect(self.go_home)
        self.render()
        self.sync()

    def icon(self, query):
        placeholder = QPixmap(36, 50)
        placeholder.fill(QColor('#24393b'))
        value = self.artwork.get(query_key(query), '')
        if isinstance(value, str) and len(value) <= 24000:
            try:
                raw = base64.b64decode(value, validate=True)
                pix = QPixmap()
                if len(raw) <= 16384 and pix.loadFromData(raw, 'PNG'):
                    return QIcon(pix)
            except (ValueError, TypeError):
                pass
        return QIcon(placeholder)

    def render(self):
        self.list.clear()
        for query in self.queries:
            item = QListWidgetItem(self.icon(query), query)
            item.setData(Qt.ItemDataRole.UserRole, query)
            item.setSizeHint(QSize(0, 66))
            item.setToolTip('Search again: ' + query)
            self.list.addItem(item)
        self.empty.setText(self.warning or 'Your recent searches will appear here.')
        self.empty.setVisible(bool(self.warning) or not self.queries)
        self.clear_button.setEnabled(bool(self.queries))

    def save(self):
        keys = {query_key(q) for q in self.queries}
        self.artwork = {k: v for k, v in self.artwork.items() if k in keys and isinstance(v, str) and len(v) <= 24000}
        try:
            prefs['recent_searches'] = list(self.queries)
            prefs['recent_search_artwork'] = self.artwork
            self.warning = ''
        except Exception:
            self.warning = 'Recent searches could not be saved.'
            self.d.add_log(self.warning)
        self.render()

    def capture_records(self, records):
        query = self.d._search_query
        if self.home or query_key(query) not in {query_key(q) for q in self.queries}:
            return
        row = next((r for r in records if r.get('cover_url')), None)
        if row:
            self.capture = (query_key(query), row['cover_url'], self.d._search_request_id)
            self.artwork_changed(row['cover_url'])

    def artwork_changed(self, url):
        if self.capture is None or self.capture[1:] != (url, self.d._search_request_id):
            return
        pix = self.d._search_pixmap(url)
        if pix is None or pix.isNull():
            return
        # Persist only a tiny representative of this query's existing result.
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pix = pix.scaled(36, 50, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        pix.save(buffer, 'PNG')
        raw = bytes(buffer.data())
        if len(raw) <= 16384:
            encoded = base64.b64encode(raw).decode('ascii')
            if self.artwork.get(self.capture[0]) != encoded:
                self.artwork[self.capture[0]] = encoded
                self.save()

    def submitted(self, query):
        self.queries = clean_recent_searches([query] + self.queries)
        self.save()
        self.show_results()
        self.capture_records(self.d.saved_manga.search_records)

    def show_results(self, *_):
        self.home = False
        self.sync()

    def go_home(self, *_):
        d = self.d
        if d._closing or d.workflow_mode == 'import' or d._download_in_progress:
            return
        self.home = True
        self.capture = None
        # Invalidate before interrupting: completion may already be queued.
        d._mode_generation += 1
        for name in ('_search_request_id', '_search_resolution_request_id', '_enrichment_request_id', '_inventory_comparison_request_id'):
            setattr(d, name, getattr(d, name) + 1)
        d.workflow_state.reset_search()
        workers = list(d.search_workers.values())
        for name in ('_search_resolution_worker', '_enrichment_worker', 'inventory_comparison_worker'):
            worker = getattr(d, name)
            if worker is not None:
                workers.append(worker)
            setattr(d, name, None)
        for worker in workers:
            if worker.isRunning():
                worker.requestInterruption()
        d.search_workers = {}
        d._search_status_timer.stop()
        d._search_cancel_requested = False
        d._search_resolution_complete = d._enrichment_received = True
        d._search_resolutions = {}
        d._search_ranked_groups = ()
        d._external_candidates = ()
        d._late_enrichment_by_provider = {}
        d._search_has_more = {}
        d._search_query = ''
        d._search_raw_results = []
        d._search_content_results = []
        d._invalidate_cover_requests()
        d._reset_reference_lookup()
        d._clear_active_provider_selection('Search for manga to begin.')
        d._selected_cover_url = ''
        d.saved_manga.showing = False
        d._publish_discovery_records([])
        d.search_box.clear()
        d.search_btn.setEnabled(True)
        d.search_btn.setText('Search')
        d._set_cancel_action(False)
        d._set_search_progress_visible(False)
        d._set_work_progress_visible(False)
        self.render()
        self.sync()

    def sync(self):
        d = self.d
        if d._closing:
            return
        local = d.workflow_mode == 'import'
        self.stack.setVisible(not local)
        self.stack.setCurrentWidget(self.page if self.home else d.discovery_view)
        d.discovery_view.setVisible(not local and not self.home)
        d.fidelity.paging_host.setVisible(not local)
        self.clear_button.setVisible(not local and self.home)
        if self.home:
            d.show_more_btn.hide()
            d.fidelity.paging_summary.hide()
        if self.home or local:
            d.saved_manga.message.hide()

    def run_item(self, item):
        if self.d._closing or self.d.workflow_mode == 'import' or not self.d.search_btn.isEnabled():
            return
        self.d.search_box.setText(item.data(Qt.ItemDataRole.UserRole))
        self.d.search_mangadex()

    def remove(self, query):
        self.queries = [value for value in self.queries if value != query]
        self.save()

    def clear(self, *_):
        self.queries = []
        self.capture = None
        self.save()

    def context_menu(self, position):
        item = self.list.itemAt(position)
        if item is None:
            return
        query = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self.list)
        action = menu.addAction('Remove from recent searches')
        action.triggered.connect(lambda *_: self.remove(query))
        try:
            menu.exec(self.list.mapToGlobal(position))
        finally:
            menu.deleteLater()
