"""Local-book UI/state extension; source discovery and processing controls stay independent."""
from pathlib import Path
from qt.core import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QTableWidget, QTableWidgetItem, QFileDialog, Qt, QAbstractItemView
from .import_workers import ImportInspectionWorker, ImportPreviewWorker, LocalBookWorker
from .local_import import series_index


class ImportWorkflowMixin:
    def _init_import_workflow(self):
        self._import_books = []
        self._selected_import_ids = set()
        self._import_generation = 0
        self._import_inspection = None
        self._import_inspection_message = ''
        self._import_overrides = {}
        self._import_edited_fields = set()

    def _build_import_ui(self):
        self.import_mode_btn = QPushButton('Import')
        self.import_mode_btn.setCheckable(True); self.import_mode_btn.setObjectName('modeChoice')
        self.import_mode_btn.setAutoDefault(False)
        self._mode_row.insertWidget(3, self.import_mode_btn)
        self.import_mode_btn.clicked.connect(lambda: self._set_workflow_mode('import'))
        self.import_panel = self._card()
        layout = QVBoxLayout(self.import_panel)
        layout.addWidget(self.heading('Imported Books'))
        note = QLabel('Browse local CBZ or PDF files. Each selected file becomes its own book.\nPDF pages are imported at 300 DPI.'); note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        self.import_browse_btn = QPushButton('Browse CBZ / PDF…')
        self.import_browse_btn.clicked.connect(self._browse_imports)
        self.import_select_btn = QPushButton('Select All'); self.import_clear_btn = QPushButton('Clear')
        self.import_remove_btn = QPushButton('Remove Selected')
        for button in (self.import_browse_btn, self.import_select_btn, self.import_clear_btn, self.import_remove_btn):
            button.setObjectName('secondaryAction'); button.setAutoDefault(False); actions.addWidget(button)
        self.import_select_btn.clicked.connect(lambda: self._select_imports(True))
        self.import_clear_btn.clicked.connect(lambda: self._select_imports(False))
        self.import_remove_btn.clicked.connect(self._remove_imports)
        layout.addLayout(actions)
        self.import_table = QTableWidget(0, 4)
        self.import_table.setHorizontalHeaderLabels(['Use', 'Book', 'Format', 'Pages'])
        self.import_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.import_table.verticalHeader().hide()
        from qt.core import QHeaderView
        self.import_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.import_table.setColumnWidth(0, 40); self.import_table.setColumnWidth(2, 65); self.import_table.setColumnWidth(3, 65)
        self.import_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.import_status = QLabel('No imported books.'); self.import_status.setWordWrap(True)
        layout.addWidget(self.import_status)
        layout.addWidget(self.import_table, 1)
        self._discovery_search_layout.addWidget(self.import_panel, 1)
        self.import_panel.hide()
        for key, field in (('title', self.title), ('series', self.series), ('author', self.author)):
            field.textEdited.connect(lambda _text, name=key: self._import_edited_fields.add(name) if self.workflow_mode == 'import' else None)
        self._update_output_format_text()

    def _selected_import_books(self):
        return [b for b in self._import_books if b['id'] in self._selected_import_ids]

    def _reset_import_selection(self):
        self._import_generation += 1
        if self._import_inspection:
            self._import_inspection.requestInterruption()
        self._import_inspection = None
        self._import_inspection_message = ''
        self._import_books = []; self._selected_import_ids.clear()
        self._import_overrides.clear(); self._import_edited_fields.clear()
        if hasattr(self, 'import_table'): self.import_table.setRowCount(0)
        if hasattr(self, 'import_browse_btn'): self.import_browse_btn.setEnabled(True)
        if hasattr(self, 'import_status'): self.import_status.setText('No imported books.')

    def _sync_import_mode(self):
        local = self.workflow_mode == 'import'
        self.import_mode_btn.setChecked(local)
        self.import_panel.setVisible(local); self._source_selected_page.setVisible(not local)
        self._discovery_gutter.setVisible(not local)
        for widget in self._source_discovery_widgets:
            widget.setVisible(not local)
        alignment = Qt.AlignmentFlag.AlignTop if local else Qt.AlignmentFlag(0)
        for layout in (self._discovery_card_layout, self._discovery_search_layout,
                       self._search_top_panel.layout()):
            layout.setAlignment(alignment)
        self._sync_discovery_top_heights()
        if not local: self.show_more_btn.setVisible(any(self._search_has_more.values()))
        for widget in (self.search_box, self.search_btn, self.url, self.load_btn, self.language):
            widget.setEnabled(not local and self.workflow_mode is not None)
        self.title.setEnabled(not local or len(self._selected_import_books()) == 1)
        self.download_btn.setText('Process && Add to Calibre' if local else 'Download && Add to Calibre')
        self.mode_helper.setText('Browse local CBZ or PDF files to begin.' if local else 'Choose Volumes, Chapters, or Import to begin.')
        self._sync_cover_mode_controls()
        self._update_output_format_text()
        self._update_workflow_actions()

    def _sync_import_cover_controls(self):
        local = self.workflow_mode == 'import'
        chapter = self.workflow_mode == 'chapter'
        self.covers.setText('Use imported cover page in Calibre metadata' if local else
                            ('Use series cover in Calibre metadata' if chapter else 'Use source volume cover in Calibre metadata'))
        self.pad.setText('Zero-pad cover numbers (Recommended)' if local else
                         ('Zero-pad chapter numbers (Recommended)' if chapter else 'Zero-pad volume numbers (Recommended)'))
        applicable = not local or (self.cover_mode.currentData() != 'keep' and
                                   any(series_index(book) is not None for book in self._selected_import_books()))
        self.pad.setVisible(applicable)
        self.pad.setEnabled(applicable and not self._download_in_progress)

    def _browse_imports(self):
        paths, _filter = QFileDialog.getOpenFileNames(self, 'Import Books', '', 'Books (*.cbz *.pdf)')
        if paths: self._inspect_import_paths(paths)

    def _inspect_import_paths(self, paths):
        if self.workflow_mode != 'import' or self._download_in_progress:
            return
        self._import_generation += 1; generation = self._import_generation
        paths = tuple(paths)
        if self._import_inspection: self._import_inspection.requestInterruption()
        worker = self._retain_async_worker(ImportInspectionWorker(paths))
        self._import_inspection = worker
        self._import_inspection_message = f'Inspecting {len(paths)} file' + ('s…' if len(paths) != 1 else '…')
        self.import_status.setText(self._import_inspection_message)
        self.import_browse_btn.setEnabled(False)
        def ready(data):
            if self._closing or generation != self._import_generation or self.workflow_mode != 'import': return
            identities = {tuple(b['identity']) for b in self._import_books}
            for book in data['books']:
                if tuple(book['identity']) not in identities:
                    self._import_books.append(book); self._selected_import_ids.add(book['id'])
                    identities.add(tuple(book['identity']))
            self._refresh_import_table(); self._import_selection_changed()
            count = len(self._import_books)
            self.import_status.setText('\n'.join(data['errors']) or f'{count} imported ' + ('book.' if count == 1 else 'books.'))
            for error in data['errors']: self.add_log('Import failed: ' + error)
        def finished():
            if self._import_inspection is worker:
                self._import_inspection = None; self.import_browse_btn.setEnabled(True)
                self._import_inspection_message = ''
                self._update_workflow_actions()
        def progress(_percent, message):
            if self._closing or generation != self._import_generation or self.workflow_mode != 'import': return
            self._import_inspection_message = message
            self.import_status.setText(message); self._update_workflow_actions()
        worker.progress.connect(progress)
        worker.ready.connect(ready)
        worker.failed.connect(lambda message: self.import_status.setText(message)
                              if generation == self._import_generation and self.workflow_mode == 'import' and not self._closing else None)
        worker.finished.connect(finished); worker.start()
        self._update_workflow_actions()

    def _refresh_import_table(self):
        self.import_table.setRowCount(len(self._import_books))
        for index, book in enumerate(self._import_books):
            selector = QCheckBox()
            selector.setObjectName('importUseCheckbox')
            selector.setStyleSheet('''
                QCheckBox#importUseCheckbox { background:transparent; padding:0; spacing:0; }
                QCheckBox#importUseCheckbox::indicator {
                    width:14px; height:14px; border:1px solid #50555A;
                    border-radius:2px; background:#121416;
                }
                QCheckBox#importUseCheckbox::indicator:unchecked:hover,
                QCheckBox#importUseCheckbox::indicator:unchecked:focus {
                    border-color:#FF6740; background:#191C1F;
                }
                QCheckBox#importUseCheckbox::indicator:checked {
                    border-color:#FF6740; background:#FF6740;
                    image:url(:/qt-project.org/styles/commonstyle/images/standardbutton-apply-16.png);
                }
                QCheckBox#importUseCheckbox::indicator:checked:hover,
                QCheckBox#importUseCheckbox::indicator:checked:focus {
                    border-color:#FF8A6B; background:#FF7B5A;
                }
            ''')
            selector.setChecked(book['id'] in self._selected_import_ids)
            selector.setToolTip('Use this imported book')
            selector.toggled.connect(lambda checked, bid=book['id']: self._toggle_import(bid, checked))
            selector_host = QWidget()
            selector_layout = QHBoxLayout(selector_host)
            selector_layout.setContentsMargins(0, 0, 0, 0); selector_layout.setSpacing(0)
            selector_layout.addWidget(selector, 0, Qt.AlignmentFlag.AlignCenter)
            self.import_table.setCellWidget(index, 0, selector_host)
            for col, text in enumerate((book['title'], book['format'].upper(), str(book['pages'])), 1):
                self.import_table.setItem(index, col, QTableWidgetItem(text))
            self.import_table.setRowHeight(index, 38)

    def _toggle_import(self, identity, checked):
        if checked: self._selected_import_ids.add(identity)
        else: self._selected_import_ids.discard(identity)
        self._import_selection_changed()

    def _select_imports(self, checked):
        self._selected_import_ids = {b['id'] for b in self._import_books} if checked else set()
        self._refresh_import_table(); self._import_selection_changed()

    def _remove_imports(self):
        self._import_books = [b for b in self._import_books if b['id'] not in self._selected_import_ids]
        self._selected_import_ids.clear()
        self._refresh_import_table(); self._import_selection_changed()
        if self._import_inspection is None:
            count = len(self._import_books)
            self.import_status.setText(f'{count} imported ' + ('book.' if count == 1 else 'books.') if count else 'No imported books.')

    def _import_selection_changed(self):
        books = self._selected_import_books()
        self._import_overrides.clear(); self._import_edited_fields.clear()
        if len(books) == 1:
            book = books[0]; self._set_applied_metadata(book['title'], book['author'], book['series'])
        else:
            self._set_applied_metadata('Multiple imported titles' if books else '', '', '')
        self.title.setEnabled(len(books) == 1)
        self.series.setPlaceholderText('Apply explicitly to all selected books' if len(books) > 1 else '')
        self.author.setPlaceholderText('Apply explicitly to all selected books' if len(books) > 1 else '')
        self._sync_import_cover_controls()
        self.invalidate_preview()

    def _import_signature(self):
        return ('import', tuple((b['id'], tuple(b['identity'])) for b in self._selected_import_books()),
                tuple(sorted(self._import_overrides.items())), self.covers.isChecked(), self.pad.isChecked(),
                self.cover_mode.currentData(), self.output_format.currentData(), self.page_layout.currentData(),
                self.reading_direction.currentData(), self.current_processing_settings())

    def _import_update_actions(self):
        selected = bool(self._selected_import_books()) and self._import_inspection is None
        stage = self.workflow_state.stage
        self._set_action_role(self.preview_btn, 'primaryAction')
        self.preview_btn.setEnabled(selected and stage != 'finalization')
        current = bool(self.preview_data and self.preview_signature == self.current_signature()
                       and not self.workflow_state.finalization_stale)
        allowed = (stage == 'finalization' and selected and current and not self._metadata_pending
                   and bool(self.preview_data.get('selected_download_count')) and not self._download_in_progress)
        self.download_btn.setEnabled(allowed)
        self._set_action_role(self.download_btn, 'primaryAction' if allowed else 'tertiaryAction')
        if self._import_inspection: message = self._import_inspection_message
        elif not selected: message = 'Browse and select at least one imported book.'
        elif stage == 'book_customization': message = 'Live Preview is optional.'
        elif stage == 'finalization' and self._metadata_pending: message = 'Apply pending metadata edits before processing.'
        elif stage == 'finalization' and not current: message = 'Refresh Final Outputs to continue.'
        else: message = ''
        self.workflow_hint.setText(message)

    def _prepare_import_finalization(self):
        if not self._selected_import_books(): return
        self._preview_request_id += 1; request = self._preview_request_id
        signature = self.current_signature(); self._preview_build_signature = signature
        self._review_cancel_requested = False
        worker = ImportPreviewWorker(self._selected_import_books(), self._import_overrides, self.output_format.currentData())
        self.preview_worker = worker; self._preview_workers.append(worker)
        worker.ready.connect(lambda data: self.on_preview_ready(data, request, signature))
        worker.failed.connect(lambda error: self.on_preview_failed(error, request, signature))
        worker.cancelled_ok.connect(lambda: self.on_preview_cancelled(request, signature))
        worker.finished.connect(lambda: self._cleanup_worker(worker, self._preview_workers))
        worker.finished.connect(lambda: self._on_preview_worker_finished(worker, request, signature))
        worker.finished.connect(worker.deleteLater)
        self._set_cancel_action(True, 'Cancel Finalization Preparation')
        self._update_workflow_actions(); worker.start()

    def _apply_import_metadata(self):
        if not self.preview_data or self._preview_build_signature is not None: return
        fields = {'title': self.title, 'series': self.series, 'author': self.author}
        edited = set(self._import_edited_fields)
        if len(self._selected_import_books()) != 1: edited.discard('title')
        if 'title' in edited and not self.title.text().strip():
            self.metadata_pending_label.setText('Title is required.'); return
        for key in edited: self._import_overrides[key] = fields[key].text().strip()
        for row in self.preview_data['rows']:
            row.update(self._import_overrides); row.pop('cover_thumbnail', None)
        self._set_applied_metadata(self.title.text(), self.author.text(), self.series.text(), sync_fields=False)
        self._import_edited_fields.clear()
        self.on_preview_ready(self.preview_data)

    def _start_import_output(self):
        if self._metadata_pending or not self.preview_data or self.preview_signature != self.current_signature():
            self.workflow_hint.setText('Apply metadata and refresh Final Outputs before processing.'); return
        rows = [r for r in self.preview_data['rows'] if r.get('selected')]
        if not rows: return
        self._check_download_disk_space()
        self._active_replace_existing = False
        self._set_download_ui_locked(True); self._set_work_progress_visible(True)
        self._toggle_activity_log(True)
        worker = LocalBookWorker(rows, self.current_processing_settings(), self.page_layout.currentData(),
                                 self.reading_direction.currentData(), self.output_format.currentData(),
                                 self.cover_mode.currentData(), self.covers.isChecked(), self.pad.isChecked())
        self.worker = worker
        worker.log.connect(self.add_log); worker.progress.connect(self.on_progress)
        worker.failed.connect(self.on_failed); worker.cancelled_ok.connect(self.on_cancelled)
        worker.finished_ok.connect(self.on_downloaded)
        self._retain_async_worker(worker); worker.start()

    def _update_output_format_text(self):
        if not hasattr(self, 'output_format'): return
        fmt = self.output_format.currentData().upper()
        self.volume_output_note.setText(f'Selected volumes will be created as individual {fmt} files.')
        self.chapter_output_combo.setItemText(0, f'Build {fmt}s from Volume Data')
        self.chapter_output_combo.setItemText(2, f'Save Each Chapter as Its Own {fmt}')

    def _output_format_changed(self):
        from .config import prefs
        prefs['output_format'] = self.output_format.currentData()
        self._update_output_format_text()
        # Container choice never changes acquisition or processed-page cache ownership.
        previous = (self.workflow_state.preview_state, self.workflow_state.preview_stale)
        self.invalidate_preview()
        self.workflow_state.preview_state, self.workflow_state.preview_stale = previous
