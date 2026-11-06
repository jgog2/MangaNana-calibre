"""Streaming container writers for pages already rendered by MangaNana."""
from pathlib import Path
import os
import xml.etree.ElementTree as ET
import zipfile
from time import perf_counter

from calibre_plugins.manganana.books.imports.local_import import inspect_pdf, parse_comicinfo
from calibre_plugins.manganana.books.output.output_series_metadata import append_output_provenance


def comicinfo_for_import(book, metadata, page_count, layout_changed=False):
    root = parse_comicinfo(book.get('comicinfo'))
    if root is None:
        root = ET.Element('ComicInfo')
    controlled = dict(Title=metadata['title'], Series=metadata.get('series', ''),
                      Writer=metadata.get('author', ''), LanguageISO=metadata.get('language',book.get('language', '')),
                      PageCount=str(page_count))
    if 'series_index' in metadata:
        controlled['Number'] = f'{metadata["series_index"]:g}'
        if metadata.get('volume') is not None:
            controlled['Volume'] = controlled['Number']
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
    append_output_provenance(root, metadata)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def validate_pdf(path, expected_pages=None, check=None):
    if not Path(path).is_file() or not Path(path).stat().st_size:
        raise ValueError('PDF validation failed: empty output.')
    _values, count = inspect_pdf(path, check)
    if expected_pages is not None and count != expected_pages:
        raise ValueError(f'PDF validation failed: expected {expected_pages} pages, found {count}.')
    return count


def _write_pdf(path, pages, title, check, comicinfo=None):
    from qt.core import QPdfWriter, QPainter, QImage, QPageSize, QPageLayout, QSizeF, QMarginsF, QRectF
    writer = QPdfWriter(str(path))
    writer.setResolution(300)
    writer.setTitle(title)
    writer.setCreator('MangaNana')
    if comicinfo:
        # QPdfWriter does not expose series/index fields. XMP keeps the same
        # effective metadata and acquisition evidence as CBZ ComicInfo.
        info = ET.fromstring(comicinfo)
        xmp = ET.Element('{adobe:ns:meta/}xmpmeta')
        rdf = ET.SubElement(xmp, '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF')
        desc = ET.SubElement(rdf, '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description')
        desc.set('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about', '')
        for field in info:
            if field.text:
                ET.SubElement(desc, '{https://mangaanka.app/ns/output/1.0/}'+field.tag).text = field.text
        creator = ET.SubElement(desc, '{http://purl.org/dc/elements/1.1/}creator')
        seq = ET.SubElement(creator, '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Seq')
        ET.SubElement(seq, '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li').text = info.findtext('Writer') or ''
        writer.setDocumentXmpMetadata(ET.tostring(xmp, encoding='utf8'))
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
            count = _write_pdf(partial, pages, title, check, comicinfo)
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
