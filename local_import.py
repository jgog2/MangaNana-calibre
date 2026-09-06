"""Local container inspection and disk-backed acquisition; independent of Qt UI."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageOps

IMAGE_SUFFIXES = frozenset(('.jpg', '.jpeg', '.png', '.webp'))
PDF_DPI = 300
PDF_PREVIEW_DPI = 100
MAX_COMICINFO = 1024 * 1024
PREVIEW_MEMORY_LIMIT = 128 * 1024 * 1024


def check_cancelled(check=None):
    if check:
        check()


def file_identity(path):
    path = Path(path).resolve(strict=True)
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns


def natural_key(value):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r'(\d+)', str(value)))


def _image_member(info):
    parts = PurePosixPath(info.filename.replace('\\', '/')).parts
    return (not info.is_dir() and parts and
            not any(part.startswith('.') or part == '__MACOSX' for part in parts) and
            PurePosixPath(parts[-1]).suffix.lower() in IMAGE_SUFFIXES)


def parse_comicinfo(data):
    try:
        if not data or len(data) > MAX_COMICINFO or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            return None
        root = ET.fromstring(data)
        return root if root.tag == 'ComicInfo' else None
    except ET.ParseError:
        return None


def poppler_tools():
    from calibre.ebooks.metadata.pdf import get_tools
    info, raster = get_tools()
    if not Path(info).is_file() or not Path(raster).is_file():
        raise RuntimeError('Calibre bundled PDF tools are unavailable. Repair the Calibre installation.')
    return str(info), str(raster)


def run_tool(arguments, check=None):
    """Drain output to disk, poll cancellation, and always reap the child."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(list(map(str, arguments)), stdout=stdout, stderr=stderr,
                                   creationflags=flags)
        try:
            while True:
                check_cancelled(check)
                try:
                    process.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
            check_cancelled(check)
            stdout.seek(0); stderr.seek(0)
            output = stdout.read(MAX_COMICINFO).decode('utf-8', 'replace')
            error = stderr.read(8192).decode('utf-8', 'replace')
            if process.returncode:
                if any(word in error.lower() for word in ('password', 'encrypted')):
                    raise ValueError('Encrypted/password-protected PDFs are not supported.')
                raise RuntimeError('PDF tool failed: ' + (error.strip() or str(process.returncode)))
            return output
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()


def inspect_pdf(path, check=None):
    output = run_tool([poppler_tools()[0], path], check)
    values = dict((key.strip(), value.strip()) for line in output.splitlines()
                  if ':' in line for key, value in [line.split(':', 1)])
    if values.get('Encrypted', '').lower().startswith('yes'):
        raise ValueError('Encrypted/password-protected PDFs are not supported.')
    try:
        count = int(values['Pages'])
        if count < 1:
            raise ValueError()
    except (KeyError, ValueError):
        raise ValueError('PDF contains no readable pages.')
    return values, count


def inspect_book(path, check=None):
    identity = file_identity(path)
    path = Path(identity[0]); fmt = path.suffix.lower().lstrip('.')
    book = dict(id=uuid.uuid4().hex, identity=identity, path=str(path), format=fmt,
                title=path.stem, series='', author='', language='', number='', volume='',
                comicinfo=None, cover_index=0, bytes=identity[1])
    check_cancelled(check)
    if fmt == 'cbz':
        try:
            with zipfile.ZipFile(path) as archive:
                members = sorted((i for i in archive.infolist() if _image_member(i)),
                                 key=lambda i: natural_key(i.filename))
                if not members:
                    raise ValueError('CBZ contains no supported image pages.')
                if any(i.flag_bits & 1 for i in members):
                    raise ValueError('Encrypted CBZ archives are not supported.')
                book['members'] = tuple(i.header_offset for i in members)
                book['pages'] = len(members)
                meta = next((i for i in archive.infolist()
                             if PurePosixPath(i.filename).name.casefold() == 'comicinfo.xml'
                             and i.file_size <= MAX_COMICINFO), None)
                try:
                    raw = archive.read(meta) if meta else None
                    root = parse_comicinfo(raw)
                except (RuntimeError, zipfile.BadZipFile):
                    root = None
                if root is not None:
                    book['comicinfo'] = raw
                    for field, tag in (('title', 'Title'), ('series', 'Series'), ('author', 'Writer'),
                                       ('language', 'LanguageISO'), ('number', 'Number'), ('volume', 'Volume')):
                        value = (root.findtext(tag) or '').strip()
                        if value:
                            book[field] = value
                    for page in root.findall('Pages/Page'):
                        if page.get('Type', '').casefold() == 'frontcover':
                            try:
                                index = int(page.get('Image', ''))
                                if 0 <= index < len(members):
                                    book['cover_index'] = index
                                    break
                            except ValueError:
                                pass
        except zipfile.BadZipFile as exc:
            raise ValueError('Unreadable or corrupt CBZ archive.') from exc
    elif fmt == 'pdf':
        values, book['pages'] = inspect_pdf(path, check)
        title = values.get('Title', '').strip()
        if title and title.casefold() != 'unknown':
            book['title'] = title
        book['author'] = values.get('Author', '')
    else:
        raise ValueError('Choose a CBZ or PDF file.')
    check_cancelled(check)
    if file_identity(path) != identity:
        raise ValueError('The input file changed during inspection. Browse it again.')
    return book


def validate_identity(book):
    if file_identity(book['path']) != tuple(book['identity']):
        raise ValueError('The imported file changed. Remove it and browse it again: ' + book['path'])


@contextmanager
def staged_pages(book, check=None, page_limit=None, indices=None, preview_budget=None, log=None):
    """Yield owned sequential page files. Archive paths never become filesystem paths."""
    validate_identity(book)
    with tempfile.TemporaryDirectory(prefix='manganana-import-') as directory:
        directory = Path(directory)
        count = book['pages']
        chosen = list(indices) if indices is not None else list(range(min(count, page_limit or count)))
        if not chosen or any(i < 0 or i >= count for i in chosen):
            raise ValueError('Invalid import page range.')
        paths = []
        if book['format'] == 'cbz':
            with zipfile.ZipFile(book['path']) as archive:
                by_offset = {i.header_offset: i for i in archive.infolist()}
                for index in chosen:
                    check_cancelled(check)
                    member = by_offset[book['members'][index]]
                    target = directory / (f'{index+1:06d}' + PurePosixPath(member.filename).suffix.lower())
                    with archive.open(member) as source, target.open('wb') as dest:
                        while True:
                            check_cancelled(check)
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            dest.write(chunk)
                    paths.append((index, target))
        else:
            # A bounded preview range; full-book finalization rasterizes to disk.
            first, last = min(chosen)+1, max(chosen)+1
            dpi = PDF_DPI if page_limit is None else PDF_PREVIEW_DPI
            run_tool([poppler_tools()[1], '-cropbox', '-r', str(dpi), '-jpeg',
                      '-jpegopt', 'quality=95,optimize=y', '-f', str(first), '-l', str(last),
                      book['path'], directory / 'page'], check)
            rendered = sorted(directory.glob('page-*.jpg'), key=lambda p: natural_key(p.name))
            if len(rendered) != last-first+1:
                raise RuntimeError('PDF rasterization returned an incomplete page sequence.')
            paths = [(i, rendered[i-first+1]) for i in chosen]
        records = []; decoded = 0
        for index, path in paths:
            check_cancelled(check)
            try:
                with Image.open(path) as source:
                    orientation = source.getexif().get(274, 1)
                    size = source.size
                    if page_limit is not None:
                        budget = PREVIEW_MEMORY_LIMIT if preview_budget is None else min(PREVIEW_MEMORY_LIMIT, preview_budget)
                        required = size[0] * size[1] * 4
                        if decoded + required > budget:
                            if log:
                                log(f'Preview: skipped oversized page {index+1} ({size[0]} × {size[1]}); it would exceed the remaining 128 MiB sample budget.')
                            continue
                    source.load()  # Reject broken pages one at a time, never cache the book.
                    if orientation in range(2, 9):
                        normalized = ImageOps.exif_transpose(source)
                        path = path.with_suffix('.png')
                        normalized.save(path)
                        size = normalized.size
                        normalized.close()
                records.append(dict(local_path=str(path), ext=path.suffix, size=size,
                                    normalized_size=size, chapter_index=1, page_in_chapter=index+1,
                                    chapter_pages=count))
                if page_limit is not None: decoded += required
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                if page_limit is not None:
                    if log: log(f'Preview: skipped page {index+1}; no safe preview image ({exc}).')
                    continue
                raise ValueError(f'Unreadable imported page {index+1}: {exc}') from exc
        validate_identity(book)
        check_cancelled(check)
        yield records


def preview_records(book, check=None, limit=14, log=None):
    """Keep safe samples, trying later pages after skips; never retain more than 128 MiB."""
    records = []; decoded = 0; cursor = 0
    limit = max(1, min(14, int(limit)))
    if log and book['format'] == 'pdf':
        log(f'PDF Live Preview uses {PDF_PREVIEW_DPI} DPI; final PDF import remains {PDF_DPI} DPI.')
    try:
        while cursor < book['pages'] and len(records) < limit and decoded < PREVIEW_MEMORY_LIMIT:
            check_cancelled(check)
            end = min(book['pages'], cursor + limit - len(records))
            with staged_pages(book, check, page_limit=limit, indices=range(cursor, end),
                              preview_budget=PREVIEW_MEMORY_LIMIT-decoded, log=log) as staged:
                for record in staged:
                    check_cancelled(check)
                    with Image.open(record['local_path']) as source:
                        row = {k: v for k, v in record.items() if k != 'local_path'}
                        row['image'] = source.copy()
                        records.append(row)
                    decoded += record['size'][0] * record['size'][1] * 4
            cursor = end
        if not records:
            raise ValueError('No safe Live Preview samples fit within the 128 MiB decoded-image limit. Final output remains available.')
        if log: log(f'Live Preview acquired {len(records)} safe source page' + ('s.' if len(records) != 1 else '.'))
        return tuple(records)
    except Exception:
        for record in records: record['image'].close()
        raise


def cover_bytes(book, check=None):
    with staged_pages(book, check, indices=[book['cover_index']]) as records:
        return Path(records[0]['local_path']).read_bytes()


def series_index(book):
    for value in (book.get('number'), book.get('volume')):
        try:
            number = float(value)
            if number >= 0 and number < float('inf'):
                return number
        except (TypeError, ValueError):
            pass
    return None


def import_plan(books, overrides=None, output_format='cbz'):
    overrides = overrides or {}
    rows = []
    for book in books:
        validate_identity(book)
        metadata = {key: overrides.get(key, book.get(key, '')) for key in ('title', 'series', 'author')}
        index = series_index(book)
        rows.append(dict(metadata, book=book, import_id=book['id'], volume=index,
                         volume_text=book.get('number') or book.get('volume') or '—',
                         kind='import', source_name='Local ' + book['format'].upper(), source_ids=[],
                         pages=book['pages'], status='Ready', existing=False, replace=False,
                         format=output_format, language=book.get('language', '')))
    return rows
