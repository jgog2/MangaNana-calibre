"""Reference foreground composition over the unchanged animated hero.

The existing fidelity layer owns all state, controller bindings and interactions.
This layer supplies geometry and presentation only; no shader or data authority.
"""
from qt.core import (Qt, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QSize, QSizePolicy, QFontMetrics, QStyle, QStyleOptionButton, QObject, QEvent)
from calibre_plugins.manganana.presentation.choose_manga_design import (
    FidelityLayout,
    badge_style,
    neutral_edition,
    TILE_STYLE,
    PICK_STYLE,
)
from calibre_plugins.manganana.presentation.mangaanka_presentation import UI_ACCENT
from calibre_plugins.manganana.presentation.interface_scale import set_presentation_style


def accent_style(style):
    for old in ('#20d4bd','#21d7d0','#21d7c3','#18dce2','#30d8cf'):
        style=style.replace(old,UI_ACCENT)
    return style.replace('#10303b','#102b49').replace('#08211e','#ffffff').replace('#03100f','#ffffff').replace('#6eeee0','#57a8ff').replace('#63eee0','#57a8ff')


def discovery_heading_margins(height, readable=True):
    if height<680:return (12,12,18,12)
    return (24,18,18,18)if readable else(24,30,18,22)


class ElidedField(QObject):
    """Recalculate plain-text elision after Qt assigns the final label width."""
    def __init__(self, label):
        super().__init__(label)
        self.label, self.text = label, ''
        label.installEventFilter(self)

    def set_text(self, text):
        self.text = text
        self.label.setToolTip(text)
        self.elide()

    def elide(self):
        self.label.setText(QFontMetrics(self.label.font()).elidedText(
            self.text, Qt.TextElideMode.ElideRight, self.label.contentsRect().width()))

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.FontChange):
            self.elide()
        return False


class ReferenceFidelityLayout(FidelityLayout):
    def __init__(self, dialog):
        super().__init__(dialog)
        dialog.header.name_label.setText('Manga<span style="color:'+UI_ACCENT+';">Ankā</span>')
        dialog.header.stepper.layout().setSpacing(2)
        dialog.header.stepper.setObjectName('referenceStepper')
        dialog.header.stepper.setStyleSheet('QWidget#referenceStepper {background:#1b2736;border-radius:18px;}')
        dialog.header.grid.setContentsMargins(14,7,14,7)
        dialog.header.icon_label.setFixedSize(36,36)
        dialog.header.icon_label.setPixmap(dialog.header.app_icon.pixmap(36,36))
        self.status_dot=QLabel('●');self.status_dot.setAccessibleName('Workflow activity indicator')
        self.status_dot.setStyleSheet('color:#18c98a;font-size:15px;')
        bar=dialog.log_toggle_btn.parentWidget().layout()
        bar.insertWidget(1,self.status_dot)
        dialog.discovery_splitter.setSizes([round(dialog.width()*.245),round(dialog.width()*.755)])

    @staticmethod
    def presentation_style():
        return accent_style(FidelityLayout.presentation_style())+'''
QPushButton {border-radius:9px;padding:6px 12px;}
QFrame#ankaHeader {background:#111a25;}
QFrame#ankaFooter {background:#111a25;}
QLabel#ankaStep {font-size:13px;padding:8px 18px;border-radius:17px;}
QLabel#ankaStep[active="true"] {background:ACCENT;border:1px solid #4b9dff;border-radius:17px;}
QFrame#acquisitionSegments {background:#1b2530;border:1px solid #354151;border-radius:11px;}
QPushButton#modeChoice {font-size:13px;padding:7px 6px;border-radius:9px;}
QPushButton#modeChoice:checked {background:ACCENT;color:white;border-color:#4b9dff;}
QPushButton#primaryAction {background:ACCENT;color:white;border:1px solid #4b9dff;}
QPushButton#primaryAction:disabled {background:#18344f;color:#8b9bae;border-color:#354151;}
QPushButton#heroDetails {background:ACCENT;color:white;border:1px solid #4b9dff;font-size:13px;}
QWidget#heroStatistics {background:rgba(14,20,28,165);border:1px solid rgba(165,180,195,100);border-radius:12px;}
QWidget#heroStatistics QLabel {background:transparent;border:0;border-radius:0;padding:10px;font-size:13px;}
QLabel#genreChip {background:rgba(45,52,61,190);border:1px solid #58616d;border-radius:9px;padding:4px 9px;font-size:12px;}
'''.replace('ACCENT',UI_ACCENT)

    def _discovery(self):
        super()._discovery()
        self.search_pane.layout().setContentsMargins(10,14,10,0)
        self.d.search_results_label.setStyleSheet('font-size:14px;font-weight:600;')
        self.results_count.setStyleSheet('font-size:12px;color:#bbc4d1;')
        self.d.search_box.setPlaceholderText('Search manga')

    def _hero(self):
        super()._hero()
        d=self.d
        old=d._hero_text_layout
        badges=None
        while old.count():
            entry=old.takeAt(0)
            if entry.layout() is not None and entry.layout().indexOf(d.selected_source_host)>=0:
                badges=entry.layout();badges.setParent(None)
        d._hero_row.removeItem(old);old.setParent(None);old.deleteLater()
        self.hero_body=QWidget();root=QVBoxLayout(self.hero_body)
        root.setContentsMargins(0,0,0,0);root.setSpacing(7)
        d._hero_row.addWidget(self.hero_body,1)
        d._hero_row.setAlignment(d.selected_cover,Qt.AlignmentFlag.AlignTop)
        root.addWidget(d.selected_title);root.addWidget(d.native_title);root.addWidget(d.selected_rating)
        self.empty_instruction=QLabel('Search your enabled manga sources, or use Import for local CBZ and PDF books.')
        self.empty_instruction.setWordWrap(True);root.addWidget(self.empty_instruction)
        self.hero_lower=QWidget();columns=QHBoxLayout(self.hero_lower)
        columns.setContentsMargins(0,0,0,0);columns.setSpacing(18)
        self.hero_copy=QWidget();copy=QVBoxLayout(self.hero_copy)
        copy.setContentsMargins(0,0,0,0);copy.setSpacing(9)
        if badges is not None:copy.addLayout(badges)
        copy.addWidget(d.selected_synopsis_scroll)
        copy.addWidget(self.facts)
        copy.addWidget(self.details_button,0,Qt.AlignmentFlag.AlignLeft)
        copy.addStretch(1)
        columns.addWidget(self.hero_copy,1);columns.addWidget(d.hero_stats,0,Qt.AlignmentFlag.AlignTop)
        root.addWidget(self.hero_lower,1)
        d._hero_text_layout=root
        d.selected_cover.setStyleSheet('background:transparent;border:0;border-radius:4px;')
        d.selected_synopsis.setContentsMargins(0,0,4,0)
        d.selected_synopsis.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        d.selected_rating.setStyleSheet('color:#ffb720;font-size:17px;font-weight:600;')
        d.hero_stats.setObjectName('heroStatistics')
        d.hero_stats.layout().setSpacing(0)
        for label in d.stat_labels:label.setStyleSheet('background:transparent;border:0;padding:10px;font-size:13px;')
        self.details_button.setObjectName('heroDetails')
        self.details_button.setText('Full synopsis and details…   ›')
        self.genre_host=QWidget();self.genre_row=QHBoxLayout(self.genre_host)
        self.genre_row.setContentsMargins(0,0,0,0);self.genre_row.setSpacing(6)
        self.genre_heading=QLabel('Genres');self.genre_heading.setStyleSheet('font-size:12px;color:#aeb8c7;')
        self.facts.layout().addWidget(self.genre_heading,0,3)
        self.facts.layout().addWidget(self.genre_host,1,3)
        self.facts.layout().setContentsMargins(0,2,0,0)
        self.facts.layout().setHorizontalSpacing(18)
        for label in self.facts.findChildren(QLabel):
            label.setWordWrap(False);label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
            label.setStyleSheet('font-size:13px;color:#dce1e9;')
        self.fact_fields = [ElidedField(label) for label in self.fact_values]
        self.title_field = ElidedField(d.selected_title)
        self.native_field = ElidedField(d.native_title)

    def _footer(self):
        super()._footer()
        self.d.footer.stack.setContentsMargins(12,8,12,8)
        self.d.log_toggle_btn.setText('Activity Log  ›')

    def results(self):
        super().results()
        from calibre_plugins.manganana.app.main import ProviderBadgeWidget
        d=self.d
        d.search_results_label.setText('Search Results')
        for i in range(d.search_results.count()):
            item=d.search_results.item(i);row=d.search_results.itemWidget(item)
            if row is None:continue
            item.setSizeHint(QSize(0,60));row.setMinimumHeight(58)
            row.cover.setFixedSize(36,50)
            row.title_label.setStyleSheet('font-size:13px;font-weight:400;')
            row.title_label.setMaximumWidth(QFontMetrics(row.title_label.font()).horizontalAdvance(row._base_title)+2)
            row._result_title.elide()
            row.details.setContentsMargins(0,14 if not row.count_line.isHidden() else 0,0,0)
            row.setStyleSheet('QFrame#reviewResultRow {background:transparent;border:0;border-bottom:1px solid #293440;border-radius:0;} QFrame#reviewResultRow:hover {background:#1e2a38;} QFrame#reviewResultRow[selected="true"] {background:#104b9e;border:1px solid #2669bc;border-radius:10px;}')
            for badge in row.findChildren(ProviderBadgeWidget):
                neutral_edition(badge);badge_style(badge,'font-size:10px;padding:1px 4px;min-height:13px;')

    def metadata(self, md):
        d=self.d
        self._typography()
        for field,key in zip(self.fact_fields,('author','status','year')):
            value=str(md.get(key) or '')
            if key=='author' and md.get('artist') and md['artist']!=md.get('author'):value+=' / '+str(md['artist'])
            field.set_text(value or '—')
        native = next((str(row.get('text') or row.get('title') or '')
            for row in md.get('titles') or () if isinstance(row, dict)
            and row.get('classification') in ('native', 'japanese_native')), '')
        self.native_field.set_text(native)
        tags=[str(tag) for tag in md.get('tags') or ()]
        limit=2 if d._source_selected_page.width()<1100 else 3
        genre_key=(tuple(tags),limit)
        if hasattr(self.genre_host,'set_tags'):
            self.genre_host.set_tags(tags)
        elif genre_key!=getattr(self,'_genre_key',None):
            self._genre_key=genre_key
            while self.genre_row.count():
                item=self.genre_row.takeAt(0)
                if item.widget():item.widget().deleteLater()
            for tag in tags[:limit]+(['+'+str(len(tags)-limit)] if len(tags)>limit else []):
                label=QLabel(tag);label.setObjectName('genreChip');label.setToolTip(', '.join(tags))
                label.setTextFormat(Qt.TextFormat.PlainText)
                self.genre_row.addWidget(label)
        self.genre_heading.setVisible(bool(tags));self.genre_host.setVisible(bool(tags))
        from calibre_plugins.manganana.providers.provider_branding import format_rating_label
        if md.get('rating_display'):
            d.selected_rating.setText(format_rating_label(md['rating_display']));d.selected_rating.show()
        d.selected_author.hide();d.selected_tags.hide();d.hero_facts.hide();d.selected_aliases.hide()
        self.empty_state(md)

    def empty_state(self, md):
        d=self.d;selected=bool(md)
        title=str(md.get('title') or 'Untitled') if selected else 'Search'
        d.selected_title.setWordWrap(False)
        self.title_field.set_text(title)
        self.empty_instruction.hide()
        for widget in (d.selected_cover,d.selected_source_host,d.edition_badge_host,d.hero_stats,self.facts,self.details_button):widget.setVisible(selected)
        d.native_title.setVisible(selected and bool(d.native_title.text()))
        synopsis=getattr(self,'synopsis_field',None)
        d.selected_synopsis_scroll.setVisible(selected and bool(synopsis.text if synopsis else d.selected_synopsis.text()))
        d.selected_tags.hide();d.selected_author.hide();d.hero_facts.hide();d.selected_aliases.hide();d.selected_inventory_summary.hide()
        if not selected:d.selected_rating.hide()

    def inventory(self):
        # Retain existing selection hooks, stable keys, membership and retry state.
        super().inventory()
        d=self.d
        available=d.anka_shell.workspace.viewport().height()-d.hero.height()-self.inventory_header_host.height()-20
        d.volume_list.setSpacing(5)
        width=max(110,min(174,round((d._source_selected_page.width()-120)/6-12)))
        cover_height=max(76,min(218,round((width-16)*1.4),available-86))
        cover_width=round(cover_height/1.4)
        self.cover_size=(cover_width,cover_height);self.tile_size=QSize(max(110,cover_width+16),cover_height+54)
        strip=self.tile_size.height()+30
        d.volume_list.setFixedHeight(strip);self.skeleton.setFixedHeight(strip)
        d.inventory_stack_host.setFixedHeight(strip+10)
        for tile in self.skeleton.tiles:
            tile.setFixedSize(self.tile_size);tile.cover.setFixedSize(*self.cover_size)
            tile.layout().setContentsMargins(8,6,8,6)
        from calibre_plugins.manganana.app.main import VolumeRowWidget
        for i in range(d.volume_list.count()):
            item=d.volume_list.item(i);row=d.volume_list.itemWidget(item)
            if not isinstance(row,VolumeRowWidget):continue
            item.setSizeHint(self.tile_size);row.setFixedSize(self.tile_size)
            row.layout().setContentsMargins(7,6,7,6);row.layout().setSpacing(3)
            row.cover.setFixedSize(*self.cover_size);row.cover_host.setFixedHeight(cover_height)
            row.title.setStyleSheet('font-size:14px;font-weight:600;');row.membership.setStyleSheet('font-size:12px;color:#c3cedd;')
            url=(item.data(Qt.ItemDataRole.UserRole) or {}).get('cover_url')
            if url and url in d._image_cache:
                pix=d._pix_for_url(url,*self.cover_size)
                if pix is not None:row.set_cover(pix)
            row._fidelity_cover_size=self.cover_size;self.restyle_tile(row)

    def restyle_tile(self,row):
        row.setStyleSheet(accent_style(TILE_STYLE));row.pick.setStyleSheet(accent_style(PICK_STYLE))
        row.style().unpolish(row);row.style().polish(row)

    def resize(self):
        d=self.d
        if not hasattr(d,'inventory_stack') or getattr(self,'_arranging',False):return
        if d.workflow_state.stage!='choose_manga':return
        viewport=d.anka_shell.workspace.viewport()
        coverage=getattr(d,'coverage_presentation',None)
        coverage_height=(coverage.host.sizeHint().height()
            if coverage is not None and coverage.host.isVisible() else 0)
        key=(viewport.width(),viewport.height(),self.right_workspace.width(),
            d.width(),d.height(),d.property('interfaceScaleFactor'),coverage_height)
        if key==getattr(self,'_layout_key',None):return
        self._layout_key=key
        self._arranging=True
        try:
            self._resize_discovery()
        finally:
            self._arranging=False

    def _typography(self):
        d=self.d
        for widget,style in ((d.selected_title,'font-size:32px;font-weight:700;color:#ffffff;background:transparent;'),
                (d.native_title,'font-size:18px;color:#e1e5eb;'),
                (d.selected_synopsis,'font-size:15px;color:#edf5f3;background:transparent;'),
                (d.inventory_heading,'font-size:23px;font-weight:600;')):
            set_presentation_style(widget,style)
        if hasattr(self,'import_heading'):
            set_presentation_style(self.import_heading,'font-size:32px;font-weight:700;color:#ffffff;background:transparent;')
            # The bookmark title row owns Search's single-line height. Match
            # that font metric instead of Import's text-dependent QLabel hint.
            margins=d.selected_title.contentsMargins()
            self.import_heading.setFixedHeight(d.selected_title.fontMetrics().height()+margins.top()+margins.bottom())

    def _resize_discovery(self):
        d=self.d
        option=QStyleOptionButton();d.search_btn.initStyleOption(option)
        content=QSize(option.fontMetrics.horizontalAdvance(d.search_btn.text()),option.fontMetrics.height())
        required=QSize()
        for focus in (False,True):
            option.state &= ~QStyle.StateFlag.State_HasFocus
            if focus:option.state |= QStyle.StateFlag.State_HasFocus
            required=required.expandedTo(d.search_btn.style().sizeFromContents(QStyle.ContentsType.CT_PushButton,option,content,d.search_btn))
        d.search_btn.setMinimumSize(required)
        target=d.anka_shell.workspace.viewport().size()
        # QScrollArea already expands its resizable page to the viewport.
        # Feeding the previous viewport height back as a page minimum makes
        # scrollbar visibility depend on the direction of the last resize.
        d._choose_stage_panel.setMinimumHeight(0)
        d.anka_shell.workspace.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # QSplitter owns the user's sidebar width. Reassigning proportions on
        # shrink, but not expansion, made a resize round trip change that width.
        dense=d.height()<680
        readable=hasattr(self,'synopsis_field')
        hero_height=max(260,min(460,round(target.height()*.54))) if readable else max(170,min(440,round(target.height()*.51)))
        d.hero.setFixedHeight(hero_height)
        if readable:
            scale=float(d.property('interfaceScaleFactor')or 1.)
            self.facts.setMinimumHeight(max(round(66*scale),self.facts.minimumSizeHint().height()))
            cover_height=max(104,min(310,hero_height-self.facts.minimumHeight()-12-(24 if dense else 36)))
        else:
            cover_height=max(104,min(310,round(hero_height*.76)))
        d.selected_cover.setFixedSize(round(cover_height*5/7),cover_height)
        self._typography()
        d.selected_title.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        d.native_title.setWordWrap(False);d.native_title.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        d.selected_synopsis_scroll.setMinimumHeight(0 if readable else 38 if dense else 58)
        d.selected_synopsis_scroll.setMaximumHeight(16777215 if readable else 38 if dense else 100)
        d._hero_row.setSpacing(24 if not dense else 12)
        heading_margins=discovery_heading_margins(d.height(),readable)
        d._selected_top_panel.layout().setContentsMargins(*heading_margins)
        if hasattr(self,'import_details_page'):
            self.import_details_page.layout().setContentsMargins(*heading_margins)
        stacked=d._source_selected_page.width()<800
        self.hero_lower.layout().setDirection(QHBoxLayout.Direction.TopToBottom if stacked else QHBoxLayout.Direction.LeftToRight)
        d.hero_stats.setMinimumWidth(0 if stacked else 162)
        d.hero_stats.setMaximumWidth(16777215 if stacked else 174)
        d.hero_stats.layout().setDirection(QHBoxLayout.Direction.LeftToRight if stacked else QHBoxLayout.Direction.TopToBottom)
        for label in d.stat_labels:set_presentation_style(label,'background:transparent;border:0;padding:'+('4px' if stacked else '10px')+';font-size:12px;')
        if readable:self._fit_hero_height()
        self.inventory_header.setFixedHeight(48);self.inventory_header_host.setFixedHeight(48)
        self.inventory_header.layout().setContentsMargins(24,4,18,4)
        d.inventory_stack_host.setMinimumHeight(0)
        d.copy_log_btn.setVisible(not dense);d.save_log_btn.setVisible(not dense)
        for key,label in d.stage_labels.items():
            full={'choose_manga':'1  Choose Manga','book_customization':'2  Book Customization','finalization':'3  Finalization'}
            short={'choose_manga':'1 Choose Manga','book_customization':'2 Customize','finalization':'3 Finalize'}
            text=(short if d.width()<1100 else full)[key]
            if label.text()!=text:label.setText(text)
        d.header._reflow()
        from calibre_plugins.manganana.app.main import ProviderBadgeWidget
        for badge in d.selected_source_host.findChildren(ProviderBadgeWidget):badge_style(badge,'font-size:12px;padding:3px 7px;')
        url=d._selected_cover_url or getattr(d,'_pending_search_cover_url','')
        if url and url in d._image_cache:
            pix=d._pix_for_url(url,d.selected_cover.width(),d.selected_cover.height())
            if pix is not None:d.selected_cover.setPixmap(pix)
        self.inventory()
        self.empty_state(getattr(d,'_immediate_info',None) or d.loaded_metadata or {})
        # Apply the changed cover constraints within their owning Qt flow now;
        # a deferred LayoutRequest otherwise leaves the title at the preceding
        # cover width for a paintable turn during a scrollbar transition.
        d._hero_row.activate()
