"""Neutral modal results dialog: no QMessageBox platform alert or system beep."""
from qt.core import (QLabel, QPushButton, QScrollArea, QWidget, QVBoxLayout, QGridLayout, Qt,
                     QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from calibre_plugins.manganana.presentation.non_modal_window import PluginDialog as QDialog


class CompletionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('completionResults')
        self.setAccessibleName('MangaAnkā output results')
        self._clicked = None
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        self.heading = QLabel()
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet('font-size:20px;font-weight:600;')
        root.addWidget(self.heading)
        scroll = QScrollArea()
        scroll.setObjectName('completionScroll')
        scroll.setWidgetResizable(True)
        body = QWidget(); body.setObjectName('completionBody'); content = QVBoxLayout(body)
        self.details = QLabel()
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.addWidget(self.details); content.addStretch(1)
        scroll.setWidget(body); root.addWidget(scroll, 1)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Output', 'Result', 'Details'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.hide(); root.addWidget(self.table, 2)
        self.actions = QGridLayout()
        root.addLayout(self.actions)
        self.setStyleSheet('QWidget#completionBody,QScrollArea#completionScroll {background:#111922;border:0;border-radius:8px;}')
        self.resize(640, 300)

    def setText(self, text):
        self.heading.setText(text)

    def setInformativeText(self, text):
        self.details.setText(text)

    def setLedger(self, ledger):
        rows = ledger['outputs']; self.table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            detail = record.get('reason') or 'Verified in the destination library.'
            for column, value in enumerate((record.get('title') or '', record['status'].title(), detail)):
                item = QTableWidgetItem(value)
                item.setToolTip(detail + ('\n' + record['generated_file'] if record.get('generated_file') else ''))
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents(); self.table.show(); self.resize(760, 440)

    def addButton(self, text, _role):
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.clicked.connect(lambda: self._choose(button))
        if text == 'OK':
            button.setDefault(True)
            button.setObjectName('primaryAction')
        index = self.actions.count()
        self.actions.addWidget(button, index // 3, index % 3)
        return button

    def _choose(self, button):
        self._clicked = button
        self.accept()

    def clickedButton(self):
        return self._clicked
