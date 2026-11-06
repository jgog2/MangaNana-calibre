"""Cover-only Finalization rendering; never acquires or processes reading pages."""
from collections import OrderedDict
from io import BytesIO

from PIL import Image
from qt.core import QThread, pyqtSignal, QTimer
from calibre_plugins.manganana.books.output.output_series_metadata import effective_output_metadata

from calibre_plugins.manganana.books.imaging.cover_rendering import badge_text, cover_title, render_cover_image
from calibre_plugins.manganana.books.imports.local_import import cover_bytes
from calibre_plugins.manganana.books.imaging.artwork_delivery import ArtworkResolver


def cover_job(row, mode, include, zero_pad, title, series, source_id, cover_url):
    """Snapshot authoritative cover inputs, excluding unrelated book settings."""
    local = row.get('kind') == 'import'
    effective = effective_output_metadata(dict(row, title=row.get('title') or title,
                                               series=row.get('series', series)), cover_mode=mode)
    title, series = effective['title'], effective['series']
    book = dict(row['book']) if local else None
    kind = effective['cover_number_kind']
    options = dict(mode=mode, title=title, series=series, output_kind=kind,
                   volume=effective['series_index'] if kind == 'volume' else None,
                   chapter_number=effective['series_index'] if kind == 'chapter' else None,
                   zero_pad=zero_pad)
    original_key = ('import', book['id'], tuple(book['identity'])) if local else ('source', source_id, cover_url)
    # Keep is byte-for-byte artwork; metadata/number edits cannot affect it.
    # Generate does not depend on source artwork or its inclusion checkbox.
    if mode == 'keep':
        key = (mode, original_key, bool(include))
    else:
        key = (mode, original_key if mode == 'stamp' else None,
               cover_title(title, series) if mode == 'generate' else None,
               badge_text(output_kind=kind, volume=options['volume'],
                          chapter_number=options['chapter_number'], zero_pad=zero_pad))
    return dict(key=key, original_key=original_key, book=book, url=cover_url,
                include=include, options=options)


class CoverBatchWorker(QThread):
    rendered = pyqtSignal(object)
    original_ready = pyqtSignal(object)

    def __init__(self, jobs, source, originals, artwork_resolver=None):
        super().__init__()
        self.jobs = jobs
        self.source = source
        self.originals = OrderedDict(originals)
        self.artwork_resolver=artwork_resolver or ArtworkResolver()
        self.provenance={}

    def check(self):
        if self.isInterruptionRequested():
            raise InterruptedError()

    def run(self):
        rendered = OrderedDict()
        for job in self.jobs:
            try:
                self.check()
                key = job['key']
                if key in rendered:
                    self.rendered.emit((job['index'], key, rendered[key], ''))
                    continue
                original = None
                mode = job['options']['mode']
                if mode != 'generate' and (mode == 'stamp' or job['include']):
                    original = self.originals.get(job['original_key']) if job['book'] else None
                    if original is None:
                        if job['book']:
                            original = cover_bytes(job['book'], self.check)
                        elif job['url']:
                            # Only missing cover artwork, never a manga page or manifest.
                            result=self.artwork_resolver.resolve_url(job['url'],self.source,self.isInterruptionRequested)
                            original=result['raw']
                            self.provenance[key]=result['candidate']
                        if original:
                            self.originals[job['original_key']] = original
                            while self.originals and sum(len(value) for value in self.originals.values()) > 16*1024*1024:
                                self.originals.popitem(last=False)
                            self.original_ready.emit((job['original_key'], original))
                        self.check()
                preview = None if mode == 'keep' and not job['include'] else render_cover_image(original, **job['options'])
                blob=None
                if preview is not None:
                    preview.thumbnail((220, 300), getattr(Image, 'Resampling', Image).LANCZOS)
                    buffer = BytesIO(); preview.save(buffer, 'PNG'); blob = buffer.getvalue()
                self.check()
                rendered[key] = blob
                while rendered and (len(rendered) > 128 or sum(len(value or b'') for value in rendered.values()) > 8*1024*1024):
                    rendered.popitem(last=False)
                self.rendered.emit((job['index'], key, blob, ''))
            except InterruptedError:
                return
            except Exception as exc:
                if not self.isInterruptionRequested():
                    self.rendered.emit((job['index'], job['key'], None, str(exc)))


class FinalizationCoverMixin:
    def _init_finalization_covers(self):
        self._cover_revision = 0
        self._cover_worker = None
        self._cover_pending_jobs = ()
        self._cover_originals = OrderedDict()
        self._cover_renders = OrderedDict()
        self._cover_request = None
        self._output_metadata_overrides = {}
        self._output_override_scope = None
        self._cover_update_timer = QTimer(self)
        self._cover_update_timer.setSingleShot(True); self._cover_update_timer.setInterval(0)
        self._cover_update_timer.timeout.connect(self._refresh_output_covers)

    def _schedule_output_covers(self):
        # The refresh compares exact render keys. Unrelated edits should neither
        # discard valid thumbnails nor cancel a worker already rendering them.
        self._cover_update_timer.start()

    def _cancel_output_covers(self):
        self._cover_update_timer.stop()
        self._cover_revision += 1
        self._cover_pending_jobs = ()
        self._cover_request = None
        if self._cover_worker:
            self._cover_worker.requestInterruption()

    @staticmethod
    def _cache_cover(cache, key, blob, limit):
        cache[key] = blob
        cache.move_to_end(key)
        while cache and (len(cache) > 128 or sum(len(value or b'') for value in cache.values()) > limit):
            cache.popitem(last=False)

    def _refresh_output_covers(self):
        self._cover_update_timer.stop()
        if self._closing or not self.preview_data or self.workflow_state.stage != 'finalization':
            return
        title, _author, series = self._applied_metadata_values()
        rows = self.preview_data.get('rows') or ()
        visible=getattr(self,'_review_widget_rows',None)
        indices=sorted(visible) if visible is not None else range(len(rows))
        specs = [(index,cover_job(rows[index], self.cover_mode.currentData(), self.covers.isChecked(),
                           self.pad.isChecked(), title, series, self.current_source_id,
                           self._planned_output_cover_url(rows[index]))) for index in indices]
        request = (id(self.preview_data), tuple((index,job['key']) for index,job in specs))
        if (request == self._cover_request and self._cover_worker
                and not self._cover_worker.isInterruptionRequested()):
            return
        self._cover_request = request
        self._cover_revision += 1
        if self._cover_worker:
            self._cover_worker.requestInterruption()
        jobs = []
        for index, job in specs:
            row=rows[index]
            url = self._planned_output_cover_url(row)
            job['index'] = index
            candidate=self._get_artwork_resolver().winner_for_url(url,self.current_source)
            if candidate:
                row['artwork_source']=candidate.source
                row['effective_cover_url']=candidate.url
            # Retain a row's current render even if the session LRU evicted it.
            if row.get('cover_key') == job['key'] and row.get('cover_state') in ('ready', 'empty'):
                continue
            row['cover_key'] = job['key']; row.pop('cover_thumbnail', None)
            row.pop('cover_error', None)
            if job['key'] in self._cover_renders:
                row['cover_thumbnail'] = self._cover_renders[job['key']]
                row['cover_state'] = 'ready' if row['cover_thumbnail'] else 'empty'
            else:
                row['cover_state'] = 'loading'; jobs.append(job)
            if index in getattr(self,'_review_widget_rows',{index}):
                self.preview_table.setCellWidget(index, 1, self._final_output_cover_widget(row))
        self._cover_pending_jobs = tuple(jobs)
        self._start_cover_batch()

    def _start_cover_batch(self):
        if self._closing or self._cover_worker or not self._cover_pending_jobs:
            return
        jobs, self._cover_pending_jobs = self._cover_pending_jobs, ()
        revision = self._cover_revision
        data = self.preview_data
        worker = self._retain_async_worker(CoverBatchWorker(
            jobs, self.current_source, self._cover_originals,self._get_artwork_resolver()))
        self._cover_worker = worker
        def original(result):
            if not self._closing and revision == self._cover_revision and data is self.preview_data:
                self._cache_cover(self._cover_originals, result[0], result[1], 16*1024*1024)
        def ready(result):
            if (self._closing or revision != self._cover_revision or data is not self.preview_data
                    or self.workflow_state.stage != 'finalization'
                    or self.preview_signature != self.current_signature()):
                return
            index, key, blob, error = result
            rows = data.get('rows') or ()
            if index >= len(rows) or rows[index].get('cover_key') != key:
                return
            row = rows[index]
            candidate=worker.provenance.get(key)
            if candidate:
                row['artwork_source']=candidate.source
                row['effective_cover_url']=candidate.url
            row['cover_thumbnail'] = blob; row['cover_error'] = error
            row['cover_state'] = 'error' if error else ('ready' if blob else 'empty')
            if not error:
                self._cache_cover(self._cover_renders, key, blob, 8*1024*1024)
            else:
                self.add_log(f'Cover unavailable for {row["title"]}: {error}')
            if index in getattr(self,'_review_widget_rows',{index}):
                self.preview_table.setCellWidget(index, 1, self._final_output_cover_widget(row))
        def finished():
            if self._cover_worker is worker:
                self._cover_worker = None
                self._start_cover_batch()
        worker.original_ready.connect(original)
        worker.rendered.connect(ready)
        worker.finished.connect(finished)
        worker.start()
