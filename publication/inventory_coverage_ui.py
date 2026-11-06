"""Dialog-owned coverage summary and plain-language evidence inspection."""
from qt.core import (QObject, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDialogButtonBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy, Qt)
from calibre_plugins.manganana.presentation.non_modal_window import PluginDialog as QDialog
from calibre_plugins.manganana.publication.inventory_coverage import describe_inventory, entry_text


class CoveragePresentation(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.d = dialog
        self.host = QWidget()
        self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        column = QVBoxLayout(self.host)
        column.setContentsMargins(28, 0, 18, 8)
        column.setSpacing(3)
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        row = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        self.details = QPushButton('Coverage details…')
        self.details.setAutoDefault(False)
        self.details.clicked.connect(self.show_details)
        self.retry = QPushButton('Retry covers')
        self.retry.setAutoDefault(False)
        self.retry.setToolTip('Try the failed visible covers again. Chapter downloads are unchanged.')
        self.retry.clicked.connect(dialog._retry_failed_covers)
        self.retry.hide()
        row.addWidget(self.retry)
        row.addWidget(self.details)
        column.addLayout(row)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setStyleSheet('color:#b9c9c3;font-size:12px;')
        # Loading and ready share a status line. Keeping its empty line avoids
        # moving the gallery when the loading explanation becomes empty.
        self.status.ensurePolished()
        self.status.setMinimumHeight(self.status.fontMetrics().height())
        policy = self.status.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.status.setSizePolicy(policy)
        column.addWidget(self.status)
        layout = dialog._source_selected_page.layout()
        layout.insertWidget(layout.indexOf(dialog.fidelity.inventory_header_host)+1, self.host)
        self.facts = None
        self.refresh()

    def refresh(self):
        d = self.d
        visible = d.workflow_mode != 'import' and bool(d.workflow_state.selected_provider_record)
        self.host.setVisible(visible)
        if not visible:
            self.facts = None
            return
        state = d.fidelity.inventory_state
        if state not in ('ready', 'empty', 'error'):
            state = 'loading'
        rows = d._chapter_plan_items if d.workflow_mode == 'chapter' else d._volume_acquisition_items
        self.facts = describe_inventory(state=state, provider_id=d.current_source_id,
            provider_name=d.current_source.display_name, language=d.language.currentText(),
            rows=rows, plan=d._current_plan if d.workflow_mode == 'volume' else None,
            manifest=d._publication_manifest)
        facts = self.facts
        if state in ('ready', 'empty'):
            self.summary.setText(f'{facts.provider} · {facts.language}' +
                (' · Includes approved alternate sources' if facts.other_entries else ''))
            if state == 'empty':
                status = 'No downloads were found for this source and language.'
            else:
                status = ''
                if facts.ungrouped:
                    noun = 'downloads' if facts.packaged or facts.mixed_units else 'chapters'
                    status = f'Other {noun} are available separately.'
                if facts.reference_gaps or facts.warnings:
                    status += ' See Coverage details for items to review.'
            self.status.setText(status)
        else:
            self.summary.setText(facts.summary)
            self.status.setText(facts.status)
        self.status.setVisible(bool(self.status.text()))
        self.details.setEnabled(state in ('ready', 'empty'))
        d._refresh_cover_retry()

    def show_details(self):
        if self.d._closing or self.facts is None or self.facts.state not in ('ready', 'empty'):
            return
        # Freeze this evidence snapshot. It cannot change acquisition ownership
        # or perform requests, even if a background callback arrives.
        facts = self.facts
        popup = QDialog(self.d)
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        popup.setWindowTitle('Inventory coverage · ' + facts.provider)
        popup.setWindowModality(Qt.WindowModality.WindowModal)
        popup.resize(700, 610)
        layout = QVBoxLayout(popup)
        table = QTableWidget(len(facts.groups), 2)
        table.setHorizontalHeaderLabels(['Volume group', 'Entries found'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for index, (volume, count) in enumerate(facts.groups):
            table.setItem(index, 0, QTableWidgetItem('Volume ' + volume))
            text = f'{count:,} source entries' if facts.mixed_units else entry_text(count, facts.packaged)
            table.setItem(index, 1, QTableWidgetItem(text))
        table.setMinimumHeight(160)
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(popup.reject)
        layout.addWidget(buttons)
        popup.show()
