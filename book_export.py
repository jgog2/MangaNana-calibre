"""Streaming container writers for pages already rendered by MangaNana."""
from pathlib import Path
import os
import xml.etree.ElementTree as ET
import zipfile
from time import perf_counter

try:
    from .local_import import inspect_pdf, parse_comicinfo
except ImportError:
    from local_import import inspect_pdf, parse_comicinfo


def comicinfo_for_import(book, metadata, page_count, layout_changed=False):
    root = parse_comicinfo(book.get('comicinfo'))
    if root is None:
        root = ET.Element('ComicInfo')
    controlled = dict(Title=metadata['title'], Series=metadata.get('series', ''),
                      Writer=metadata.get('author', ''), LanguageISO=book.get('language', ''),
                      PageCount=str(page_count))
    for tag, value in controlled.items():
        for old in list(root.findall(tag)):
            root.remove(old)
        ET.SubElement(root, tag).text = str(value)
    # Page mappings belong to the original sequence; preserve only if it still matches.
    if layout_changed:
        for old in list(root.findall('Pages')):
            root.remove(old)
    else:
        for pages in root.findall('Pages'):
            for page in list(pages):
                try:
                    valid = page.tag == 'Page' and 0 <= int(page.get('Image', '')) < page_count
                except ValueError:
                    valid = False
                if not valid:
                    pages.remove(page)
                else:
                    for attribute in ('ImageSize', 'ImageWidth', 'ImageHeight'):
                        page.attrib.pop(attribute, None)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def validate_pdf(path, expected_pages=None, check=None):
    if not Path(path).is_file() or not Path(path).stat().st_size:
        raise ValueError('PDF validation failed: empty output.')
    _values, count = inspect_pdf(path, check)
    if expected_pages is not None and count != expected_pages:
        raise ValueError(f'PDF validation failed: expected {expected_pages} pages, found {count}.')
    return count


def _write_pdf(path, pages, title, check):
    from qt.core import QPdfWriter, QPainter, QImage, QPageSize, QPageLayout, QSizeF, QMarginsF, QRectF
    writer = QPdfWriter(str(path))
    writer.setResolution(300)
    writer.setTitle(title)
    writer.setCreator('MangaNana')
    painter = QPainter()
    count = 0
    try:
        for _index, (_ext, blob, _kind) in pages:
            if check: check()
            image = QImage.fromData(blob)
            if image.isNull():
                raise ValueError('Cannot export an unreadable rendered page to PDF.')
            size = QPageSize(QSizeF(image.width()/300, image.height()/300), QPageSize.Unit.Inch,
                             'MangaNana page', QPageSize.SizeMatchPolicy.ExactMatch)
            layout = QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0),
                                 QPageLayout.Unit.Inch)
            layout.setMode(QPageLayout.Mode.FullPageMode)
            if not writer.setPageLayout(layout):
                raise RuntimeError('PDF writer rejected the rendered page dimensions.')
            if count:
                if not writer.newPage():
                    raise OSError('Could not write the next PDF page. Check available disk space.')
            elif not painter.begin(writer):
                raise OSError('Could not open PDF output. Check permissions and available disk space.')
            painter.drawImage(QRectF(0, 0, writer.width(), writer.height()), image)
            count += 1
        if not count:
            raise ValueError('Cannot export a book with no pages.')
    finally:
        if painter.isActive():
            painter.end()
        del painter
        del writer  # Flush the PDF before pdfinfo and atomic replacement.
    return count


def write_book(output, output_format, pages, title='', comicinfo=None, check=None, finalizing=None, metrics=None):
    if output_format not in ('cbz', 'pdf'):
        raise ValueError('Unsupported output format.')
    partial = Path(str(output) + '.part')
    metrics = metrics if metrics is not None else {}
    metrics['write_seconds'] = 0.0
    try:
        if output_format == 'pdf':
            count = _write_pdf(partial, pages, title, check)
            if finalizing: finalizing()
            validate_pdf(partial, count, check)
        else:
            count = 0
            with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_STORED) as archive:
                for index, (ext, blob, _kind) in pages:
                    if check: check()
                    started = perf_counter()
                    archive.writestr(f'{index+1:05d}{ext}', blob)
                    metrics['write_seconds'] += perf_counter() - started
                    count += 1
                if not count:
                    raise ValueError('Cannot export a book with no pages.')
                if finalizing: finalizing()
                started = perf_counter()
                if comicinfo:
                    archive.writestr('ComicInfo.xml', comicinfo)
            metrics['write_seconds'] += perf_counter() - started
            with zipfile.ZipFile(partial) as archive:
                if archive.testzip():
                    raise ValueError('CBZ validation failed.')
        if check: check()
        os.replace(partial, output)
        return count
    finally:
        close = getattr(pages, 'close', None)
        if close: close()
        partial.unlink(missing_ok=True)
