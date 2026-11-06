"""Compact settings and inventory presentation using the dialog's controls."""
import re
from qt.core import (Qt, QWidget, QLabel, QCheckBox, QPushButton, QToolButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QStackedWidget, QScrollArea,
    QListWidget, QGroupBox, QSizePolicy, QSpinBox, QPainter, QColor, QRectF,
    QEvent, QMenu, QStyle, QStyleOptionButton, QIcon, QAbstractSpinBox, QTransform, QSize)
from calibre_plugins.manganana.presentation.choose_manga_reference import ReferenceFidelityLayout, accent_style
from calibre_plugins.manganana.presentation.choose_manga_design import TILE_STYLE, PICK_STYLE, CoverToggle
from types import MethodType
from qt.core import QFontMetrics, QFont
from calibre_plugins.manganana.presentation.mangaanka_presentation import UI_ACCENT
from calibre_plugins.manganana.presentation.choose_manga_resources import asset_root
from calibre_plugins.manganana.metadata.description_text import normalize_description
from calibre_plugins.manganana.presentation.interface_scale import set_presentation_style


def seafoam(style):
    for color in ('#087fff', '#4b9dff', '#57a8ff', '#2669bc', '#18c98a'):
        style = style.replace(color, UI_ACCENT)
    for color in ('#104b9e', '#102b49', '#18344f'):
        style = style.replace(color, '#29453f')
    return style.replace('#111a25', '#151b1e').replace('#1b2736', '#252c2f')


SETTINGS_STYLE = '''
QDialog {background:#191d20;}
QWidget#settingsPage {background:#191d20;}
QListWidget#settingsNavigation {background:#202629;border:0;border-radius:9px;}
QListWidget#settingsNavigation::item {padding:10px 12px;margin:3px;border-radius:6px;}
QListWidget#settingsNavigation::item:selected {background:#344b46;color:#f1f5f4;}
QGroupBox {background:#23292c;border:1px solid #343c3f;border-radius:9px;margin-top:24px;padding:14px 12px 12px;}
QGroupBox::title {subcontrol-origin:margin;left:3px;padding:0;color:#edf0f0;}
QLineEdit,QComboBox,QAbstractSpinBox {background:#2c3337;border:1px solid #41494c;border-radius:6px;padding:5px 8px;}
QPushButton {background:#2c3337;border-color:#41494c;}
QPushButton#primaryAction {background:ACCENT;color:#102421;border-color:ACCENT;}
QPushButton[updateAvailable="true"] {border-color:ACCENT;}
'''.replace('ACCENT', UI_ACCENT)


class BoundSwitch(QCheckBox):
    """Native accessible checkbox behavior with a painted pill and white thumb."""
    def __init__(self, control, off=None, name='', parent=None):
        super().__init__(parent)
        self.control, self.off = control, off
        self.setAccessibleName(name or control.accessibleName() or control.text())
        self.setToolTip(control.toolTip())
        self.setFixedSize(42, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        control.installEventFilter(self)
        control.toggled.connect(self.sync)
        self.clicked.connect(self.activate)
        self.sync()

    def sync(self, *_):
        previous = self.blockSignals(True)
        self.setChecked(self.control.isChecked())
        self.setEnabled(self.control.isEnabled())
        self.blockSignals(previous)

    def activate(self, checked):
        if self.off is None:
            self.control.setChecked(checked)
        else:
            (self.control if checked else self.off).click()
        self.sync()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.sync()
        return False

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.45)
        track = QRectF(3, 4, 36, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(UI_ACCENT if self.isChecked() else '#4d555a'))
        painter.drawRoundedRect(track, 9, 9)
        painter.setBrush(QColor('#f7faf9' if self.isChecked() else '#c3c9cc'))
        painter.drawEllipse(QRectF(track.right()-16 if self.isChecked() else track.left()+2, track.top()+2, 14, 14))
        if self.hasFocus():
            painter.setPen(QColor(UI_ACCENT));painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), 11, 11)
        painter.end()


class SliderValue(QSpinBox):
    def __init__(self, slider, name, suffix=''):
        super().__init__()
        self.slider=slider
        self.setAccessibleName(name);self.setRange(slider.minimum(),slider.maximum())
        self.setSuffix(suffix);self.setValue(slider.value());self.setKeyboardTracking(False)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setEnabled(slider.isEnabled());slider.installEventFilter(self)
        slider.valueChanged.connect(self.setValue);self.valueChanged.connect(slider.setValue)

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Type.EnabledChange:self.setEnabled(self.slider.isEnabled())
        return False


def park_layout(layout, parking):
    """Keep controller-owned widgets alive while replacing their presentation."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide();item.widget().setParent(parking)
        elif item.layout():
            park_layout(item.layout(), parking)
            item.layout().deleteLater()


def page():
    body = QWidget();body.setObjectName('settingsPage')
    body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    layout = QVBoxLayout(body);layout.setContentsMargins(14,0,4,4);layout.setSpacing(14)
    scroll = QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(body)
    return scroll, layout


def form_card(title, layout):
    box = QGroupBox(title);form = QFormLayout(box)
    form.setContentsMargins(12,12,12,12);form.setVerticalSpacing(12)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(box)
    return form


def navigation(parent, entries):
    host = QWidget(parent);row = QHBoxLayout(host);row.setContentsMargins(0,0,0,0);row.setSpacing(8)
    nav = QListWidget();nav.setObjectName('settingsNavigation');nav.setFixedWidth(155)
    stack = QStackedWidget();row.addWidget(nav);row.addWidget(stack,1)
    for name, widget in entries:
        nav.addItem(name);stack.addWidget(widget)
    nav.currentRowChanged.connect(stack.setCurrentIndex);nav.setCurrentRow(0)
    return host, nav, stack


def polish_preferences(dialog):
    if dialog.property('seafoamPreferences'):
        return
    dialog.setProperty('seafoamPreferences', True)
    dialog.setWindowTitle('MangaAnkā · Preferences')
    dialog.setStyleSheet(dialog.styleSheet()+SETTINGS_STYLE)
    root = dialog.layout();old = dialog.preferences_scroll
    groups = [old.widget().layout().itemAt(i).widget() for i in range(old.widget().layout().count())]
    groups = [w for w in groups if w is not None]
    entries = []
    # Route by section role: adding a metadata preference must not move Google
    # Books into Cache merely by changing a positional slice.
    role=lambda widget: {'Defaults':'Defaults','Behavior':'Behavior','Search Metadata Cache':'Cache'}.get(
        widget.title() if isinstance(widget,QGroupBox) else '', 'Metadata')
    for name in ('Defaults','Behavior','Metadata','Cache'):
        selected=[widget for widget in groups if role(widget)==name]
        scroll, column = page()
        for widget in selected:
            widget.setParent(scroll.widget());column.addWidget(widget)
        column.addStretch(1);entries.append((name,scroll))
    host, dialog.settings_navigation, dialog.settings_pages = navigation(dialog, entries)
    root.replaceWidget(old,host);old.hide()
    dialog.settings_switches = []
    for group in groups:
        form = group.layout()
        if not isinstance(form,QFormLayout):continue
        for row in range(form.rowCount()):
            item = form.itemAt(row,QFormLayout.ItemRole.LabelRole)
            if item:
                label = item.widget();label.setMinimumWidth(0)
                replacements={'Preferred title/metadata language:':'Title language','Interface language:':'Interface language',
                    'Default page layout:':'Page display','Default reading direction:':'Reading direction','Existing volumes:':'Existing books'}
                label.setText(replacements.get(label.text(),label.text()))
            field = form.itemAt(row,QFormLayout.ItemRole.FieldRole)
            if not field or not isinstance(field.widget(),QCheckBox):continue
            control = field.widget();name = control.text()
            control.setAccessibleName(name)
            form.removeWidget(control);control.hide()
            label_item=form.itemAt(row,QFormLayout.ItemRole.LabelRole)
            if label_item:
                form.removeWidget(label_item.widget());label_item.widget().hide()
            line = QWidget();bar = QHBoxLayout(line);bar.setContentsMargins(0,0,0,0)
            text = QLabel(name);text.setWordWrap(True)
            switch = BoundSwitch(control,name=name)
            bar.addStretch(1);bar.addWidget(switch)
            form.setWidget(row,QFormLayout.ItemRole.LabelRole,text)
            form.setWidget(row,QFormLayout.ItemRole.FieldRole,line)
            dialog.settings_switches.append(switch)
    dialog.resize(790,610)


class SeafoamPolishLayout(ReferenceFidelityLayout):
    def _hero(self):
        super()._hero()
        from calibre_plugins.manganana.presentation.hero_readability import SynopsisField, GenreStrip
        d = self.d
        copy = self.hero_copy.layout()
        copy.removeWidget(self.facts)
        # Keep the rating and source on one quiet line above the synopsis.
        badges = copy.takeAt(0).layout()
        badges.setParent(None)
        root = self.hero_body.layout()
        root.removeWidget(d.selected_rating)
        status = QHBoxLayout();status.setContentsMargins(0,0,0,0);status.setSpacing(12)
        status.addWidget(d.selected_rating)
        status.addLayout(badges)
        status.addStretch(1)
        root.insertLayout(2, status)
        root.setSpacing(8)
        copy.setContentsMargins(14,10,14,10)
        copy.setSpacing(8)
        copy.setStretch(copy.indexOf(d.selected_synopsis_scroll),1)
        # The old trailing stretch competed with the synopsis for its height.
        tail = copy.takeAt(copy.count()-1)
        del tail
        self.hero_copy.setObjectName('heroSynopsisPanel')
        self.hero_copy.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.hero_copy.setStyleSheet('QWidget#heroSynopsisPanel {background:rgba(4,14,19,205);'
                                    'border:1px solid rgba(102,183,168,70);border-radius:8px;}')
        d.selected_synopsis.setContentsMargins(0,0,0,0)
        d.selected_synopsis_scroll.setStyleSheet('background:transparent;border:0;')
        self.synopsis_field = SynopsisField(d.selected_synopsis,d.selected_synopsis_scroll)
        d.selected_synopsis_scroll.setMinimumHeight(0)
        d.selected_synopsis_scroll.setMaximumHeight(16777215)
        grid = self.facts.layout()
        grid.removeWidget(self.genre_host)
        self.genre_host.hide();self.genre_host.deleteLater()
        self.genre_host = GenreStrip()
        self.genre_row = self.genre_host.layout()
        grid.addWidget(self.genre_host,1,3)
        grid.setContentsMargins(14,10,14,10)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(5)
        for column,stretch in enumerate((2,1,1,3)):grid.setColumnStretch(column,stretch)
        self.facts.setObjectName('heroMetadata')
        self.facts.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.facts.setStyleSheet('QWidget#heroMetadata {background:rgba(4,14,19,205);'
                                'border:1px solid rgba(102,183,168,70);border-radius:8px;}')
        d._selected_top_panel.layout().addWidget(self.facts)
        d._selected_top_panel.layout().setSpacing(12)
        for label in self.fact_values:
            set_presentation_style(label,'font-size:14px;font-weight:600;color:#edf5f2;background:transparent;')
        d.selected_cover.setStyleSheet('background:transparent;border:1px solid #46625d;border-radius:4px;')

    @staticmethod
    def presentation_style():
        return seafoam(ReferenceFidelityLayout.presentation_style())+'''
QPushButton#modeChoice:checked,QPushButton#heroDetails,QPushButton#primaryAction {color:#102421;}
QLabel#ankaStep[active="true"] {color:#102421;}
QWidget#customizationSection {background:#20272a;border:1px solid #343c3f;border-radius:8px;}
QPushButton#sectionHeader {background:transparent;border:0;text-align:left;font-size:13px;padding:3px 0;}
QWidget#customizationSection QLabel {font-size:12px;}
QWidget#customizationSection QComboBox,QWidget#customizationSection QAbstractSpinBox {font-size:12px;padding:4px 6px;background:#30373b;}
QPushButton#layoutChoice {font-size:12px;padding:4px 7px;min-height:18px;border-radius:6px;}
QPushButton#layoutChoice:checked {background:#385a52;border-color:#66B7A8;}
QPushButton#tertiaryAction {font-size:12px;}
'''

    def __init__(self, dialog):
        super().__init__(dialog)
        # The strip has a bounded height. Give spare space to one trailing
        # spacer, rather than letting QVBoxLayout distribute it around the hero
        # whenever the loading page or coverage summary changes its size hint.
        source_layout = dialog._source_selected_page.layout()
        source_layout.setStretch(source_layout.indexOf(dialog.inventory_stack_host), 0)
        source_layout.addStretch(1)
        self.parking = QWidget(dialog);self.parking.hide()
        self.switches = []
        self.empty_instruction.clear();self.empty_instruction.hide()
        dialog.header.stepper.setStyleSheet('QWidget#referenceStepper {background:#252c2f;border-radius:18px;}')
        self.status_dot.setStyleSheet('color:'+UI_ACCENT+';font-size:15px;')
        self._main_discovery_controls()
        self._settings_cards()
        self._compact_customization()
        for pane in (self.search_pane,dialog.customization_settings_card,dialog.finalization_metadata_card):
            pane.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
            pane.setAutoFillBackground(False)
            pane.setStyleSheet(pane.styleSheet()+f'\nQWidget#{pane.objectName()} {{background:#111922;border:0;border-radius:0;}}')
        self._center_progress()

    def _main_discovery_controls(self):
        d = self.d;options = d.discovery_options.layout()
        self.quick_controls = QWidget();column = QVBoxLayout(self.quick_controls)
        column.setContentsMargins(0,0,0,5);column.setSpacing(8)
        d._search_top_panel.layout().addWidget(self.quick_controls)
        top=d._search_top_panel.layout()
        for i in reversed(range(top.count())):
            item=top.itemAt(i)
            if item.layout() and item.layout().indexOf(d.search_box)>=0:
                previous=top.takeAt(i).layout()
                previous.removeWidget(d.search_box);previous.removeWidget(d.search_btn)
                previous.deleteLater()
        self.discovery_fields=QGridLayout();self.discovery_fields.setHorizontalSpacing(8);self.discovery_fields.setVerticalSpacing(8)
        self.discovery_fields.setColumnStretch(0,1)
        self.discovery_fields.addWidget(d.search_box,0,0);self.discovery_fields.addWidget(d.search_btn,0,1)
        column.addLayout(self.discovery_fields)
        # Preserve the original preference checkbox and its persisted signals.
        options.removeWidget(d.prefer_colored);d.prefer_colored.hide();d.prefer_colored.setParent(self.parking)
        for i in reversed(range(options.count())):
            item = options.itemAt(i)
            if item.layout() and item.layout().indexOf(d.url)>=0:
                line=options.takeAt(i).layout();line.setParent(None)
                line.removeWidget(d.url);line.removeWidget(d.load_btn);line.deleteLater()
                self.discovery_fields.addWidget(d.url,1,0);self.discovery_fields.addWidget(d.load_btn,1,1)
        self.prefer_row = QHBoxLayout();self.prefer_row.setSpacing(8)
        self.prefer_label = QLabel('Prefer Colored');self.prefer_row.addWidget(self.prefer_label)
        self.color_switch = BoundSwitch(d.prefer_colored,name='Prefer Colored');self.prefer_row.addWidget(self.color_switch)
        self.prefer_row.addStretch(1)
        column.addLayout(self.prefer_row)
        d.url.setPlaceholderText('Paste a direct manga link…');d.url.setAccessibleName('Direct Link')
        d.url.show();d.load_btn.show()
        for label in d.discovery_options.findChildren(QLabel):
            if label.text() in ('Direct Link','Choose Volumes, Chapters, or Import to begin.'):
                label.hide()
        self.color_switch.show()
        # These are the live discovery controls. Legacy labels/list widgets
        # were reparented or replaced and must not be shown by mode changes.
        d._source_discovery_widgets = (self.quick_controls, d.search_box,
            d.search_btn, d.url, d.load_btn)

    def _settings_cards(self):
        d = self.d;view = self.settings_window
        view.setProperty('seafoamSettings',True)
        park_layout(view.layout(),self.parking)
        view.setWindowTitle('MangaAnkā · Settings');view.setStyleSheet(SETTINGS_STYLE)
        root = view.layout();root.setContentsMargins(16,14,16,14);root.setSpacing(12)
        heading = QLabel('Settings');heading.setStyleSheet('font-size:21px;font-weight:600;');root.addWidget(heading)
        general, column = page();form = form_card('Acquisition',column)
        form.addRow('Language',d.language);d.language.show()
        utilities=form_card('Application',column)
        d.check_updates_btn=QPushButton('Check for updates')
        d.check_updates_btn.setAutoDefault(False)
        d.check_updates_btn.clicked.connect(lambda: d.release_updates.check(manual=True))
        utilities.addRow(d.check_updates_btn)
        d.update_status=QLabel('Official stable releases only');d.update_status.setWordWrap(True)
        utilities.addRow(d.update_status)
        d.release_notes_btn=QPushButton('Release notes & download…');d.release_notes_btn.hide()
        d.release_notes_btn.clicked.connect(lambda: d.release_updates.open_release_page())
        utilities.addRow(d.release_notes_btn)
        from calibre_plugins.manganana.app.main import prefs
        d.automatic_update_checks=QCheckBox('Check automatically')
        d.automatic_update_checks.setChecked(bool(prefs.get('update_auto_check',True)))
        updates_switch=BoundSwitch(d.automatic_update_checks,name='Check automatically')
        d.automatic_update_checks.hide();d.automatic_update_checks.setParent(self.parking)
        utilities.addRow('Automatic updates check',updates_switch)
        def automatic_changed(enabled):
            prefs['update_auto_check']=bool(enabled)
            updater=getattr(d,'release_updates',None)
            if not enabled and updater is not None and updater.worker is not None and not updater.manual:
                updater.worker.requestInterruption()
        d.automatic_update_checks.toggled.connect(automatic_changed)
        for button in (d.preferences_btn,d.about_btn):utilities.addRow(button);button.show()
        d.google_books_key_btn.setText('Google Books (optional)…')
        utilities.addRow(d.google_books_key_btn)
        d._refresh_google_books_key_button()
        notifications=form_card('Notifications',column)
        from calibre_plugins.manganana.app.main import prefs
        d.completion_sound_enabled=QCheckBox('Completion sounds')
        d.completion_sound_enabled.setChecked(bool(prefs.get('completion_sounds',True)))
        sound_switch=BoundSwitch(d.completion_sound_enabled,name='Completion sounds')
        d.completion_sound_enabled.hide();d.completion_sound_enabled.setParent(self.parking)
        sound_row=QHBoxLayout();sound_row.addWidget(sound_switch);sound_row.addStretch(1)
        d.completion_sound_preview=QPushButton('Preview')
        d.completion_sound_preview.setToolTip('Hear the built-in bell, including when automatic sounds are muted.')
        d.completion_sound_preview.clicked.connect(lambda:d.completion_audio.play('preview'))
        sound_row.addWidget(d.completion_sound_preview);notifications.addRow('Completion sound',sound_row)
        def sound_changed(enabled):
            prefs['completion_sounds']=bool(enabled)
            if not enabled:d.completion_audio.stop()
        d.completion_sound_enabled.toggled.connect(sound_changed)
        d.completion_sound_status=QLabel('Only verified, fully successful batches ring.');d.completion_sound_status.setWordWrap(True)
        notifications.addRow(d.completion_sound_status)
        column.addStretch(1)
        sources,column=page();form=form_card('Manga sources',column)
        form.addRow(d.sources_btn);d.sources_btn.show()
        d.source_status_layout.setDirection(QHBoxLayout.Direction.TopToBottom)
        form.addRow(d.source_status_host);d.source_status_host.show();column.addStretch(1)
        rendering,column=page();form=form_card('Hero rendering',column)
        form.addRow('Animation',d.animation_rate);form.addRow('Resolution',d.render_scale)
        d.animation_rate.show();d.render_scale.show();column.addStretch(1)
        display,column=page()
        from calibre_plugins.manganana.presentation.interface_scale import add_display_settings
        add_display_settings(d,column,form_card);column.addStretch(1)
        host,self.settings_navigation,self.settings_pages=navigation(view,[('General',general),('Sources',sources),('Display',display),('Rendering',rendering)])
        root.addWidget(host,1)
        done=QPushButton('Done');done.setObjectName('primaryAction');done.clicked.connect(view.hide)
        row=QHBoxLayout();row.addStretch(1);row.addWidget(done);root.addLayout(row)
        view.resize(720,480)

    def _compact_customization(self):
        d=self.d;card=d.customization_settings_card;outer=card.layout()
        # Only the heading and settings scroll remain in the card's outer flow.
        for label in card.findChildren(QLabel):
            if label.text()=='Adjust how your manga will be prepared for eBook output.':label.hide()
        self.settings_scroll=QScrollArea();self.settings_scroll.setWidgetResizable(True)
        body=QWidget();body.setObjectName('settingsPage');column=QVBoxLayout(body)
        column.setContentsMargins(0,0,7,0);column.setSpacing(7)
        self.settings_scroll.setWidget(body)
        self.settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.settings_scroll.viewport().setAutoFillBackground(False)
        body.setAutoFillBackground(False)
        body.setStyleSheet('QWidget#settingsPage {background:transparent;border:0;}')
        for title,section in d.customization_sections.items():
            outer.removeWidget(section);section.setParent(body);column.addWidget(section)
            park_layout(section.content,self.parking)
            section.content.setContentsMargins(8,5,2,3);section.content.setSpacing(7)
            section.summary.hide()
            section.header.toggled.connect(lambda _on,s=section:s.summary.hide())
            section.header.toggled.connect(lambda on,s=section:self._section_title(s,on))
            section.header.setChecked(True);self._section_title(section,True)
        column.addStretch(1)
        while outer.count()>1:
            item=outer.takeAt(1)
            if item.widget():item.widget().hide()
        outer.addWidget(self.settings_scroll,1)
        card.setMinimumWidth(420);card.setMaximumWidth(500)
        self.rows={}
        labels=[];self.field_labels=labels
        def row(section,label,widgets):
            if section not in self.rows:
                grid=QGridLayout();grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(9);grid.setVerticalSpacing(7)
                d.customization_sections[section].content.addLayout(grid);self.rows[section]=grid
            grid=self.rows[section];index=grid.rowCount();name=QLabel(label)
            labels.append(name)
            grid.addWidget(name,index,0)
            line=QWidget();bar=QHBoxLayout(line);bar.setContentsMargins(0,0,0,0);bar.setSpacing(6)
            for widget,stretch in widgets:bar.addWidget(widget,stretch);widget.show()
            grid.addWidget(line,index,1);grid.setColumnStretch(1,1)
            return name
        for button,text in ((d.portrait_btn,'Single Pages'),(d.landscape_btn,'Paired Pages')):
            button.setText(text);button.setIcon(QIcon());button.setMinimumSize(0,0);button.setMaximumHeight(30)
        row('Reading & Layout','Page display',[(d.portrait_btn,1),(d.landscape_btn,1)])
        d.reading_direction_label=row('Reading & Layout','Reading direction',[(d.reading_direction,1)])
        def preset(section,combo,save,menu):
            more=QToolButton();more.setText('…');more.setAccessibleName(section+' preset actions')
            more.setStyleSheet('QToolButton {padding:1px 6px;} QToolButton::menu-indicator {image:none;width:0;}')
            more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            actions=QMenu(more);actions.addAction('Save Preset…',save.click);actions.addMenu(menu);more.setMenu(actions)
            row(section,'Preset',[(combo,1),(more,0)])
        preset('Page Framing',d.framing_preset,d.save_framing_preset,d.framing_preset_menu)
        self.framing_value=self._numeric(d.page_framing,'Page framing value')
        name=row('Page Framing','Page framing',[(d.page_framing,1),(self.framing_value,0)])
        name.setToolTip('Existing framing scale: negative adds margins; positive reduces safe padding or zooms. Original preset and processing rules apply.')
        self.gutter_value=self._numeric(d.page_gutter,'Gutter pixels',' px')
        self.gutter_label=row('Page Framing','Gutter (center)',[(d.page_gutter,1),(self.gutter_value,0)])
        d.page_layout.currentIndexChanged.connect(self._framing_visibility)
        self._framing_visibility()
        preset('Image Adjustments',d.processing_preset,d.save_processing_preset,d.processing_preset_menu)
        section=d.customization_sections['Image Adjustments']
        header=QHBoxLayout();section.layout().removeWidget(section.header);header.addWidget(section.header,1);header.addWidget(d.processing_reset)
        d.processing_reset.show();section.layout().insertLayout(0,header)
        for name,(slider,label) in d._processing_controls.items():
            label.setStyleSheet('background:#30373b;border:1px solid #41494c;border-radius:5px;padding:3px 6px;')
            row('Image Adjustments',name.title(),[(slider,1),(label,0)])
        for label,on,off in (('Grayscale',d.grayscale_on,d.grayscale_off),('Dark Page Inversion',d.dark_mode_on,d.dark_mode_off)):
            switch=BoundSwitch(on,off,label);self.switches.append(switch)
            row('Tone & Color',label,[(self._spacer(),1),(switch,0)])
        row('Output Quality','Image depth',[(d.output_depth,1)])
        row('Output Quality','Dithering',[(d.dithering,1)])
        self.strength_label=row('Output Quality','Dither strength',[(d.dither_strength,1),(d.dither_strength_value,0)])
        width=max(label.sizeHint().width() for label in labels)
        for grid in self.rows.values():grid.setColumnMinimumWidth(0,width)
        self.sync_switches()

    def resize(self):
        super().resize()
        if hasattr(self,'quick_controls'):
            # Use Qt's styled font metrics for a shared button column, keeping
            # Search and Direct Link inputs aligned at every scale.
            d=self.d
            width=0
            for button,texts in ((d.search_btn,(d.search_btn.text(),)),(d.load_btn,('Load','Loading...'))):
                option=QStyleOptionButton();button.initStyleOption(option)
                for text in texts:
                    content=QSize(option.fontMetrics.horizontalAdvance(text),option.fontMetrics.height())
                    required=button.style().sizeFromContents(QStyle.ContentsType.CT_PushButton,option,content,button)
                    width=max(width,required.width())
            self.discovery_fields.setColumnMinimumWidth(1,width)
        if hasattr(self,'field_labels'):
            width=max(label.sizeHint().width() for label in self.field_labels)
            for grid in self.rows.values():grid.setColumnMinimumWidth(0,width)

    @staticmethod
    def _spacer():return QWidget()

    @staticmethod
    def _section_title(section,expanded):
        section.header.setText(section.title.replace('&','&&'))
        icon=QIcon(str(asset_root()/'assets/ui/icons/chevron-down.svg'))
        if not expanded:icon=QIcon(icon.pixmap(QSize(12,12)).transformed(QTransform().rotate(-90)))
        section.header.setIcon(icon);section.header.setIconSize(QSize(12,12))

    @staticmethod
    def _numeric(slider,name,suffix=''):
        return SliderValue(slider,name,suffix)

    def _framing_visibility(self,*_):
        visible=self.d.page_layout.currentData()=='paired_landscape'
        self.gutter_label.setVisible(visible);self.d.page_gutter.parentWidget().setVisible(visible)

    def sync_switches(self):
        for switch in getattr(self,'switches',()):switch.sync()
        if hasattr(self,'strength_label'):
            active=self.d.dither_strength.isEnabled()
            self.strength_label.setVisible(active);self.d.dither_strength.parentWidget().setVisible(active)

    def _center_progress(self):
        d=self.d
        for host,label,bar in ((d.search_progress_widget,d.search_progress_text,d.search_progress),(d.work_progress_widget,d.progress_text,d.progress)):
            park_layout(host.layout(),self.parking)
            line=QVBoxLayout();line.setContentsMargins(0,0,0,0);line.setSpacing(4)
            label.setMaximumWidth(16777215);label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
            line.addWidget(label)
            line.addWidget(bar);bar.setFixedHeight(6)
            host.layout().setContentsMargins(0,0,0,0);host.layout().addLayout(line,1)
            label.show();bar.show()

    def mode(self):
        super().mode()
        self.search_pane.layout().setContentsMargins(10,14,10,0)
        local=self.d.workflow_mode=='import'
        if hasattr(self.d,'discovery_view'):
            self.d.discovery_view.setVisible(not local)
        self.paging_host.setVisible(not local)
        saved=getattr(self.d,'saved_manga',None)
        if saved is not None:
            saved.message.setVisible(not local and bool(saved.message.text()))
        if hasattr(self,'quick_controls'):
            self.quick_controls.setVisible(not local)
            self.d.prefer_colored.hide()
        if hasattr(self.d,'recent_searches'):self.d.recent_searches.sync()

    def prepare_import(self):
        super().prepare_import()
        d=self.d
        # Use the same sidebar inset and button treatment as source discovery.
        d.import_panel.layout().setContentsMargins(0,12,0,0)
        d.import_panel.layout().setSpacing(8)
        for button in (d.import_select_btn,d.import_clear_btn,d.import_remove_btn):
            button.setStyleSheet('')
        d.import_table.setFrameShape(QScrollArea.Shape.NoFrame)
        d.import_table.horizontalHeader().hide()
        d.import_table.setColumnHidden(2,True);d.import_table.setColumnHidden(3,True)
        d.import_table.setWordWrap(False);d.import_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        d.import_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        set_presentation_style(self.import_heading,'font-size:32px;font-weight:700;color:#ffffff;background:transparent;')
        if not hasattr(self,'import_empty_space'):
            column=self.import_details_page.layout()
            column.addStretch(1)
            self.import_empty_space=column.count()-1
        for label in self.d.import_panel.findChildren(QLabel):
            if 'PDF pages are imported' in label.text():label.hide()

    def import_details(self):
        super().import_details()
        if not hasattr(self,'import_overview'):return
        books=self.d._selected_import_books();inspecting=self.d._import_inspection is not None
        if not books and not inspecting:self.import_summary.clear()
        loaded=bool(self.d._import_books)
        if loaded and not books and not inspecting:self.import_summary.setText('0 books selected')
        self.import_summary.setVisible(loaded or inspecting)
        self.import_overview.setVisible(loaded)
        self.import_details_page.layout().setStretch(self.import_empty_space,0 if loaded else 1)
        self.d.import_status.setVisible(bool(self.d._import_books) or inspecting)

    def metadata(self,md):
        text=normalize_description(md.get('description') or md.get('work_description'))
        text=re.sub(r'\s*\(Source\s*:[^()]*\)\s*$', '', text, flags=re.IGNORECASE)
        self.synopsis_field.set_text(text)
        super().metadata(md)
        if self._fit_hero_height() and hasattr(self.d,'inventory_stack'):
            self.inventory()

    def _fit_hero_height(self):
        """The content owns its minimum; the page owns any necessary scrolling."""
        d=self.d
        if not hasattr(d,'anka_shell'):return False
        # Genres and scaled fonts can arrive after the initial window layout.
        # Recalculate the panel floor here as well as during window resizing.
        self.facts.layout().invalidate()
        scale=float(d.property('interfaceScaleFactor')or 1.)
        minimum=max(round(66*scale),self.facts.layout().minimumSize().height())
        if self.facts.minimumHeight()!=minimum:
            self.facts.setMinimumHeight(minimum)
        base=max(260,min(460,round(d.anka_shell.workspace.viewport().height()*.54)))
        needed=d._selected_top_panel.layout().minimumSize().height()
        height=max(base,needed)
        if d.hero.height()==height:return False
        d.hero.setFixedHeight(height)
        return True

    def results(self):
        super().results()
        for i in range(self.d.search_results.count()):
            row=self.d.search_results.itemWidget(self.d.search_results.item(i))
            if row:row.setStyleSheet(seafoam(row.styleSheet()))

    def restyle_tile(self,row):
        # Apply changed styles only; repolishing every card interrupts scrolling.
        for widget,style in ((row,seafoam(accent_style(TILE_STYLE))),
                             (row.pick,seafoam(accent_style(PICK_STYLE)))):
            if widget.styleSheet()!=style:widget.setStyleSheet(style)

    def inventory(self, items=None):
        """Fit inventory cards using the final strip geometry."""
        from calibre_plugins.manganana.app.main import VolumeRowWidget
        d=self.d;self.carousel.sync()
        if items is None:
            scale=float(d.property('interfaceScaleFactor') or 1.)
            caption_heights=[]
            for pixels,minimum_height in ((14,20),(12,18)):
                font=QFont(d.font());font.setPixelSize(max(10,round(pixels*scale)))
                caption_heights.append(max(minimum_height,QFontMetrics(font).height()))
            self.caption_heights=tuple(caption_heights)
            caption_extra=sum(caption_heights)-38
            available=d.anka_shell.workspace.viewport().height()-d.hero.height()-self.inventory_header_host.height()-20
            coverage=getattr(d,'coverage_presentation',None)
            if coverage is not None and coverage.host.isVisible():
                available-=coverage.host.sizeHint().height()
            width=max(110,min(174,round((d._source_selected_page.width()-120)/6-12)))
            # Responsive fitting belongs to a real layout transition, not a
            # scroll event materializing new cards into an established strip.
            minimum=round(140*scale)
            height=max(minimum,min(218,round((width-16)*1.4),available-86-caption_extra))
            self.cover_size=(round(height/1.4),height)
            self.tile_size=QSize(max(110,self.cover_size[0]+16),height+54+caption_extra)
            strip=self.tile_size.height()+30
            d.volume_list.setSpacing(5);d.volume_list.setFixedHeight(strip)
            d.volume_list.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            self.skeleton.setFixedHeight(strip);d.inventory_stack_host.setFixedHeight(strip+10)
            for tile in self.skeleton.tiles:
                if tile.size()!=self.tile_size:tile.setFixedSize(self.tile_size)
                if tile.cover.size()!=QSize(*self.cover_size):tile.cover.setFixedSize(*self.cover_size)
                tile.layout().setContentsMargins(8,6,8,6)
        height=self.cover_size[1]
        # Keep hidden model items at the same extent as visible cards. Only
        # a responsive geometry change needs a model-wide extent update.
        if getattr(self,'_model_tile_size',None)!=self.tile_size:
            self._model_tile_size=QSize(self.tile_size)
            for i in range(d.volume_list.count()):d.volume_list.item(i).setSizeHint(self.tile_size)
        for item in (items if items is not None else (d.volume_list.item(i) for i in range(d.volume_list.count()))):
            row=d.volume_list.itemWidget(item)
            if not isinstance(row,VolumeRowWidget):continue
            if item.sizeHint()!=self.tile_size:item.setSizeHint(self.tile_size)
            if row.size()!=self.tile_size:row.setFixedSize(self.tile_size)
            if (getattr(row,'_final_inventory_geometry',None)!=self.cover_size or
                    row.cover.size()!=QSize(*self.cover_size)):
                row._final_inventory_geometry=self.cover_size
                row.layout().setContentsMargins(7,6,7,6);row.layout().setSpacing(3)
                row.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
                row.layout().setStretch(row.layout().indexOf(row.title),0)
                item.setData(Qt.ItemDataRole.ForegroundRole,QColor(0,0,0,0))
                row.cover.setFixedSize(*self.cover_size);row.cover_host.setFixedHeight(height)
                set_presentation_style(row.title,'font-size:14px;font-weight:600;');row.title.setFixedHeight(self.caption_heights[0])
                row.title.setWordWrap(False)
                if not hasattr(row,'_fidelity_title'):row._fidelity_title=row.title.text()
                row.title.setToolTip(row._fidelity_title)
                row.title.setText(QFontMetrics(row.title.font()).elidedText(row._fidelity_title,Qt.TextElideMode.ElideRight,self.tile_size.width()-18))
                set_presentation_style(row.membership,'font-size:12px;color:#c3cedd;');row.membership.setFixedHeight(self.caption_heights[1]);row.membership.setWordWrap(False)
                url=(item.data(Qt.ItemDataRole.UserRole) or {}).get('cover_url')
                if url and url in d._image_cache:
                    pix=d._pix_for_url(url,*self.cover_size)
                    if pix is not None:row.set_cover(pix)
                row._fidelity_cover_size=self.cover_size
            if not hasattr(row,'_fidelity_toggle'):
                row._fidelity_toggle=CoverToggle(row)
                row.cover.installEventFilter(row._fidelity_toggle);row.installEventFilter(row._fidelity_toggle)
                row.toggled.connect(lambda _checked,r=row:self.restyle_tile(r))
                original=row.set_checked
                def checked(instance,value,emit_signal=False,_original=original):
                    _original(value,emit_signal=emit_signal);self.restyle_tile(instance)
                row.set_checked=MethodType(checked,row)
            self.restyle_tile(row)
        self.sync_inventory()

    def set_state(self,state,detail=''):
        super().set_state(state,detail)
        coverage=getattr(self.d,'coverage_presentation',None)
        if coverage is not None:
            coverage.refresh()
