"""Preview output numbering without changing acquisition identities."""
from qt.core import (QVBoxLayout, QFormLayout, QLabel, QLineEdit,
                     QTableWidget, QTableWidgetItem, QHeaderView,
                     QAbstractItemView, QDialogButtonBox)
from calibre_plugins.manganana.presentation.non_modal_window import PluginDialog as QDialog
from calibre_plugins.manganana.books.output.output_series_metadata import (
    planned_series_index,
    format_series_index,
    renumber_values,
)


class SeriesNumberDialog(QDialog):
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Set Series Numbers')
        self.rows = tuple(rows)
        self.values = None
        layout = QVBoxLayout(self)
        text = ('Change the series number for this checked book.' if len(rows) == 1 else
                f'Number {len(rows)} books checked in the Use column, in table order.')
        heading = QLabel(text); heading.setWordWrap(True); layout.addWidget(heading)
        form = QFormLayout()
        self.start = QLineEdit(format_series_index(planned_series_index(rows[0])))
        self.start.setAccessibleName('Series number' if len(rows) == 1 else 'First series number')
        self.step = QLineEdit('1'); self.step.setAccessibleName('Increase by')
        form.addRow('Series number:' if len(rows) == 1 else 'First number:', self.start)
        if len(rows) > 1: form.addRow('Increase by:', self.step)
        else: self.step.hide()
        layout.addLayout(form)
        self.preview = QTableWidget(len(rows), 3)
        self.preview.setHorizontalHeaderLabels(['Book', 'Current #', 'New #'])
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.verticalHeader().hide()
        header = self.preview.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2): header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for index, row in enumerate(rows):
            self.preview.setItem(index, 0, QTableWidgetItem(row['title']))
            self.preview.setItem(index, 1, QTableWidgetItem(format_series_index(planned_series_index(row))))
        layout.addWidget(self.preview)
        note = QLabel('Updates Calibre metadata and stamped/generated cover numbers. Source chapters stay the same.')
        note.setWordWrap(True); layout.addWidget(note)
        self.error = QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply.setText('Apply Numbers' if len(rows) > 1 else 'Apply Number')
        self.apply.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject); layout.addWidget(self.buttons)
        self.start.textChanged.connect(self.update_preview); self.step.textChanged.connect(self.update_preview)
        self.start.returnPressed.connect(self.accept); self.step.returnPressed.connect(self.accept)
        self.resize(560, 320 if len(rows) == 1 else 420)
        self.update_preview(); self.start.selectAll(); self.start.setFocus()

    def update_preview(self, *_args):
        try:
            self.values = renumber_values(len(self.rows), self.start.text(), self.step.text())
            self.error.clear()
        except ValueError as exc:
            self.values = None; self.error.setText(str(exc))
        self.apply.setEnabled(self.values is not None)
        for index in range(len(self.rows)):
            self.preview.setItem(index, 2, QTableWidgetItem(
                format_series_index(self.values[index]) if self.values is not None else '—'))

    def accept(self):
        self.update_preview()
        if self.values is not None: super().accept()
