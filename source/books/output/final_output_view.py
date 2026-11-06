"""Viewport-owned editors for the complete, identity-owned output plan.

All requested outputs remain in the table model and preview_data. Child
widgets and thumbnail previews are presentation resources, not output state.
"""
from contextlib import contextmanager
from time import perf_counter
from weakref import ref
from qt.core import QApplication, QHeaderView, QTimer, QWidget, QHBoxLayout, Qt, QEvent, QSize, QPersistentModelIndex


class SourcePillCell(QWidget):
    """Let the column measure its actual icon/pill layout, including scaling."""
    def bind(self, table, row, column):
        self._table = ref(table)
        self._index = QPersistentModelIndex(table.model().index(row,column))
        for i in range(self.layout().count()):
            widget=self.layout().itemAt(i).widget()
            if widget is not None:widget.installEventFilter(self)
        self._sync_width()

    def _sync_width(self):
        index=getattr(self,'_index',None)
        if index is None or not index.isValid():return
        table=self._table()
        if table is None or table.cellWidget(index.row(),index.column()) is not self:return
        item=table.item(index.row(),index.column())
        if item is None:return
        layout=self.layout()
        for i in range(layout.count()):
            widget=layout.itemAt(i).widget()
            if widget is None:continue
            # A newly reparented badge can still have pre-polish metrics when
            # the table measures it. Establish its actual styled minimum before
            # asking the layout/header for a width; no delayed correction.
            widget.ensurePolished()
            minimum=max(0,widget.minimumSizeHint().width())
            if widget.minimumWidth()!=minimum:widget.setMinimumWidth(minimum)
        wanted=QSize(self.layout().minimumSize().width()+2,0)
        if item.sizeHint()!=wanted:item.setSizeHint(wanted)

    def event(self, event):
        result=super().event(event)
        if event.type()==QEvent.Type.LayoutRequest:self._sync_width()
        return result

    def eventFilter(self, watched, event):
        # Native icon/font metrics can settle on first exposure/DPR after the
        # parent's LayoutRequest. Recheck before drawing, with no timer. These
        # filters belong only to this cell's children and retire with the cell.
        if event.type() in (QEvent.Type.Show, QEvent.Type.Paint):self._sync_width()
        return False


class FinalOutputViewMixin:
    def _init_output_view(self):
        self._review_widget_rows = set()
        self._review_widget_busy = False
        self._review_population = None
        self._review_population_timer = QTimer(self)
        self._review_population_timer.setSingleShot(True)
        self._review_population_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._review_population_timer.timeout.connect(self._populate_review_rows)
        self._review_widget_timer = QTimer(self)
        self._review_widget_timer.setSingleShot(True)
        self._review_widget_timer.timeout.connect(self._materialize_review_widgets)
        bar = self.preview_table.verticalScrollBar()
        bar.valueChanged.connect(self._schedule_review_widgets)
        bar.rangeChanged.connect(self._schedule_review_widgets)
        self.preview_table.currentCellChanged.connect(
            lambda row, *_: self._review_focus_changed(row, 0))
        self.preview_table.viewport().installEventFilter(self)

    def _schedule_review_widgets(self, *_):
        if not self._closing:
            self._review_widget_timer.start(0)

    @contextmanager
    def _review_table_batch(self):
        table = self.preview_table
        header = table.horizontalHeader()
        modes = {c: header.sectionResizeMode(c) for c in (2, 5, 6, 7)}
        signals = table.blockSignals(True)
        updates = table.updatesEnabled()
        table.setUpdatesEnabled(False)
        for column in modes:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        try:
            yield
        finally:
            for column, mode in modes.items():
                header.setSectionResizeMode(column, mode)
            table.blockSignals(signals)
            table.setUpdatesEnabled(updates)

    def _reset_review_widgets(self):
        self._cancel_review_population()
        self._review_widget_timer.stop()
        for index in self._review_widget_rows:
            for column in (0, 1, 3, 5):
                self.preview_table.removeCellWidget(index, column)
        self._review_widget_rows.clear()

    def _materialize_review_widgets(self):
        if (self._closing or self._review_population is not None or self._review_widget_busy or not self.preview_data or
                self.workflow_state.stage != 'finalization'):
            return
        self._review_widget_busy = True
        try:
            table = self.preview_table
            rows = self.preview_data.get('rows') or ()
            first = max(0, table.rowAt(0))
            last = table.rowAt(max(0, table.viewport().height()-1))
            if last < 0:
                last = min(len(rows)-1, first + table.viewport().height()//80)
            wanted = set(range(max(0, first-2), min(len(rows), last+3)))
            focus_row = getattr(self, '_review_focus_row', -1)
            if 0 <= focus_row < len(rows):
                wanted.add(focus_row)
            # A wheel gesture must not discard an editor's uncommitted text.
            focused = QApplication.focusWidget()
            for index in self._review_widget_rows:
                editor = table.cellWidget(index, 3)
                if editor is not None and focused is not None and editor.isAncestorOf(focused):
                    wanted.add(index)
            changed = wanted != self._review_widget_rows
            for index in self._review_widget_rows-wanted:
                for column in (0, 1, 3, 5):
                    table.removeCellWidget(index, column)
            for index in wanted-self._review_widget_rows:
                self._create_review_widgets(index, rows[index])
            self._review_widget_rows = wanted
            if changed:
                self._refresh_output_covers()
        finally:
            self._review_widget_busy = False

    def _create_review_widgets(self, index, row):
        from calibre_plugins.manganana.app.main import PreviewUseSelector
        data = self.preview_data
        selector = PreviewUseSelector(checked=row['selected'], enabled=not row['existing'])
        selector.changed.connect(lambda checked, i=index, owner=data:
            self._preview_use_toggled(i, checked) if self.preview_data is owner and not self._closing else None)
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(6, 0, 6, 0); layout.setSpacing(0)
        layout.addStretch(1); layout.addWidget(selector); layout.addStretch(1)
        self.preview_table.setCellWidget(index, 0, host)
        self.preview_table.setCellWidget(index, 1, self._final_output_cover_widget(row))
        self.preview_table.setCellWidget(index, 3, self._series_index_editor(index, row))
        source=self._final_output_source_widget(row)
        self.preview_table.setCellWidget(index, 5, source)
        source.bind(self.preview_table,index,5)

    def _start_review_population(self):
        """Publish all rows in short GUI turns; no partial plan can be processed."""
        table=self.preview_table;header=table.horizontalHeader()
        controls=(self.output_format,self.cover_mode,self.covers,self.pad,self.title,self.author,self.series,
                  self.renumber_outputs_btn,self.edit_output_metadata_btn)
        modes={c:header.sectionResizeMode(c)for c in (2,5,6,7)}
        read=Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        self._review_population=dict(data=self.preview_data,request=self._preview_request_id,
            signature=self.current_signature(),index=0,modes=modes,enabled=table.isEnabled(),
            controls=[(widget,widget.isEnabled())for widget in controls],
            flags=(read,read|Qt.ItemFlag.ItemIsEditable,int(Qt.AlignmentFlag.AlignCenter)))
        self._preview_build_signature=self._review_population['signature']
        self.workflow_state.finalization_stale=True
        self.download_btn.setEnabled(False);self._set_cancel_action(True,'Cancel Finalization Preparation')
        for widget in controls:widget.setEnabled(False)
        for column in modes:header.setSectionResizeMode(column,QHeaderView.ResizeMode.Fixed)
        table.setEnabled(False);table.setRowCount(len(self.preview_data.get('rows')or()))
        table.setVisible(True)
        self._populate_review_rows()

    def _cancel_review_population(self, discard=True):
        if not hasattr(self,'_review_population_timer'):return False
        self._review_population_timer.stop()
        state=self._review_population
        if state is None:return False
        self._review_population=None
        for column,mode in state['modes'].items():self.preview_table.horizontalHeader().setSectionResizeMode(column,mode)
        self.preview_table.setEnabled(state['enabled'])
        for widget,enabled in state['controls']:widget.setEnabled(enabled)
        if discard and self.preview_data is state['data']:
            self.preview_data=None;self.preview_signature=None;self.preview_table.setRowCount(0)
        return True

    def _populate_review_rows(self):
        state=self._review_population
        if state is None:return
        if (self._closing or self._review_cancel_requested or self.workflow_state.stage!='finalization' or
                state['data'] is not self.preview_data or state['request']!=self._preview_request_id or
                state['signature']!=self.current_signature()):
            self._invalidate_inflight_preview()
            return
        rows=state['data'].get('rows')or();deadline=perf_counter()+.005
        table=self.preview_table;signals=table.blockSignals(True);updates=table.updatesEnabled()
        table.setUpdatesEnabled(False)
        try:
            while state['index']<len(rows):
                index=state['index'];self._append_review_table_row(index,rows[index],state['flags'])
                state['index']+=1
                if perf_counter()>=deadline:break
        finally:
            table.blockSignals(signals);table.setUpdatesEnabled(updates)
        if state['index']<len(rows):
            self.progress_text.setText(f'Preparing Final Outputs: {state["index"]} / {len(rows)}')
            # Yield to native paint/input timers between bounded work slices;
            # continuously requeued zero timers can starve them on Windows.
            self._review_population_timer.start(1)
        else:
            self._cancel_review_population(discard=False)
            self._finish_review_presentation(state['data'])
