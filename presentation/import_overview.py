"""Read-only import facts in the main workspace; selection stays in the sidebar."""
from qt.core import (Qt, QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
                     QHeaderView, QAbstractItemView, QFrame)


def file_size(value):
    size=max(0,int(value or 0))
    for unit in ('B','KiB','MiB','GiB','TiB'):
        if size<1024 or unit=='TiB':
            return f'{int(size)} B'if unit=='B'else f'{size:.1f} {unit}'
        size/=1024


class ImportOverview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.table=QTableWidget(0,6)
        self.table.setObjectName('importOverview')
        self.table.setAccessibleName('Imported book details')
        self.table.setHorizontalHeaderLabels(['Book title','Format','Pages','Size','Included','File location'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False);self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame);self.table.verticalHeader().hide()
        self.table.verticalHeader().setMinimumSectionSize(32)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setStyleSheet('''QTableWidget#importOverview {background:transparent;}
QTableWidget#importOverview,QTableWidget#importOverview QHeaderView {border:0;border-radius:0;padding:0;}
''')
        header=self.table.horizontalHeader();header.setStretchLastSection(False)
        header.setResizeContentsPrecision(32)
        for column in range(6):
            header.setSectionResizeMode(column,QHeaderView.ResizeMode.Stretch if column in (0,5)
                                        else QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)
        self._rows=None

    def set_books(self, books, selected):
        rows=tuple((book['id'],str(book.get('title') or ''),str(book.get('format') or '').upper(),
            str(book.get('pages') or 0),file_size(book.get('bytes')),
            'Yes'if book['id']in selected else'No',str(book.get('path') or ''),
            str(book.get('author') or ''),str(book.get('series') or ''))for book in books)
        if rows==self._rows:return
        current=self.table.item(self.table.currentRow(),0)
        current_id=current.data(Qt.ItemDataRole.UserRole)if current else None
        signals=self.table.blockSignals(True);self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(rows))
            for index,row in enumerate(rows):
                identity,title,fmt,pages,size,included,path,author,series=row
                if self._rows is not None and index<len(self._rows)and row==self._rows[index]:continue
                tooltip=f'{title}\n{path}\nAuthor: {author or "—"}\nSeries: {series or "—"}'
                for column,value in enumerate((title,fmt,pages,size,included,path)):
                    item=self.table.item(index,column)
                    if item is None:
                        item=QTableWidgetItem();self.table.setItem(index,column,item)
                    if item.text()!=value:item.setText(value)
                    item.setToolTip(tooltip)
                    item.setData(Qt.ItemDataRole.UserRole,identity)
                    if column in (1,2,3,4):item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if identity==current_id:self.table.setCurrentCell(index,0)
            self._rows=rows
        finally:
            self.table.blockSignals(signals);self.table.setUpdatesEnabled(True)
