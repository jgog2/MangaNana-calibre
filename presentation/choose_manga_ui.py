"""Native Choose Manga presentation over the dialog controllers.

All acquisitions, selection, generations, mappings and stage guards remain in
the existing dialog. This subclass only arranges its native presentation.
"""
from qt.core import (Qt, QSize, QWidget, QLabel, QPushButton,
    QLineEdit, QComboBox, QVBoxLayout, QHBoxLayout, QGridLayout, QBoxLayout,
    QListView, QAbstractItemView, QTimer, QEvent, QFont, QPainter, QColor, QIcon,
    QStyle, QStyleOptionButton, QPersistentModelIndex)
from calibre_plugins.manganana.presentation.non_modal_window import PluginDialog as QDialog
from calibre_plugins.manganana.app.main import (
    MangaNanaDialog,
    VolumeRowWidget,
    SearchResultRowWidget,
    SOURCE_REGISTRY,
)
from calibre_plugins.manganana.presentation.choose_manga_background import HeroSurface, PROVIDER_PRESETS
from calibre_plugins.manganana.presentation.choose_manga_design import PreviewFlowLayout, PreviewFlowScroll
from calibre_plugins.manganana.presentation.choose_manga_polish import SeafoamPolishLayout as FidelityLayout
from calibre_plugins.manganana.presentation.interface_scale import set_presentation_style
from calibre_plugins.manganana.metadata.description_text import normalize_description
from calibre_plugins.manganana.presentation.mangaanka_presentation import (
    apply_presentation,
    PresentationScope,
    UI_ACCENT,
)

CYAN = '#18dce2'
STYLE = '''
QDialog { background:#06111a; color:#edf5f8; }
QWidget { font-family:'Segoe UI'; font-size:13px; }
QWidget#reviewSearch { background:#091721; border:1px solid #203c4b; border-radius:12px; }
QWidget#reviewInventory { background:transparent; border:0; }
QWidget#selectedMangaCard { background:rgba(4,14,24,105); border:0; border-radius:12px; }
QLabel { color:#e6eff4; }
QPushButton { min-height:20px; border-radius:7px; padding:5px 10px; }
QLineEdit, QComboBox { background:#091923; color:#eaf7fa;
 border:1px solid #294858; border-radius:7px; padding:7px; selection-background-color:#185361; }
QListWidget { background:transparent; border:0; outline:0; }
QListWidget::item { border:0; padding:0; }
QListWidget::item:selected { background:#143645; border-radius:10px; }
QPushButton#providerFilter { background:#0c202c; border:1px solid #243f4e;
 border-radius:15px; padding:5px 7px; color:#e8f4fa; font-size:12px; }
QPushButton#providerFilter:checked { background:#124553; border:1px solid #18dce2; }
QPushButton#providerFilter:focus { border:2px solid #eafcff; }
QPushButton#modeChoice:checked { background:#27b9bd; color:#04131b; border:1px solid #30f5ee; }
QPushButton#reviewOptions { background:transparent; border:0; color:#a4c2cf; padding:2px; }
QFrame#reviewVolumeRow { background:transparent; border:1px solid transparent; border-radius:8px; }
QFrame#reviewVolumeRow[selected="true"] { background:#0a2731; border:1px solid #18dce2; }
QScrollBar:horizontal { background:#0e2431; height:12px; border-radius:6px; }
QScrollBar::handle:horizontal { background:#557f91; min-width:32px; border-radius:6px; }
QScrollBar:vertical { background:#0e2431; width:12px; border-radius:6px; }
QScrollBar::handle:vertical { background:#557f91; min-height:32px; border-radius:6px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
'''


def membership_summary(group):
    """Summarize explicitly supplied members; never manufacture range endpoints."""
    from calibre_plugins.manganana.publication.inventory_coverage import entry_text
    rows = (group or {}).get('chapters') or ()
    if any(row.get('_unit_kind') == 'volume' for row in rows):
        packaged = all(row.get('_unit_kind') == 'volume' for row in rows)
        return (entry_text(len(rows), True) if packaged else f'{len(rows)} source entries',
                'Acquisition entries: ' + ', '.join(str(row.get('id') or '') for row in rows))
    if any(row.get('_publication_identity') for row in rows if isinstance(row,dict)):
        tokens = [str((row.get('_publication_identity') or {}).get('episode_token')
            or row.get('chapter') or row.get('id') or '?') for row in rows]
        return entry_text(len(tokens)), 'Episodes in reading order: ' + ', '.join(tokens)
    values = [str(row.get('chapter') if row.get('chapter') is not None else row.get('number') if row.get('number') is not None else row.get('label') or ('ID: ' + str(row['id']) if row.get('id') is not None else '?'))
              for row in rows if isinstance(row, dict)]
    if not values:
        return 'Entry count unavailable', ''
    full = 'Chapters: ' + ', '.join(values)
    try:
        numbers = [int(value) for value in values]
        if len(set(numbers)) == len(numbers) and sorted(numbers) == list(range(min(numbers), max(numbers)+1)):
            return entry_text(len(values)), full
    except ValueError:
        pass
    return entry_text(len(values)), full


class ChooseMangaDialog(MangaNanaDialog):
    _viewport_chapter_cards=True
    _viewport_volume_cards=True
    _ui_input_active=False
    def _layout_icon(self, landscape=False):
        # Preserve the existing artwork; explicitly supply both Qt states for
        # the neutral segments used by this presentation.
        base=super()._layout_icon(landscape)
        icon=QIcon()
        for state,color in ((QIcon.State.On,UI_ACCENT),(QIcon.State.Off,'#46515b')):
            pixmap=base.pixmap(QSize(46,36),QIcon.Mode.Normal,QIcon.State.Off)
            painter=QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(),QColor(color));painter.end()
            for mode in (QIcon.Mode.Normal,QIcon.Mode.Active,QIcon.Mode.Selected):
                icon.addPixmap(pixmap,mode,state)
        return icon

    def __init__(self,gui,icon):
        super().__init__(gui,icon)
        from calibre_plugins.manganana.app.main import prefs
        mode=prefs.get('acquisition_mode','volume')
        self._set_workflow_mode(mode if mode in ('volume','chapter','import') else 'volume')
        apply_presentation(self)
        self.setStyleSheet(self.styleSheet()+self.fidelity.presentation_style())
        self.presentation_scope=PresentationScope(self)
        from calibre_plugins.manganana.presentation.interface_scale import InterfaceScale
        self.interface_scaling=InterfaceScale(self)
        for button in (self.portrait_btn, self.landscape_btn):
            button.ensurePolished()
            option=QStyleOptionButton();button.initStyleOption(option)
            content=option.fontMetrics.size(Qt.TextFlag.TextShowMnemonic, button.text())
            if not button.icon().isNull():
                content.setWidth(content.width()+button.iconSize().width()+button.style().pixelMetric(
                    QStyle.PixelMetric.PM_LayoutHorizontalSpacing, option, button))
            required=button.style().sizeFromContents(QStyle.ContentsType.CT_PushButton,option,content,button)
            button.setMinimumWidth(max(button.sizeHint().width(),required.width()))
        self.fidelity.resize()
        from collections import OrderedDict
        self._search_image_cache=OrderedDict()
        self._search_scaled_pixmaps=OrderedDict()
        self._setup_discovery_view()
        if hasattr(self,'discovery_view'):
            from calibre_plugins.manganana.discovery.recent_searches_ui import RecentSearches
            self.recent_searches=RecentSearches(self)
        from calibre_plugins.manganana.diagnostics.thumbnail_diagnostics import enable
        if hasattr(self,'discovery_view'):enable(self)
        from calibre_plugins.manganana.app.updates.release_updates_ui import ReleaseUpdates
        self.release_updates=ReleaseUpdates(self)
        self._chapter_card_items=set()
        self._chapter_card_timer=QTimer(self);self._chapter_card_timer.setSingleShot(True)
        self._chapter_card_timer.timeout.connect(self._materialize_chapter_cards)
        self.volume_list.horizontalScrollBar().valueChanged.connect(lambda *_:self._chapter_card_timer.start(0))
        self.volume_list.horizontalScrollBar().rangeChanged.connect(lambda *_:self._chapter_card_timer.start(0))
        import os
        if os.environ.get('MANGAANKA_PERF_DIR') and os.environ.get('MANGAANKA_PERF_AUTOSTART','1')!='0':
            from calibre_plugins.manganana.app import main
            from calibre_plugins.manganana.diagnostics.performance_diagnostics import attach
            self.performance_recorder=attach(main,self)
        self.clear_volume_btn.clicked.connect(lambda *_:setattr(self,'_inventory_shift_anchor',None))
        self._ui_input_active=True
        self.anka_shell.workspace.viewport().installEventFilter(self)
        self.fidelity.right_workspace.installEventFilter(self)
        self.finished.connect(self._detach_ui_input)
        from calibre_plugins.manganana.presentation.non_modal_window import NonModalSession
        self.nonmodal_session=NonModalSession(self)

    def _detach_ui_input(self, *_):
        self._ui_input_active=False
        from qt.core import QApplication, QObject
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        app=QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        # Remove local filters too: child destruction can reenter Python while
        # cyclic GC is clearing the dialog's workflow and presentation state.
        for child in self.findChildren(QObject):
            child.removeEventFilter(self)
        carousel=getattr(getattr(self,'fidelity',None),'carousel',None)
        if carousel is not None:
            carousel.detach()
        page_filter=getattr(self,'_page_wheel_filter',None)
        if page_filter is not None:
            page_filter.detach()
        presentation=getattr(self,'presentation_scope',None)
        if presentation is not None:
            presentation.detach()
        timer=getattr(self,'_chapter_card_timer',None)
        if timer is not None and not sip.isdeleted(timer):
            timer.stop()
        favorites=getattr(self,'saved_manga',None)
        if favorites is not None:
            favorites.detach()

    def __del__(self):
        self._detach_ui_input()

    def _setup_discovery_view(self):
        import os
        if os.environ.get('MANGAANKA_DISCOVERY_LEGACY')=='1':return
        from qt.core import QToolButton,QMenu
        from calibre_plugins.manganana.discovery.discovery_view import DiscoveryView
        from calibre_plugins.manganana.app.main import prefs
        self._discovery_items={}
        self.discovery_view=DiscoveryView(self)
        host=self.search_results.parentWidget().layout()
        host.replaceWidget(self.search_results,self.discovery_view)
        self.search_results.hide()
        self.search_results.setMaximumHeight(0)
        # Retain a lightweight provider-record store for all existing controller
        # and snapshot APIs. It has no per-result widgets in the model/view path.
        self.search_results.model().modelReset.connect(self._clear_discovery_view)
        self.search_results.currentItemChanged.connect(lambda *_:self.discovery_view.sync_selection())
        self.discovery_mode=QToolButton();self.discovery_mode.setAccessibleName('Discovery display mode')
        self.discovery_mode.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu=QMenu(self.discovery_mode)
        self.discovery_mode_actions=[]
        for label,grouped in (('Grouped results',True),('Flat results',False)):
            action=menu.addAction(label);action.setCheckable(True)
            action.triggered.connect(lambda _checked,g=grouped:self._set_discovery_grouped(g))
            self.discovery_mode_actions.append(action)
        self.discovery_mode.setMenu(menu)
        self.search_results_label.parentWidget().layout().addWidget(self.discovery_mode)
        self._set_discovery_grouped(bool(prefs.get('grouped_discovery',True)),persist=False)
        from calibre_plugins.manganana.discovery.saved_manga_ui import SavedManga
        self.saved_manga=SavedManga(self)
        from calibre_plugins.manganana.publication.inventory_coverage_ui import CoveragePresentation
        self.coverage_presentation=CoveragePresentation(self)
        menu.addSeparator()
        self.retry_covers_action=menu.addAction('Retry covers')
        self.retry_covers_action.triggered.connect(self._retry_failed_covers)
        menu.aboutToShow.connect(self._refresh_cover_retry)
        self.fidelity.mode()
        self._refresh_cover_retry()

    def search_mangadex(self, reset=True, expected_generation=None):
        # Change the visible discovery view at submission, including cached
        # searches. Background publications and pagination keep their view.
        if (reset and not self._closing
                and self.workflow_mode in ('volume', 'chapter')
                and (expected_generation is None or expected_generation == self._mode_generation)):
            saved = getattr(self, 'saved_manga', None)
            if saved is not None and saved.showing:
                saved.show_search()
        previous=self._search_request_id
        result=super().search_mangadex(reset, expected_generation)
        recent=getattr(self,'recent_searches',None)
        if recent is not None and reset and self._search_request_id!=previous:
            recent.submitted(self._search_query)
        return result

    def _clear_discovery_view(self):
        if not self._closing and not getattr(self,'_publishing_discovery',False):
            if hasattr(self,'saved_manga'):
                self.saved_manga.publish([])
            else:
                self.discovery_view.set_records([])
            self._discovery_count()

    def _apply_late_search_enrichment(self,render=True):
        super()._apply_late_search_enrichment(render=render)
        if render and hasattr(self,'discovery_view'):
            self._refresh_search_rows()

    def _set_discovery_grouped(self,grouped,persist=True):
        self.discovery_view.set_grouped(grouped)
        self.discovery_mode.setText('Grouped' if grouped else 'Flat')
        for action,value in zip(self.discovery_mode_actions,(True,False)):action.setChecked(value==grouped)
        if persist:
            from calibre_plugins.manganana.app.main import prefs
            prefs['grouped_discovery']=bool(grouped)
        self._discovery_count()

    def _discovery_count(self):
        if not hasattr(self,'discovery_view'):return
        count=len(self.discovery_view.records);groups=len(self.discovery_view.model().roots)
        if getattr(self.discovery_view,'saved_mode',False):
            self.fidelity.results_count.setText(f'{count} saved')
            self.fidelity.results_count.setToolTip('Exact provider listings · H toggles the focused heart')
            self.fidelity.paging_summary.hide()
            return
        self.fidelity.results_count.setText(f'{groups} group'+('s' if groups!=1 else '')+f' · {count}' if self.discovery_view.grouped else f'{count} results')
        self.fidelity.results_count.setToolTip(f'{groups} groups · {count} provider listings')
        self.fidelity.paging_summary.setVisible(not self.show_more_btn.isVisible())
        recent=getattr(self,'recent_searches',None)
        if recent is not None:recent.sync()

    def _sync_discovery_footer(self):
        if self._closing:return
        self.fidelity.paging_summary.setVisible(not self.show_more_btn.isVisible())
        recent=getattr(self,'recent_searches',None)
        if recent is not None:recent.sync()

    def _publish_discovery_records(self,records):
        from qt.core import QListWidgetItem
        from calibre_plugins.manganana.discovery.discovery_groups import provider_key
        selected=self.search_results.currentItem()
        selected_key=provider_key(selected.data(256) or {}) if selected else None
        blocked=self.search_results.blockSignals(True)
        self._publishing_discovery=True
        self.search_results.clear();self._discovery_items={}
        for record in records:
            item=QListWidgetItem();item.setData(Qt.ItemDataRole.UserRole,record)
            self.search_results.addItem(item);self._discovery_items[provider_key(record)]=item
        if selected_key in self._discovery_items:self.search_results.setCurrentItem(self._discovery_items[selected_key])
        self.search_results.blockSignals(blocked)
        self._publishing_discovery=False
        if hasattr(self,'saved_manga'):
            self.saved_manga.publish(records)
        else:
            self.discovery_view.set_records(records)
        self._discovery_count()

        recent=getattr(self,'recent_searches',None)
        if recent is not None:recent.capture_records(records)

    def _compatible_fallback_candidates(self,selected):
        if selected.get('_favorite_exact'):
            return (dict(selected),)
        return super()._compatible_fallback_candidates(selected)

    def _load_visible_search_thumbs(self):
        if not hasattr(self,'discovery_view'):return super()._load_visible_search_thumbs()
        from calibre_plugins.manganana.app.main import (
            ImageBatchWorker,
            SOURCE_REGISTRY,
            MANGADEX_SOURCE,
            COVER_BATCH_LIMIT,
        )
        if self._closing:return
        batch=[];queued=set()
        for info in self.discovery_view.visible_records():
            url=info.get('cover_url') or ''
            if not url or url in queued or url in self._search_image_cache or url in self._failed_image_urls:continue
            source=SOURCE_REGISTRY.get(info.get('source_id')) or MANGADEX_SOURCE
            urls=[url+'.256.jpg',url] if source.source_id=='mangadex' else [url]
            batch.append((url,urls,source));queued.add(url)
            if len(batch)>=COVER_BATCH_LIMIT:break
        current=self.search_thumb_worker
        if current is not None and current.isRunning():
            current.prioritize(batch)
            return
        if not batch:return
        self._search_cover_batch_token+=1
        worker=self._retain_async_worker(ImageBatchWorker(('search',self._search_cover_batch_token,self._cover_generation),batch))
        worker.thumbnail_audit=getattr(self,'thumbnail_audit',None)
        self.search_thumb_worker=worker
        worker.image_ready.connect(self._on_search_thumb_ready);worker.image_failed.connect(self._on_search_thumb_failed)
        worker.finished.connect(lambda w=worker:self._on_search_thumb_finished(w));worker.start()

    def _on_search_thumb_ready(self,data):
        super()._on_search_thumb_ready(data)
        if (hasattr(self,'discovery_view') and not self._closing and
                data.get('batch_id')==('search',self._search_cover_batch_token,self._cover_generation)):
            url=data.get('key');raw=data.get('raw')
            if url and raw:
                self._search_image_cache[url]=raw;self._search_image_cache.move_to_end(url)
                for key in tuple(self._search_scaled_pixmaps):
                    if key[0]==url:self._search_scaled_pixmaps.pop(key,None)
                while sum(map(len,self._search_image_cache.values()))>16*1024*1024:
                    expired,_=self._search_image_cache.popitem(last=False)
                    for key in tuple(self._search_scaled_pixmaps):
                        if key[0]==expired:self._search_scaled_pixmaps.pop(key,None)
            self.discovery_view.model().artwork_changed(data.get('key'))
            recent=getattr(self,'recent_searches',None)
            if recent is not None:recent.artwork_changed(data.get('key'))
        self._refresh_cover_retry()

    def _on_search_thumb_failed(self,data):
        super()._on_search_thumb_failed(data)
        if (hasattr(self,'discovery_view') and not self._closing and
                data.get('batch_id')==('search',self._search_cover_batch_token,self._cover_generation)):
            self.discovery_view.model().artwork_changed(data.get('key'))
        self._refresh_cover_retry()

    def _visible_failed_covers(self):
        from calibre_plugins.manganana.app.main import SOURCE_REGISTRY
        if self._closing or self.workflow_mode == 'import':
            return {}
        targets={}
        if hasattr(self,'discovery_view'):
            for record in self.discovery_view.visible_records():
                url=record.get('cover_url')
                if url in self._failed_image_urls:
                    source=SOURCE_REGISTRY.get(record.get('source_id'))
                    if source is not None:targets[url]=source
        if self.workflow_state.selected_provider_record:
            if self._selected_cover_url in self._failed_image_urls:
                targets[self._selected_cover_url]=self.current_source
            for i in self._visible_row_range(self.volume_list,66,4):
                info=self.volume_list.item(i).data(Qt.ItemDataRole.UserRole) or {}
                url=info.get('cover_url')
                if url in self._failed_image_urls:targets[url]=self.current_source
        return targets

    def _refresh_cover_retry(self):
        if self._closing:return
        targets=self._visible_failed_covers()
        busy=any(worker is not None and worker.isRunning()
            for worker in (self.search_thumb_worker,self.volume_thumb_worker))
        if hasattr(self,'retry_covers_action'):
            self.retry_covers_action.setEnabled(bool(targets) and not busy)
        presentation=getattr(self,'coverage_presentation',None)
        if presentation is not None:
            presentation.retry.setVisible(bool(targets))
            presentation.retry.setEnabled(not busy)

    def _retry_failed_covers(self, *_):
        if self._closing:return
        if any(worker is not None and worker.isRunning()
                for worker in (self.search_thumb_worker,self.volume_thumb_worker)):
            return
        targets=self._visible_failed_covers()
        if not targets:return
        resolver=self._get_artwork_resolver()
        for url,source in targets.items():
            self._failed_image_urls.discard(url)
            resolver.retry_failed_url(url,source)
        for i in range(self.volume_list.count()):
            item=self.volume_list.item(i);info=item.data(Qt.ItemDataRole.UserRole) or {}
            if info.get('cover_url') in targets:
                info['thumb_requested']=False;item.setData(Qt.ItemDataRole.UserRole,info)
        audit=getattr(self,'thumbnail_audit',None)
        if audit:
            for url,source in targets.items():
                audit.event('retry.explicit',url=url,provider=source.source_id,generation=self._cover_generation)
        self._load_visible_search_thumbs()
        self._load_visible_volume_thumbs()
        self._refresh_cover_retry()

    def _on_search_thumb_finished(self, worker):
        super()._on_search_thumb_finished(worker)
        self._refresh_cover_retry()

    def _on_volume_thumb_ready(self, data):
        super()._on_volume_thumb_ready(data)
        self._refresh_cover_retry()

    def _on_volume_thumb_failed(self, data):
        super()._on_volume_thumb_failed(data)
        self._refresh_cover_retry()

    def _on_volume_thumb_finished(self, worker):
        super()._on_volume_thumb_finished(worker)
        self._refresh_cover_retry()

    def _inventory_selection_key(self, item):
        info=item.data(Qt.ItemDataRole.UserRole) or {}
        value=info.get('chapter_id') if info.get('kind')=='chapter' else info.get('volume')
        return (info.get('kind'),str(value) if value is not None else 'standalone')

    def _volume_row_toggled(self, item, checked):
        if self._volume_check_syncing or item is None:return
        from qt.core import QApplication
        row=self.volume_list.itemWidget(item)
        modifiers=getattr(row,'_selection_modifiers',None)
        if modifiers is None:modifiers=QApplication.keyboardModifiers()
        context=(self.workflow_mode,self.current_source_id,self.current_manga_url,
                 self._manga_request_id,self._volume_plan_request_id)
        anchor=getattr(self,'_inventory_shift_anchor',None)
        if modifiers & Qt.KeyboardModifier.ShiftModifier and anchor and anchor[0]==context:
            first=next((i for i in range(self.volume_list.count())
                if self._inventory_selection_key(self.volume_list.item(i))==anchor[1]),None)
            last=self.volume_list.row(item)
            if first is not None and last>=0:
                self._apply_inventory_selection((self.volume_list.item(i)
                    for i in range(min(first,last),max(first,last)+1)),True)
                return
        super()._volume_row_toggled(item,checked)
        self._inventory_shift_anchor=(context,self._inventory_selection_key(item))

    def _processing_changed(self, *args):
        super()._processing_changed(*args)
        if hasattr(self, 'fidelity') and hasattr(self.fidelity, 'sync_switches'):
            self.fidelity.sync_switches()

    def build_ui(self):
        super().build_ui()
        self.setFont(QFont('Segoe UI', 10))
        self.setStyleSheet(self.styleSheet() + STYLE)
        self.anka_shell.layout.setContentsMargins(14, 8, 14, 8)
        self.header.subtitle.show()
        self.header.icon_label.setFixedSize(40, 40)
        self.header.icon_label.setPixmap(self.header.app_icon.pixmap(40, 40))
        self.header.name_label.setStyleSheet('font-size:28px;font-weight:700;font-family:Segoe UI;')
        self.header.name_label.setText('Manga<span style="color:#18dce2;">Ankā</span>')
        search_page = self._discovery_layout.itemAt(0).widget()
        search_page.setObjectName('reviewSearch')
        search_page.setMinimumWidth(325)
        search_page.setMaximumWidth(490)
        self._source_selected_page.setObjectName('reviewInventory')
        self._source_selected_page.setMinimumWidth(460)
        self._source_selected_page.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
        self._source_selected_page.layout().setContentsMargins(0,0,0,0)
        self._source_selected_page.layout().setSpacing(8)
        search_page.layout().itemAt(0).widget().setStyleSheet('font-size:21px;font-weight:600;color:#f1f7fa;')
        self._discovery_layout.setStretch(0, 3)
        self._discovery_layout.setStretch(1, 7)
        self._discovery_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setAccessibleName('Search manga sources')
        self.search_results.setMinimumHeight(230)
        self.search_results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.search_results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_results.itemActivated.connect(self.use_search_result)
        self.search_results.currentItemChanged.connect(lambda *_args: self._style_search_selection())
        self.search_results.setUniformItemSizes(False)
        self._build_discovery_options()
        self._mode_row.itemAt(0).widget().hide()
        self._search_label = self._search_top_panel.layout().itemAt(1).widget()
        self._search_label.hide()
        self._build_hero()
        self._build_inventory_actions()
        self._source_selected_page.layout().addStretch(1)
        self.volume_list.horizontalScrollBar().valueChanged.connect(lambda _v: self._load_visible_volume_thumbs())
        self.volume_list.installEventFilter(self)
        self._review_ready = True
        self._arrange_inventory()
        self._arrange_live_preview()
        self.fidelity = FidelityLayout(self)

    def _arrange_live_preview(self):
        # Both provider and imported samples use the unchanged shared renderer.
        # Replace only its empty presentation container before any work starts.
        old = self.live_preview_scroll
        host = old.parentWidget().layout()
        scroll = PreviewFlowScroll()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); body.setObjectName('previewBody')
        self.live_preview_grid = PreviewFlowLayout(body)
        scroll.setWidget(body)
        host.replaceWidget(old, scroll)
        old.hide(); old.deleteLater()
        self.live_preview_scroll = scroll
        self.live_preview_body = body
        scroll.hide()
        # A bounded settings column leaves room for readable page samples.
        self.customization_settings_card.setMinimumWidth(460)
        self.customization_settings_card.setMaximumWidth(560)
        self._book_customization_stage_panel.columns.setStretch(0, 0)
        self._book_customization_stage_panel.columns.setStretch(1, 1)

    def _sync_discovery_top_heights(self):
        # Hero and search are intentionally different heights in this design.
        for name in ('_search_top_panel', '_selected_top_panel'):
            panel = getattr(self, name, None)
            if panel is not None:
                panel.setMinimumHeight(0)
                panel.setMaximumHeight(16777215)

    def _sync_progress_visibility(self):
        super()._sync_progress_visibility()
        if hasattr(self, 'fidelity'):
            self.fidelity.progress()

    def _build_discovery_options(self):
        top = self._search_top_panel.layout()
        self.options_button = QPushButton('Discovery options ▸')
        self.options_button.setCheckable(True)
        self.options_button.setObjectName('reviewOptions')
        self.options_button.setFixedHeight(26)
        self.options_button.setAutoDefault(False)
        self.discovery_options = QWidget()
        options = QVBoxLayout(self.discovery_options)
        options.setContentsMargins(0, 4, 0, 4)
        # Existing language, preference and direct-link widgets/signals survive.
        while top.count() > 3:
            item = top.takeAt(3)
            def reparent(cell):
                if cell.widget():
                    cell.widget().setParent(self.discovery_options)
                elif cell.layout():
                    for i in range(cell.layout().count()):
                        reparent(cell.layout().itemAt(i))
            reparent(item)
            options.addItem(item)
        top.addWidget(self.options_button)
        top.addWidget(self.discovery_options)
        self.discovery_options.hide()
        self.options_button.toggled.connect(self._toggle_discovery_options)

    def _toggle_discovery_options(self, checked):
        if hasattr(self, 'fidelity'):
            self.fidelity.settings_window.setVisible(checked)
            return
        self.discovery_options.setVisible(checked)
        self.options_button.setText('Discovery options ▾' if checked else 'Discovery options ▸')





    def _refresh_search_rows(self):
        # Presentation only: ranking, source qualification and counts stay in
        # the original models. No second provider-filter configuration exists.
        if hasattr(self,'discovery_view'):
            self.discovery_view.set_records([self.search_results.item(i).data(256) for i in range(self.search_results.count())])
            self._discovery_count();return
        for index in range(self.search_results.count()):
            item=self.search_results.item(index)
            data=item.data(Qt.ItemDataRole.UserRole) or {}
            row=self.search_results.itemWidget(item)
            if isinstance(row,SearchResultRowWidget):
                row.setObjectName('reviewResultRow')
                row.setAccessibleName(str(data.get('title',''))+' — '+str(data.get('source_id','')))
                if hasattr(row,'inventory_label'):row.inventory_label.hide()
        self._style_search_selection()
        if hasattr(self,'fidelity'):self.fidelity.results()


    def _style_search_selection(self):
        if hasattr(self,'discovery_view'):
            self.discovery_view.sync_selection();return
        for index in range(self.search_results.count()):
            item = self.search_results.item(index)
            row = self.search_results.itemWidget(item)
            if row is not None:
                row.setProperty('selected', item.isSelected())
                row.style().unpolish(row)
                row.style().polish(row)

    def _render_provider_search_results(self):
        if hasattr(self,'discovery_view'):
            from calibre_plugins.manganana.discovery.canonical_identity import edition_display_label
            records=[]
            for ranked in self._ranked_provider_results():
                primary=dict(ranked.result)
                primary.update(badge=primary.get('badge') or edition_display_label(primary),
                    provider_key=ranked.provider_key,match_tier=int(ranked.match.tier),
                    rank_sort_key=ranked.sort_key,resolution_state='provider_local')
                records.append(primary)
            self._publish_discovery_records(records);return
        super()._render_provider_search_results()
        self._refresh_search_rows()

    def _render_canonical_search_results(self, final=False):
        super()._render_canonical_search_results(final)
        self._refresh_search_rows()

    def _render_fresh_cached_snapshot(self, snapshot):
        if hasattr(self,'discovery_view'):
            from calibre_plugins.manganana.app.main import final_search_records
            records=[]
            for row in final_search_records(snapshot):
                primary=dict(row);primary.update(resolution_state='cached_final',cached_final=True,
                    provider_key=(row.get('source_id'),row.get('id') or row.get('url')))
                records.append(primary)
            self._publish_discovery_records(records);return
        super()._render_fresh_cached_snapshot(snapshot)
        self._refresh_search_rows()

    def _build_hero(self):
        parent_layout = self._source_selected_page.layout()
        parent_layout.itemAt(0).widget().hide()  # Redundant Selected Manga heading.
        parent_layout.removeWidget(self._selected_top_panel)
        self.hero = HeroSurface(self._selected_top_panel)
        self.hero.setFixedHeight(350)
        parent_layout.insertWidget(1, self.hero)
        self._selected_top_panel.layout().setContentsMargins(20, 20, 20, 20)
        self.selected_cover.setFixedSize(204, 286)
        self.selected_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.selected_title.setTextFormat(Qt.TextFormat.PlainText)
        self.selected_synopsis_scroll.setMaximumHeight(100)
        self.selected_synopsis_scroll.setMinimumHeight(60)
        self.selected_synopsis_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.selected_synopsis.setStyleSheet('color:#edf4f8;font-size:13px;background:transparent;')
        self.selected_synopsis.setTextFormat(Qt.TextFormat.PlainText)
        self.selected_synopsis_scroll.setStyleSheet('background:transparent;')
        # Insert native script only from typed native-title evidence.
        text = self._selected_top_panel.layout().itemAt(0).layout().itemAt(1).layout()
        text.setSpacing(7)
        self.native_title = QLabel('')
        self.native_title.setTextFormat(Qt.TextFormat.PlainText)
        self.native_title.setWordWrap(True)
        self.native_title.setStyleSheet('font-size:20px;color:#e0f1f5;')
        text.insertWidget(1, self.native_title)
        self.hero_stats = QWidget()
        stats = QVBoxLayout(self.hero_stats)
        stats.setContentsMargins(0,0,0,0)
        stats.setSpacing(6)
        self.stat_labels = []
        for _ in range(3):
            label = QLabel('—')
            label.setWordWrap(True)
            label.setStyleSheet('background:rgba(5,24,38,205);border:1px solid #2a4858;border-radius:8px;padding:8px;color:#eaf9ff;')
            stats.addWidget(label)
            self.stat_labels.append(label)
        text.addWidget(self.hero_stats)
        self.hero_facts = QLabel('')
        self.hero_facts.setTextFormat(Qt.TextFormat.PlainText)
        self.hero_facts.setWordWrap(True)
        self.hero_facts.setStyleSheet('font-size:13px;color:#c7dbe5;')
        text.removeWidget(self.selected_author)
        text.insertWidget(text.indexOf(self.selected_synopsis_scroll)+1, self.selected_author)
        text.insertWidget(text.indexOf(self.selected_author)+1, self.hero_facts)
        self._hero_text_layout = text
        self._hero_row = self._selected_top_panel.layout().itemAt(0).layout()
        toolbar = QWidget()
        toolbar.setFixedHeight(32)
        controls = QHBoxLayout(toolbar)
        controls.setContentsMargins(0,0,0,0)
        self.animation_rate = QComboBox()
        self.animation_rate.setAccessibleName('Hero animation rate')
        for label, rate in [('Static hero', 0), ('15 FPS', 15), ('20 FPS', 20), ('30 FPS', 30)]:
            self.animation_rate.addItem(label, rate)
        self.animation_rate.currentIndexChanged.connect(self._animation_changed)
        self.render_scale = QComboBox()
        self.render_scale.setAccessibleName('Hero render resolution')
        for scale in (.5, .75, 1.):
            self.render_scale.addItem(f'{scale:g}× render', scale)
        self.render_scale.currentIndexChanged.connect(self._render_scale_changed)
        controls.addStretch(1)
        controls.addWidget(self.animation_rate)
        controls.addWidget(self.render_scale)
        parent_layout.insertWidget(2, toolbar)
        self.render_scale.setCurrentIndex(2)
        self.animation_rate.setCurrentIndex(2)
        self._refresh_hero()

    def _animation_changed(self):
        self.hero.set_animation(self.animation_rate.currentData())
        self._render_scale_changed()

    def _render_scale_changed(self):
        if self.hero.gl:
            self.hero.gl.scale = float(self.render_scale.currentData())
            self.hero.gl.update()

    def _refresh_hero(self):
        if not hasattr(self, 'native_title'):
            return
        metadata = getattr(self, '_immediate_info', None) or self.loaded_metadata or {}
        if not hasattr(getattr(self,'fidelity',None),'synopsis_field'):
            self.selected_synopsis.setText(normalize_description(metadata.get('description') or metadata.get('work_description')))
        native = next((str(row.get('text') or row.get('title') or '')
            for row in metadata.get('titles') or () if isinstance(row, dict)
            and row.get('classification') in ('native', 'japanese_native')), '')
        self.native_title.setText(native)
        self.native_title.setVisible(bool(native))
        set_presentation_style(self.selected_title,'font-size:32px;font-weight:700;color:#ffffff;background:transparent;')
        set_presentation_style(self.selected_author,'font-size:13px;color:#e3eff4;background:transparent;')
        set_presentation_style(self.selected_tags,'font-size:12px;color:#c1d9e6;background:transparent;')
        facts = [(label, metadata.get(key)) for label, key in (('Artist','artist'),('Status','status'),('Release','year')) if metadata.get(key)]
        self.hero_facts.setText('   ·   '.join(f'{label}  {value}' for label, value in facts))
        self.hero_facts.setVisible(bool(facts))
        language = self.language.currentText()
        coverage = getattr(self, 'coverage_presentation', None)
        if coverage is not None:
            coverage.refresh()
        facts = coverage.facts if coverage is not None else None
        if facts is not None and facts.state in ('ready', 'empty'):
            units = 'Downloads found' if facts.mixed_units else 'Volume files found' if facts.packaged else 'Chapters found'
            self._set_hero_stats((f'{len(facts.groups)}\nVolumes found', f'{facts.source_entries}\n{units}', f'{language}\nDownload language'))
        else:
            self._set_hero_stats(('—\nVolumes found', '—\nChapters found', f'{language}\nDownload language'))
        if hasattr(self, 'fidelity'):
            self.fidelity.metadata(metadata)
        if hasattr(self, 'saved_manga'):
            self.saved_manga.update_selected()

    def _set_hero_stats(self, values):
        for label, value in zip(self.stat_labels, values):
            label.setText(value)

    def _set_hero_provider(self, provider_id):
        self._hero_selected_provider = provider_id if provider_id in PROVIDER_PRESETS else None
        if hasattr(self, 'hero'):
            self.hero.set_provider(provider_id)
            self._animation_changed()

    def _set_selected_source_badge(self, source_id='', display_name='', public_url=''):
        super()._set_selected_source_badge(source_id, display_name, public_url)
        if hasattr(self, 'fidelity'):
            from calibre_plugins.manganana.presentation.choose_manga_design import badge_style
            for i in range(self.selected_source_layout.count()):
                badge=self.selected_source_layout.itemAt(i).widget()
                if badge:
                    badge_style(badge,'font-size:12px;padding:3px 7px;')

    def use_search_result(self, item=None):
        item = item or self.search_results.currentItem()
        info = (item.data(Qt.ItemDataRole.UserRole) or {}) if item else {}
        self._hero_requested_provider = info.get('source_id')
        try:
            super().use_search_result(item)
        finally:
            self._hero_requested_provider = None

    def _begin_search_result(self, info):
        # Follow explicit user selection; asynchronous fallback calls do not
        # change this presentation identity or any acquisition controller.
        self._retry_result = dict(info)
        requested = getattr(self, '_hero_requested_provider', None)
        if requested:
            self._set_hero_provider(requested)
        super()._begin_search_result(info)
        if hasattr(self, 'fidelity'):
            self.fidelity.begin(info)
        if hasattr(self, 'saved_manga'):
            self.saved_manga.update_selected()

    def load_metadata(self, url_override=None, source_id=None, discovery_kind=None, prompt_disabled=True):
        direct = discovery_kind == 'direct' or not isinstance(url_override, str)
        if direct and self.workflow_mode in ('volume', 'chapter'):
            from calibre_plugins.manganana.app.main import SOURCE_REGISTRY
            url = (url_override if isinstance(url_override, str) else self.url.text()).strip()
            match = SOURCE_REGISTRY.identify(url)
            source = SOURCE_REGISTRY.get(source_id) if source_id else (match.source if match else None)
            if source and source.parse_manga_ref(url) is not None:
                self._set_hero_provider(source.source_id)
        super().load_metadata(url_override, source_id, discovery_kind, prompt_disabled)
        if hasattr(self, 'fidelity') and self.load_btn.text() == 'Loading...':
            if discovery_kind == 'search' and getattr(self, '_immediate_info', None):
                self.fidelity.begin(self._immediate_info)
            else:
                self.fidelity.set_loading(True)

    def _apply_loaded_manga(self, request_id, data):
        if request_id != self._manga_request_id:
            return  # Preserve the controller's request boundary before touching presentation.
        self._immediate_info = None
        super()._apply_loaded_manga(request_id, data)
        if hasattr(self, 'fidelity'):
            self._refresh_hero()
            if not self.loaded_metadata:
                self.fidelity.set_loading(False)

    def _apply_volume_plan_data(self, data):
        if data.get('request_id') != self._volume_plan_request_id or data.get('language') != self.language.currentData():
            return
        super()._apply_volume_plan_data(data)
        if hasattr(self, 'fidelity') and not self._volume_plan_loading:
            self.fidelity.set_loading(False)

    def _on_volume_plan_failed(self, data):
        current = data.get('request_id') == self._volume_plan_request_id
        super()._on_volume_plan_failed(data)
        if current and hasattr(self, 'fidelity'):
            self.fidelity.set_loading(False)

    def _on_manga_worker_failed(self, data):
        current = data.get('request_id') == self._manga_request_id
        super()._on_manga_worker_failed(data)
        if current and hasattr(self, 'fidelity'):
            self._immediate_info = None
            self.fidelity.set_state('error', str(data.get('error') or data.get('message') or 'Could not load the selected manga. Retry or select another result.'))

    def _refresh_selected_details(self, metadata=None):
        super()._refresh_selected_details(metadata)
        description = normalize_description((metadata or self.loaded_metadata or {}).get('description'))
        self.selected_synopsis.setText(description)
        self._refresh_hero()

    def _clear_selected_details(self):
        super()._clear_selected_details()
        if hasattr(self, 'native_title'):
            self.native_title.clear()
            self.native_title.hide()
            self.hero_facts.clear()
            self._set_hero_stats(('—\nVolumes found', '—\nChapters found', 'Waiting for inventory'))
            if self.selected_title.text() == 'No manga selected':
                self._set_hero_provider(None)

    def _clear_active_provider_selection(self, message='No manga selected'):
        self._inventory_shift_anchor=None
        self._immediate_info = None
        self._retry_result = None
        self._hero_requested_provider = None
        super()._clear_active_provider_selection(message)
        if hasattr(self, 'fidelity'):
            # Reset through the foreground owner so elision's full text, facts,
            # genre chips and selected-only controls agree with the controller.
            self.fidelity.metadata({})
            self.fidelity.set_state('idle')
        self._set_hero_provider(None)
        if hasattr(self, 'saved_manga'):
            self.saved_manga.update_selected()

    def _set_selected_inventory_count(self, count):
        super()._set_selected_inventory_count(count)
        self._refresh_hero()

    def _build_inventory_actions(self):
        header = self.select_all_btn.parentWidget().layout()
        self.select_all_btn.parentWidget().setFixedHeight(40)
        self.inventory_heading.setStyleSheet('font-size:20px;font-weight:600;color:#f1f7fa;')
        self.range_button = QPushButton('Select Range')
        self.range_button.setAutoDefault(False)
        self.range_button.clicked.connect(self._choose_range)
        self.inventory_order = QComboBox()
        self.inventory_order.setAccessibleName('Inventory display order')
        self.inventory_order.addItem('Ascending', False)
        self.inventory_order.addItem('Descending', True)
        self.inventory_order.currentIndexChanged.connect(self._sort_inventory)
        header.insertWidget(header.count()-2, self.range_button)
        header.addWidget(self.inventory_order)

    def _choose_range(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Select numbered volume range')
        layout = QVBoxLayout(dialog)
        note = QLabel('Selects existing numbered volumes only. Clears standalone selection.')
        note.setWordWrap(True)
        layout.addWidget(note)
        first, last = QLineEdit(), QLineEdit()
        first.setPlaceholderText('First volume')
        last.setPlaceholderText('Last volume')
        layout.addWidget(first)
        layout.addWidget(last)
        error = QLabel('')
        layout.addWidget(error)
        apply = QPushButton('Select Range')
        layout.addWidget(apply)
        def select():
            try:
                low, high = float(first.text()), float(last.text())
                if low > high or not any(low <= v <= high for v in self._available_volume_values()):
                    raise ValueError('No existing volumes in that range')
            except ValueError as exc:
                error.setText(str(exc) or 'Enter numeric volume values')
                return
            self.start.setText(first.text())
            self.end.setText(last.text())
            self._range_inputs_changed()
            dialog.accept()
        apply.clicked.connect(select)
        dialog.exec()

    def _arrange_inventory(self, items=None):
        if not hasattr(self, 'range_button'):
            return
        # Materialization owns only new rows, never the mode or hero layout.
        local = items is not None
        horizontal = self.workflow_mode in ('volume','chapter')
        self.volume_list.setFlow(QListView.Flow.LeftToRight if horizontal else QListView.Flow.TopToBottom)
        self.volume_list.setWrapping(False)
        self.volume_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.volume_list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.volume_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn if horizontal else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.volume_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if horizontal else Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        if not hasattr(self,'fidelity'):self.volume_list.setFixedHeight(242 if horizontal else 285)
        self.range_button.setVisible(self.workflow_mode=='volume')
        self.range_button.setEnabled(bool(self._available_volume_values()) and self._download_language_valid)
        self.inventory_order.hide()
        groups = {float(group['volume']): group for group in (self._current_plan or {}).get('volume_groups') or ()
                  if group.get('kind') == 'volume' and group.get('volume') is not None}
        if not groups and self.workflow_mode == 'volume':
            for chapter in self._volume_acquisition_items or ():
                if chapter.get('volume') is not None:
                    try:
                        groups.setdefault(float(chapter['volume']), {'chapters': []})['chapters'].append(chapter)
                    except (TypeError, ValueError):
                        pass
        for item in (items if local else (self.volume_list.item(i) for i in range(self.volume_list.count()))):
            row = self.volume_list.itemWidget(item)
            if not isinstance(row, VolumeRowWidget) or not horizontal:
                continue
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            item.setSizeHint(getattr(getattr(self,'fidelity',None),'tile_size',QSize(132,224)))
            row.setObjectName('reviewVolumeRow')
            row.layout().setDirection(QBoxLayout.Direction.TopToBottom)
            row.layout().setSpacing(4)
            row.layout().setContentsMargins(8, 6, 8, 6)
            if not hasattr(self,'fidelity'):row.cover.setFixedSize(108,150)
            if not hasattr(row, 'cover_host'):
                row.layout().removeWidget(row.cover)
                row.layout().removeWidget(row.pick)
                row.cover_host = QWidget()
                overlay = QGridLayout(row.cover_host)
                overlay.setContentsMargins(0,0,0,0)
                overlay.addWidget(row.cover,0,0,Qt.AlignmentFlag.AlignCenter)
                overlay.addWidget(row.pick,0,0,Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                row.layout().insertWidget(0,row.cover_host)
                # A late-created card is already visible when its cover is
                # reparented. The new container must enter the shown layout.
                row.cover_host.show()
            row.layout().setAlignment(row.cover, Qt.AlignmentFlag.AlignCenter)
            set_presentation_style(row.title,'font-size:14px;font-weight:600;' if hasattr(self,'fidelity') else 'font-size:12px;color:#edf9ff;font-weight:600;')
            row.title.setWordWrap(True)
            # Keep round native selection controls and exact stable UserRole key.
            row.pick.setAccessibleName('Select ' + row.title.text())
            for child in row.findChildren(QLabel):
                child.setTextFormat(Qt.TextFormat.PlainText)
            if not hasattr(row, 'membership'):
                row.membership = QLabel()
                set_presentation_style(row.membership,'font-size:12px;color:#c3cedd;' if hasattr(self,'fidelity') else 'font-size:11px;color:#9ebccb;')
                row.membership.setWordWrap(True)
                row.layout().insertWidget(2, row.membership)
            if data.get('kind') == 'volume':
                from calibre_plugins.manganana.publication.inventory_coverage import chapter_range_text
                from calibre_plugins.manganana.presentation.choose_manga_reference import ElidedField
                group = data.get('group') or groups.get(float(data['volume'])) or {}
                caption = chapter_range_text(group.get('chapters'))
                if not hasattr(row, '_chapter_range_field'):
                    row._chapter_range_field = ElidedField(row.membership)
                row._chapter_range_field.set_text(caption)
                row.membership.setVisible(bool(caption))
                row.setToolTip(caption or 'View chapter information in Coverage details.')
            elif data.get('kind') == 'chapter':
                chapter=data.get('chapter') or {}
                row.membership.show()
                row.membership.setText('Volume '+str(chapter['volume']) if chapter.get('volume') is not None else '')
            else:
                row.title.setText('Other chapters')
                row.membership.show()
                row.membership.setText('Available')
                row.setToolTip('These chapters are available separately because their volume assignment is uncertain. They are not missing chapters.')
            # Provider badges remain accessible in provenance/tooltip; avoid
            # forcing a full-width provider pill into a narrow carousel tile.
            for child in row.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                if child.__class__.__name__ == 'ProviderBadgeWidget':
                    child.hide()
        if not local:
            self._sort_inventory()
            self._refresh_hero()
        if hasattr(self, 'fidelity'):
            self.fidelity.inventory(items=items)
        scaling=getattr(self,'interface_scaling',None)
        if scaling is not None:
            for item in (items if local else (self.volume_list.item(i) for i in range(self.volume_list.count()))):
                row=self.volume_list.itemWidget(item)
                if row is not None:scaling.apply_tree(row)

    def _sort_inventory(self, *_args):
        if not hasattr(self, 'inventory_order') or self.workflow_mode != 'volume':
            return
        for index in range(self.volume_list.count()):
            item = self.volume_list.item(index)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            if data.get('kind') not in ('volume', 'standalone'):
                return  # Preserve the controller's loading/error message verbatim.
            item.setData(Qt.ItemDataRole.AccessibleTextRole, 'Standalone chapters' if data['kind']=='standalone' else f"Volume {data['volume']:g}")
            item.setData(Qt.ItemDataRole.DisplayRole, f"{float(data['volume']):030.9f}" if data.get('kind') == 'volume' else 'z')
        self.volume_list.sortItems(Qt.SortOrder.DescendingOrder if self.inventory_order.currentData() else Qt.SortOrder.AscendingOrder)
        if hasattr(self,'_chapter_card_timer') and not self._closing:
            self._chapter_card_timer.start(0)

    def _rebuild_volume_list(self):
        self._chapter_card_items=set()
        super()._rebuild_volume_list()
        if self.workflow_mode in ('volume','chapter') and self.volume_list.count():
            # Keep every exact acquisition row in the existing Qt item model;
            # only the few viewport cards need child widgets and styles.
            size=getattr(getattr(self,'fidelity',None),'tile_size',QSize(132,224))
            for i in range(self.volume_list.count()):self.volume_list.item(i).setSizeHint(size)
            self._sort_inventory()
            self._materialize_chapter_cards(arrange=False)
        self._arrange_inventory()

    def _create_volume_card(self,item):
        row=super()._create_volume_card(item)
        if row is not None:row._inventory_model_index=QPersistentModelIndex(self.volume_list.indexFromItem(item))
        return row

    def _create_chapter_card(self,item):
        row=super()._create_chapter_card(item)
        if row is not None:row._inventory_model_index=QPersistentModelIndex(self.volume_list.indexFromItem(item))
        return row

    def _live_inventory_items(self):
        """Validate Qt-owned card indices after sorting, removal and deletion."""
        result=[]
        for row in self.volume_list.viewport().findChildren(VolumeRowWidget,options=Qt.FindChildOption.FindDirectChildrenOnly):
            index=getattr(row,'_inventory_model_index',None)
            if index is None or not index.isValid():continue
            item=self.volume_list.item(index.row())
            if item is not None and self.volume_list.itemWidget(item) is row:result.append(item)
        return result

    def _restyle_inventory_rows(self):
        if not getattr(self,'_viewport_volume_cards',False):return super()._restyle_inventory_rows()
        syncing=self._volume_check_syncing;updates=self.volume_list.updatesEnabled()
        self._volume_check_syncing=True;self.volume_list.setUpdatesEnabled(False)
        try:
            for item in self._live_inventory_items():self._style_volume_item(item)
        finally:
            self.volume_list.setUpdatesEnabled(updates);self._volume_check_syncing=syncing
        self.volume_list.viewport().update()

    def _materialize_chapter_cards(self,arrange=True):
        if self._closing or self.workflow_mode not in ('volume','chapter'):return
        # Provisional model records remain available to the controller. The
        # dedicated loading page hides this strip until publication settles;
        # creating its QWidget cards now only tears them down a moment later.
        if self.workflow_mode=='volume' and self._volume_resolution_pending():return
        if self.workflow_mode=='chapter' and not self.workflow_state.chapter_presentation_frozen:return
        wanted=set(self._visible_row_range(self.volume_list,72,2))
        # Sorting moves item widgets with their exact model records. Recompute
        # ownership rather than reusing stale viewport indices.
        existing={self.volume_list.row(item) for item in self._live_inventory_items()}
        for i in existing-wanted:
            item=self.volume_list.item(i)
            if item is not None:self.volume_list.removeItemWidget(item)
        created=[]
        missing=sorted(wanted-existing)
        for offset,i in enumerate(missing):
            item=self.volume_list.item(i)
            if item is not None:
                kind=(item.data(256) or {}).get('kind')
                if kind=='chapter':self._create_chapter_card(item)
                elif kind in ('volume','standalone'):self._create_volume_card(item)
                created.append(item)
            # Styling and layout of eleven new Qt cards used to occupy one
            # long GUI turn on warm revisits. Yield between small groups; the
            # complete item model/selection remains authoritative throughout.
            if len(created)==3:
                if offset+1<len(missing):self._chapter_card_timer.start(0)
                break
        self._chapter_card_items=wanted
        if arrange and wanted!=existing:
            if created:self._arrange_inventory(items=created)
            self._load_visible_volume_thumbs()

    def _set_workflow_mode(self, mode):
        if mode != getattr(self,'workflow_mode',None):self._inventory_shift_anchor=None
        if (mode != getattr(self,'workflow_mode',None) and not (
                mode in ('volume','chapter') and getattr(self,'workflow_mode',None) in ('volume','chapter')
                and self.workflow_state.selected_provider_record)):
            self._immediate_info = None
            if hasattr(self, 'fidelity'):
                self.fidelity.set_loading(False)
            self._set_hero_provider(None)
        super()._set_workflow_mode(mode)
        self._arrange_inventory()
        if mode in ('volume','chapter','import') and self.workflow_mode==mode:
            from calibre_plugins.manganana.app.main import prefs
            prefs['acquisition_mode']=mode
        if hasattr(self,'fidelity'):
            self.fidelity.mode()
        if hasattr(self,'saved_manga'):
            self.saved_manga.update_selected()
        if hasattr(self,'recent_searches'):self.recent_searches.sync()

    def _set_edition_badge(self,text=None):
        super()._set_edition_badge(text)
        from calibre_plugins.manganana.presentation.choose_manga_design import neutral_edition
        from calibre_plugins.manganana.app.main import ProviderBadgeWidget
        if hasattr(self,'edition_badge_host'):
            for badge in self.edition_badge_host.findChildren(ProviderBadgeWidget):neutral_edition(badge)

    def _visible_row_range(self,widget,row_height,buffer_rows=3):
        if widget is getattr(self,'volume_list',None) and self.workflow_mode in ('volume','chapter'):
            width=getattr(getattr(self,'fidelity',None),'tile_size',QSize(132,224)).width()
            visible=widget.viewport().rect().adjusted(-width*buffer_rows,0,width*buffer_rows,0)
            count=widget.count()
            if not count:return range(0)
            first=widget.visualItemRect(widget.item(0));last=widget.visualItemRect(widget.item(count-1))
            if first.isValid() and last.isValid():
                forward=first.center().x()<=last.center().x()
                left,right=(visible.left(),visible.right())if forward else(-visible.right(),-visible.left())
                def bounds(index):
                    rect=widget.visualItemRect(widget.item(index))
                    return (rect.left(),rect.right())if forward else(-rect.right(),-rect.left())
                lo,hi=0,count
                while lo<hi:
                    mid=(lo+hi)//2
                    if bounds(mid)[1]<left:lo=mid+1
                    else:hi=mid
                start=lo;hi=count
                while lo<hi:
                    mid=(lo+hi)//2
                    if bounds(mid)[0]<=right:lo=mid+1
                    else:hi=mid
                if start<lo:return range(start,lo)
                return range(min(count,5))
            # Loading/empty layouts can lack valid geometry for binary search.
            indices=[i for i in range(count)if widget.visualItemRect(widget.item(i)).intersects(visible)]
            return range(min(indices),max(indices)+1)if indices else range(min(count,5))
        return super()._visible_row_range(widget,row_height,buffer_rows)

    def _pix_for_url(self,url,w,h):
        # Resolve controller thumbnail sizes against the current cover viewport.
        if not hasattr(self,'fidelity'):return super()._pix_for_url(url,w,h)
        if (w,h)==(42,58):w,h=self.fidelity.cover_size
        elif (w,h)==(150,210):w,h=self.selected_cover.width(),self.selected_cover.height()
        ratio=self.devicePixelRatioF()
        key=(str(url or ''),int(w),int(h),'cover-fill',ratio)
        if key not in self._scaled_pixmap_cache:
            raw=self._image_cache.get(str(url or ''))
            if not raw:return None
            image=self._decoded_cover_images.get(str(url or ''))
            pix=self._cover_pixmap(raw,w,h,ratio,image=image)
            if pix is None:return None
            self._scaled_pixmap_cache[key]=pix
            return pix
        return self._scaled_pixmap_cache[key]

    def _cover_pixmap(self,raw,w,h,ratio,image=None):
        from qt.core import QPixmap
        pix=QPixmap.fromImage(image)if image is not None else QPixmap()
        if image is None:pix.loadFromData(raw)
        pw,ph=max(1,round(w*ratio)),max(1,round(h*ratio))
        if pix.isNull():pix=self._pix_from_bytes(raw,pw*2,ph*2)
        if pix is None or pix.isNull():return None
        pix=pix.scaled(pw,ph,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation)
        pix=pix.copy((pix.width()-pw)//2,(pix.height()-ph)//2,pw,ph)
        pix.setDevicePixelRatio(ratio)
        return pix

    def _search_pixmap(self,url):
        raw=self._search_image_cache.get(url)
        if not raw:return None
        self._search_image_cache.move_to_end(url)
        key=(url,self.devicePixelRatioF())
        if key not in self._search_scaled_pixmaps:
            pix=self._cover_pixmap(raw,36,50,key[1])
            if pix is None:return None
            self._search_scaled_pixmaps[key]=pix
        self._search_scaled_pixmaps.move_to_end(key)
        while len(self._search_scaled_pixmaps)>256:self._search_scaled_pixmaps.popitem(last=False)
        return self._search_scaled_pixmaps[key]

    def _show_volume_acquisition_loading(self):
        super()._show_volume_acquisition_loading()
        if hasattr(self, 'fidelity'):
            self.fidelity.set_loading(True)

    def _load_volume_plan(self, force=False):
        if hasattr(self,'fidelity') and self.loaded_metadata:
            self.fidelity.set_state('loading')
        super()._load_volume_plan(force=force)
        if hasattr(self,'fidelity'):self.fidelity.sync_inventory()

    def _set_chapter_preparing(self, message):
        super()._set_chapter_preparing(message)
        if hasattr(self,'fidelity'):self.fidelity.set_state('loading',message)

    def _apply_volume_plan(self, request_id, language, plan, announce_ready=True):
        if request_id != self._volume_plan_request_id or language != self.language.currentData():return
        super()._apply_volume_plan(request_id,language,plan,announce_ready)
        if hasattr(self,'fidelity'):self.fidelity.sync_inventory()

    def _try_finalize_chapter_projection(self, prepared_projection=None):
        result=super()._try_finalize_chapter_projection(prepared_projection)
        if hasattr(self,'fidelity'):self.fidelity.sync_inventory()
        return result

    def _update_workflow_actions(self):
        super()._update_workflow_actions()
        if hasattr(self,'fidelity') and self.workflow_state.stage=='choose_manga':
            if self.workflow_mode=='import':self.fidelity.import_details()
            else:self.fidelity.sync_inventory()

    def _retry_inventory(self):
        # Reuse controller entry points, including their ownership and cache guards.
        if self.workflow_mode not in ('volume','chapter'):return
        if self.loaded_metadata:self._load_volume_plan(force=True)
        elif getattr(self,'_retry_result',None):
            self._hero_requested_provider=self._retry_result.get('source_id')
            try:self._begin_search_result(self._retry_result)
            finally:self._hero_requested_provider=None
        else:self.load_metadata()

    def _sync_import_mode(self):
        super()._sync_import_mode()
        if hasattr(self,"fidelity"):self.fidelity.mode()



    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'hero') and self.hero.gl:
            self.hero.gl.sync_timer()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self,'fidelity'):self._layout_hero()

    def _layout_hero(self):
        if hasattr(self, 'fidelity'):
            self.fidelity.resize()
            return
        if hasattr(self, '_hero_row') and not self._closing:
            wide = self.hero.width() >= 800
            if wide != getattr(self, '_hero_wide', None):
                self._hero_wide = wide
                self._hero_text_layout.removeWidget(self.hero_stats)
                self._hero_row.removeWidget(self.hero_stats)
                self.hero_stats.setMaximumWidth(155 if wide else 16777215)
                self.hero_stats.setMinimumWidth(145 if wide else 0)
                if wide:
                    self._hero_row.addWidget(self.hero_stats, 0, Qt.AlignmentFlag.AlignVCenter)
                else:
                    self._hero_text_layout.addWidget(self.hero_stats)
                self.selected_cover.setFixedSize(204 if wide else 120, 286 if wide else 168)
                self.hero.setFixedHeight(350 if wide else 520)
                self._refresh_hero()

    def eventFilter(self, watched, event):
        if not self._ui_input_active:
            return False
        if (hasattr(self, 'fidelity') and watched is self.show_more_btn
                and event.type() in (QEvent.Type.Show, QEvent.Type.Hide)):
            QTimer.singleShot(0, self._sync_discovery_footer)
        if (hasattr(self,'fidelity') and event.type()==QEvent.Type.Resize
                and watched in (self.anka_shell.workspace.viewport(),self.fidelity.right_workspace)):
            self._layout_hero()
        if (watched is getattr(self, 'volume_list', None) and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Space and self.volume_list.isEnabled()):
            item = self.volume_list.currentItem()
            row = self.volume_list.itemWidget(item) if item is not None else None
            if isinstance(row, VolumeRowWidget):
                row._selection_modifiers=event.modifiers()
                row.pick.click()
                return True
        return super().eventFilter(watched, event)

    def reject(self):
        self._detach_ui_input()
        if hasattr(self, 'hero'):
            self.hero.cleanup()
        super().reject()

    def closeEvent(self, event):
        self._detach_ui_input()
        if hasattr(self, 'hero'):
            self.hero.cleanup()
        super().closeEvent(event)
