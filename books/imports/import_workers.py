"""Qt worker adapters for local acquisition; page processing remains in the shared renderer."""
from io import BytesIO
from pathlib import Path
import shutil
import tempfile
import time
from PIL import Image
from qt.core import QThread, pyqtSignal
from calibre_plugins.manganana.books.imports.local_import import (
    inspect_book,
    import_plan,
    preview_records,
    staged_pages,
    cover_bytes,
)
from calibre_plugins.manganana.books.output.book_export import comicinfo_for_import, write_book
from calibre_plugins.manganana.books.imaging.cover_rendering import render_cover
from calibre_plugins.manganana.books.output.output_series_metadata import effective_output_metadata
from calibre_plugins.manganana.books.imaging.page_rendering import final_workers, ordered_render
from calibre_plugins.manganana.books.imaging import native_dithering


class LocalWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled_ok = pyqtSignal()
    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def cancel(self):
        self.cancelled = True
        self.requestInterruption()

    def check(self):
        if getattr(self, 'cancelled', False) or self.isInterruptionRequested():
            raise InterruptedError('Local book operation cancelled.')

    def run(self):
        try:
            result = self.execute()
            self.check()
            self.ready.emit(result)
        except InterruptedError:
            self.cancelled_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class ImportInspectionWorker(LocalWorker):
    def __init__(self, paths):
        super().__init__(); self.paths = tuple(paths)

    def execute(self):
        books, errors = [], []
        for index, path in enumerate(self.paths, 1):
            self.check()
            self.progress.emit(int((index-1)*100/max(1,len(self.paths))),
                               f'Inspecting file {index} of {len(self.paths)}: {Path(path).name}…')
            try:
                books.append(inspect_book(path, self.check))
            except InterruptedError:
                raise
            except Exception as exc:
                errors.append(f'{Path(path).name}: {exc}')
        return dict(books=books, errors=errors)


class ImportPreviewWorker(LocalWorker):
    def __init__(self, books, overrides, output_format):
        super().__init__(); self.books = tuple(books); self.overrides = dict(overrides)
        self.output_format = output_format

    def execute(self):
        self.check()
        rows = import_plan(self.books, self.overrides, self.output_format)
        return dict(rows=rows, download_count=len(rows), existing_count=0, replacement_count=0,
                    import_mode=True)


class LocalPreviewWorker(LocalWorker):
    def __init__(self, book, layout, direction):
        super().__init__(); self.book = book; self.layout = layout; self.direction = direction

    def execute(self):
        from calibre_plugins.manganana.app.main import output_page_jobs
        # Match PairingPreviewWorker's 12-page base / 14-page ceiling. Import
        # used to render all 14, so equivalent books could show different pair
        # boundaries and overview lengths. No source image or archive changes.
        acquired = preview_records(self.book, self.check, log=self.log.emit)
        try:
            count=min(12,len(acquired))
            records=acquired[:count]
            jobs,stats=output_page_jobs(records,self.layout,self.direction,self.check)
            while self.layout=='paired_landscape' and jobs and jobs[-1]['kind']=='ISOLATED' and count<len(acquired):
                self.check();count+=1;records=acquired[:count]
                jobs,stats=output_page_jobs(records,self.layout,self.direction,self.check)
            self.check()
            self.log.emit(f'Live Preview uses {count} source pages with the shared 12-page base / 14-page ceiling.')
            for record in acquired[count:]:record['image'].close()
            return dict(volume=None, label=self.book['title'], layout=self.layout, records=records,
                        stats=stats, source_pages=len(records), output_pages=len(jobs))
        except Exception:
            for record in acquired:record['image'].close()
            raise


def render_local_cover(book, metadata, mode, include, zero_pad, check, original=None):
    metadata = dict(metadata, **effective_output_metadata(metadata, cover_mode=mode))
    if mode == 'keep' and not include:
        return None
    if mode != 'generate' and original is None:
        original = cover_bytes(book, check)
    check()
    return render_cover(original, mode=mode, title=metadata['title'], series=metadata.get('series', ''),
                        output_kind=metadata['cover_number_kind'],
                        volume=metadata['series_index'] if metadata['cover_number_kind'] == 'volume' else None, zero_pad=zero_pad)


class LocalCoverWorker(LocalWorker):
    def __init__(self, row, mode, include, zero_pad):
        super().__init__(); self.row = dict(row); self.mode = mode
        self.include = include; self.zero_pad = zero_pad

    def execute(self):
        blob = render_local_cover(self.row['book'], self.row, self.mode, self.include, self.zero_pad, self.check)
        if blob:
            with Image.open(BytesIO(blob)) as source:
                source.thumbnail((220, 300))
                out = BytesIO(); source.save(out, 'PNG'); blob = out.getvalue()
        return blob


class LocalBookWorker(LocalWorker):
    finished_ok = pyqtSignal(object)
    stats = pyqtSignal(object)

    def __init__(self, rows, processing, layout, direction, output_format, cover_mode, include_cover, zero_pad, framing=0, gutter_px=0):
        super().__init__(); self.rows = tuple(dict(row) for row in rows)
        self.processing = processing; self.layout = layout; self.direction = direction
        self.framing = framing
        self.gutter_px = gutter_px
        self.output_format = output_format; self.cover_mode = cover_mode
        self.include_cover = include_cover; self.zero_pad = zero_pad

    def run(self):
        from calibre_plugins.manganana.books.output.batch_progress import BatchProgress
        from calibre_plugins.manganana.app.main import (
            output_page_jobs,
            render_output_page,
            safe_filename,
            _validate_cbz_output,
        )
        started = time.monotonic(); work = None
        batch = BatchProgress([0] * len(self.rows))
        try:
            parent = getattr(self,'output_directory',None)
            if parent: Path(parent).mkdir(parents=True,exist_ok=True)
            work = tempfile.mkdtemp(prefix='manganana-local-output-',dir=parent)
            outputs = []; source_pages = 0
            for ordinal, row in enumerate(self.rows, 1):
                row = dict(row, **effective_output_metadata(row, output_format=self.output_format, cover_mode=self.cover_mode))
                self.check(); book = row['book']
                self.progress.emit(batch.value,f'Output {ordinal}/{len(self.rows)} · Preparing local pages...')
                self.log.emit(f'Importing {row["title"]} ({ordinal}/{len(self.rows)})…')
                # Ordinal directory avoids collisions without changing displayed titles.
                directory = Path(work) / str(ordinal); directory.mkdir()
                output = directory / (safe_filename(row['title']) + '.' + self.output_format)
                with staged_pages(book, self.check) as records:
                    original = None
                    if self.cover_mode != 'generate' and (self.include_cover or self.cover_mode == 'stamp'):
                        original = Path(records[book['cover_index']]['local_path']).read_bytes()
                    blob = render_local_cover(book, row, self.cover_mode, self.include_cover,
                                              self.zero_pad, self.check, original)
                    cover_path = None
                    if blob:
                        with Image.open(BytesIO(blob)) as cover:
                            cover_path = str(directory / 'metadata-cover.png'); cover.save(cover_path)
                    # All records, including the metadata cover page, stay in this sequence.
                    jobs, _stats = output_page_jobs(records, self.layout, self.direction, self.check, self.log.emit)
                    xml = comicinfo_for_import(book, row, len(jobs), self.layout == 'paired_landscape')
                    iterator = ordered_render(jobs, lambda job, check: render_output_page(job, self.processing, check, framing=self.framing, gutter_px=self.gutter_px),
                                              final_workers(self.processing), self.check,
                                              lambda n: self.progress.emit(batch.update(ordinal-1,'render',n,len(jobs)),
                                                                          f'Output {ordinal}/{len(self.rows)} · Processing {n}/{len(jobs)} pages...'),
                                              fallback_active=lambda: native_dithering.backend_status() != 'native')
                    write_book(output, self.output_format, iterator, row['title'], xml, self.check,
                        finalizing=lambda:self.progress.emit(batch.update(ordinal-1,'write'),
                            f'Output {ordinal}/{len(self.rows)} · Writing {self.output_format.upper()} and validating...'))
                    if self.output_format == 'cbz':
                        _validate_cbz_output(output, self.layout, self.processing)
                    self.check()
                    source_pages += len(records)
                outputs.append(dict(effective_output_metadata(row), path=str(output), title=row['title'], series=row['series'],
                                    author=row['author'], language=row.get('language', ''), volume=row.get('volume'),
                                    format=self.output_format, kind='import', import_id=row['import_id'], cover_path=cover_path))
                self.progress.emit(batch.update(ordinal-1,'settled'),f'Output {ordinal}/{len(self.rows)} prepared; Calibre import follows...')
            self.check()
            self.finished_ok.emit(dict(files=outputs, workdir=work, pages=source_pages, planned_pages=source_pages,
                                       elapsed=time.monotonic()-started, bytes=sum(r['book']['bytes'] for r in self.rows),
                                       final_bytes=sum(Path(r['path']).stat().st_size for r in outputs), skipped=0,
                                       failed_volumes=[], failed_labels=[], failures=[]))
        except Exception as exc:
            if work: shutil.rmtree(work, ignore_errors=True)
            if isinstance(exc, InterruptedError): self.cancelled_ok.emit()
            else: self.failed.emit(str(exc))
