import os
import re
import math
import shutil
import sys
import tempfile
import time
import urllib.parse
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageStat, ImageOps, ImageDraw

from calibre.constants import config_dir
from calibre.ebooks.metadata.book.base import Metadata
from calibre.gui2 import error_dialog, info_dialog
from qt.core import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, Qt, QSize,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QThread, QVBoxLayout, QWidget, QScrollArea, QPixmap, QIcon, QLayout,
    QPainter, QColor, QPen, QTimer, QEvent, pyqtSignal, QGraphicsDropShadowEffect, QHeaderView, QSizePolicy
)

from calibre_plugins.manganana.config import prefs
from calibre_plugins.manganana.core_helpers import (
    _iter_aggregate_nodes,
    choose_preferred_title,
    collect_titles,
    first_localized,
    fmt_volume,
    is_doujinshi_entry,
    volume_from_name,
)
from calibre_plugins.manganana.i18n import tr, UI_LANGUAGES
from calibre_plugins.manganana.mangadex_source import MangaDexSource
from calibre_plugins.manganana.mangapill_source import MangaPillSource
from calibre_plugins.manganana.weebcentral_source import WeebCentralSource
from calibre_plugins.manganana.source_registry import SourceRegistry
from calibre_plugins.manganana.source_coordinator import SourceCoordinator, count_chapter_pages, format_page_count, provider_search_progress_text, review_manifest_progress, settled_provider_progress
from calibre_plugins.manganana.source_policy import enabled_sources, is_source_enabled, save_source_enabled_states
from calibre_plugins.manganana.canonical_identity import edition_identity, normalize_identity_text
from calibre_plugins.manganana.search_ranking import rank_canonical_results
from calibre_plugins.manganana.search_resolution import resolve_search_group
from calibre_plugins.manganana.provider_branding import provider_badge_spec, source_badge_specs
from calibre_plugins.manganana.inventory_comparison import compare_inventories, inspect_source_inventory
from calibre_plugins.manganana.cross_source_fallback import build_cross_source_plan
from calibre_plugins.manganana.chapter_workflow import chapter_label, chapter_output_title, chapter_series_index, chapter_sort_key, chapter_selection_ids
from calibre_plugins.manganana.version_info import DISPLAY_VERSION, SHORT_VERSION_LABEL, USER_AGENT
from calibre_plugins.manganana.diagnostics import write_diagnostic_report
try:
    from calibre_plugins.manganana.build_info import GIT_COMMIT
except ImportError:
    GIT_COMMIT = 'source'

ORANGE = '#FF6740'
COVER_BATCH_LIMIT = 8
SEARCH_RESOLUTION_LIMIT = 8
VL_NAME = 'MangaNana'
VL_TAG = 'MangaNana'
PAGE_RE = re.compile(r'(?i)Downloading\s+(.+?)\s+page\s+([0-9]+)\s*$')
LOG_VOL_RE = re.compile(r'(?i)\bVolume\.\s*([0-9]+(?:\.[0-9]+)?)')
LOG_CHAPTER_RE = re.compile(r'(?i)\bChapter\.\s*([^\s]+)')
ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')

MAJOR_MANGA_LANGUAGES = [
    ('English', 'en'),
    ('Spanish', 'es'),
    ('Spanish (Latin America)', 'es-la'),
    ('French', 'fr'),
    ('German', 'de'),
    ('Italian', 'it'),
    ('Portuguese (Brazil)', 'pt-br'),
    ('Portuguese', 'pt'),
    ('Russian', 'ru'),
    ('Korean', 'ko'),
    ('Chinese (Simplified)', 'zh'),
    ('Chinese (Traditional)', 'zh-hk'),
    ('Indonesian', 'id'),
    ('Vietnamese', 'vi'),
    ('Thai', 'th'),
    ('Polish', 'pl'),
]

LANGUAGE_LABELS = dict((code, label) for label, code in MAJOR_MANGA_LANGUAGES)
LANGUAGE_LABELS.update({
    'ar': 'Arabic',
    'be': 'Belarusian',
    'bg': 'Bulgarian',
    'bn': 'Bengali',
    'ca': 'Catalan',
    'cs': 'Czech',
    'da': 'Danish',
    'el': 'Greek',
    'fa': 'Persian',
    'fi': 'Finnish',
    'he': 'Hebrew',
    'hi': 'Hindi',
    'hu': 'Hungarian',
    'kk': 'Kazakh',
    'la': 'Latin',
    'lt': 'Lithuanian',
    'mn': 'Mongolian',
    'ms': 'Malay',
    'my': 'Burmese',
    'ne': 'Nepali',
    'nl': 'Dutch',
    'no': 'Norwegian',
    'ro': 'Romanian',
    'sr': 'Serbian',
    'sv': 'Swedish',
    'tl': 'Filipino (Tagalog)',
    'tr': 'Turkish',
    'uk': 'Ukrainian',
    'ur': 'Urdu',
})


class CappedComboBox(QComboBox):
    """Combo box whose popup stays inside the MangaNana window/screen."""
    def __init__(self, *args, max_popup_rows=12, **kwargs):
        super().__init__(*args, **kwargs)
        self._max_popup_rows = max(4, int(max_popup_rows))
        self.setMaxVisibleItems(self._max_popup_rows)

    def showPopup(self):
        super().showPopup()
        # Some Windows/Qt styles ignore QComboBox.maxVisibleItems and create a
        # popup tall enough for every language. Cap the actual popup after Qt
        # creates it so long MangaDex language lists scroll instead.
        QTimer.singleShot(0, self._cap_popup_height)

    def _cap_popup_height(self):
        try:
            view = self.view()
            if view is None or self.count() <= 0:
                return
            row_h = view.sizeHintForRow(0)
            if row_h <= 0:
                row_h = max(24, self.fontMetrics().height() + 10)
            rows = min(self.count(), self._max_popup_rows)
            max_h = int(row_h * rows + 10)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            view.verticalScrollBar().setSingleStep(max(12, row_h // 2))
            view.setMaximumHeight(max_h)
            popup = view.window()
            if popup is not None and popup is not self.window():
                popup.setMaximumHeight(max_h + 8)
                if popup.height() > max_h + 8:
                    popup.resize(popup.width(), max_h + 8)
        except Exception:
            pass


def populate_manga_languages(combo, available=None, preferred=None):
    """Populate only common MangaDex languages, optionally filtered to this title."""
    combo.blockSignals(True)
    combo.clear()
    allowed = set(available or []) if available is not None else None
    for label, code in MAJOR_MANGA_LANGUAGES:
        if allowed is None or code in allowed:
            combo.addItem(label, code)
    # If a title has translations outside the curated list and none of the
    # common languages match, expose those actual languages rather than leave
    # the user with an empty control.
    if combo.count() == 0 and available:
        for code in sorted(set(available)):
            combo.addItem(code, code)
    target = preferred or prefs['language']
    idx = combo.findData(target)
    if idx < 0:
        idx = combo.findData('en')
    if idx < 0 and combo.count():
        idx = 0
    if idx >= 0:
        combo.setCurrentIndex(idx)
    combo.blockSignals(False)


def populate_download_languages(combo, available=None, preferred='en'):
    """Populate actual chapter languages and choose a usable one automatically."""
    combo.blockSignals(True)
    combo.clear()
    if available is None:
        combo.addItem('Load manga first', None)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        return
    available = [str(x) for x in (available or []) if x]
    allowed = set(available)
    ordered = []
    for label, code in MAJOR_MANGA_LANGUAGES:
        if code in allowed:
            ordered.append((label, code))
    known = {code for _label, code in ordered}
    for code in sorted(allowed - known):
        ordered.append((language_label(code), code))

    if not ordered:
        combo.addItem('No downloadable languages reported', None)
        combo.setCurrentIndex(0)
    else:
        for label, code in ordered:
            combo.addItem(label, code)
        idx = combo.findData(preferred)
        # If the preferred language is unavailable, immediately choose the first
        # language MangaDex reports as downloadable rather than blocking workflow.
        combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.blockSignals(False)


def language_label(code):
    return LANGUAGE_LABELS.get(code, code or 'Unknown')


def api_json(url, timeout=30, retries=3, retry_callback=None):
    return MANGADEX_SOURCE._api_json(
        url, timeout=timeout, retries=retries, retry_callback=retry_callback
    )


def manga_uuid(url):
    match = SOURCE_REGISTRY.identify(url)
    if match and match.source.source_id == MANGADEX_SOURCE.source_id:
        return match.reference
    return None


def load_manga_metadata(url, preferred='en'):
    return MANGADEX_SOURCE.get_manga(url, preferred=preferred)


def _plan_from_aggregate(url, language, start_volume=None, end_volume=None):
    return MANGADEX_SOURCE._aggregate_plan(url, language, start_volume, end_volume)


def _plan_from_feed(url, language, start_volume=None, end_volume=None):
    """Build a lightweight plan from chapter-feed rows without trusting page counts."""
    entries = fetch_chapter_entries(url, language, start_volume, end_volume)
    volumes = {}
    bonus_chapters = 0
    for entry in entries:
        volume = entry.get('volume')
        if volume is None:
            bonus_chapters += 1
        else:
            volumes[float(volume)] = volumes.get(float(volume), 0) + 1
    return volumes, bonus_chapters


def fetch_download_plan(url, language, start_volume=None, end_volume=None):
    return MANGADEX_SOURCE.get_download_plan(url, language, start_volume, end_volume)

def format_eta(seconds):
    if seconds is None or seconds < 0:
        return 'calculating...'
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f'{h}h {m}m'
    if m:
        return f'{m}m {sec:02d}s'
    return f'{sec}s'


def format_speed(bps):
    if not bps or bps <= 0:
        return 'calculating speed...'
    if bps >= 1024**2:
        return f'{bps / (1024**2):.2f} MB/s'
    return f'{bps / 1024:.0f} KB/s'


def directory_size(path):
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    except Exception:
        pass
    return total


def fetch_chapter_entries(url, language, start_volume=None, end_volume=None):
    return MANGADEX_SOURCE.get_chapters(url, language, start_volume, end_volume)


def fetch_volume_covers(url):
    return MANGADEX_SOURCE.get_volume_covers(url)


MANGADEX_SOURCE = MangaDexSource()
MANGAPILL_SOURCE = MangaPillSource()
WEEBCENTRAL_SOURCE = WeebCentralSource()
SOURCE_REGISTRY = SourceRegistry((MANGADEX_SOURCE, MANGAPILL_SOURCE, WEEBCENTRAL_SOURCE))
SOURCE_COORDINATOR = SourceCoordinator(SOURCE_REGISTRY)


def download_bytes(url, timeout=45, retries=5, user_agent=USER_AGENT, retry_callback=None):
    return MANGADEX_SOURCE.fetch_binary(
        url, timeout=timeout, retries=retries, user_agent=user_agent,
        retry_callback=retry_callback,
    )


def chapter_page_urls(chapter_id, data_saver=False, retry_callback=None):
    manifest = MANGADEX_SOURCE.get_page_manifest(chapter_id, retry_callback=retry_callback)
    return manifest['data_saver'] if data_saver and manifest['data_saver'] else manifest['full']


def image_extension(url):
    path = urllib.parse.urlparse(url).path
    ext = Path(path).suffix.lower()
    return ext if ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif') else '.jpg'

def safe_filename(s):
    s = re.sub(r'[<>:"/\\|?*]', '-', s).strip().rstrip('.')
    return s or 'Manga'


def first_image_from_cbz(path):
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
        if not names:
            return None, None
        # MangaDex-DL places the volume cover first when --use-volume-cover is enabled.
        n = names[0]
        ext = Path(n).suffix.lower().lstrip('.') or 'jpg'
        return ext, zf.read(n)


def write_comicinfo(path, title, series, author, volume, language, source_url):
    import xml.etree.ElementTree as ET
    tmp = str(path) + '.manganana.tmp'
    with zipfile.ZipFile(path, 'r') as src, zipfile.ZipFile(tmp, 'w') as dst:
        old_info = None
        for item in src.infolist():
            if item.filename.lower() == 'comicinfo.xml':
                try:
                    old_info = ET.fromstring(src.read(item))
                except Exception:
                    old_info = None
                continue
            dst.writestr(item, src.read(item))
        root = old_info if old_info is not None else ET.Element('ComicInfo')
        def setv(tag, value):
            el = root.find(tag)
            if el is None:
                el = ET.SubElement(root, tag)
            el.text = str(value)
        setv('Title', title)
        setv('Series', series)
        setv('Writer', author)
        setv('LanguageISO', language)
        setv('Web', source_url)
        if volume is not None:
            setv('Volume', f'{volume:g}')
            setv('Number', f'{volume:g}')
        xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        dst.writestr('ComicInfo.xml', xml)
    os.replace(tmp, path)


def _image_size(blob):
    with Image.open(BytesIO(blob)) as im:
        return im.size




def _normalize_exif_orientation(blob, ext='.jpg'):
    """Bake EXIF orientation into pixels so e-readers do not need EXIF support.

    Returns (blob, size, changed, orientation). All eight standard EXIF orientation
    values are handled by Pillow's exif_transpose. The orientation tag is removed
    from rewritten images after the pixels have been normalized.
    """
    try:
        with Image.open(BytesIO(blob)) as src:
            orientation = src.getexif().get(274, 1)
            if orientation in (None, 1):
                return blob, src.size, False, orientation or 1
            fixed = ImageOps.exif_transpose(src)
            fmt = (src.format or '').upper()
            out = BytesIO()
            if fmt in ('JPEG', 'JPG') or ext.lower() in ('.jpg', '.jpeg'):
                _to_rgb(fixed).save(out, 'JPEG', quality=95, subsampling=0)
            elif fmt == 'PNG' or ext.lower() == '.png':
                fixed.save(out, 'PNG')
            elif fmt == 'WEBP' or ext.lower() == '.webp':
                fixed.save(out, 'WEBP', quality=95)
            else:
                _to_rgb(fixed).save(out, 'JPEG', quality=95, subsampling=0)
            return out.getvalue(), fixed.size, True, orientation
    except Exception:
        try:
            return blob, _image_size(blob), False, 1
        except Exception:
            return blob, (1, 2), False, 1


def _exif_orientation_value(blob):
    """Return an image's EXIF orientation, defaulting to normal orientation."""
    try:
        with Image.open(BytesIO(blob)) as src:
            return src.getexif().get(274, 1) or 1
    except Exception:
        return 1


def _select_verified_preview_source(saver_blob, full_url, fetch_full, cache):
    """Use full-quality pixels only when their EXIF proves a display transform.

    Landscape data-saver dimensions trigger verification, never rotation. Results
    are cached by aligned full-quality page URL for the lifetime of a preview job.
    Returns (selected_blob, used_full_quality, verification_details_or_none).
    """
    saver_size = _image_size(saver_blob)
    saver_exif = _exif_orientation_value(saver_blob)
    if saver_size[0] <= saver_size[1]:
        return saver_blob, False, None

    cached = cache.get(full_url)
    if cached is None:
        full_blob = fetch_full(full_url)
        full_exif = _exif_orientation_value(full_blob)
        cached = {
            'exif': full_exif,
            'blob': full_blob if full_exif in range(2, 9) else None,
        }
        cache[full_url] = cached

    full_exif = cached.get('exif', 1)
    details = {
        'saver_size': saver_size,
        'saver_exif': saver_exif,
        'full_exif': full_exif,
    }
    if full_exif in range(2, 9) and cached.get('blob'):
        return cached['blob'], True, details
    return saver_blob, False, details


def _to_rgb(im):
    if im.mode == 'RGB':
        return im
    if im.mode in ('RGBA', 'LA'):
        bg = Image.new('RGB', im.size, 'white')
        alpha = im.getchannel('A')
        bg.paste(im.convert('RGB'), mask=alpha)
        return bg
    return im.convert('RGB')


def _save_jpeg(im):
    out = BytesIO(); im.save(out, 'JPEG', quality=95, subsampling=0)
    return out.getvalue()


def _landscape_safe_area(horizontal_ratio=0.018, vertical_ratio=0.030):
    """Return the established Kobo canvas and calibrated inner safe area."""
    canvas_w, canvas_h = 1680, 1264
    mx = max(4, round(canvas_w * horizontal_ratio))
    my = max(4, round(canvas_h * vertical_ratio))
    return canvas_w, canvas_h, mx, my, canvas_w - mx * 2, canvas_h - my * 2


def _kobo_landscape_canvas(im, horizontal_ratio=0.018, vertical_ratio=0.030):
    """Contain artwork inside a fixed Kobo Libra Colour landscape canvas.

    The final JPEG is always 1680x1264, matching the device's landscape pixel
    geometry.  Artwork is scaled to fit completely inside the safe rectangle,
    never cropped, and centered.  The current safety insets remain 1.8% on the
    sides and 3.0% vertically, based on Kobo Libra Colour on-device calibration.
    """
    canvas_w, canvas_h, mx, my, safe_w, safe_h = _landscape_safe_area(
        horizontal_ratio, vertical_ratio
    )

    art = _to_rgb(im)
    scale = min(safe_w / art.width, safe_h / art.height)
    out_w = max(1, round(art.width * scale))
    out_h = max(1, round(art.height * scale))
    if (out_w, out_h) != art.size:
        art = art.resize((out_w, out_h), Image.Resampling.LANCZOS)

    canvas = Image.new('RGB', (canvas_w, canvas_h), 'white')
    x = (canvas_w - out_w) // 2
    y = (canvas_h - out_h) // 2
    canvas.paste(art, (x, y))

    # Temporary calibration aid.  It is opt-in in Preferences and never alters
    # the artwork itself.  If Kobo clips or shifts this rectangle, the visible
    # border tells us exactly which edge of the device viewport is responsible.
    if False and bool(prefs['kobo_safe_area_border']):
        draw = ImageDraw.Draw(canvas)
        for i in range(3):
            draw.rectangle((mx+i, my+i, canvas_w-mx-1-i, canvas_h-my-1-i), outline='black')
    return canvas


def _landscape_canvas_for_single(blob):
    """Put an isolated portrait page on the RIGHT half before final Kobo fitting."""
    with Image.open(BytesIO(blob)) as src:
        page = _to_rgb(src.copy())
    w, h = page.size
    spread = Image.new('RGB', (w * 2, h), 'white')
    spread.paste(page, (w, 0))
    return _save_jpeg(_kobo_landscape_canvas(spread))


def _fit_page_to_slot(page, slot_w, slot_h):
    """Aspect-fit and center one page inside a fixed slot without cropping."""
    scale = min(slot_w / page.width, slot_h / page.height)
    fitted_w = max(1, round(page.width * scale))
    fitted_h = max(1, round(page.height * scale))
    fitted = page
    if fitted.size != (fitted_w, fitted_h):
        fitted = fitted.resize((fitted_w, fitted_h), Image.Resampling.LANCZOS)
    left = (slot_w - fitted_w) // 2
    top = (slot_h - fitted_h) // 2
    margins = {
        'left': left,
        'right': slot_w - fitted_w - left,
        'top': top,
        'bottom': slot_h - fitted_h - top,
    }
    return fitted, margins


def _paired_canvas(left_blob, right_blob, left_record=None, right_record=None, log=None):
    """Fit two pages independently into halves of the calibrated safe area."""
    canvas_w, canvas_h, mx, my, safe_w, safe_h = _landscape_safe_area()
    slot_w = safe_w // 2
    with Image.open(BytesIO(left_blob)) as a, Image.open(BytesIO(right_blob)) as b:
        left = _to_rgb(a.copy()); right = _to_rgb(b.copy())
    left_size, right_size = left.size, right.size
    left, left_margins = _fit_page_to_slot(left, slot_w, safe_h)
    right, right_margins = _fit_page_to_slot(right, slot_w, safe_h)
    canvas = Image.new('RGB', (canvas_w, canvas_h), 'white')
    canvas.paste(left, (mx + left_margins['left'], my + left_margins['top']))
    canvas.paste(right, (mx + slot_w + right_margins['left'], my + right_margins['top']))

    if log:
        log(
            f"Landscape safe area: canvas {canvas_w}x{canvas_h} | "
            f"inset L{mx} R{mx} T{my} B{my} | content area {safe_w}x{safe_h}"
        )
        for side, record, source_size, fitted, margins in (
            ('left', left_record, left_size, left, left_margins),
            ('right', right_record, right_size, right, right_margins),
        ):
            source_page = (record or {}).get('page_in_chapter', '?')
            normalized = (record or {}).get('normalized_size') or source_size
            log(
                f"Pair fit: source page {source_page} ({side}) | "
                f"normalized {normalized[0]}x{normalized[1]} | safe slot {slot_w}x{safe_h} | "
                f"fitted {fitted.width}x{fitted.height} | "
                f"outer margins L{mx} R{mx} T{my} B{my} | "
                f"slot margins L{margins['left']} R{margins['right']} "
                f"T{margins['top']} B{margins['bottom']}"
            )
    return _save_jpeg(canvas)


def _spread_with_margin(blob):
    """Fit an existing spread into the same fixed Kobo canvas without cropping."""
    with Image.open(BytesIO(blob)) as src:
        spread = _to_rgb(src.copy())
    return _save_jpeg(_kobo_landscape_canvas(spread))


def build_landscape_pages(records, direction='rtl', log=None, detailed=False):
    """Create book-style landscape pages while using genuine source spreads as parity anchors.

    Landscape dimensions make an image a spread candidate, not proof of a spread.
    Orientation correction must already be baked into source pixels from trustworthy
    metadata. Odd single pages are placed on the right half without rotation.
    """
    if not records:
        return [], {'spreads': 0, 'pairs': 0, 'isolated': 0, 'rotated': 0}

    # Work on shallow copies so orientation correction never mutates downloader state.
    records = [dict(r) for r in records]
    spread_flags = []
    for r in records:
        w, h = r['size']
        spread_flags.append(h > 0 and (w / h) >= 1.15)

    portrait_areas = sorted((r['size'][0] * r['size'][1] for i, r in enumerate(records) if not spread_flags[i] and r['size'][0] > 1 and r['size'][1] > 1))
    median_area = portrait_areas[len(portrait_areas)//2] if portrait_areas else 0
    extra_flags = []
    for i, r in enumerate(records):
        w, h = r['size']; ratio = (w / h) if h else 0
        terminal = r.get('page_in_chapter') == r.get('chapter_pages')
        unusual = bool(median_area and ((w*h) < median_area * 0.55 or (ratio < 0.42) or (0.96 < ratio < 1.15)))
        extra_flags.append(bool(terminal and unusual and not spread_flags[i]))
    spread_indices = [i for i, yes in enumerate(spread_flags) if yes]
    output=[]; stats={'spreads':0,'pairs':0,'isolated':0,'extras':sum(extra_flags),'rotated':0}

    def trace_record(record):
        chapter = record.get('chapter_label') or record.get('chapter_index') or '?'
        chapter_title = str(record.get('chapter_title') or '').strip()
        chapter_text = f'Chapter {chapter}' + (f' "{chapter_title}"' if chapter_title else '')
        source_page = record.get('page_in_chapter') or '?'
        original_size = record.get('original_size') or record.get('size') or ('?', '?')
        normalized_size = record.get('normalized_size') or record.get('size') or ('?', '?')
        transforms = record.get('later_transforms') or []
        later = ', '.join(transforms) if transforms else 'none'
        return (
            f"[{chapter_text}, source page {source_page} | "
            f"{record.get('download_quality') or 'unknown quality'} | "
            f"downloaded {original_size[0]}x{original_size[1]} | "
            f"EXIF before {record.get('exif_before', '?')} | "
            f"normalized {normalized_size[0]}x{normalized_size[1]} | "
            f"EXIF after {record.get('exif_after', '?')} | later transforms: {later}]"
        )

    def add_output(ext, blob, kind, source_records):
        output.append((ext, blob, kind) if detailed else (ext, blob))
        if detailed and log:
            final_size = _image_size(blob)
            sources = ' + '.join(trace_record(record) for record in source_records)
            trace_kind = kind.replace(' ', '_')
            composition = {
                'ISOLATED': 'padded upright single',
                'PAIRED': 'side-by-side',
                'ORIGINAL SPREAD': 'source spread fitted to canvas',
            }.get(kind, 'unchanged')
            log(
                f"Preview trace: Output page {len(output)} | {trace_kind} | {sources} | "
                f"composition: {composition} | final {final_size[0]}x{final_size[1]}"
            )

    def emit_single(rec):
        add_output('generated.jpg', _landscape_canvas_for_single(rec['blob']), 'ISOLATED', [rec])
        stats['isolated'] += 1

    def emit_pair(earlier, later):
        if direction == 'rtl':
            left, right = later, earlier
        else:
            left, right = earlier, later
        paired = _paired_canvas(
            left['blob'], right['blob'],
            left_record=left, right_record=right, log=log if detailed else None,
        )
        add_output('generated.jpg', paired, 'PAIRED', [earlier, later])
        stats['pairs'] += 1

    def emit_run(run, backwards=False):
        if not run: return
        if backwards:
            start = 0
            if len(run) % 2:
                emit_single(run[0]); start = 1
            for i in range(start, len(run), 2): emit_pair(run[i], run[i+1])
        else:
            i=0
            while i + 1 < len(run): emit_pair(run[i], run[i+1]); i += 2
            if i < len(run): emit_single(run[i])

    anchors = sorted(set(spread_indices + [i for i, yes in enumerate(extra_flags) if yes]))
    cursor=0; first_spread = spread_indices[0] if spread_indices else None
    for anchor_i in anchors:
        run=records[cursor:anchor_i]
        emit_run(run, backwards=(anchor_i == first_spread and cursor == 0))
        if spread_flags[anchor_i]:
            add_output('generated.jpg', _spread_with_margin(records[anchor_i]['blob']), 'ORIGINAL SPREAD', [records[anchor_i]]); stats['spreads'] += 1
        else:
            emit_single(records[anchor_i])
        cursor=anchor_i+1
    emit_run(records[cursor:], backwards=False)
    if log:
        log(f"Layout analysis: {stats['spreads']} original spread(s), {stats['pairs']} paired page(s), {stats['isolated']} isolated page(s), {stats['rotated']} sideways portrait page(s) corrected, {stats['extras']} likely supplemental page(s) excluded from parity.")
    return output, stats


def _validate_cbz_output(path, page_layout):
    """Final sanity check before a generated book is handed to calibre."""
    with zipfile.ZipFile(path, 'r') as zf:
        names = zf.namelist()
        image_names = [n for n in names if n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        auxiliary_cover_names = {'cover.jpg', 'cover.jpeg', 'cover.png', 'cover.webp'}
        reading = []
        for name in image_names:
            basename = Path(name).name.casefold()
            stem = Path(basename).stem
            if basename in auxiliary_cover_names or basename.startswith('0000_cover') or stem.endswith('_cover'):
                continue
            reading.append(name)
        if not reading:
            raise RuntimeError('CBZ validation failed: no readable manga pages were produced.')
        if len(reading) != len(set(reading)):
            raise RuntimeError('CBZ validation failed: duplicate reading-page filenames were produced.')
        for name in reading:
            try:
                blob = zf.read(name)
                with Image.open(BytesIO(blob)) as im:
                    im.verify()
                if page_layout == 'paired_landscape':
                    with Image.open(BytesIO(blob)) as im:
                        if im.size != (1680, 1264):
                            raise RuntimeError(f'CBZ validation failed: {name} is {im.size[0]}x{im.size[1]}, expected 1680x1264.')
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f'CBZ validation failed: {name} is unreadable ({e}).')
    return len(reading)


def manga_has_downloadable_content(manga_id, attrs=None):
    return MANGADEX_SOURCE.has_downloadable_content(manga_id, attrs)


class SourceSearchWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, source, query, offset=0, limit=12, include_adult=False, preferred='en', availability_cache=None, parent=None):
        super().__init__(parent)
        self.source = source
        self.query = query
        self.offset = int(offset)
        self.limit = int(limit)
        self.include_adult = bool(include_adult)
        self.preferred = preferred or 'en'
        self.availability_cache = availability_cache if availability_cache is not None else {}

    @staticmethod
    def score(query, title, full_title='', preferred_available=False):
        return MangaDexSource._score(query, title, full_title, preferred_available)

    def run(self):
        try:
            def check_cancel():
                if self.isInterruptionRequested():
                    raise InterruptedError('Provider search cancelled.')
            check_cancel()
            source=(self.source.with_cancel_check(check_cancel)
                    if hasattr(self.source,'with_cancel_check') else self.source)
            data = source.search(
                self.query, offset=self.offset, limit=self.limit,
                include_adult=self.include_adult, preferred=self.preferred,
                availability_cache=self.availability_cache,
            )
            check_cancel()
            self.ready.emit({'source_id': self.source.source_id, 'data': data})
        except InterruptedError as e:
            if self.isInterruptionRequested():
                return
            self.failed.emit({'source_id': self.source.source_id, 'error': str(e)})
        except Exception as e:
            self.failed.emit({'source_id': self.source.source_id, 'error': str(e)})


MangaDexSearchWorker = SourceSearchWorker


class InventoryComparisonWorker(QThread):
    progress = pyqtSignal(int, int, str)
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, registry, candidates, language, workflow='volume', parent=None):
        super().__init__(parent)
        self.registry=registry; self.candidates=list(candidates or [])
        self.language=language or 'en'; self.workflow=workflow

    def run(self):
        try:
            inventories=[]; total=len(self.candidates)
            expected_edition=edition_identity(self.candidates[0]) if self.candidates else 'original'
            for index,candidate in enumerate(self.candidates,1):
                if self.isInterruptionRequested():
                    return
                source=self.registry.get(candidate.get('source_id'))
                if source is None:
                    continue
                self.progress.emit(index-1,total,f'Checking {source.display_name} inventory...')
                inventories.append(inspect_source_inventory(source,candidate,self.language,workflow=self.workflow))
                self.progress.emit(index,total,f'{source.display_name} inventory checked ({index}/{total})')
            if self.isInterruptionRequested():
                return
            decision=compare_inventories(inventories,expected_edition,self.workflow)
            if decision.selected is not None:
                # Keep the plan available to later Chapter-mode work without
                # forcing an unsafe mixed-provider volume CBZ today.
                fallback_plan=build_cross_source_plan(
                    inventories, self.registry, primary=decision.selected,
                    workflow=self.workflow,
                )
                decision=replace(decision, fallback_plan=fallback_plan)
            self.ready.emit(decision)
        except Exception as exc:
            self.failed.emit(str(exc))


class SearchResolutionWorker(QThread):
    """Resolve mode/language source confidence for a bounded set of groups."""
    resolved = pyqtSignal(object)

    def __init__(self, request_id, registry, groups, language, workflow,
                 metadata_cache, inventory_cache, include_adult=False):
        super().__init__()
        self.request_id = request_id
        self.registry = registry
        self.groups = tuple(groups or ())
        self.language = language or 'en'
        self.workflow = workflow
        self.metadata_cache = metadata_cache
        self.inventory_cache = inventory_cache
        self.include_adult = bool(include_adult)

    def run(self):
        def check_cancel():
            if self.isInterruptionRequested():
                raise InterruptedError('Search source resolution cancelled.')

        for group_key, candidates in self.groups:
            try:
                check_cancel()
                resolution = resolve_search_group(
                    self.registry, candidates, self.language, self.workflow,
                    self.metadata_cache, self.inventory_cache, check_cancel,
                    self.include_adult,
                )
                check_cancel()
                self.resolved.emit({
                    'request_id': self.request_id,
                    'group_key': group_key,
                    'resolution': resolution,
                })
            except InterruptedError:
                return
            except Exception as exc:
                self.resolved.emit({
                    'request_id': self.request_id,
                    'group_key': group_key,
                    'error': str(exc),
                })


class MangaLoadWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, request_id, source, url, preferred='en', parent=None):
        super().__init__(parent)
        self.request_id=request_id; self.source=source; self.url=url; self.preferred=preferred or 'en'

    def run(self):
        try:
            # Keep title switching lightweight. Volume-cover discovery happens
            # with the volume plan only after this result is still current.
            md=self.source.get_manga(self.url, preferred=self.preferred)
            original_ref=self.source.parse_manga_ref(self.url)
            resolved_url=(md.get('source_url') or self.url) if str(original_ref).startswith('http') else self.url
            self.ready.emit({'request_id':self.request_id,'url':resolved_url,'metadata':md,
                             'source_id':self.source.source_id})
        except Exception as e:
            self.failed.emit({'request_id':self.request_id,'error':str(e)})


class VolumePlanWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, request_id, source, url, language, parent=None):
        super().__init__(parent)
        self.request_id=request_id; self.source=source; self.url=url; self.language=language

    def run(self):
        try:
            plan=self.source.get_download_plan(self.url, self.language)
            # Do not expose aggregate-only volume rows. Review and Download
            # require real chapter references in the requested language.
            chapters=self.source.get_chapters(self.url, self.language)
            actual_by_volume={}
            actual_bonus=0
            for chapter in chapters or ():
                volume=chapter.get('volume')
                if volume is None:
                    actual_bonus += 1
                    continue
                try:
                    volume=float(volume)
                except (TypeError, ValueError):
                    continue
                actual_by_volume[volume]=actual_by_volume.get(volume,0)+1
            plan=dict(plan or {})
            plan['volumes']=sorted(actual_by_volume)
            plan['chapters_by_volume']=actual_by_volume
            plan['bonus_chapters']=actual_bonus
            cover_error=''
            try:
                covers=self.source.get_volume_covers(self.url)
            except Exception as e:
                covers={}; cover_error=str(e)
            self.ready.emit({'request_id':self.request_id,'url':self.url,'language':self.language,
                             'source_id':self.source.source_id,'plan':plan,'covers':covers,'cover_error':cover_error})
        except Exception as e:
            self.failed.emit({'request_id':self.request_id,'url':self.url,'language':self.language,'error':str(e)})


class ChapterPlanWorker(QThread):
    """Discover a chapter-native selection list off the Qt GUI thread."""
    ready = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, request_id, source, url, language, parent=None):
        super().__init__(parent)
        self.request_id=request_id; self.source=source; self.url=url; self.language=language

    def run(self):
        try:
            chapters=self.source.get_chapters(self.url, self.language)
            self.ready.emit({'request_id':self.request_id,'url':self.url,'language':self.language,
                             'source_id':self.source.source_id,'chapters':chapters or []})
        except Exception as e:
            self.failed.emit({'request_id':self.request_id,'url':self.url,'language':self.language,'error':str(e)})


class ImageBatchWorker(QThread):
    image_ready = pyqtSignal(object)
    image_failed = pyqtSignal(object)
    batch_done = pyqtSignal(object)

    def __init__(self, batch_id, entries, parent=None, source=None):
        super().__init__(parent)
        self.batch_id=batch_id
        self.entries=list(entries or [])
        self.source=source or MANGADEX_SOURCE

    def run(self):
        for entry in self.entries:
            if self.isInterruptionRequested():
                break
            key, urls = entry[:2]
            source = entry[2] if len(entry) > 2 else self.source
            raw=None
            for url in urls:
                if self.isInterruptionRequested():
                    break
                if not url:
                    continue
                try:
                    raw=source.fetch_binary(url, timeout=14, retries=2, user_agent=USER_AGENT)
                    if raw:
                        break
                except Exception:
                    raw=None
            if raw:
                self.image_ready.emit({'batch_id':self.batch_id,'key':key,'raw':raw})
            elif not self.isInterruptionRequested():
                self.image_failed.emit({'batch_id':self.batch_id,'key':key})
        self.batch_done.emit({'batch_id':self.batch_id})


class DownloadWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    stats = pyqtSignal(object)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled_ok = pyqtSignal()

    def __init__(self, source, url, title, author, series, language, start, end, covers, zero_pad, existing_volumes, selected_volumes=None, include_bonus=True, page_layout='original_pages', reading_direction='rtl', main_cover_url='', chapter_jobs=None):
        super().__init__()
        self.source = source
        self.source_name = source.display_name
        self.url, self.title, self.author, self.series = url, title, author, series
        self.main_cover_url = main_cover_url or ''
        self.language = language
        self.start_volume, self.end_volume = start, end
        self.covers, self.zero_pad = covers, zero_pad
        self.existing = set(existing_volumes)
        self.selected_volumes = None if selected_volumes is None else set(selected_volumes)
        self.include_bonus = bool(include_bonus)
        self.page_layout = page_layout
        self.reading_direction = reading_direction
        self.cancelled = False
        self.chapter_jobs=tuple(chapter_jobs or ())

    def cancel(self):
        self.cancelled = True

    def _check_cancel(self):
        if self.cancelled:
            raise RuntimeError('Download cancelled.')

    def _comicinfo_xml(self, title, volume, chapter_number=None):
        import xml.etree.ElementTree as ET
        root = ET.Element('ComicInfo')
        values = {
            'Title': title,
            'Series': self.series,
            'Writer': self.author,
            'LanguageISO': self.language,
            'Web': self.url,
        }
        if volume is not None:
            values['Volume'] = f'{volume:g}'
            values['Number'] = f'{volume:g}'
        elif chapter_number:
            values['Number'] = str(chapter_number)
        for tag, value in values.items():
            el = ET.SubElement(root, tag)
            el.text = str(value)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)

    def _download_group(self, group, output_path, final_title, volume, cover_url,
                        state, job_index, job_total, volume_pages_total, chapter_number=None):
        cover_blob = None
        cover_ext = '.jpg'
        if self.covers and cover_url:
            self._check_cancel()
            try:
                self.log.emit(f'Downloading volume cover for {final_title}...')
                cover_blob = self.source.fetch_binary(cover_url, timeout=40, retries=4, retry_callback=self.log.emit)
                cover_ext = image_extension(cover_url)
                cover_blob, _cover_size, cover_exif_changed, cover_orientation = _normalize_exif_orientation(cover_blob, cover_ext)
                if cover_exif_changed:
                    self.log.emit(f'EXIF orientation normalized for volume cover (orientation {cover_orientation}).')
                state['bytes'] += len(cover_blob)
            except Exception as e:
                self.log.emit(f'Warning: volume cover could not be downloaded: {e}')

        records = []
        for chap_num, chapter in enumerate(group, 1):
            self._check_cancel()
            ch_label = chapter.get('chapter') or 'unnumbered'
            if volume is None: self.log.emit(f'Downloading standalone Chapter {ch_label}...')
            else: self.log.emit(f'Downloading Volume {volume:g}, Chapter {ch_label}...')
            source=SOURCE_REGISTRY.get(chapter.get('_source_id')) or self.source
            urls = source.get_page_manifest(chapter['id'], retry_callback=self.log.emit)['full']
            if len(urls) != int(chapter.get('pages') or 0):
                state['pages_total'] += len(urls) - int(chapter.get('pages') or 0)
                volume_pages_total += len(urls) - int(chapter.get('pages') or 0)
            for page_in_chapter, url in enumerate(urls, 1):
                self._check_cancel()
                blob = source.fetch_binary(url, timeout=50, retries=5, retry_callback=self.log.emit)
                ext = image_extension(url)
                blob, size, exif_changed, exif_orientation = _normalize_exif_orientation(blob, ext)
                if exif_changed:
                    self.log.emit(f'EXIF orientation normalized: Volume {volume:g}, Chapter {ch_label}, page {page_in_chapter} (orientation {exif_orientation}).' if volume is not None else f'EXIF orientation normalized: standalone Chapter {ch_label}, page {page_in_chapter} (orientation {exif_orientation}).')
                records.append({'blob':blob, 'ext':ext, 'size':size, 'chapter_index':chap_num, 'page_in_chapter':page_in_chapter, 'chapter_pages':len(urls)})
                state['bytes'] += len(blob); state['pages_done'] += 1; state['volume_done'] += 1
                elapsed=max(.001,time.time()-state['started']); bps=state['bytes']/elapsed
                total=max(state['pages_total'],state['pages_done']); pct=int(min(100,state['pages_done']*100/total)) if total else 0
                eta=(elapsed/state['pages_done'])*(total-state['pages_done']) if state['pages_done']>=3 and total>state['pages_done'] else None
                self.stats.emit({'job_index':job_index,'job_total':job_total,'volume':volume,'volume_pages_done':state['volume_done'],'volume_pages_total':max(volume_pages_total,state['volume_done']),'pages_done':state['pages_done'],'pages_total':total,'percent':pct,'bytes_per_second':bps,'eta_seconds':eta})

        cover_path = None
        if cover_blob:
            cover_path = str(Path(output_path).with_suffix('')) + '_cover' + cover_ext
            Path(cover_path).write_bytes(cover_blob)
            self.log.emit('Portrait cover assigned to Calibre metadata; excluded from CBZ reading pages.')

        with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_STORED) as zf:
            page_index=1
            if self.page_layout == 'paired_landscape':
                self.log.emit(f'Analyzing {final_title} for landscape paired-page layout...')
                pages, layout_stats = build_landscape_pages(records, self.reading_direction, self.log.emit)
                for ext, blob in pages:
                    out_ext = ext if ext.startswith('.') else '.jpg'
                    zf.writestr(f'{page_index:05d}{out_ext}', blob); page_index += 1
                self.log.emit('Landscape layout complete. Every reading page uses the fixed Kobo landscape canvas.')
            else:
                for rec in records:
                    zf.writestr(f'{page_index:05d}{rec["ext"]}', rec['blob']); page_index += 1
            zf.writestr('ComicInfo.xml', self._comicinfo_xml(final_title, volume, chapter_number))
        return cover_path

    def run(self):
        t0 = time.time()
        work = tempfile.mkdtemp(prefix='manganana-calibre-')
        try:
            if self.chapter_jobs:
                return self._run_chapter_jobs(work, t0)
            self.log.emit(f'[{self.source_name}] Reading chapter information and page counts...')
            chapters = self.source.get_chapters(self.url, self.language, self.start_volume, self.end_volume)
            if not chapters:
                raise RuntimeError('No downloadable chapters were found for the selected language and volume range.')

            groups = {}
            for chapter in chapters:
                groups.setdefault(chapter['volume'], []).append(chapter)

            numeric = sorted(v for v in groups if v is not None)
            skipped_volumes = sorted(v for v in numeric if v in self.existing)
            jobs = [(v, groups[v]) for v in numeric if v not in self.existing and (self.selected_volumes is None or v in self.selected_volumes)]
            if None in groups and self.include_bonus:
                jobs.append((None, groups[None]))

            if skipped_volumes:
                self.log.emit('Skipping existing calibre volume(s): ' + ', '.join(f'{v:g}' for v in skipped_volumes))
            if not jobs:
                self.finished_ok.emit({'files': [], 'skipped': len(skipped_volumes), 'elapsed': time.time()-t0,
                                       'pages': 0, 'planned_pages': 0, 'workdir': work, 'bytes': 0,
                                       'failed_volumes': [], 'failed_labels': []})
                return

            planned_pages = sum(int(c.get('pages') or 0) for _v, group in jobs for c in group)
            planned_chapters = sum(len(group) for _v, group in jobs)
            self.log.emit(f'Plan: {len(jobs)} download job(s), {planned_chapters} chapters, {planned_pages} pages.')

            covers = {}
            if self.covers:
                try:
                    covers = self.source.get_volume_covers(self.url)
                except Exception as e:
                    self.log.emit(f'Warning: volume-cover metadata unavailable: {e}')

            outputs = []
            failures = []
            state = {'pages_done': 0, 'pages_total': planned_pages, 'bytes': 0, 'started': time.time(), 'volume_done': 0}
            for idx, (vol, group) in enumerate(jobs, 1):
                self._check_cancel()
                state['volume_done'] = 0
                if vol is None:
                    final_title = f'{self.title} (Standalone Chapters)'
                    filename = safe_filename(final_title) + '.cbz'
                    label = 'Standalone Chapters'
                    # Standalone chapters do not have a formal volume cover.
                    # Use the manga's main cover so the Calibre entry still has
                    # a meaningful, consistent portrait cover.
                    cover_url = self.main_cover_url
                else:
                    vol_s = fmt_volume(vol, self.zero_pad)
                    final_title = f'{self.title} (Vol. {vol_s})'
                    filename = safe_filename(final_title) + '.cbz'
                    label = f'Volume {vol:g}'
                    cover_url = covers.get(vol) or self.main_cover_url
                output = Path(work) / filename
                volume_pages_total = sum(int(c.get('pages') or 0) for c in group)
                self.log.emit(f'Starting {label}...')
                self.progress.emit(int(state['pages_done'] * 100 / max(1, state['pages_total'])),
                                   f'Downloading {label} ({idx}/{len(jobs)})')
                before_done = state['pages_done']
                before_bytes = state['bytes']
                try:
                    cover_path = self._download_group(group, output, final_title, vol, cover_url, state, idx, len(jobs), volume_pages_total)
                    validated_pages = _validate_cbz_output(output, self.page_layout)
                    self.log.emit(f'Validated {label}: {validated_pages} reading page(s), CBZ structure OK.')
                    outputs.append({'path': str(output), 'volume': vol, 'title': final_title, 'cover_path': cover_path})
                    self.log.emit(f'{label} prepared for calibre.')
                except Exception as e:
                    if self.cancelled:
                        raise
                    try:
                        output.unlink(missing_ok=True)
                    except Exception:
                        pass
                    # Failed page attempts should not count as completed progress.
                    state['pages_done'] = before_done
                    state['bytes'] = before_bytes
                    failures.append({'volume': vol, 'label': label, 'error': str(e)})
                    self.log.emit(f'FAILED {label}: {e}')
                    self.log.emit('Continuing with the remaining selected volumes...')

            self.progress.emit(100 if outputs or failures else 0, 'Preparing calibre import...')
            final_bytes = 0
            for prepared in outputs:
                try:
                    final_bytes += Path(prepared['path']).stat().st_size
                except Exception:
                    pass
            self.finished_ok.emit({'files': outputs, 'skipped': len(skipped_volumes),
                                   'elapsed': time.time()-t0, 'workdir': work,
                                   'pages': state['pages_done'], 'planned_pages': state['pages_total'],
                                   'bytes': state['bytes'], 'final_bytes': final_bytes,
                                   'failed_volumes': [f['volume'] for f in failures if f['volume'] is not None],
                                   'failed_bonus': any(f['volume'] is None for f in failures),
                                   'failed_labels': [f['label'] for f in failures],
                                   'failures': failures})
        except Exception as e:
            shutil.rmtree(work, ignore_errors=True)
            if self.cancelled:
                self.cancelled_ok.emit()
            else:
                self.failed.emit(str(e))

    def _run_chapter_jobs(self, work, t0):
        jobs=list(self.chapter_jobs)
        planned_pages=sum(int(row.get('pages') or 0) for row in jobs)
        state={'pages_done':0,'pages_total':planned_pages,'bytes':0,'started':time.time(),'volume_done':0}
        outputs=[]; failures=[]
        self.log.emit(f'Chapter plan: {len(jobs)} chapter CBZ file(s).')
        for index, chapter in enumerate(jobs, 1):
            self._check_cancel(); state['volume_done']=0
            label=f'Chapter {chapter_label(chapter, self.zero_pad)}'
            final_title=chapter_output_title(self.title, chapter, self.zero_pad)
            output=Path(work) / (safe_filename(final_title) + '.cbz')
            self.log.emit(f'Starting {label} [{chapter.get("_source_name") or self.source_name}]...')
            before_done=state['pages_done']; before_bytes=state['bytes']
            try:
                cover_path=self._download_group([chapter], output, final_title, None,
                                                self.main_cover_url, state, index, len(jobs),
                                                int(chapter.get('pages') or 0),
                                                chapter_number=chapter.get('chapter'))
                _validate_cbz_output(output, self.page_layout)
                outputs.append({'path':str(output),'volume':chapter_series_index(chapter),
                                'title':final_title,'cover_path':cover_path,'kind':'chapter',
                                'chapter_number':chapter.get('chapter'),'source_id':chapter.get('_source_id')})
            except Exception as exc:
                if self.cancelled: raise
                output.unlink(missing_ok=True); state['pages_done']=before_done; state['bytes']=before_bytes
                failures.append({'volume':None,'label':label,'error':str(exc)})
                self.log.emit(f'FAILED {label}: {exc}')
        final_bytes=sum(Path(item['path']).stat().st_size for item in outputs if Path(item['path']).exists())
        self.finished_ok.emit({'files':outputs,'skipped':0,'elapsed':time.time()-t0,'workdir':work,
                              'pages':state['pages_done'],'planned_pages':state['pages_total'],'bytes':state['bytes'],
                              'final_bytes':final_bytes,'failed_volumes':[],'failed_bonus':False,
                              'failed_labels':[item['label'] for item in failures],'failures':failures})


class PreviewWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled_ok = pyqtSignal()
    progress = pyqtSignal(int, str)

    def __init__(self, source, url, title, author, series, language, start, end, zero_pad, existing_volumes, selected_volumes=None, include_standalone=False, bytes_per_page=450*1024, planned_chapters=None, chapter_items=None):
        super().__init__()
        self.source = source
        self.url = url
        self.title = title
        self.author = author
        self.series = series
        self.language = language
        self.start_volume = start
        self.end_volume = end
        self.zero_pad = zero_pad
        self.existing = set(existing_volumes)
        self.selected_volumes = None if selected_volumes is None else set(float(v) for v in selected_volumes)
        self.include_standalone = bool(include_standalone)
        self.bytes_per_page = max(128*1024, min(2*1024*1024, int(bytes_per_page or 450*1024)))
        self.planned_chapters=tuple(planned_chapters or ())
        self.chapter_items=None if chapter_items is None else set(chapter_items)

    def run(self):
        try:
            self._check_cancel()
            if hasattr(self, 'chapter_items') and self.chapter_items is not None:
                return self._run_chapter_mode()
            chapters = self.source.get_chapters(self.url, self.language, self.start_volume, self.end_volume)
            if not chapters:
                raise RuntimeError('No downloadable chapters were found for the selected language and volume range.')
            groups = {}
            for chapter in chapters:
                volume = chapter['volume']
                if self.selected_volumes is not None and volume is not None and float(volume) not in self.selected_volumes:
                    continue
                if volume is None and not self.include_standalone:
                    continue
                groups.setdefault(volume, []).append(chapter)
            if self.selected_volumes is not None and not groups:
                raise RuntimeError('No downloadable chapters were found for the checked volume selection.')

            rows = []
            manifest_total=sum(chapter.get('pages') is None for group in groups.values() for chapter in group)
            manifest_base=0

            def count_pages(chapter_group):
                nonlocal manifest_base
                group_missing=sum(chapter.get('pages') is None for chapter in chapter_group)
                def report(done, _total):
                    current=manifest_base+done
                    pct=int(current*100/max(1,manifest_total))
                    self.progress.emit(pct,review_manifest_progress(self.source.display_name,current,manifest_total))
                result=count_chapter_pages(
                    self.source,chapter_group,progress=report,
                    check_cancel=lambda: (_ for _ in ()).throw(InterruptedError()) if self.isInterruptionRequested() else None,
                )
                self._check_cancel()
                manifest_base += group_missing
                return result

            numbered = sorted(v for v in groups if v is not None)
            for volume in numbered:
                final_title = f'{self.title} (Vol. {fmt_volume(volume, self.zero_pad)})'
                pages = count_pages(groups[volume])
                rows.append({
                    'title': final_title,
                    'author': self.author,
                    'volume': volume,
                    'volume_text': f'{volume:g}',
                    'series': self.series,
                    'status': 'Already in Calibre' if volume in self.existing else 'Will download',
                    'pages': pages,
                    'existing': volume in self.existing,
                })
            if None in groups:
                pages = count_pages(groups[None])
                rows.append({
                    'title': f'{self.title} (Standalone Chapters)',
                    'author': self.author,
                    'volume': None,
                    'volume_text': 'Standalone',
                    'series': self.series,
                    'status': 'Will download',
                    'pages': pages,
                    'existing': False,
                })

            to_download = [r for r in rows if not r['existing']]
            pages = None if any(r['pages'] is None for r in to_download) else sum(r['pages'] for r in to_download)
            estimate = None if pages is None else pages * self.bytes_per_page
            self.ready.emit({
                'rows': rows,
                'existing_count': sum(1 for r in rows if r['existing']),
                'download_count': len(to_download),
                'pages': pages,
                'estimated_bytes': estimate,
            })
        except InterruptedError:
            self.cancelled_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))

    def _check_cancel(self):
        if self.isInterruptionRequested():
            raise InterruptedError()

    def _run_chapter_mode(self):
        rows=[]; selected=set(self.chapter_items)
        planned=list(getattr(self, 'planned_chapters', ()) or ())
        total=len(planned); done=0
        for chapter in planned:
            self._check_cancel()
            chapter_id=str(chapter.get('id') or '')
            if chapter_id not in selected:
                continue
            source=SOURCE_REGISTRY.get(chapter.get('_source_id')) or self.source
            pages=chapter.get('pages')
            if pages is None:
                try:
                    manifest=source.get_page_manifest(chapter_id) or {}; pages=len(manifest.get('full') or [])
                    self._check_cancel()
                except Exception:
                    self._check_cancel(); pages=None
                    pages=None
            done += 1
            self.progress.emit(int(done*100/max(1,total)), review_manifest_progress(source.display_name, done, total))
            label=chapter_label(chapter, self.zero_pad)
            rows.append({'title':chapter_output_title(self.title, chapter, self.zero_pad), 'author':self.author,
                         'volume':None,'volume_text':f'Ch. {label}','series':self.series,'status':'Will download',
                         'pages':pages,'existing':False,'kind':'chapter','chapter':chapter,
                         'source_name':source.display_name,'fallback':bool(chapter.get('_fallback_reason') not in ('', 'primary', None))})
        pages=None if any(row['pages'] is None for row in rows) else sum(row['pages'] for row in rows)
        self._check_cancel()
        self.ready.emit({'rows':rows,'existing_count':0,'download_count':len(rows),'pages':pages,
                         'estimated_bytes':None if pages is None else pages*self.bytes_per_page,
                         'chapter_mode':True})


class PairingPreviewWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    cancelled_ok = pyqtSignal()

    def __init__(self, source, url, language, volume, direction):
        super().__init__()
        self.source = source
        self.url, self.language, self.volume, self.direction = url, language, volume, direction
        self.cancelled = False
        self._orientation_verification_cache = {}

    def cancel(self):
        self.cancelled = True

    def _check_cancel(self):
        if self.cancelled:
            raise InterruptedError()

    def _fetch_preview_page(self, saver_url, full_url, page_number):
        """Fetch a data-saver page with transient retries, then fall back to full quality."""
        return self.source.fetch_preview_page(
            saver_url, full_url, page_number,
            log=self.log.emit, check_cancel=self._check_cancel,
        )

    def run(self):
        started = time.monotonic()
        try:
            chapters = self.source.get_chapters(self.url, self.language, self.volume, self.volume)
            chapters = [c for c in chapters if c.get('volume') == self.volume]
            if not chapters:
                raise RuntimeError('No chapters were found for the selected pairing-preview item.')

            base_limit = 12
            hard_limit = 14
            self.log.emit(f'Pairing preview starts with the first {base_limit} source pages and may sample up to {hard_limit} to finish a complete pair.')
            self.log.emit(f'Preview mode: using {self.source.display_name} reduced-quality images when available.')

            # Build a lightweight ordered page queue first. This lets the sample
            # request one or two extra source pages only when its current ending
            # would be an artificial isolated page caused by the sample boundary.
            page_refs=[]
            for chap_num, chapter in enumerate(chapters, 1):
                self._check_cancel()
                ch_label=chapter.get('chapter') or 'unnumbered'
                ch_title=str(chapter.get('title') or '').strip()
                manifest=self.source.get_page_manifest(chapter['id'])
                full_urls=manifest.get('full') or []
                saver_urls=manifest.get('data_saver') or list(full_urls)
                if len(full_urls) != len(saver_urls):
                    raise RuntimeError(f'MangaDex returned mismatched preview page lists for Chapter {ch_label}.')
                for page_in_chapter, saver_url in enumerate(saver_urls, 1):
                    page_refs.append((chap_num, ch_label, ch_title, page_in_chapter, len(saver_urls), saver_url, full_urls[page_in_chapter-1]))
                    if len(page_refs) >= hard_limit:
                        break
                if len(page_refs) >= hard_limit:
                    break
            if not page_refs:
                raise RuntimeError('MangaDex returned no readable pages for the selected preview volume.')

            target=min(base_limit, len(page_refs))
            records=[]; bytes_done=0; fallback_count=0; recent=[]; last_bucket=-1
            announced_chapter=None

            def fetch_until(target_count):
                nonlocal bytes_done, fallback_count, last_bucket, announced_chapter
                while len(records) < target_count:
                    self._check_cancel()
                    chap_num, ch_label, ch_title, page_in_chapter, chapter_pages, saver_url, full_url = page_refs[len(records)]
                    if announced_chapter != chap_num:
                        announced_chapter=chap_num
                        self.log.emit(f'Preview: Chapter {chap_num} of {len(chapters)} (Chapter {ch_label})...')
                    page_no=len(records)+1
                    t0=time.monotonic()
                    blob, used_fallback=self._fetch_preview_page(saver_url, full_url, page_no)
                    orientation_verification=None
                    if not used_fallback and 'data_saver' in self.source.capabilities and saver_url != full_url:
                        try:
                            blob, verified_full, orientation_verification = _select_verified_preview_source(
                                blob,
                                full_url,
                                lambda url: self.source.fetch_binary(
                                    url,
                                    timeout=45,
                                    retries=4,
                                    user_agent=USER_AGENT,
                                ),
                                self._orientation_verification_cache,
                            )
                            used_fallback = bool(verified_full)
                        except Exception as e:
                            self.log.emit(
                                f'Orientation verification: Chapter {ch_label}, source page {page_in_chapter} | '
                                f'full-quality verification failed; using data saver ({e})'
                            )
                    dt=max(0.001,time.monotonic()-t0)
                    if used_fallback: fallback_count += 1
                    bytes_done += len(blob)
                    recent.append((len(blob),dt))
                    if len(recent)>12: recent.pop(0)
                    speed=sum(x[0] for x in recent)/max(0.001,sum(x[1] for x in recent))
                    ext=image_extension(full_url if used_fallback else saver_url)
                    original_size=_image_size(blob)
                    exif_before=_exif_orientation_value(blob)
                    blob,size,exif_changed,orientation=_normalize_exif_orientation(blob,ext)
                    exif_after=_exif_orientation_value(blob)
                    if orientation_verification:
                        saver_size=orientation_verification['saver_size']
                        saver_exif=orientation_verification['saver_exif']
                        full_exif=orientation_verification['full_exif']
                        if used_fallback and full_exif in range(2, 9):
                            self.log.emit(
                                f'Orientation verification: Chapter {ch_label}, source page {page_in_chapter} | '
                                f'data saver {saver_size[0]}x{saver_size[1]} EXIF {saver_exif} | '
                                f'full quality EXIF {full_exif} | using full quality normalized {size[0]}x{size[1]}'
                            )
                        else:
                            self.log.emit(
                                f'Orientation verification: Chapter {ch_label}, source page {page_in_chapter} | '
                                f'data saver {saver_size[0]}x{saver_size[1]} EXIF {saver_exif} | '
                                f'full quality EXIF {full_exif} | confirmed landscape spread'
                            )
                    records.append({'blob':blob,'ext':ext,'size':size,'chapter_index':chap_num,
                                    'chapter_label':ch_label,'chapter_title':ch_title,
                                    'page_in_chapter':page_in_chapter,
                                    'chapter_pages':chapter_pages,'original_size':original_size,
                                    'normalized_size':size,'exif_before':exif_before,
                                    'exif_after':exif_after,
                                    'download_quality':('full quality' if used_fallback else 'data saver'),
                                    'later_transforms':[]})
                    total=max(target_count,len(records)); done=len(records)
                    remaining=max(0,total-done); elapsed=max(0.001,time.monotonic()-started)
                    pages_per_sec=done/elapsed; eta=remaining/pages_per_sec if pages_per_sec>0 else None
                    pct=min(82,int(done*82/max(1,total)))
                    self.progress.emit(pct, f'Preview download: Page {done}/{total} • {format_speed(speed)} • ETA {format_eta(eta)}')
                    bucket=int(done*10/max(1,total))
                    if bucket>last_bucket or done==total:
                        last_bucket=bucket
                        self.log.emit(f'Preview: downloaded {done} / {total} pages ({min(100,int(done*100/max(1,total)))}%) • {format_speed(speed)} • ETA {format_eta(eta)}.')

            fetch_until(target)
            pages,stats=build_landscape_pages(records,self.direction,log=self.log.emit,detailed=True)
            # If the current sample ends on an isolated source page and more pages
            # exist, extend just enough to reveal the real following pair.
            while pages and pages[-1][2] == 'ISOLATED' and len(records) < min(hard_limit,len(page_refs)):
                target=len(records)+1
                self.log.emit('Preview sample ended on an incomplete pair; sampling one additional source page.')
                fetch_until(target)
                pages,stats=build_landscape_pages(records,self.direction,log=self.log.emit,detailed=True)

            self._check_cancel()
            if fallback_count:
                self.log.emit(f'Preview download complete. {fallback_count} page(s) used full-quality fallback.')
            else:
                self.log.emit('Preview download complete. All pages used reduced-quality images.')
            self.progress.emit(85,f'Analyzing page layout... {len(records)} source pages')
            self.log.emit(f'Analyzing {len(records)} pages...')
            self.log.emit(f"Preview layout: {stats.get('spreads',0)} original spreads, {stats.get('pairs',0)} paired pages, {stats.get('isolated',0)} isolated pages.")
            thumbs=[]; total_out=len(pages)
            for i,(_ext,blob,kind) in enumerate(pages,1):
                self._check_cancel()
                with Image.open(BytesIO(blob)) as im:
                    im=_to_rgb(im.copy()); im.thumbnail((360,270),Image.Resampling.LANCZOS)
                    out=BytesIO(); im.save(out,'JPEG',quality=78)
                    thumbs.append((i,out.getvalue(),kind))
                    self.log.emit(f'Preview trace: Output page {i} thumbnail {im.width}x{im.height} supplied to the preview widget.')
                pct=88+int(i*12/max(1,total_out)); self.progress.emit(min(100,pct),f'Building preview thumbnails... {i}/{total_out}')
            elapsed=time.monotonic()-started
            self.log.emit(f'Pairing preview ready. {len(records)} source pages → {total_out} landscape pages. Completed in {elapsed:.1f}s.')
            self.ready.emit({'volume':self.volume,'label':('Standalone Chapters' if self.volume is None else f'Volume {self.volume:g}'),'thumbs':thumbs,'stats':stats,'source_pages':len(records),'output_pages':total_out})
        except InterruptedError:
            self.cancelled_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


class PairingPreviewDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        label=data.get('label') or ('Standalone Chapters' if data.get('volume') is None else f"Volume {data['volume']:g}")
        self.setWindowTitle(f"Landscape Pairing Preview - {label}")
        self.resize(1100, 760)
        root = QVBoxLayout(self)
        st = data.get('stats') or {}
        summary = QLabel(
            f"{label} | {data.get('source_pages',0)} source pages → {data.get('output_pages',0)} landscape pages | "
            f"{st.get('spreads',0)} original spreads | {st.get('pairs',0)} paired pages"
        )
        summary.setWordWrap(True); root.addWidget(summary)
        note = QLabel('Short pairing sample only. Nothing is added to Calibre.')
        note.setWordWrap(True); root.addWidget(note)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        body = QWidget(); grid = QGridLayout(body)
        for n, blob, _kind in data.get('thumbs', []):
            cell = QFrame(); lay = QVBoxLayout(cell)
            pic = QLabel(); pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap(); pm.loadFromData(blob); pic.setPixmap(pm)
            cap = QLabel(f'Output page {n}'); cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(pic); lay.addWidget(cap)
            grid.addWidget(cell, (n-1)//3, (n-1)%3)
        self.scroll.setWidget(body); root.addWidget(self.scroll, 1)
        buttons = QHBoxLayout(); buttons.addStretch(1)
        close = QPushButton('Close'); close.clicked.connect(self.reject); buttons.addWidget(close)
        root.addLayout(buttons)


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MangaNana Preferences')
        self.resize(500, 430)
        root = QVBoxLayout(self)

        general = QGroupBox('Defaults')
        form = QFormLayout(general)
        self.language = QComboBox()
        populate_manga_languages(self.language)
        idx = self.language.findData(prefs['language'])
        if idx >= 0:
            self.language.setCurrentIndex(idx)
        self.covers = QCheckBox('Include volume covers')
        self.covers.setChecked(bool(prefs['include_volume_covers']))
        self.pad = QCheckBox('Zero-pad volume numbers')
        self.pad.setChecked(bool(prefs['zero_pad']))
        self.page_layout = QComboBox(); self.page_layout.addItem('Portrait (Individual Pages)', 'original_pages'); self.page_layout.addItem('Landscape (Paired Pages)', 'paired_landscape')
        pli=self.page_layout.findData(prefs['page_layout']); self.page_layout.setCurrentIndex(max(0, pli))
        self.reading_direction = QComboBox(); self.reading_direction.addItem('Right to Left (Manga)', 'rtl'); self.reading_direction.addItem('Left to Right', 'ltr')
        rdi=self.reading_direction.findData(prefs['reading_direction']); self.reading_direction.setCurrentIndex(max(0, rdi))
        self.ui_language = QComboBox()
        for label, code in UI_LANGUAGES:
            self.ui_language.addItem(label, code)
        ui_idx = self.ui_language.findData(prefs['ui_language'])
        if ui_idx >= 0:
            self.ui_language.setCurrentIndex(ui_idx)
        self.ui_language.setToolTip('Sets the MangaNana interface language.\nEnglish is currently included.')
        self.language.setToolTip('Preferred language for manga titles and metadata.\nDownload Language is chosen separately for each loaded manga.')
        self.covers.setToolTip('Downloads the selected source volume cover for Calibre and Kobo metadata.\nThe cover is kept outside the CBZ reading pages.')
        self.pad.setToolTip('Formats volumes as 01, 02, 03, etc.\nHelps titles sort in numerical order.')
        self.page_layout.setToolTip('Portrait keeps individual source pages.\nLandscape creates book-style paired pages.\nIsolated pages stay on the right.')
        self.reading_direction.setToolTip('Controls pairing order in Landscape mode.\nRight to Left is standard manga order.')
        form.addRow('Preferred title/metadata language:', self.language)
        form.addRow('Interface language:', self.ui_language)
        form.addRow('Default page layout:', self.page_layout)
        form.addRow('Default reading direction:', self.reading_direction)
        form.addRow('', self.covers)
        form.addRow('', self.pad)
        root.addWidget(general)

        behavior = QGroupBox('Behavior')
        bl = QVBoxLayout(behavior)
        self.ask_vl = QCheckBox('Ask to create the MangaNana Virtual Library')
        self.ask_vl.setChecked(bool(prefs['ask_virtual_library']))
        self.summary = QCheckBox('Show completion summary after downloads')
        self.summary.setChecked(bool(prefs['show_completion_summary']))
        self.adult_search = QCheckBox('Show 18+ search results')
        self.adult_search.setChecked(bool(prefs['show_adult_search_results']))
        self.adult_search.setToolTip('When disabled, providers hide adult titles when that classification is available.\nSuggestive titles remain visible.')
        self.ask_vl.setToolTip('Offers to create a MangaNana Virtual Library.\nUseful for separating manga from other books.')
        self.summary.setToolTip('Shows download statistics and quick actions\nwhen a job finishes.')
        self.duplicate_policy = QComboBox()
        self.duplicate_policy.addItem('Skip existing (Recommended)', 'skip')
        self.duplicate_policy.addItem('Ask when existing volumes are found', 'ask')
        self.duplicate_policy.addItem('Replace existing CBZ files', 'replace')
        dpi = self.duplicate_policy.findData(prefs['duplicate_policy'])
        if dpi >= 0: self.duplicate_policy.setCurrentIndex(dpi)
        self.duplicate_policy.setToolTip('Chooses what happens when the same volume\nalready exists in Calibre.')
        bl.addWidget(self.ask_vl)
        bl.addWidget(self.summary)
        bl.addWidget(self.adult_search)
        dpform = QFormLayout(); dpform.addRow('Existing volumes:', self.duplicate_policy); bl.addLayout(dpform)
        root.addWidget(behavior)

        note = QLabel('Existing numbered volumes are skipped automatically to protect books already in Calibre.')
        note.setWordWrap(True)
        note.setStyleSheet('color:#bdbdbd;')
        root.addWidget(note)
        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def accept(self):
        prefs['language'] = self.language.currentData()
        prefs['ui_language'] = self.ui_language.currentData()
        prefs['include_volume_covers'] = self.covers.isChecked()
        prefs['zero_pad'] = self.pad.isChecked()
        prefs['page_layout'] = self.page_layout.currentData()
        prefs['reading_direction'] = self.reading_direction.currentData()
        prefs['ask_virtual_library'] = self.ask_vl.isChecked()
        prefs['show_completion_summary'] = self.summary.isChecked()
        prefs['show_adult_search_results'] = self.adult_search.isChecked()
        prefs['duplicate_policy'] = self.duplicate_policy.currentData()
        try:
            prefs.commit()
        except Exception:
            pass
        super().accept()


class CoverLoadingLabel(QLabel):
    """Themed cover surface; only the selected cover owns a spinner timer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading=False; self._failed=False; self._loading_style='spinner'; self._phase=0
        self._spinner_timer=QTimer(self); self._spinner_timer.setInterval(85)
        self._spinner_timer.timeout.connect(self._spin)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _spin(self):
        self._phase=(self._phase + 1) % 12; self.update()

    def set_loading(self, loading=True, style='spinner'):
        self._loading=bool(loading); self._failed=False
        self._loading_style=style
        if self._loading and style == 'spinner':
            super().clear(); self._spinner_timer.start()
        else:
            self._spinner_timer.stop()
        self.update()

    def set_failed(self, text='No Cover'):
        self._loading=False; self._failed=True; self._spinner_timer.stop()
        super().setText(text); self.update()

    def setPixmap(self, pixmap):
        self._loading=False; self._failed=False; self._spinner_timer.stop()
        super().setPixmap(pixmap); self.update()

    def clear(self):
        self._loading=False; self._failed=False; self._spinner_timer.stop()
        super().clear(); self.update()

    def paintEvent(self, event):
        if not self._loading:
            return super().paintEvent(event)
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor('#17191B'))
        if self._loading_style == 'pulse':
            # The dialog's shared timer advances this only for visible rows.
            glow=46 + (self._phase % 8) * 9
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(255,103,64,glow))
            size=max(9, min(self.width(), self.height()) // 3)
            center=self.rect().center()
            painter.drawRoundedRect(center.x()-size//2, center.y()-size//2, size, size, 3, 3)
            painter.end()
            return
        center=self.rect().center(); radius=max(5, min(self.width(), self.height()) // 4)
        dot=max(2, min(5, radius // 3))
        for index in range(12):
            trail=(index - self._phase) % 12
            alpha=max(28, 255 - trail * 19)
            angle=(index / 12.0) * math.tau - math.pi / 2
            x=center.x() + math.cos(angle) * radius
            y=center.y() + math.sin(angle) * radius
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(255,103,64,alpha))
            painter.drawEllipse(int(x-dot), int(y-dot), dot*2, dot*2)
        painter.end()


class VolumeRowWidget(QFrame):
    """Compact volume selector row with a right-side round multi-select control."""
    toggled = pyqtSignal(bool)

    def __init__(self, title, parent=None, cover_loading=False):
        super().__init__(parent)
        self.setObjectName('volumeRow')
        # Let the row derive its height from the cover and current font/DPI.
        # This avoids text/header overlap on laptops using larger Windows scaling.
        self.setMinimumHeight(68)
        row=QHBoxLayout(self); row.setContentsMargins(8,5,8,5); row.setSpacing(10)
        self.cover=CoverLoadingLabel(); self.cover.setFixedSize(42,58); self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet('background:#17191B; color:#FF6740; border:0; border-radius:3px; font-size:10px; font-weight:800;')
        if cover_loading: self.cover.set_loading(style='pulse')
        else: self.cover.set_failed()
        row.addWidget(self.cover,0,Qt.AlignmentFlag.AlignVCenter)
        self.title=QLabel(title); self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setWordWrap(False); self.title.setMinimumWidth(0)
        self.title.setStyleSheet('font-size:12px; font-weight:600; color:#F1F1F1;')
        row.addWidget(self.title,1,Qt.AlignmentFlag.AlignVCenter)
        self.pick=QPushButton('')
        self.pick.setCheckable(True); self.pick.setFixedSize(22,22)
        self.pick.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pick.clicked.connect(self._button_toggled)
        row.addWidget(self.pick,0,Qt.AlignmentFlag.AlignVCenter)
        self.set_checked(False)

    def _button_toggled(self, checked):
        self.set_checked(bool(checked), emit_signal=True)

    def mousePressEvent(self, event):
        # Clicking anywhere on the row toggles the volume, matching the concept UI.
        if not self.pick.geometry().contains(event.position().toPoint()):
            self.set_checked(not self.pick.isChecked(), emit_signal=True)
        super().mousePressEvent(event)

    def set_checked(self, checked, emit_signal=False):
        checked=bool(checked)
        self.pick.blockSignals(True); self.pick.setChecked(checked); self.pick.setText('✓' if checked else ''); self.pick.blockSignals(False)
        if checked:
            self.setStyleSheet('QFrame#volumeRow { background:#3B241D; border:1px solid #FF6740; border-radius:6px; }')
            self.pick.setStyleSheet('QPushButton { background:#FF6740; color:#17191B; border:1px solid #FF6740; border-radius:11px; padding:0; font-weight:900; }')
        else:
            self.setStyleSheet('QFrame#volumeRow { background:#121416; border:1px solid transparent; border-radius:6px; } QFrame#volumeRow:hover { background:#181B1E; border:1px solid #3A3F44; }')
            self.pick.setStyleSheet('QPushButton { background:#121416; color:#FF6740; border:1px solid #50555A; border-radius:11px; padding:0; } QPushButton:hover { border:1px solid #FF6740; }')
        if emit_signal:
            self.toggled.emit(checked)

    def set_cover(self, pixmap):
        if pixmap is None:
            self.cover.set_failed()
        else:
            self.cover.setPixmap(pixmap)


_PROVIDER_ICON_PIXMAPS = {}


def _provider_icon_pixmap(icon_path):
    """Load a bundled plugin resource, with a source-tree fallback for tests."""
    path = str(icon_path or '')
    if not path:
        return None
    if path not in _PROVIDER_ICON_PIXMAPS:
        pixmap = QPixmap()
        try:
            raw = get_resources(path)
            if raw:
                pixmap.loadFromData(raw)
        except Exception:
            asset = Path(path)
            if not asset.is_absolute():
                asset = Path(__file__).resolve().parent / asset
            if asset.is_file():
                pixmap.load(str(asset))
        _PROVIDER_ICON_PIXMAPS[path] = pixmap
    pixmap = _PROVIDER_ICON_PIXMAPS[path]
    return pixmap if not pixmap.isNull() else None


class ProviderBadgeWidget(QFrame):
    """Dark, content-sized MangaNana pill for a confirmed provider source."""
    ICON_SIZE = 16

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        spec = dict(spec or {})
        accent = spec.get('accent_color') or '#555B61'
        text_color = spec.get('text_color') or '#FFFFFF'
        self.setAccessibleName(f"Provider: {spec.get('text') or 'Provider'}")
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            f'QFrame {{ color:{text_color}; background:#211E1D; border:1px solid {accent}; '
            'border-radius:8px; }}'
        )
        glow = QGraphicsDropShadowEffect(self)
        glow_color = QColor(accent); glow_color.setAlpha(105)
        glow.setColor(glow_color); glow.setBlurRadius(7); glow.setOffset(0, 0)
        self.setGraphicsEffect(glow)
        layout = QHBoxLayout(self); layout.setContentsMargins(6, 2, 7, 2); layout.setSpacing(5)
        pixmap = _provider_icon_pixmap(spec.get('icon_path'))
        if pixmap is not None:
            icon = QLabel(); icon.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setStyleSheet('QLabel { background:transparent; border:0; }')
            icon.setPixmap(pixmap.scaled(
                QSize(self.ICON_SIZE, self.ICON_SIZE),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QLabel(spec.get('text') or 'Provider'); text.setWordWrap(False)
        text.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        text.setStyleSheet(f'QLabel {{ color:{text_color}; background:transparent; border:0; font-size:9px; font-weight:800; }}')
        text.setMinimumWidth(text.sizeHint().width())
        layout.addWidget(text, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(max(20, text.sizeHint().height() + 4))


class MangaSourcesDialog(QDialog):
    """Generic general-search participation controls for registered sources."""

    def __init__(self, registry, preferences, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.preferences = preferences
        self.checkboxes = {}
        self.setWindowTitle('MangaNana - Manga Sources')
        self.resize(470, 300)
        self.setStyleSheet(
            'QDialog { background:#17191B; color:#ECECEC; } '
            'QFrame#sourceManagerRow { background:#211E1D; border:1px solid #3C3F42; border-radius:8px; } '
            'QLabel { color:#ECECEC; } QCheckBox { color:#DADADA; spacing:7px; }'
        )
        root = QVBoxLayout(self); root.setContentsMargins(16,16,16,14); root.setSpacing(10)
        heading = QLabel('Manga Sources')
        heading.setStyleSheet('font-size:17px; font-weight:800; color:#FFFFFF;')
        root.addWidget(heading)
        note = QLabel('Choose which registered sources participate in general title searches. Direct links remain supported.')
        note.setWordWrap(True); note.setStyleSheet('color:#AEB2B6; font-size:10px;')
        root.addWidget(note)

        for source in registry.all():
            spec = provider_badge_spec(source.source_id, source.display_name)
            row = QFrame(); row.setObjectName('sourceManagerRow')
            layout = QHBoxLayout(row); layout.setContentsMargins(11,8,12,8); layout.setSpacing(10)
            pixmap = _provider_icon_pixmap(spec.get('icon_path'))
            if pixmap is not None:
                icon = QLabel(); icon.setFixedSize(24,24); icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setPixmap(pixmap.scaled(
                    QSize(22,22), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
                layout.addWidget(icon)
            name = QLabel(spec.get('text') or source.display_name)
            name.setStyleSheet('font-size:12px; font-weight:750; color:#F1F1F1;')
            layout.addWidget(name); layout.addStretch(1)
            checkbox = QCheckBox('Enabled')
            checkbox.setChecked(is_source_enabled(preferences, source))
            self.checkboxes[source.source_id] = checkbox
            layout.addWidget(checkbox)
            root.addWidget(row)

        root.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def accept(self):
        save_source_enabled_states(
            self.preferences,
            {source_id: checkbox.isChecked() for source_id, checkbox in self.checkboxes.items()},
            commit=True,
        )
        super().accept()


class SearchResultRowWidget(QFrame):
    """Compact search row that does not claim unresolved sources are usable."""
    def __init__(self, title, author, confirmed_sources=(), badge='', parent=None, cover_loading=False):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row=QHBoxLayout(self); row.setContentsMargins(6,5,8,5); row.setSpacing(10)
        self.cover=CoverLoadingLabel(); self.cover.setFixedSize(70,98); self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet('background:#17191B; color:#FF6740; border-radius:4px; font-size:11px; font-weight:800;')
        if cover_loading: self.cover.set_loading(style='pulse')
        else: self.cover.set_failed()
        row.addWidget(self.cover,0,Qt.AlignmentFlag.AlignVCenter)
        details=QVBoxLayout(); details.setContentsMargins(0,2,0,2); details.setSpacing(5)
        self.details = details
        title_text=title + (f'   [{badge}]' if badge else '')
        title_label=QLabel(title_text); title_label.setStyleSheet('color:#F1F1F1; font-size:12px; font-weight:700;')
        title_label.setWordWrap(True); details.addWidget(title_label)
        self.source_state_widget = None
        self.set_source_state(confirmed_sources)
        if author:
            author_label=QLabel(author); author_label.setStyleSheet('color:#A9ADB1; font-size:10px;')
            details.addWidget(author_label)
        details.addStretch(1); row.addLayout(details,1)

    def set_source_state(self, confirmed_sources=(), language_note=''):
        if self.source_state_widget is not None:
            self.details.removeWidget(self.source_state_widget)
            self.source_state_widget.deleteLater()
        host = QWidget(self)
        state = QVBoxLayout(host); state.setContentsMargins(0,0,0,0); state.setSpacing(2)
        if confirmed_sources:
            source_ids = tuple(source_id for source_id, _name in confirmed_sources)
            source_names = tuple(name for _source_id, name in confirmed_sources)
            chips=QHBoxLayout(); chips.setContentsMargins(0,0,0,0); chips.setSpacing(5)
            for spec in source_badge_specs(source_names, source_ids):
                chips.addWidget(ProviderBadgeWidget(spec,self),0,Qt.AlignmentFlag.AlignVCenter)
            chips.addStretch(1); state.addLayout(chips)
        else:
            unresolved = QLabel('Checking sources…')
            unresolved.setStyleSheet('color:#8F9499; font-size:9px; font-weight:600;')
            state.addWidget(unresolved)
        if language_note:
            note = QLabel(language_note)
            note.setStyleSheet('color:#D6A46C; font-size:9px; font-weight:600;')
            state.addWidget(note)
        self.source_state_widget = host
        self.details.insertWidget(1, host)

    def set_cover(self, pixmap):
        if pixmap is not None:
            self.cover.setPixmap(pixmap)
        else:
            self.cover.set_failed()

    def cover_failed(self):
        self.cover.set_failed()


class MangaNanaProgressBar(QProgressBar):
    """Standard solid progress bar with an explicit determinate helper."""
    def setDeterminateValue(self, value):
        """Keep Review progress static, solid, left-anchored, and determinate."""
        self.setRange(0, 100)
        self.setValue(value)


class PreviewUseSelector(QPushButton):
    """Round include/exclude control matching the Volumes selector."""
    changed = pyqtSignal(bool)

    def __init__(self, checked=True, enabled=True, parent=None):
        super().__init__('', parent)
        self.setCheckable(True)
        self.setFixedSize(22,22)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.clicked.connect(self._clicked)
        self.setEnabled(bool(enabled))
        self.set_selected(bool(checked))

    def _clicked(self, checked):
        self.set_selected(bool(checked))
        self.changed.emit(bool(checked))

    def set_selected(self, checked):
        checked=bool(checked)
        self.blockSignals(True); self.setChecked(checked); self.setText('✓' if checked else ''); self.blockSignals(False)
        if not self.isEnabled():
            self.setStyleSheet('QPushButton { background:#121416; color:#60656A; border:1px solid #3A3F44; border-radius:11px; padding:0; }')
        elif checked:
            self.setStyleSheet('QPushButton { background:#FF6740; color:#17191B; border:1px solid #FF6740; border-radius:11px; padding:0; font-weight:900; }')
        else:
            self.setStyleSheet('QPushButton { background:#121416; color:#FF6740; border:1px solid #50555A; border-radius:11px; padding:0; } QPushButton:hover { border:1px solid #FF6740; }')



class MangaNanaDialog(QDialog):
    def __init__(self, gui, icon):
        super().__init__(gui)
        self.gui = gui
        self.db = gui.current_db.new_api
        self.icon = icon
        self.worker = None
        self.preview_worker = None
        self._preview_workers = []
        self.pairing_preview_worker = None
        self.preview_data = None
        self.preview_signature = None
        self._preview_request_id = 0
        self._preview_build_signature = None
        self.loaded_metadata = None
        self.current_manga_url = ''
        self.current_source = MANGADEX_SOURCE
        self.current_source_id = MANGADEX_SOURCE.source_id
        self._loaded_covers = {}
        self._main_cover_url = ''
        self._pending_search_url = ''
        self._pending_source_id = ''
        self._pending_search_cover_url = ''
        self._pending_search_language = ''
        self._last_discovery_kind = None
        self._last_discovery_value = ''
        self._manga_discovery_kinds = {}
        self._current_plan = None
        self.workflow_mode = None
        self._mode_generation = 0
        self._chapter_plan_items = ()
        self._pending_cross_source_plan = None
        self._selected_chapter_ids = set()
        self._download_language_valid = False
        self._volume_plan_loading = False
        self._session_replace_existing = False
        self._last_retry_context = None
        self._download_in_progress = False
        self._search_cache = {}
        self._download_availability_cache = {}
        self._manga_cache = {}
        self._plan_cache = {}
        self._image_cache = {}
        self._failed_image_urls = set()
        self._search_page_size = 12
        self._search_query = ''
        self._search_raw_results = []
        self._search_offsets = {}
        self._search_has_more = {}
        self._search_total = 0
        self._search_request_id = 0
        self._search_cancel_requested = False
        self._search_started_at = 0.0
        self._search_provider_ids = ()
        self._search_ranked_groups = ()
        self._search_resolutions = {}
        self._search_resolution_request_id = 0
        self._search_resolution_worker = None
        self._search_resolution_metadata_cache = {}
        self._search_resolution_inventory_cache = {}
        self._manga_request_id = 0
        self._manga_requested_languages = {}
        self._volume_plan_request_id = 0
        self._pending_result_token = 0
        self._selected_volume = None
        self._selected_volumes = set()
        self._standalone_selected = False
        self._using_entire_series = False
        self._bytes_per_page_estimate = 450 * 1024
        self._manual_range_invalid = False
        self._manual_range_error = ''
        self._last_invalid_range_log_key = None
        self._range_edit_snapshot = ('', '')
        self._range_event_filter_installed = False
        self._selected_cover_url = ''
        self._range_syncing = False
        self._volume_check_syncing = False
        self._pending_auto_preview = False
        self._review_cancel_requested = False
        self._auto_preview_delay_ms = 360
        self.search_worker = None
        self.search_workers = {}
        self.search_coordinator = SourceCoordinator(SOURCE_REGISTRY)
        self.inventory_comparison_worker = None
        self._inventory_comparison_request_id = 0
        self._last_inventory_decision = None
        self.search_thumb_worker = None
        self.volume_thumb_worker = None
        self._cover_generation = 0
        self._search_cover_batch_token = 0
        self._volume_cover_batch_token = 0
        self._closing = False
        self._manga_workers = []
        self._plan_workers = []
        self.setWindowTitle(f'{DISPLAY_VERSION} for calibre')
        self.setWindowIcon(icon)
        self.resize(int(prefs.get('window_w', 1450) or 1450), int(prefs.get('window_h', 850) or 850))
        self.setMinimumSize(1280, 760)
        self.build_ui()
        self._search_status_timer=QTimer(self); self._search_status_timer.setInterval(1000)
        self._search_status_timer.timeout.connect(self._update_search_status)
        self._cover_pulse_timer=QTimer(self); self._cover_pulse_timer.setInterval(170)
        self._cover_pulse_timer.timeout.connect(self._refresh_visible_cover_pulses)
        self._cover_pulse_timer.start()
        self._install_diagnostic_hook()
        self._install_range_focus_behavior()
        self._restore_session()

    def heading(self, text):
        l = QLabel(text)
        l.setStyleSheet(f'font-weight:700; color:{ORANGE}; font-size:14px;')
        return l

    def _diagnostic_context(self):
        source=getattr(self, 'current_source', None)
        return {
            'version': DISPLAY_VERSION,
            'build_id': GIT_COMMIT,
            'mode': getattr(self, 'workflow_mode', None),
            'provider': getattr(source, 'display_name', None) or getattr(self, 'current_source_id', None),
            'operation': getattr(self, '_diagnostic_operation', 'idle'),
        }

    def _record_diagnostic(self, exc_type, exc, tb, operation=None):
        if operation:
            self._diagnostic_operation=operation
        try:
            path=write_diagnostic_report(
                Path(config_dir) / 'plugins', exc_type=exc_type, exc=exc, tb=tb,
                **self._diagnostic_context(),
            )
            if path and not self._closing and hasattr(self, 'log'):
                self.add_log(f'Diagnostic report saved: {path}')
            return path
        except Exception:
            return None

    def _install_diagnostic_hook(self):
        self._previous_excepthook=sys.excepthook

        def report_uncaught(exc_type, exc, tb):
            self._record_diagnostic(exc_type, exc, tb, 'uncaught Qt/Python callback')
            self._previous_excepthook(exc_type, exc, tb)

        self._diagnostic_excepthook=report_uncaught
        sys.excepthook=report_uncaught

    def _restore_diagnostic_hook(self):
        if getattr(self, '_diagnostic_excepthook', None) is sys.excepthook:
            sys.excepthook=getattr(self, '_previous_excepthook', sys.__excepthook__)

    def _invalidate_cover_requests(self):
        """Make in-flight thumbnail signals harmless after a new UI context."""
        self._cover_generation += 1
        for worker in (self.search_thumb_worker, self.volume_thumb_worker):
            if worker and worker.isRunning():
                worker.requestInterruption()

    def _refresh_visible_cover_pulses(self):
        if self._closing:
            return
        for widget, row_height in ((self.search_results,127), (self.volume_list,66)):
            for index in self._visible_row_range(widget,row_height,1):
                row=widget.itemWidget(widget.item(index))
                cover=getattr(row, 'cover', None)
                if isinstance(cover,CoverLoadingLabel) and cover._loading and cover._loading_style == 'pulse':
                    cover._phase=(cover._phase + 1) % 16
                    cover.update()

    def _set_edition_badge(self, text=None):
        text = str(text or '').strip()
        if not text:
            self.edition_badge.clear()
            self.edition_badge.setVisible(False)
            return
        self.edition_badge.setText(text)
        try:
            width = max(48, min(108, self.edition_badge.fontMetrics().horizontalAdvance(text) + 22))
            self.edition_badge.setFixedWidth(width)
        except Exception:
            pass
        self.edition_badge.setVisible(True)

    def _apply_manganana_theme(self):
        self.setStyleSheet(f"""
            QDialog {{ background:#111315; color:#ECECEC; }}
            QWidget {{ color:#ECECEC; font-size:12px; }}
            QFrame#card, QGroupBox {{ background:#191C1F; border:1px solid #30353A; border-radius:9px; }}
            QGroupBox {{ margin-top:12px; padding:12px 10px 10px 10px; font-weight:600; color:#D9D9D9; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 5px; }}
            QLineEdit, QComboBox, QListWidget, QTableWidget {{
                background:#121416; border:1px solid #3A3F44; border-radius:6px; padding:6px; color:#F2F2F2;
                selection-background-color:#3B241D; selection-color:#FFFFFF;
            }}
            QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTableWidget:focus {{ border:1px solid {ORANGE}; }}
            QComboBox:disabled {{ background:#17191B; color:#686868; border:1px solid #33373A; }}
            QLabel:disabled {{ color:#686868; }}
            QComboBox::drop-down {{ border:0; width:24px; }}
            QPushButton {{
                background:#1B1E21; color:{ORANGE}; border:1px solid #A7442D; border-radius:6px;
                padding:7px 13px; font-weight:600;
            }}
            QPushButton:hover {{ background:#22262A; border:1px solid {ORANGE}; color:#FF8A6B; }}
            QPushButton:pressed {{ background:#2B211E; border:1px solid #FF8A6B; }}
            QPushButton:disabled {{ background:#17191B; color:#686868; border:1px solid #33373A; }}
            QPushButton#layoutChoice {{ min-width:118px; min-height:68px; max-height:74px; font-size:12px; padding:6px 7px; }}
            QPushButton#layoutChoice:checked {{ background:#3A211B; color:#FFFFFF; border:2px solid {ORANGE}; }}
            QPushButton#secondaryAction {{ min-height:18px; padding:9px 18px; border:1px solid {ORANGE}; background:#1B1E21; color:{ORANGE}; }}
            QPushButton#primaryAction {{ min-height:18px; padding:9px 20px; border:1px solid {ORANGE}; background:{ORANGE}; color:#17191B; font-weight:800; }}
            QPushButton#primaryAction:hover {{ background:#FF7B5A; color:#111315; border:1px solid #FF8A6B; }}
            QPushButton#primaryAction:disabled {{ background:#17191B; color:#686868; border:1px solid #33373A; font-weight:600; }}
            QPushButton#secondaryAction:disabled {{ background:#17191B; color:#686868; border:1px solid #33373A; }}
            QPushButton#tertiaryAction {{ background:#181B1E; color:#AEB3B8; border:1px solid #3A3F44; font-weight:600; }}
            QPushButton#tertiaryAction:hover {{ background:#202428; color:#E6E6E6; border:1px solid #555B61; }}
            QPushButton#modeChoice:checked {{ background:#3A211B; color:#FFFFFF; border:2px solid {ORANGE}; }}
            QCheckBox {{ spacing:7px; }}
            QCheckBox::indicator {{ width:15px; height:15px; }}
            QProgressBar {{ border:1px solid #3A3F44; border-radius:5px; background:#151719; min-height:11px; }}
            QProgressBar::chunk {{ background:{ORANGE}; border-radius:4px; }}
            QHeaderView::section {{ background:#202428; color:#D8D8D8; border:0; border-bottom:1px solid #383D42; padding:6px; }}
            QTableWidget {{ gridline-color:#292D31; }}
            QToolTip {{ background:#202326; color:#F2F2F2; border:1px solid {ORANGE}; padding:6px; }}
        """)

    def _sync_discovery_top_heights(self):
        try:
            panels=[self._search_top_panel, self._selected_top_panel]
            target=max(228, *(p.sizeHint().height() for p in panels))
            for panel in panels:
                panel.setMinimumHeight(target)
        except Exception:
            pass

    def _add_glow(self, button, strength=10):
        try:
            effect = QGraphicsDropShadowEffect(button)
            effect.setBlurRadius(strength)
            effect.setOffset(0, 0)
            from qt.core import QColor
            effect.setColor(QColor(255, 103, 64, 115))
            button.setGraphicsEffect(effect)
        except Exception:
            pass

    def _card(self):
        f = QFrame(); f.setObjectName('card')
        return f

    def _layout_icon(self, landscape=False):
        pm=QPixmap(46,32)
        pm.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pm)
        pen=QPen(QColor(ORANGE)); pen.setWidth(2); painter.setPen(pen)
        if landscape:
            painter.drawRoundedRect(3,5,18,23,2,2)
            painter.drawRoundedRect(25,5,18,23,2,2)
            painter.drawLine(23,6,23,27)
        else:
            painter.drawRoundedRect(13,3,20,27,2,2)
            painter.drawLine(17,8,29,8)
        painter.end()
        return QIcon(pm)

    def build_ui(self):
        self._apply_manganana_theme()
        shell = QVBoxLayout(self)
        shell.setContentsMargins(16, 12, 16, 14)
        shell.setSpacing(10)

        # Brand header. The icon and wordmark are one centered visual group.
        header = QHBoxLayout()
        header.setSpacing(0)
        left_balance = QWidget(); left_balance.setFixedWidth(105)
        header.addWidget(left_balance)
        header.addStretch(1)
        brand_group = QWidget()
        brand_row = QHBoxLayout(brand_group); brand_row.setContentsMargins(0,0,0,0); brand_row.setSpacing(8)
        icon_label = QLabel()
        try: icon_label.setPixmap(self.icon.pixmap(38, 38))
        except Exception: pass
        icon_label.setFixedSize(42, 42); icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand = QLabel(f'<span style="color:#F2F2F2;">Manga</span><span style="color:{ORANGE};">Nana</span>')
        brand.setTextFormat(Qt.TextFormat.RichText)
        brand.setStyleSheet('font-size:26px; font-weight:800; letter-spacing:1px;')
        brand_row.addWidget(icon_label); brand_row.addWidget(brand)
        header.addWidget(brand_group)
        header.addStretch(1)
        ver = QLabel(SHORT_VERSION_LABEL)
        ver.adjustSize(); ver.setMinimumWidth(ver.sizeHint().width() + 8)
        ver.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ver.setStyleSheet('color:#777; font-size:10px; font-weight:700;')
        header.addWidget(ver)
        shell.addLayout(header)

        body = QHBoxLayout(); body.setSpacing(10)
        shell.addLayout(body, 1)

        # LEFT: discovery, selected manga, and volume browser
        left = self._card(); left.setMinimumWidth(520)
        lv = QVBoxLayout(left); lv.setContentsMargins(14,14,14,14); lv.setSpacing(9)
        lv.addWidget(self.heading('Choose Manga'))
        discovery = QHBoxLayout(); discovery.setSpacing(12)

        search_col = QVBoxLayout(); search_col.setSpacing(7)
        search_top = QWidget(); search_top.setMinimumHeight(248)
        search_top_l = QVBoxLayout(search_top); search_top_l.setContentsMargins(0,0,0,0); search_top_l.setSpacing(7)
        mode_label=QLabel('Search for:'); mode_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;')
        mode_row=QHBoxLayout(); mode_row.addWidget(mode_label)
        self.volume_mode_btn=QPushButton('Volumes'); self.chapter_mode_btn=QPushButton('Chapters')
        for button in (self.volume_mode_btn, self.chapter_mode_btn):
            button.setCheckable(True); button.setObjectName('modeChoice')
            # Enter in the search field must not activate the dialog's first
            # push button (Volumes) as an implicit default action.
            button.setAutoDefault(False); button.setDefault(False)
        self.volume_mode_btn.clicked.connect(lambda: self._set_workflow_mode('volume'))
        self.chapter_mode_btn.clicked.connect(lambda: self._set_workflow_mode('chapter'))
        mode_row.addWidget(self.volume_mode_btn); mode_row.addWidget(self.chapter_mode_btn); mode_row.addStretch(1); search_top_l.addLayout(mode_row)
        search_label=QLabel('Search manga sources'); search_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;'); search_top_l.addWidget(search_label)
        search_row = QHBoxLayout()
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText('Search manga sources...')
        self.search_box.setToolTip('Search every enabled manga source by title.')
        self.search_btn = QPushButton('Search'); self.search_btn.setObjectName('secondaryAction'); self.search_btn.clicked.connect(lambda: self.search_mangadex(True))
        self.search_box.returnPressed.connect(lambda: self.search_mangadex(True))
        search_row.addWidget(self.search_box,1); search_row.addWidget(self.search_btn); search_top_l.addLayout(search_row)
        self.mode_helper=QLabel('Choose Volumes or Chapters to begin.')
        self.mode_helper.setStyleSheet('color:#8F9499; font-size:11px;')
        search_top_l.addWidget(self.mode_helper)

        or_row=QHBoxLayout(); or_left=QFrame(); or_left.setFrameShape(QFrame.Shape.HLine); or_left.setStyleSheet('color:#34383C;')
        or_text=QLabel('or'); or_text.setStyleSheet('color:#777; font-size:10px; font-weight:700;')
        or_right=QFrame(); or_right.setFrameShape(QFrame.Shape.HLine); or_right.setStyleSheet('color:#34383C;')
        or_row.addWidget(or_left,1); or_row.addWidget(or_text); or_row.addWidget(or_right,1); search_top_l.addLayout(or_row)

        direct_label=QLabel('Already have a manga link?'); direct_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;'); search_top_l.addWidget(direct_label)
        direct_note=QLabel('Paste a supported manga link.')
        direct_note.setWordWrap(True); direct_note.setStyleSheet('color:#92979C; font-size:11px;'); search_top_l.addWidget(direct_note)
        urlrow=QHBoxLayout(); self.url = QLineEdit(); self.url.setPlaceholderText('Paste a supported manga link...')
        self.url.setToolTip('Paste a supported manga link.')
        self.load_btn = QPushButton('Load Manga'); self.load_btn.setObjectName('secondaryAction'); self.load_btn.clicked.connect(self.load_metadata); self.url.returnPressed.connect(self.load_metadata)
        urlrow.addWidget(self.url,1); urlrow.addWidget(self.load_btn); search_top_l.addLayout(urlrow)
        search_top_l.addStretch(1)
        self._search_top_panel = search_top
        search_col.addWidget(search_top)

        search_results_header=QWidget(); search_results_header.setFixedHeight(36)
        search_results_head=QHBoxLayout(search_results_header); search_results_head.setContentsMargins(0,0,0,0); search_results_head.setSpacing(6)
        self.search_results_label=QLabel('Search Results'); self.search_results_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;')
        search_results_head.addWidget(self.search_results_label); search_results_head.addStretch(1); search_col.addWidget(search_results_header)
        self.search_results = QListWidget(); self.search_results.setMinimumHeight(185)
        self.search_results.setIconSize(QSize(78,108)); self.search_results.setSpacing(5); self.search_results.setWordWrap(True)
        self.search_results.setUniformItemSizes(True)
        self.search_results.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.search_results.verticalScrollBar().setSingleStep(14)
        self.search_results.itemClicked.connect(self.use_search_result)
        self.search_results.verticalScrollBar().valueChanged.connect(lambda _v: self._load_visible_search_thumbs())
        search_col.addWidget(self.search_results,1)
        self.search_results.setMaximumHeight(300)
        # Keep the paging action in normal layout flow below the scrolling list.
        # A dedicated spacer prevents the final result row from visually touching
        # or appearing underneath the button when the window is vertically tight.
        search_footer=QWidget(); search_footer.setFixedHeight(54)
        search_footer_l=QVBoxLayout(search_footer); search_footer_l.setContentsMargins(0,7,0,7); search_footer_l.setSpacing(0)
        self.show_more_btn=QPushButton('Show More Results'); self.show_more_btn.setObjectName('tertiaryAction'); self.show_more_btn.setFixedHeight(32); self.show_more_btn.setVisible(False); self.show_more_btn.clicked.connect(self._show_more_search_results)
        search_footer_l.addWidget(self.show_more_btn)
        search_col.addWidget(search_footer)
        discovery.addLayout(search_col, 45)

        selected_col=QVBoxLayout(); selected_col.setSpacing(7)
        selected_top = QWidget(); selected_top.setObjectName('selectedMangaCard'); selected_top.setStyleSheet('QWidget#selectedMangaCard { background:#171A1D; border:1px solid #2C3136; border-radius:7px; }')
        selected_top_l = QVBoxLayout(selected_top); selected_top_l.setContentsMargins(8,7,8,8); selected_top_l.setSpacing(7)
        # Let Qt derive the card's minimum height from its cover, metadata and
        # Alternate Title control. The inventory header is a sibling below it,
        # never an overlay that may consume this button's hit area.
        selected_top_l.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.title=QLineEdit(); self.author=QLineEdit(); self.series=QLineEdit(); self.title.hide(); self.author.hide(); self.series.hide()
        self.alt_titles_btn=QPushButton('Alternate Title...'); self.alt_titles_btn.setObjectName('tertiaryAction'); self.alt_titles_btn.setFixedHeight(32); self.alt_titles_btn.setEnabled(False); self.alt_titles_btn.setVisible(False); self.alt_titles_btn.clicked.connect(self.choose_alternate_title)
        self.selected_cover=CoverLoadingLabel(); self.selected_cover.setFixedSize(130,180); self.selected_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selected_cover.setStyleSheet('background:#121416; color:#FF6740; border:1px solid #34393e; border-radius:6px; font-size:11px; font-weight:800;'); self.selected_cover.setVisible(False)
        self.selected_title=QLabel('No manga selected'); self.selected_title.setWordWrap(True); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignCenter); self.selected_title.setStyleSheet('font-size:12px; font-weight:600; color:#777;')
        self.selected_author=QLabel(''); self.selected_author.setStyleSheet('color:#aaa;')
        self.edition_badge=QLabel(''); self.edition_badge.setAlignment(Qt.AlignmentFlag.AlignCenter); self.edition_badge.setVisible(False)
        self.edition_badge.setStyleSheet(f'color:{ORANGE}; border:1px solid {ORANGE}; border-radius:7px; background:#151719; padding:2px 7px; font-weight:700; font-size:11px;')
        self.availability_badge=QLabel('Unavailable'); self.availability_badge.setAlignment(Qt.AlignmentFlag.AlignCenter); self.availability_badge.setVisible(False)
        self.availability_badge.setStyleSheet('color:#B7BBC0; border:1px solid #555B61; border-radius:7px; background:#151719; padding:2px 7px; font-weight:700; font-size:11px;')
        selected=QHBoxLayout(); selected.setContentsMargins(0,0,0,0); selected.addWidget(self.selected_cover)
        seltext=QVBoxLayout(); seltext.setContentsMargins(0,0,0,0); seltext.addWidget(self.selected_title); seltext.addWidget(self.selected_author)
        badge_row=QHBoxLayout(); badge_row.setContentsMargins(0,0,0,0); badge_row.addWidget(self.edition_badge); badge_row.addWidget(self.availability_badge); badge_row.addStretch(1); seltext.addLayout(badge_row)
        seltext.addStretch(1); seltext.addWidget(self.alt_titles_btn)
        selected.addLayout(seltext,1); selected_top_l.addLayout(selected,1)
        self._selected_top_panel = selected_top
        selected_col.addWidget(selected_top)

        vols_header=QWidget(); vols_header.setFixedHeight(36)
        vols_head=QHBoxLayout(vols_header); vols_head.setContentsMargins(0,0,0,0); vols_head.setSpacing(6); self.inventory_heading=self.heading('Volumes'); vols_head.addWidget(self.inventory_heading); vols_head.addStretch(1)
        self.volume_count_label=QLabel(''); self.volume_count_label.setStyleSheet('color:#999; font-size:11px;'); vols_head.addWidget(self.volume_count_label); selected_col.addWidget(vols_header)
        self.volume_list=QListWidget(); self.volume_list.setMinimumHeight(185); self.volume_list.setMaximumHeight(300); self.volume_list.setEnabled(False)
        self.volume_list.setSpacing(3); self.volume_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel); self.volume_list.verticalScrollBar().setSingleStep(18)
        self.volume_list.verticalScrollBar().valueChanged.connect(lambda _v: self._load_visible_volume_thumbs()); selected_col.addWidget(self.volume_list,1)
        # Keep the selection action below the list instead of inside an overlay-like
        # footer. This guarantees the last volume row can scroll fully above it.
        volume_footer=QWidget(); volume_footer.setFixedHeight(54)
        volume_footer_l=QVBoxLayout(volume_footer); volume_footer_l.setContentsMargins(0,7,0,7); volume_footer_l.setSpacing(0)
        self.clear_volume_btn=QPushButton('Use Entire Series'); self.clear_volume_btn.setObjectName('secondaryAction'); self.clear_volume_btn.setFixedHeight(34)
        self.clear_volume_btn.setEnabled(False); self.clear_volume_btn.clicked.connect(self._use_entire_series); volume_footer_l.addWidget(self.clear_volume_btn)
        selected_col.addWidget(volume_footer)
        self.meta_summary=QLabel(''); self.meta_summary.setVisible(False)
        discovery.addLayout(selected_col, 55)
        lv.addLayout(discovery,1)
        body.addWidget(left, 44)

        # CENTER: job settings
        center=self._card(); center.setMinimumWidth(320)
        cv=QVBoxLayout(center); cv.setContentsMargins(14,14,14,14); cv.setSpacing(8)
        cv.addWidget(self.heading('Download Settings'))
        cv.addWidget(QLabel('Output Layout'))
        choices=QHBoxLayout(); choices.setSpacing(7)
        self.portrait_btn=QPushButton('PORTRAIT\nIndividual Pages'); self.portrait_btn.setObjectName('layoutChoice'); self.portrait_btn.setCheckable(True)
        self.landscape_btn=QPushButton('LANDSCAPE\nPaired Pages'); self.landscape_btn.setObjectName('layoutChoice'); self.landscape_btn.setCheckable(True)
        self.portrait_btn.setIcon(self._layout_icon(False)); self.landscape_btn.setIcon(self._layout_icon(True)); self.portrait_btn.setIconSize(QSize(38,28)); self.landscape_btn.setIconSize(QSize(38,28))
        self.portrait_btn.setToolTip('Keeps source pages individually. Best for normal portrait reading.')
        self.landscape_btn.setToolTip('Paired-page landscape layout. Occasional mismatches may occur, especially near the beginning of a volume.')
        choices.addWidget(self.portrait_btn,1); choices.addWidget(self.landscape_btn,1); cv.addLayout(choices)
        self.page_layout=QComboBox(); self.page_layout.addItem('Portrait (Individual Pages)','original_pages'); self.page_layout.addItem('Landscape (Paired Pages)','paired_landscape')
        pli=self.page_layout.findData(prefs['page_layout']); self.page_layout.setCurrentIndex(max(0,pli)); self.page_layout.hide()
        self.portrait_btn.clicked.connect(lambda: self._choose_layout('original_pages'))
        self.landscape_btn.clicked.connect(lambda: self._choose_layout('paired_landscape'))

        grid=QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(7)
        self.download_language_label=QLabel('Download Language')
        self.reading_direction_label=QLabel('Reading Direction')
        grid.addWidget(self.download_language_label,0,0); grid.addWidget(self.reading_direction_label,0,1)
        self.language=CappedComboBox(max_popup_rows=12); populate_download_languages(self.language, available=None, preferred=prefs['language'])
        self.language.setToolTip('Chapter language used for downloads. Only languages reported for the loaded manga are shown.')
        self.reading_direction=QComboBox(); self.reading_direction.addItem('Right to Left (Manga)','rtl'); self.reading_direction.addItem('Left to Right','ltr')
        self.reading_direction.setToolTip('Reading direction applies only to Landscape (Paired Pages).')
        rdi=self.reading_direction.findData(prefs['reading_direction']); self.reading_direction.setCurrentIndex(max(0,rdi))
        grid.addWidget(self.language,1,0); grid.addWidget(self.reading_direction,1,1)
        self.range_label=QLabel('Select a Volume Range (Optional)'); grid.addWidget(self.range_label,2,0,1,2)
        self.start=QLineEdit(); self.start.setPlaceholderText('From'); self.end=QLineEdit(); self.end.setPlaceholderText('To')
        grid.addWidget(self.start,3,0); grid.addWidget(self.end,3,1)
        cv.addLayout(grid)
        self.range_help=QLabel('Shortcut: select a continuous range instead of choosing volumes individually.')
        self.range_help.setWordWrap(True); self.range_help.setStyleSheet('color:#8F9499; font-size:11px;')
        cv.addWidget(self.range_help)
        self.range_hint=QLabel('Select at least one volume to continue.')
        self.range_hint.setWordWrap(True); self.range_hint.setMinimumHeight(18); self.range_hint.setStyleSheet('color:#8F9499; font-size:11px;')
        cv.addWidget(self.range_hint)
        self.covers=QCheckBox('Use source volume cover in Calibre metadata'); self.covers.setChecked(prefs['include_volume_covers'])
        self.pad=QCheckBox('Zero-pad volume numbers (Recommended)'); self.pad.setChecked(prefs['zero_pad'])
        cv.addWidget(self.covers); cv.addWidget(self.pad)
        dest=QLabel(f'Calibre library\n{getattr(self.gui.current_db,"library_path","Current calibre library")}')
        dest.setWordWrap(True); dest.setStyleSheet('color:#A8A8A8; padding-top:4px;')
        cv.addWidget(dest); cv.addStretch(1)
        body.addWidget(center, 25)

        # RIGHT: preview and planned volumes
        right=self._card(); right.setMinimumWidth(360)
        rv=QVBoxLayout(right); rv.setContentsMargins(14,14,14,14); rv.setSpacing(8)
        preview_header_box=QWidget(); preview_header_box.setFixedHeight(38)
        preview_head=QHBoxLayout(preview_header_box); preview_head.setContentsMargins(0,0,0,0); preview_head.setAlignment(Qt.AlignmentFlag.AlignTop)
        preview_title=self.heading('Review')
        preview_head.addWidget(preview_title,0,Qt.AlignmentFlag.AlignTop); preview_head.addStretch(1)
        self.pairing_preview_btn=QPushButton('Pairing Preview'); self.pairing_preview_btn.setEnabled(False); self.pairing_preview_btn.clicked.connect(self.open_pairing_preview)
        preview_head.addWidget(self.pairing_preview_btn,0,Qt.AlignmentFlag.AlignTop); rv.addWidget(preview_header_box)
        self.preview_summary=QLabel('Load a manga, choose your settings, then build a download preview.')
        self.preview_summary.setWordWrap(True); self.preview_summary.setMinimumHeight(66); self.preview_summary.setMaximumHeight(86); self.preview_summary.setAlignment(Qt.AlignmentFlag.AlignTop); self.preview_summary.setStyleSheet('color:#B8B8B8;')
        rv.addWidget(self.preview_summary)
        self.preview_table=QTableWidget(0,6); self.preview_table.setHorizontalHeaderLabels(['Use','Type','Title','Source','Pages','Status'])
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel); self.preview_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.preview_table.setAlternatingRowColors(True); self.preview_table.verticalHeader().setVisible(False)
        ph=self.preview_table.horizontalHeader(); ph.setStretchLastSection(False); ph.setMinimumSectionSize(36); ph.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setFixedHeight(36)
        ph.setStyleSheet('QHeaderView::section { background:#202428; color:#D8D8D8; border:0; border-right:1px solid #383D42; border-bottom:1px solid #383D42; padding:8px 6px; }')
        # Keep the Use column wide enough for the 22px round selector plus breathing room.
        ph.setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed)
        self.preview_table.setColumnWidth(0,60)
        ph.setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(3,QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(4,QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(5,QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.setVisible(True)
        rv.addWidget(self.preview_table,1)
        body.addWidget(right, 31)

        # Provider-search progress owns only provider search tasks. Review,
        # pairing, and download work use a separate strip in the same card.
        progress_card=self._card(); pv=QVBoxLayout(progress_card); pv.setContentsMargins(12,7,12,8); pv.setSpacing(5)
        search_statrow=QHBoxLayout(); self.search_progress_text=QLabel('Search ready'); self.search_progress_text.setStyleSheet('color:#D8D8D8; font-size:11px;')
        search_statrow.addWidget(self.search_progress_text); search_statrow.addStretch(1); pv.addLayout(search_statrow)
        self.search_progress=MangaNanaProgressBar(); self.search_progress.setRange(0,1); self.search_progress.setValue(0); self.search_progress.setTextVisible(False); pv.addWidget(self.search_progress)
        self.work_progress_widget=QWidget(); work_layout=QVBoxLayout(self.work_progress_widget); work_layout.setContentsMargins(0,3,0,0); work_layout.setSpacing(5)
        statrow=QHBoxLayout(); self.progress_text=QLabel('Ready'); self.progress_text.setStyleSheet('color:#D8D8D8; font-size:11px;')
        statrow.addWidget(self.progress_text); statrow.addStretch(1); work_layout.addLayout(statrow)
        self.progress=MangaNanaProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.setTextVisible(False); work_layout.addWidget(self.progress)
        self.work_progress_widget.setVisible(False); pv.addWidget(self.work_progress_widget)
        shell.addWidget(progress_card)

        activity=self._card(); av=QVBoxLayout(activity); av.setContentsMargins(12,8,12,9); av.setSpacing(5)
        loghead=QHBoxLayout()
        self.log_toggle_btn=QPushButton('Activity Log  ▸'); self.log_toggle_btn.setObjectName('tertiaryAction'); self.log_toggle_btn.setFlat(True); self.log_toggle_btn.setStyleSheet('QPushButton { text-align:left; padding:4px 6px; border:0; color:#DADADA; font-size:11px; font-weight:700; background:transparent; } QPushButton:hover { color:#FFFFFF; }')
        self.log_toggle_btn.clicked.connect(lambda _checked=False: self._toggle_activity_log())
        loghead.addWidget(self.log_toggle_btn); loghead.addStretch(1)
        self.copy_log_btn=QPushButton('Copy Log'); self.copy_log_btn.setObjectName('tertiaryAction'); self.copy_log_btn.clicked.connect(self.copy_log)
        self.save_log_btn=QPushButton('Save Log'); self.save_log_btn.setObjectName('tertiaryAction'); self.save_log_btn.clicked.connect(self.save_log)
        loghead.addWidget(self.copy_log_btn); loghead.addWidget(self.save_log_btn); av.addLayout(loghead)
        self.log=QListWidget(); self.log.setMaximumHeight(105); self.log.setVisible(False); av.addWidget(self.log); self._activity_log_expanded=False
        shell.addWidget(activity)

        self.workflow_hint=QLabel('Choose Volumes or Chapters before searching.')
        self.workflow_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.workflow_hint.setStyleSheet('color:#9EA3A8; font-size:11px; padding:0 4px 2px 4px;')
        shell.addWidget(self.workflow_hint)

        actions=QHBoxLayout()
        self.preview_btn=QPushButton('Review'); self.preview_btn.setObjectName('secondaryAction'); self.preview_btn.clicked.connect(self.continue_preview); self.preview_btn.setEnabled(False)
        self.download_btn=QPushButton('Download and Add to Calibre'); self.download_btn.setObjectName('primaryAction'); self.download_btn.clicked.connect(self.start_download); self.download_btn.setEnabled(False)
        self.cancel_btn=QPushButton('Cancel'); self.cancel_btn.setObjectName('tertiaryAction'); self.cancel_btn.setEnabled(False); self.cancel_btn.clicked.connect(self.cancel_download)
        self.preferences_btn=QPushButton('Preferences...'); self.preferences_btn.setObjectName('tertiaryAction'); self.preferences_btn.clicked.connect(self.open_preferences)
        self.sources_btn=QPushButton('Manga Sources'); self.sources_btn.setObjectName('tertiaryAction'); self.sources_btn.clicked.connect(self.open_manga_sources)
        self.about_btn=QPushButton('About'); self.about_btn.setObjectName('tertiaryAction'); self.about_btn.clicked.connect(self.show_about)
        actions.addWidget(self.preferences_btn); actions.addWidget(self.sources_btn); actions.addWidget(self.about_btn); actions.addStretch(1); actions.addWidget(self.cancel_btn); actions.addWidget(self.preview_btn); actions.addWidget(self.download_btn)
        shell.addLayout(actions)

        # Match the discovery cards after Qt has calculated the active font/DPI size.
        QTimer.singleShot(0, self._sync_discovery_top_heights)

        # Compatibility placeholder: old code may call preview_panel.show()/hide().
        self.preview_panel = right
        self.preview_close = QPushButton(); self.preview_close.hide()

        watched=[self.title,self.author,self.series]
        for widget in watched: widget.textChanged.connect(self.invalidate_preview)
        self.start.textChanged.connect(self._range_inputs_changed); self.end.textChanged.connect(self._range_inputs_changed)
        self.start.editingFinished.connect(self._log_invalid_manual_range); self.end.editingFinished.connect(self._log_invalid_manual_range)
        self.language.currentIndexChanged.connect(self._download_language_changed); self.covers.toggled.connect(self.invalidate_preview); self.pad.toggled.connect(self.invalidate_preview)
        self.page_layout.currentIndexChanged.connect(self._layout_mode_changed); self.reading_direction.currentIndexChanged.connect(self.invalidate_preview)
        self._preview_refresh_timer=QTimer(self); self._preview_refresh_timer.setSingleShot(True); self._preview_refresh_timer.timeout.connect(self._run_silent_preview_refresh)
        self._layout_mode_changed(); self._range_inputs_changed()
        self.search_box.setEnabled(False); self.search_btn.setEnabled(False)
        self.url.setEnabled(False); self.load_btn.setEnabled(False)

    def _set_workflow_mode(self, mode):
        """Choose an explicit workflow and discard mode-specific stale state."""
        if mode not in ('volume', 'chapter'):
            return
        if self.workflow_mode == mode:
            self.volume_mode_btn.setChecked(mode == 'volume'); self.chapter_mode_btn.setChecked(mode == 'chapter')
            return
        previous_mode=self.workflow_mode
        replay_kind=self._last_discovery_kind
        replay_value=self._last_discovery_value
        should_research=bool(previous_mode and replay_kind == 'search' and replay_value and replay_value == self.search_box.text().strip())
        should_reload_direct=bool(previous_mode and replay_kind == 'direct' and replay_value)
        self.workflow_mode=mode
        self._invalidate_cover_requests()
        self._mode_generation += 1
        self._search_request_id += 1; self._inventory_comparison_request_id += 1
        self._search_resolution_request_id += 1
        self._manga_request_id += 1; self._volume_plan_request_id += 1
        # Old network requests may finish later, but their mode/generation is
        # rejected. Clearing this registry lets the new explicit mode search
        # begin immediately instead of waiting behind obsolete requests.
        for worker in self.search_workers.values():
            if worker.isRunning(): worker.requestInterruption()
        self.search_workers={}
        self._search_status_timer.stop(); self._search_cancel_requested=False
        if self._search_resolution_worker and self._search_resolution_worker.isRunning():
            self._search_resolution_worker.requestInterruption()
        self._search_resolution_worker=None; self._search_resolutions={}; self._search_ranked_groups=()
        if self.inventory_comparison_worker and self.inventory_comparison_worker.isRunning():
            self.inventory_comparison_worker.requestInterruption()
        self.inventory_comparison_worker=None
        self.volume_mode_btn.setChecked(mode == 'volume'); self.chapter_mode_btn.setChecked(mode == 'chapter')
        self.search_box.setEnabled(True); self.search_btn.setEnabled(True); self.url.setEnabled(True); self.load_btn.setEnabled(True)
        self._chapter_plan_items=(); self._selected_chapter_ids.clear(); self._pending_cross_source_plan=None
        self._invalidate_inflight_preview()
        if self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_worker.cancel()
        self._selected_volumes.clear(); self._standalone_selected=False; self._using_entire_series=False
        self._current_plan=None; self._download_language_valid=False; self._last_inventory_decision=None
        self.loaded_metadata=None; self.current_manga_url=''; self._loaded_covers={}; self._main_cover_url=''
        self._pending_search_language=''
        self.search_results.clear(); self._search_raw_results=[]; self.show_more_btn.setVisible(False)
        self.title.clear(); self.author.clear(); self.series.clear(); self.selected_cover.clear(); self.selected_cover.setVisible(False)
        self.selected_title.setText('No manga selected'); self.selected_author.clear(); self._set_edition_badge(''); self.availability_badge.setVisible(False)
        self.volume_list.clear(); self.volume_list.setEnabled(False); self.clear_volume_btn.setEnabled(False)
        self.start.setVisible(mode == 'volume'); self.end.setVisible(mode == 'volume')
        self.range_label.setVisible(mode == 'volume'); self.range_help.setVisible(mode == 'volume')
        self.inventory_heading.setText('Volumes' if mode == 'volume' else 'Chapters')
        self.covers.setText('Use series cover in Calibre metadata' if mode == 'chapter' else 'Use source volume cover in Calibre metadata')
        self.pad.setText('Zero-pad chapter numbers (Recommended)' if mode == 'chapter' else 'Zero-pad volume numbers (Recommended)')
        self.clear_volume_btn.setText('Select All Chapters' if mode == 'chapter' else 'Use Entire Series')
        self._clear_preview_state('Load a manga, choose your settings, then build a download preview.')
        self.cancel_btn.setEnabled(False)
        self.meta_summary.clear(); self.search_progress.setRange(0,1); self.search_progress.setValue(0); self.search_progress_text.setText(f'{mode.title()} mode selected. Search again to load availability.')
        self.work_progress_widget.setVisible(False)
        self.workflow_hint.setText(f'{mode.title()} mode selected. Search or load a title.')
        self.mode_helper.setText(f'{mode.title()} mode selected.')
        self.add_log(f'{mode.title()} mode selected.')
        if should_research:
            QTimer.singleShot(0, lambda generation=self._mode_generation: self.search_mangadex(True, generation))
        elif should_reload_direct:
            QTimer.singleShot(0, lambda value=replay_value: self.load_metadata(
                value, discovery_kind='direct', prompt_disabled=False,
            ))

    def _choose_layout(self, mode):
        idx=self.page_layout.findData(mode)
        if idx >= 0 and self.page_layout.currentIndex() != idx:
            self.page_layout.setCurrentIndex(idx)
        else:
            self._layout_mode_changed()

    def _search_score(self, query, title, author=''):
        return MangaDexSearchWorker.score(query, title)

    def _cleanup_worker(self, worker, collection):
        try:
            if worker in collection:
                collection.remove(worker)
        except Exception:
            pass

    def search_mangadex(self, reset=True, expected_generation=None):
        """Compatibility name for the provider-neutral coordinated search."""
        if self.workflow_mode not in ('volume', 'chapter'):
            info_dialog(self, 'Choose workflow', 'Choose Volumes or Chapters before searching.', show=True)
            return
        if expected_generation is not None and expected_generation != self._mode_generation:
            return
        mode=self.workflow_mode; generation=self._mode_generation
        self._diagnostic_operation='provider search'
        query=self.search_box.text().strip()
        if not query:
            return
        if not reset and query != self._search_query:
            reset=True
        if any(worker.isRunning() for worker in self.search_workers.values()):
            return
        if reset:
            participating = enabled_sources(SOURCE_REGISTRY, prefs)
            if not participating:
                self.search_btn.setEnabled(True); self.search_btn.setText('Search')
                self.cancel_btn.setEnabled(False); self.show_more_btn.setVisible(False)
                self.search_progress.setRange(0,1); self.search_progress.setValue(0)
                self.search_progress_text.setText('No manga sources are enabled.')
                info_dialog(
                    self, 'No manga sources enabled',
                    'No manga sources are enabled.\nOpen Manga Sources to enable at least one source.',
                    show=True,
                )
                return
            self.search_coordinator = SourceCoordinator(SOURCE_REGISTRY, participating)
        self._search_request_id += 1; search_request_id=self._search_request_id
        self._search_resolution_request_id += 1
        if self._search_resolution_worker and self._search_resolution_worker.isRunning():
            self._search_resolution_worker.requestInterruption()
        self._search_resolution_worker=None; self._search_resolutions={}; self._search_ranked_groups=()
        self._search_cancel_requested=False; self._search_started_at=time.monotonic()
        if reset:
            self._last_discovery_kind='search'; self._last_discovery_value=query
            self._pending_search_language=''
            self._search_query=query
            self._search_offsets={source.source_id:0 for source in self.search_coordinator.sources}
            self._search_has_more={source.source_id:False for source in self.search_coordinator.sources}
            self.search_coordinator.reset()
            self._search_raw_results=[]
            self.search_results.clear()
            self.show_more_btn.setVisible(False)
        self.search_btn.setEnabled(False); self.search_btn.setText('Searching...'); self.cancel_btn.setEnabled(True)
        self.show_more_btn.setEnabled(False)
        participating_sources=tuple(
            source for source in self.search_coordinator.sources
            if reset or self._search_has_more.get(source.source_id)
        )
        self._search_provider_ids=tuple(source.source_id for source in participating_sources)
        self.search_progress.setRange(0,max(1,len(participating_sources)))
        self.search_progress.setValue(0)
        self.search_progress_text.setText(provider_search_progress_text(self.search_coordinator.snapshot(),0))
        self._search_status_timer.start()
        include_adult=bool(prefs['show_adult_search_results'])
        started=0
        for source in participating_sources:
            offset=self._search_offsets.get(source.source_id,0)
            key=(source.source_id,query.casefold(),offset,self._search_page_size,include_adult,prefs['language'])
            self.search_coordinator.mark_running(source.source_id)
            worker=SourceSearchWorker(source,query,offset,self._search_page_size,include_adult,prefs['language'],self._download_availability_cache,self)
            self.search_workers[source.source_id]=worker
            worker.ready.connect(lambda payload,k=key,m=mode,g=generation,r=search_request_id:self._on_search_ready(k,payload,m,g,r))
            worker.failed.connect(lambda payload,m=mode,g=generation,r=search_request_id:self._on_search_failed(payload,m,g,r))
            worker.finished.connect(lambda sid=source.source_id,w=worker,m=mode,g=generation,r=search_request_id:self._search_worker_finished(sid,w,m,g,r))
            worker.start(); started += 1
        if not started:
            self._finish_coordinated_search()

    def _on_search_ready(self, key, payload, mode=None, generation=None, request_id=None):
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        source_id=payload.get('source_id')
        data=self.search_coordinator.complete(source_id,payload.get('data') or {})
        self._sync_provider_search_progress()
        self._search_cache[key]=data
        self._apply_search_page(data)

    def _apply_search_page(self, data):
        if data.get('query') != self._search_query:
            return
        existing={(row.get('source_id'),row.get('id')) for row in self._search_raw_results}
        for row in data.get('rows') or []:
            mid=row.get('id')
            source_id=row.get('source_id') or data.get('source_id')
            identity=(source_id,mid)
            if not mid or identity in existing:
                continue
            source=SOURCE_REGISTRY.get(source_id)
            url=row.get('url') or (f'https://mangadex.org/title/{mid}' if source_id=='mangadex' else '')
            normalized=dict(row)
            normalized.update({'id':mid,'url':url,'cover_url':row.get('cover_url') or '',
                               'source_id':source_id,'source_name':row.get('source_name') or data.get('source_name')})
            self._search_raw_results.append(normalized)
            existing.add(identity)
        self._render_canonical_search_results()
        fetched=int(data.get('fetched_count') if data.get('fetched_count') is not None else len(data.get('rows') or []))
        next_offset=data.get('next_offset')
        source_id=data.get('source_id')
        self._search_offsets[source_id]=int(next_offset if next_offset is not None else int(data.get('offset') or 0)+fetched)
        more=bool(data.get('has_more'))
        self._search_has_more[source_id]=more
        self.show_more_btn.setText('Show More Results')
        parts=[f'[{data.get("source_name")}] Search returned {len(data.get("rows") or [])} result(s) for “{self._search_query}”.']
        if more: parts.append('More results are available from this provider.')
        if not prefs['show_adult_search_results']: parts.append('Adult content excluded.')
        filtered=int(data.get('filtered_doujinshi') or 0)
        empty_filtered=int(data.get('filtered_empty') or 0)
        if empty_filtered: parts.append(f'{empty_filtered} title(s) with no downloadable chapters filtered.')
        if filtered: parts.append(f'{filtered} doujinshi result(s) filtered while filling this page.')
        self.add_log(' '.join(parts))
        QTimer.singleShot(0, self._load_visible_search_thumbs)

    def _canonical_search_key(self, group):
        identities=tuple(sorted(
            (str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or ''))
            for row in group.results
        ))
        return (edition_identity(group.results[0]) if group.results else 'original',identities)

    def _ranked_search_groups(self, final=False):
        rows=list(rank_canonical_results(self._search_query,self._search_raw_results))[:SEARCH_RESOLUTION_LIMIT]
        if not final:
            return tuple(rows)
        eligible=[]
        for ranked in rows:
            resolution=self._search_resolutions.get(self._canonical_search_key(ranked.group))
            if resolution and resolution.usable:
                match=ranked.match; popularity=ranked.popularity
                eligible.append(((
                    -int(match.tier),-match.edition_preference,
                    1 if resolution.language_fallback else 0,
                    match.extra_words,-match.precision,
                    0 if match.title_kind == 'primary' else 1,
                    -int(popularity.known),-(popularity.bounded_score or 0.0),
                    normalize_identity_text(ranked.group.display_title),
                ),ranked))
        return tuple(ranked for _key,ranked in sorted(eligible,key=lambda row:row[0]))

    def _render_canonical_search_results(self, final=False):
        selected_info=self.search_results.currentItem().data(Qt.ItemDataRole.UserRole) if self.search_results.currentItem() else {}
        selected_key=selected_info.get('group_key') if isinstance(selected_info,dict) else None
        scroll_value=self.search_results.verticalScrollBar().value()
        ranked_groups=self._ranked_search_groups(final)
        self._search_ranked_groups=ranked_groups
        self.search_results.clear()
        for ranked in ranked_groups:
            group=ranked.group
            group_key=self._canonical_search_key(group)
            resolution=self._search_resolutions.get(group_key)
            candidates=[dict(row) for row in group.results]
            primary=dict(resolution.primary.result) if resolution and resolution.usable else candidates[0]
            item=QListWidgetItem()
            info=dict(primary)
            info['candidates']=list(resolution.candidates) if resolution and resolution.usable else candidates
            info['aliases']=list(group.aliases)
            info['canonical_reason']=group.reason
            info['source_names']=list(group.source_names)
            info['group_key']=group_key
            info['match_tier']=int(ranked.match.tier)
            info['rank_sort_key']=ranked.sort_key
            info['resolution_state']='resolved' if resolution and resolution.usable else 'unresolved'
            info['resolution']=resolution
            item.setData(Qt.ItemDataRole.UserRole, info)
            title=group.display_title or 'Untitled'; author=primary.get('author') or ''; badge=primary.get('badge') or ''
            item.setSizeHint(QSize(0,122))
            self.search_results.addItem(item)
            confirmed=()
            language_note=''
            if resolution and resolution.usable:
                names={row.source_id:row.source_name for row in resolution.inventories}
                confirmed=tuple((source_id,names.get(source_id) or source_id) for source_id in resolution.expected_source_ids)
                if resolution.language_fallback:
                    language_note=f'{language_label(resolution.preferred_language)} unavailable · {language_label(resolution.language)} available'
            row=SearchResultRowWidget(
                title, author, badge=badge, parent=self.search_results,
                cover_loading=bool(primary.get('cover_url')),
            )
            if confirmed:
                row.set_source_state(confirmed,language_note)
            self.search_results.setItemWidget(item,row)
            if group_key == selected_key:
                self.search_results.setCurrentItem(item)
        self.search_results.verticalScrollBar().setValue(scroll_value)

    def _on_search_failed(self, data, mode=None, generation=None, request_id=None):
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        source_id=data.get('source_id'); source=SOURCE_REGISTRY.get(source_id)
        self.search_coordinator.fail(source_id,data.get('error'))
        self._sync_provider_search_progress()
        self.add_log(f'[{source.display_name if source else source_id}] Search failed: {data.get("error")}')

    def _search_worker_finished(self, source_id, completed_worker=None, mode=None, generation=None, request_id=None):
        worker=self.search_workers.get(source_id)
        if worker is completed_worker:
            self.search_workers.pop(source_id,None)
            worker.deleteLater()
        elif completed_worker is not None:
            completed_worker.deleteLater()
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        self._finish_coordinated_search()

    def _sync_provider_search_progress(self):
        settled,total=settled_provider_progress(
            self.search_coordinator.snapshot(), self._search_provider_ids,
        )
        self.search_progress.setRange(0,max(1,total))
        self.search_progress.setValue(settled if total else 0)
        return settled,total

    def _finish_coordinated_search(self):
        if self.search_workers:
            snap=self.search_coordinator.snapshot()
            self._sync_provider_search_progress()
            self.search_progress_text.setText(provider_search_progress_text(snap,time.monotonic()-self._search_started_at))
            return
        snap=self.search_coordinator.snapshot()
        self._search_status_timer.stop()
        self._sync_provider_search_progress()
        self.search_btn.setEnabled(True); self.search_btn.setText('Search'); self.cancel_btn.setEnabled(False)
        more=any(self._search_has_more.values())
        self.show_more_btn.setVisible(more); self.show_more_btn.setEnabled(more)
        if snap['all_failed']:
            self.search_progress_text.setText('Search failed: all providers failed.')
        else:
            failures=sum(provider.get('status') == 'failed' for provider in snap['providers'])
            suffix=f' ({failures} failed)' if failures else ''
            blocked=[p.get('display_name') for p in snap['providers'] if p.get('status')=='failed' and 'access blocked by site protection' in str(p.get('error') or '').casefold()]
            blocked_suffix=(' · '+', '.join(blocked)+' — Access blocked by site protection') if blocked else ''
            self.search_progress_text.setText(f'Search complete: {snap["completed"]}/{snap["total"]} providers{suffix}{blocked_suffix}')
        if snap['all_failed']:
            error_dialog(self,'Search failed',snap['combined_error'],show=True)
        elif self.search_results.count()==0:
            info_dialog(self,'MangaNana search','No matching titles were found.',show=True)
        else:
            self._start_search_resolution()

    def _find_search_item(self, group_key):
        for index in range(self.search_results.count()):
            item=self.search_results.item(index)
            info=item.data(Qt.ItemDataRole.UserRole) or {}
            if isinstance(info,dict) and info.get('group_key') == group_key:
                return item
        return None

    def _start_search_resolution(self):
        entries=tuple(
            (self._canonical_search_key(ranked.group),tuple(dict(row) for row in ranked.group.results))
            for ranked in self._search_ranked_groups
        )
        if not entries:
            return
        self._search_resolution_request_id += 1
        request_id=self._search_resolution_request_id
        mode=self.workflow_mode; generation=self._mode_generation
        worker=SearchResolutionWorker(
            request_id,SOURCE_REGISTRY,entries,prefs['language'],mode,
            self._search_resolution_metadata_cache,self._search_resolution_inventory_cache,
            prefs['show_adult_search_results'],
        )
        self._search_resolution_worker=worker
        worker.resolved.connect(lambda payload,m=mode,g=generation:self._on_search_resolution(payload,m,g))
        worker.finished.connect(lambda w=worker,r=request_id,m=mode,g=generation:self._search_resolution_finished(w,r,m,g))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_search_resolution(self, payload, mode=None, generation=None):
        if (payload.get('request_id') != self._search_resolution_request_id or
                mode != self.workflow_mode or generation != self._mode_generation):
            return
        group_key=payload.get('group_key')
        resolution=payload.get('resolution')
        item=self._find_search_item(group_key)
        if item is None:
            return
        if payload.get('error') or not resolution or not resolution.usable:
            index=self.search_results.row(item)
            self.search_results.takeItem(index)
            self._search_resolutions[group_key]=None
            message=payload.get('error') or getattr(resolution,'error','') or 'no usable source'
            self.add_log(f'Excluded search result after {self.workflow_mode}-mode source resolution: {message}')
            return
        self._search_resolutions[group_key]=resolution
        info=item.data(Qt.ItemDataRole.UserRole) or {}
        primary=dict(resolution.primary.result)
        preserved={key:info.get(key) for key in ('aliases','canonical_reason','source_names','group_key','match_tier','rank_sort_key')}
        info.update(primary); info.update(preserved)
        info['candidates']=list(resolution.candidates)
        info['resolution_state']='resolved'; info['resolution']=resolution
        item.setData(Qt.ItemDataRole.UserRole,info)
        names={row.source_id:row.source_name for row in resolution.inventories}
        confirmed=tuple((source_id,names.get(source_id) or source_id) for source_id in resolution.expected_source_ids)
        note=''
        if resolution.language_fallback:
            note=f'{language_label(resolution.preferred_language)} unavailable · {language_label(resolution.language)} available'
        row=self.search_results.itemWidget(item)
        if isinstance(row,SearchResultRowWidget):
            row.set_source_state(confirmed,note)

    def _search_resolution_finished(self, worker, request_id, mode=None, generation=None):
        if self._search_resolution_worker is worker:
            self._search_resolution_worker=None
        if (request_id != self._search_resolution_request_id or
                mode != self.workflow_mode or generation != self._mode_generation):
            return
        self._render_canonical_search_results(final=True)
        if self.search_results.count()==0:
            info_dialog(self,'MangaNana search',f'No usable titles were found for {self.workflow_mode.title()} mode.',show=True)
        else:
            QTimer.singleShot(0,self._load_visible_search_thumbs)

    def _show_more_search_results(self):
        self.search_mangadex(False)

    def _update_search_status(self):
        if self.search_workers and not self._search_cancel_requested:
            self._sync_provider_search_progress()
            self.search_progress_text.setText(provider_search_progress_text(
                self.search_coordinator.snapshot(),time.monotonic()-self._search_started_at,
            ))

    def _visible_row_range(self, widget, row_height, buffer_rows=3):
        count=widget.count()
        if count <= 0:
            return range(0)
        value=widget.verticalScrollBar().value()
        height=max(1,widget.viewport().height())
        start=max(0,int(value/max(1,row_height))-buffer_rows)
        end=min(count,int((value+height)/max(1,row_height))+buffer_rows+2)
        return range(start,end)

    def _pix_from_bytes(self, raw, w, h):
        try:
            pix=QPixmap(); pix.loadFromData(raw)
            if not pix.isNull():
                return pix.scaled(w,h,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass
        return None

    def _load_visible_search_thumbs(self):
        if self._closing or (self.search_thumb_worker and self.search_thumb_worker.isRunning()):
            return
        batch=[]; queued_urls=set()
        for i in self._visible_row_range(self.search_results,127,4):
            item=self.search_results.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if not isinstance(info,dict):
                continue
            url=info.get('cover_url') or ''
            if not url:
                continue
            if url in self._failed_image_urls:
                row=self.search_results.itemWidget(item)
                if isinstance(row,SearchResultRowWidget): row.cover_failed()
                continue
            raw=self._image_cache.get(url)
            if raw:
                pix=self._pix_from_bytes(raw,78,108)
                row=self.search_results.itemWidget(item)
                if isinstance(row,SearchResultRowWidget):
                    row.set_cover(pix) if pix is not None else row.cover_failed()
            elif not info.get('thumb_requested') and url not in queued_urls and len(batch) < COVER_BATCH_LIMIT:
                info['thumb_requested']=True; item.setData(Qt.ItemDataRole.UserRole,info)
                source=SOURCE_REGISTRY.get(info.get('source_id')) or MANGADEX_SOURCE
                urls=[url+'.256.jpg',url] if source.source_id == 'mangadex' else [url]
                batch.append((url,urls,source)); queued_urls.add(url)
        if not batch:
            return
        self._search_cover_batch_token += 1; token=self._search_cover_batch_token; generation=self._cover_generation
        # Do not parent a running QThread to the dialog; it may outlive close
        # briefly while an in-flight request notices interruption.
        worker=ImageBatchWorker(('search',token,generation),batch); self.search_thumb_worker=worker
        # Bound QObject methods are queued onto this dialog's GUI thread.
        worker.image_ready.connect(self._on_search_thumb_ready)
        worker.image_failed.connect(self._on_search_thumb_failed)
        worker.batch_done.connect(self._on_search_thumb_batch_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_search_thumb_ready(self, data):
        batch_id=data.get('batch_id') or ()
        _kind, token, generation=(batch_id + (None,None,None))[:3] if isinstance(batch_id,tuple) else (None,None,None)
        if self._closing or generation != self._cover_generation or token != self._search_cover_batch_token:
            return
        url=data.get('key'); raw=data.get('raw')
        if not url or not raw:
            return
        self._image_cache[url]=raw
        for i in range(self.search_results.count()):
            item=self.search_results.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if isinstance(info,dict) and info.get('cover_url')==url:
                pix=self._pix_from_bytes(raw,78,108)
                row=self.search_results.itemWidget(item)
                if isinstance(row,SearchResultRowWidget):
                    row.set_cover(pix) if pix is not None else row.cover_failed()

    def _on_search_thumb_failed(self, data):
        batch_id=data.get('batch_id') or ()
        _kind, token, generation=(batch_id + (None,None,None))[:3] if isinstance(batch_id,tuple) else (None,None,None)
        if self._closing or generation != self._cover_generation or token != self._search_cover_batch_token:
            return
        url=data.get('key')
        if not url:
            return
        self._failed_image_urls.add(url)
        for i in range(self.search_results.count()):
            item=self.search_results.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if isinstance(info,dict) and info.get('cover_url') == url:
                row=self.search_results.itemWidget(item)
                if isinstance(row,SearchResultRowWidget):
                    row.cover_failed()

    def _on_search_thumb_batch_done(self, data):
        self.search_thumb_worker=None
        if not self._closing:
            QTimer.singleShot(0,self._load_visible_search_thumbs)

    def use_search_result(self, item=None):
        if item is None: item=self.search_results.currentItem()
        if item is None: return
        info=item.data(Qt.ItemDataRole.UserRole) or {}
        resolution=info.get('resolution') if isinstance(info,dict) else None
        if info.get('resolution_state') != 'resolved' or not resolution or not resolution.usable:
            self.add_log('This result is still checking usable sources.')
            return
        selected=resolution.primary
        fallback_plan=resolution.fallback_plan
        if resolution.decision and resolution.decision.ambiguous:
            selected=self._choose_ambiguous_inventory(info,resolution.decision)
            if selected is None:
                return
            fallback_plan=build_cross_source_plan(
                resolution.inventories,SOURCE_REGISTRY,primary=selected,
                workflow=self.workflow_mode,
            ) if self.workflow_mode == 'chapter' else None
        self._last_inventory_decision=resolution.decision
        self._pending_cross_source_plan=fallback_plan if self.workflow_mode == 'chapter' else None
        self._pending_search_language=resolution.language
        for inventory in resolution.inventories:
            self.add_log(f'[{inventory.source_name}] Inventory: {inventory.summary}.')
        self.add_log(f'Primary source: {selected.source_name}.')
        if fallback_plan and fallback_plan.fallback_items and fallback_plan.can_execute:
            self.add_log(fallback_plan.notice)
        self._begin_search_result(selected.result)

    def _start_inventory_comparison(self, group_info, candidates):
        if self.inventory_comparison_worker and self.inventory_comparison_worker.isRunning():
            self.inventory_comparison_worker.requestInterruption()
        self._inventory_comparison_request_id += 1
        self._last_inventory_decision=None
        request_id=self._inventory_comparison_request_id
        mode=self.workflow_mode; generation=self._mode_generation
        self.search_results.setEnabled(False)
        self.workflow_hint.setText('Checking provider inventories...')
        worker=InventoryComparisonWorker(SOURCE_REGISTRY,candidates,prefs['language'],self.workflow_mode,self)
        self.inventory_comparison_worker=worker
        worker.progress.connect(lambda done,total,text,rid=request_id,m=mode,g=generation:self._on_inventory_comparison_progress(rid,done,total,text,m,g))
        worker.ready.connect(lambda decision,rid=request_id,info=dict(group_info),m=mode,g=generation:self._on_inventory_comparison_ready(rid,info,decision,m,g))
        worker.failed.connect(lambda message,rid=request_id,m=mode,g=generation:self._on_inventory_comparison_failed(rid,message,m,g))
        worker.finished.connect(lambda w=worker:self._inventory_comparison_finished(w))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _inventory_comparison_finished(self, worker):
        if self.inventory_comparison_worker is worker:
            self.inventory_comparison_worker=None
            self.search_results.setEnabled(True)

    def _on_inventory_comparison_progress(self, request_id, done, total, text, mode=None, generation=None):
        if request_id != self._inventory_comparison_request_id or mode != self.workflow_mode or generation != self._mode_generation:
            return
        self.workflow_hint.setText(text)

    def _on_inventory_comparison_ready(self, request_id, group_info, decision, mode=None, generation=None):
        if request_id != self._inventory_comparison_request_id or mode != self.workflow_mode or generation != self._mode_generation:
            return
        self.inventory_comparison_worker=None
        self._last_inventory_decision=decision
        self.search_results.setEnabled(True)
        for inventory in decision.inventories:
            self.add_log(f'[{inventory.source_name}] Inventory: {inventory.summary}.')
        if decision.selected is not None:
            selected=decision.selected
            fallback_plan=decision.fallback_plan
            self._pending_cross_source_plan=fallback_plan if self.workflow_mode == 'chapter' else None
            self.add_log(f'Primary source: {selected.source_name}.')
            fallback_blocked=False
            if fallback_plan and fallback_plan.fallback_items:
                if fallback_plan.can_execute:
                    self.add_log(fallback_plan.notice)
                else:
                    fallback_blocked=True
                    self.add_log(
                        'Compatible fallback chapters were identified, but mixed-provider '
                        'volume output is not supported yet; using the primary source only.'
                    )
            language_name=language_label(selected.language)
            status=f'Using {selected.source_name} — best available {language_name} inventory'
            if fallback_blocked:
                status += ' (compatible chapter gaps need Chapter mode)'
            self.workflow_hint.setText(status)
            self.add_log(status+f'. {decision.reason}')
            self._begin_search_result(selected.result)
            return
        if decision.error:
            if self.workflow_mode == 'volume':
                language_name=language_label(prefs['language'])
                message=f'No usable {language_name} volumes are currently available from the enabled sources.'
                self.workflow_hint.setText(message)
                self.add_log('Volume mode unavailable for this series with the enabled sources.')
                for inventory in decision.inventories:
                    if inventory.native_volume_metadata and not inventory.native_volumes:
                        self.add_log(f'[{inventory.source_name}] Native volume metadata found, but no usable {language_name} volume content.')
                    elif inventory.usable and not inventory.native_volumes:
                        self.add_log(f'[{inventory.source_name}] {inventory.chapter_count} chapters available; native volumes unsupported. Try Chapter mode.')
                return
            self.workflow_hint.setText('No usable provider inventory found.')
            error_dialog(self,'No usable inventory',decision.error,show=True)
            return
        self.workflow_hint.setText('Provider inventories require a choice.')
        selected=self._choose_ambiguous_inventory(group_info,decision)
        if selected is not None:
            self._begin_search_result(selected.result)

    def _choose_ambiguous_inventory(self, group_info, decision):
        box=QMessageBox(self)
        box.setWindowTitle('Choose a source for this series')
        box.setText(f'{group_info.get("title") or "This manga"} has similarly usable provider inventories.')
        comparison='\n'.join(f'{row.source_name}: {row.summary}' for row in decision.inventories)
        box.setInformativeText(
            'MangaNana identified one canonical series, but no provider is clearly better.\n\n'
            + comparison + '\n\nChoose which provider to use. Inventories will not be combined.'
        )
        buttons=[]
        for inventory in decision.inventories:
            if not inventory.usable:
                continue
            button=box.addButton(inventory.source_name,QMessageBox.ButtonRole.ActionRole)
            buttons.append((button,inventory))
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return next((inventory for button,inventory in buttons if box.clickedButton() is button),None)

    def _on_inventory_comparison_failed(self, request_id, message, mode=None, generation=None):
        if request_id != self._inventory_comparison_request_id or mode != self.workflow_mode or generation != self._mode_generation:
            return
        self.inventory_comparison_worker=None
        self.search_results.setEnabled(True)
        self.workflow_hint.setText('Inventory comparison failed.')
        error_dialog(self,'Inventory comparison failed',message,show=True)

    def _begin_search_result(self, info):
        mid=info.get('id') if isinstance(info,dict) else info
        if not mid: return
        self._pending_search_url=info.get('url') or ('https://mangadex.org/title/'+str(mid))
        self._pending_source_id=info.get('source_id') or MANGADEX_SOURCE.source_id
        self._pending_search_cover_url=(info.get('cover_url') or '') if isinstance(info,dict) else ''
        had_preview=bool(self.preview_data is not None or self.preview_signature is not None or self._preview_build_signature is not None)
        self._invalidate_inflight_preview()
        if had_preview:
            self._pending_auto_preview=True
            self.download_btn.setEnabled(False)
        else:
            self._clear_preview_state('Load a manga, choose your settings, then build a download preview.')
        self.preview_btn.setEnabled(False); self.download_btn.setEnabled(False)
        self._selected_volumes.clear(); self._standalone_selected=False; self._using_entire_series=False; self.volume_list.clear(); self.volume_list.setEnabled(False); self.volume_count_label.clear(); self.clear_volume_btn.setEnabled(False)
        self.selected_cover.setVisible(True); self.alt_titles_btn.setVisible(False); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop); self.selected_title.setStyleSheet('font-size:15px; font-weight:700;'); self.selected_title.setText('Loading manga...'); self.selected_author.setText(''); self._set_edition_badge(''); self.availability_badge.setVisible(False)
        if self._pending_search_cover_url:
            raw=self._image_cache.get(self._pending_search_cover_url)
            if raw:
                pix=self._pix_from_bytes(raw,130,180)
                if pix is not None: self.selected_cover.setPixmap(pix)
                else: self.selected_cover.set_failed()
            else:
                self.selected_cover.set_loading()
        else:
            self.selected_cover.set_loading()
        self._pending_result_token += 1
        token=self._pending_result_token
        QTimer.singleShot(250, lambda t=token: self._load_debounced_search_result(t))

    def _load_debounced_search_result(self, token):
        if token == self._pending_result_token and self._pending_search_url:
            self.load_metadata(self._pending_search_url, self._pending_source_id, discovery_kind='search')

    def _offer_enable_direct_source(self, source):
        """Offer future search participation without blocking this direct load."""
        box = QMessageBox(self)
        box.setWindowTitle('Manga source disabled for search')
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(f'{source.display_name} is disabled for general searches.')
        box.setInformativeText('Enable it for future searches?\n\nThis direct-link operation will continue either way.')
        enable = box.addButton('Enable', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Not now', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is enable:
            save_source_enabled_states(prefs, {source.source_id: True}, commit=True)
            self.add_log(f'[{source.display_name}] Enabled for future general searches.')
        else:
            self.add_log(f'[{source.display_name}] Remains disabled for general searches; direct link allowed.')

    def load_metadata(self, url_override=None, source_id=None, discovery_kind=None, prompt_disabled=True):
        # QPushButton.clicked may supply a bool. Only strings are URL overrides.
        if not isinstance(url_override, str):
            url_override=None
        if self.workflow_mode not in ('volume', 'chapter'):
            error_dialog(self, 'Choose workflow', 'Choose Volumes or Chapters before loading a title.', show=True)
            return
        url=(url_override or self.url.text()).strip()
        discovery_kind=discovery_kind or ('direct' if url_override is None else 'search')
        if url_override is None:
            self._pending_cross_source_plan=None
        match=SOURCE_REGISTRY.identify(url)
        source=SOURCE_REGISTRY.get(source_id) if source_id else (match.source if match else None)
        ref=source.parse_manga_ref(url) if source else None
        if url_override is None and hasattr(self, 'url'):
            self.url.setCursorPosition(0); self.url.deselect()
        if not source or ref is None:
            error_dialog(self,'Metadata error','Paste a supported manga link.',show=True)
            return
        if (discovery_kind == 'direct' and prompt_disabled and
                not is_source_enabled(prefs, source)):
            self._offer_enable_direct_source(source)
        if discovery_kind == 'direct':
            self._search_request_id += 1; self._search_resolution_request_id += 1
            for search_worker in self.search_workers.values():
                if search_worker.isRunning(): search_worker.requestInterruption()
            if self.search_workers:
                self.search_coordinator.cancel_remaining(); self._sync_provider_search_progress()
            self.search_workers={}; self._search_status_timer.stop()
            if self._search_resolution_worker and self._search_resolution_worker.isRunning():
                self._search_resolution_worker.requestInterruption()
            self._search_resolution_worker=None
            self.search_btn.setEnabled(True); self.search_btn.setText('Search')
        self._manga_request_id += 1
        self._invalidate_cover_requests()
        request_id=self._manga_request_id
        self._manga_discovery_kinds[request_id]=(discovery_kind, url)
        self._manga_requested_languages[request_id]=self._pending_search_language if discovery_kind == 'search' else ''
        had_preview=bool(self.preview_data is not None or self.preview_signature is not None or self._preview_build_signature is not None or self._pending_auto_preview)
        self.current_manga_url=url
        self.current_source=source; self.current_source_id=source.source_id
        self._invalidate_inflight_preview()
        if had_preview:
            self._pending_auto_preview=True
            self.download_btn.setEnabled(False)
            if hasattr(self,'pairing_preview_btn'): self.pairing_preview_btn.setEnabled(False)
        else:
            self._clear_preview_state('Load a manga, choose your settings, then build a download preview.')
        self.load_btn.setEnabled(False); self.load_btn.setText('Loading...'); self.preview_btn.setEnabled(False)
        self.alt_titles_btn.setEnabled(False)
        self.selected_cover.setVisible(True); self.alt_titles_btn.setVisible(False); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop); self.selected_title.setStyleSheet('font-size:15px; font-weight:700;'); self.selected_title.setText('Loading manga...'); self.selected_author.setText(''); self._set_edition_badge(''); self.availability_badge.setVisible(False)
        self.volume_list.clear(); self.volume_list.setEnabled(False); self.volume_count_label.clear(); self.meta_summary.setText(f'Loading {source.display_name} metadata...')
        if not self._pending_search_cover_url or url != self._pending_search_url:
            self.selected_cover.set_loading()
        populate_download_languages(self.language, available=None, preferred=prefs['language'])
        self._current_plan=None; self._chapter_plan_items=(); self._selected_chapter_ids.clear(); self._download_language_valid=False; self._volume_plan_loading=False; self._selected_volumes.clear(); self._standalone_selected=False; self._using_entire_series=False
        self._range_syncing=True
        try:
            self.start.clear(); self.end.clear()
        finally:
            self._range_syncing=False
        self._manual_range_invalid=False; self._manual_range_error=''; self._last_invalid_range_log_key=None
        cache_key=(source.source_id,ref)
        cached=self._manga_cache.get(cache_key)
        if cached is not None:
            QTimer.singleShot(0,lambda d=cached,r=request_id:self._apply_loaded_manga(r,d))
            return
        worker=MangaLoadWorker(request_id,source,url,prefs['language'],self)
        self._manga_workers.append(worker)
        worker.ready.connect(self._on_manga_worker_ready)
        worker.failed.connect(self._on_manga_worker_failed)
        worker.finished.connect(lambda w=worker:self._cleanup_worker(w,self._manga_workers))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_manga_worker_ready(self, data):
        mid=(data.get('metadata') or {}).get('uuid')
        if mid: self._manga_cache[(data.get('source_id'),mid)]=data
        self._apply_loaded_manga(data.get('request_id'),data)

    def _on_manga_worker_failed(self, data):
        if data.get('request_id') != self._manga_request_id:
            return
        self._manga_discovery_kinds.pop(data.get('request_id'), None)
        self._manga_requested_languages.pop(data.get('request_id'), None)
        self.loaded_metadata=None; self.alt_titles_btn.setEnabled(False); self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self._record_diagnostic(RuntimeError, RuntimeError(data.get('error') or 'Unknown source error.'), None, 'metadata load')
        self.load_btn.setEnabled(True); self.load_btn.setText('Load Manga')
        self.selected_cover.set_failed(); self.selected_cover.setVisible(False); self.alt_titles_btn.setVisible(False); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignCenter); self.selected_title.setStyleSheet('font-size:12px; font-weight:600; color:#777;'); self.selected_title.setText('No manga selected'); self.meta_summary.clear()
        error_dialog(self,'Metadata error',data.get('error') or 'Unknown source error.',show=True)

    def _apply_loaded_manga(self, request_id, data):
        if request_id != self._manga_request_id:
            return
        md=data.get('metadata') or {}
        if md.get('adult') and not prefs['show_adult_search_results']:
            self._manga_discovery_kinds.pop(request_id,None)
            self._manga_requested_languages.pop(request_id,None)
            self.loaded_metadata=None; self.current_manga_url=''; self._current_plan=None; self._chapter_plan_items=(); self._selected_chapter_ids.clear()
            self.title.clear(); self.author.clear(); self.series.clear(); self.volume_list.clear(); self.volume_list.setEnabled(False)
            self.load_btn.setEnabled(True); self.load_btn.setText('Load Manga'); self.preview_btn.setEnabled(False)
            self.selected_cover.set_failed(); self.selected_cover.setVisible(False); self.alt_titles_btn.setVisible(False)
            self.selected_title.setAlignment(Qt.AlignmentFlag.AlignCenter); self.selected_title.setText('No manga selected')
            self.meta_summary.setText('Adult title blocked by the current search preference.')
            self.add_log(f'[{data.get("source_id") or "Source"}] Adult title blocked by preference after metadata validation.')
            error_dialog(self,'Adult title hidden','Enable “Show 18+ search results” in Preferences to load this title.',show=True)
            return
        self.loaded_metadata=md; self.current_manga_url=data.get('url') or self.current_manga_url
        discovery_kind, discovery_value=self._manga_discovery_kinds.pop(request_id, (None, ''))
        requested_language=self._manga_requested_languages.pop(request_id,'')
        if discovery_kind == 'direct' and discovery_value:
            self._last_discovery_kind=discovery_kind; self._last_discovery_value=discovery_value
        self.current_source=SOURCE_REGISTRY.get(data.get('source_id')) or self.current_source
        self.current_source_id=self.current_source.source_id
        self._loaded_covers={}
        self._main_cover_url=md.get('main_cover_url') or (self._pending_search_cover_url if self.current_manga_url == self._pending_search_url else '')
        self.title.setText(md.get('title','')); self.author.setText(md.get('author','')); self.series.setText(md.get('title',''))
        self.selected_cover.setVisible(True); self.alt_titles_btn.setVisible(True); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop); self.selected_title.setStyleSheet('font-size:15px; font-weight:700;'); self.selected_title.setText(md.get('title') or 'Untitled'); self.selected_author.setText(md.get('author') or '')
        if not self._main_cover_url:
            self.selected_cover.set_failed()
        raw=' '.join(x.get('title','') for x in md.get('titles',[])).casefold()
        badge='COLOR' if any(x in raw for x in ('digital colored','digital coloured','digital color','digital colour','full color','full colour','color edition','colour edition','colored comics','coloured comics','fan-colored','fan colored','fan-coloured','fan coloured')) else 'B&W'
        self._set_edition_badge(badge); self.alt_titles_btn.setEnabled(bool(md.get('titles')))
        available=md.get('available_languages') or []
        self.availability_badge.setVisible(not bool(available))
        populate_download_languages(self.language, available=available, preferred=requested_language or prefs['language'])
        auto_fallback = bool(self.language.currentData() and self.language.currentData() != prefs['language'])
        self._selected_volume=None; self._selected_volumes.clear(); self._selected_chapter_ids.clear(); self._standalone_selected=False; self._using_entire_series=False; self._current_plan=None; self._chapter_plan_items=(); self._download_language_valid=False; self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self._rebuild_volume_list()
        self.load_btn.setEnabled(True); self.load_btn.setText('Load Manga')
        self.add_log(f"[{self.current_source.display_name}] Loaded metadata: {md.get('title','')} | {md.get('author','')}")
        if self.language.currentData():
            if auto_fallback:
                self.add_log(f'Preferred download language ({language_label(prefs["language"])}) is unavailable; using {self.language.currentText()} automatically.')
            self.add_log('Download language: '+self.language.currentText())
            self._load_volume_plan()
        else:
            preferred=language_label(prefs['language'])
            if available:
                self.meta_summary.setText(f'Preferred language ({preferred}) is unavailable for this manga. Choose a Download Language.')
                self.add_log(f'Preferred language ({preferred}) is unavailable. Choose one of the reported download languages.')
            else:
                self.meta_summary.setText('No downloadable chapters are currently available for this title.')
                self._show_volume_empty_message('No downloadable chapters available.')
                self.clear_volume_btn.setEnabled(False)
                self.add_log('No downloadable chapters are currently available for this title.')
        QTimer.singleShot(0,self._load_visible_volume_thumbs)

    def _download_language_changed(self, *args):
        self.invalidate_preview()
        if self.preview_data is not None or self.preview_signature is not None:
            self._pending_auto_preview=True
        if not self.loaded_metadata:
            return
        self._selected_volumes.clear(); self._selected_chapter_ids.clear(); self._standalone_selected=False; self._using_entire_series=False; self._current_plan=None; self._chapter_plan_items=(); self._download_language_valid=False; self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self._rebuild_volume_list()
        if self.language.currentData():
            self._load_volume_plan()
        else:
            self.meta_summary.setText('Choose a Download Language before continuing.')

    def _load_volume_plan(self):
        if not self.loaded_metadata:
            return
        lang=self.language.currentData(); mid=self.loaded_metadata.get('uuid')
        if not lang or not mid:
            return
        self._volume_plan_request_id += 1; request_id=self._volume_plan_request_id
        self._diagnostic_operation='chapter inventory load' if self.workflow_mode == 'chapter' else 'volume inventory load'
        key=(self.workflow_mode,self.current_source_id,mid,lang)
        cached=self._plan_cache.get(key)
        self._volume_plan_loading=True; self.meta_summary.setText(f'Loading {self.language.currentText()} volume information...')
        if cached is not None:
            cached_data=dict(cached); cached_data['request_id']=request_id
            QTimer.singleShot(0,lambda d=cached_data:self._apply_volume_plan_data(d))
            return
        worker=(VolumePlanWorker if self.workflow_mode == 'volume' else ChapterPlanWorker)(request_id,self.current_source,self.current_manga_url,lang,self)
        self._plan_workers.append(worker)
        worker.ready.connect(self._on_volume_plan_ready); worker.failed.connect(self._on_volume_plan_failed)
        worker.finished.connect(lambda w=worker:self._cleanup_worker(w,self._plan_workers)); worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_volume_plan_ready(self, data):
        source=SOURCE_REGISTRY.get(data.get('source_id')) or self.current_source
        mid=source.parse_manga_ref(data.get('url') or '')
        if mid:
            self._plan_cache[(self.workflow_mode,source.source_id,mid,data.get('language'))]={
                'url':data.get('url'),'language':data.get('language'),'plan':data.get('plan') or {},
                'source_id':source.source_id,'covers':data.get('covers') or {},'cover_error':data.get('cover_error') or '',
                'chapters':data.get('chapters') or [],
            }
        self._apply_volume_plan_data(data)

    def _apply_volume_plan_data(self, data):
        request_id=data.get('request_id'); language=data.get('language')
        if request_id != self._volume_plan_request_id or language != self.language.currentData():
            return
        self._loaded_covers=data.get('covers') or {}
        if data.get('cover_error'):
            self.add_log('Volume-cover metadata unavailable: '+str(data.get('cover_error')))
        if self.workflow_mode == 'chapter':
            chapters=data.get('chapters') or []
            self._apply_chapter_plan(request_id,language,chapters)
        else:
            self._apply_volume_plan(request_id,language,data.get('plan') or {})

    def _apply_volume_plan(self, request_id, language, plan):
        if request_id != self._volume_plan_request_id or language != self.language.currentData():
            return
        self._volume_plan_loading=False; self._current_plan=plan
        if plan.get('aggregate_error'):
            self.add_log(f'[{self.current_source.display_name}] Aggregate lookup warning: '+str(plan.get('aggregate_error')))
        if plan.get('feed_error'):
            self.add_log(f'[{self.current_source.display_name}] Chapter-feed lookup warning: '+str(plan.get('feed_error')))
        chapter_total=sum(int(v or 0) for v in (plan.get('chapters_by_volume') or {}).values()) + int(plan.get('bonus_chapters') or 0)
        self._download_language_valid=chapter_total > 0
        self._rebuild_volume_list(); self.volume_list.setEnabled(self._download_language_valid)
        self._update_preview_button_for_volume_selection()
        if self._download_language_valid and self.preview_data is None:
            self.preview_summary.setText('Choose volumes if needed, then press PREVIEW.')
        if self._download_language_valid:
            self.availability_badge.setVisible(False)
            if self._pending_auto_preview:
                QTimer.singleShot(80, self._run_silent_preview_refresh)
            numeric=len(plan.get('volumes') or [])
            extras=int(plan.get('bonus_chapters') or 0)
            self.start.setEnabled(numeric > 0)
            self.end.setEnabled(numeric > 0)
            volume_word='volume' if numeric==1 else 'volumes'
            if numeric and extras:
                msg=f'{numeric} {volume_word} plus {extras} standalone chapter' + ('' if extras==1 else 's') + f' available in {self.language.currentText()}.'
                log_msg=f'Volume browser ready: {numeric} {volume_word} plus {extras} standalone chapter' + ('' if extras==1 else 's') + f' in {self.language.currentText()}.'
            elif extras:
                msg=f'{extras} standalone chapter' + ('' if extras==1 else 's') + f' available in {self.language.currentText()}.'
                log_msg=f'Volume browser ready: {extras} standalone chapter' + ('' if extras==1 else 's') + f' in {self.language.currentText()}.'
            else:
                msg=f'{numeric} {volume_word} available in {self.language.currentText()}.'
                log_msg=f'Volume browser ready: {numeric} {volume_word} in {self.language.currentText()}.'
            self.meta_summary.setText(msg)
            self.add_log(log_msg)
        else:
            self.availability_badge.setVisible(True)
            lang_name=self.language.currentText()
            message=f'No downloadable chapters in {lang_name}. Try another edition or Download Language.'
            self.meta_summary.setText(message)
            self._show_volume_empty_message(message)
            self.add_log(f'[{self.current_source.display_name}] No downloadable chapters found in {lang_name}.')
        QTimer.singleShot(0,self._load_visible_volume_thumbs)

    def _apply_chapter_plan(self, request_id, language, chapters):
        if request_id != self._volume_plan_request_id or language != self.language.currentData():
            return
        self._volume_plan_loading=False
        # Use a prior inventory plan only when it was built for this exact
        # selected language and primary provider; otherwise rediscovery remains
        # the authoritative single-provider chapter list.
        planned = self._pending_cross_source_plan
        if (planned and planned.can_execute and planned.language == language and
                planned.primary_source_id == self.current_source_id):
            items=[]
            for item in planned.items:
                row=dict(item.reference); row['_source_id']=item.source_id; row['_source_name']=item.source_name
                row['_fallback_reason']=item.reason; items.append(row)
            self._chapter_plan_items=tuple(sorted(items, key=chapter_sort_key))
            if planned.fallback_items:
                self.add_log(planned.notice)
        else:
            self._chapter_plan_items=tuple(sorted((dict(row) for row in chapters or ()), key=chapter_sort_key))
        self._current_plan={'volumes': [], 'bonus_chapters': len(self._chapter_plan_items)}
        self._download_language_valid=bool(self._chapter_plan_items)
        self._rebuild_volume_list(); self.volume_list.setEnabled(self._download_language_valid)
        self._update_preview_button_for_volume_selection()
        count=len(self._chapter_plan_items)
        if count:
            self.meta_summary.setText(f'{count} chapter' + ('' if count == 1 else 's') + f' available in {self.language.currentText()}.')
            self.add_log(f'Chapter browser ready: {count} chapters in {self.language.currentText()}.')
        else:
            self.meta_summary.setText('No downloadable chapters were found for Chapter mode.')
            self._show_volume_empty_message('No downloadable chapters were found for Chapter mode.')

    def _on_volume_plan_failed(self, data):
        if data.get('request_id') != self._volume_plan_request_id:
            return
        self._volume_plan_loading=False; self._download_language_valid=False; self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self._record_diagnostic(RuntimeError, RuntimeError(data.get('error') or 'Unknown error'), None, self._diagnostic_operation)
        self.meta_summary.setText('Volume information could not be loaded. Try the language again.')
        self._show_volume_empty_message('Volume information could not be loaded. Try the language again.')
        self.add_log('Volume browser unavailable: '+str(data.get('error') or 'Unknown error'))

    def _show_volume_empty_message(self, text):
        self._volume_check_syncing=True
        try:
            self.volume_list.clear()
            item=QListWidgetItem(str(text or ''))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            item.setForeground(QColor('#8F9499'))
            item.setSizeHint(QSize(0,78))
            self.volume_list.addItem(item)
        finally:
            self._volume_check_syncing=False

    def _rebuild_volume_list(self):
        self._volume_check_syncing=True
        try:
            self.volume_list.clear(); self.selected_cover.clear()
            if self.workflow_mode == 'chapter':
                rows=tuple(self._chapter_plan_items or ())
                valid=chapter_selection_ids(rows)
                self._selected_chapter_ids.intersection_update(valid)
                self.volume_count_label.setText(f'{len(rows)} chapter' + ('' if len(rows)==1 else 's') if rows else '')
                for chapter in rows:
                    chapter_id=str(chapter.get('id') or '')
                    item=QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, {'kind':'chapter','chapter':chapter,'chapter_id':chapter_id,
                                                           'cover_url':self._main_cover_url or ''})
                    item.setSizeHint(QSize(0,72)); self.volume_list.addItem(item)
                    title=str(chapter.get('title') or '').strip()
                    source_name=str(chapter.get('_source_name') or self.current_source.display_name)
                    label=f'Chapter {chapter_label(chapter, self.pad.isChecked())}' + (f'  ·  {title}' if title else '') + f'  ·  {source_name}'
                    row=VolumeRowWidget(label, self.volume_list, cover_loading=bool(self._main_cover_url))
                    row.set_checked(chapter_id in self._selected_chapter_ids)
                    row.toggled.connect(lambda checked, it=item: self._volume_row_toggled(it, checked))
                    self.volume_list.setItemWidget(item,row)
                self.clear_volume_btn.setEnabled(bool(rows) and self._download_language_valid)
                self._update_volume_selection_hint(); self._update_preview_button_for_volume_selection()
                self._selected_cover_url=self._main_cover_url or ''
                if self._selected_cover_url:
                    self.selected_cover.set_loading()
                else:
                    self.selected_cover.set_failed()
                QTimer.singleShot(0,self._load_visible_volume_thumbs)
                return
            covers=self._loaded_covers or {}; plan=self._current_plan or {}
            self._selected_cover_url=self._main_cover_url or covers.get(None) or ''
            if self._selected_cover_url:
                self.selected_cover.set_loading()
            else:
                self.selected_cover.set_failed()
            vols=plan.get('volumes') or []
            numeric=sorted(set(float(k) for k in vols)) if self._current_plan is not None else sorted(set(k for k in covers if k is not None))
            valid=set(float(v) for v in numeric)
            self._selected_volumes.intersection_update(valid)
            standalone_count=int(plan.get('bonus_chapters') or 0)
            if standalone_count <= 0:
                self._standalone_selected=False
            total_entries=len(numeric) + (1 if standalone_count else 0)
            if total_entries:
                if standalone_count and not numeric:
                    self.volume_count_label.setText(f'{standalone_count} chapter' + ('' if standalone_count==1 else 's'))
                else:
                    self.volume_count_label.setText(f'{len(numeric)} volume' + ('' if len(numeric)==1 else 's') + (' + standalone' if standalone_count else ''))
            else:
                self.volume_count_label.clear()
            for v in numeric:
                c=covers.get(v) or self._main_cover_url or self._selected_cover_url or ''
                item=QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole,{'kind':'volume','volume':float(v),'cover_url':c})
                item.setSizeHint(QSize(0,72)); self.volume_list.addItem(item)
                row=VolumeRowWidget(f'Volume {v:g}', self.volume_list, cover_loading=bool(c))
                row.set_checked(float(v) in self._selected_volumes)
                row.toggled.connect(lambda checked, it=item: self._volume_row_toggled(it, checked))
                self.volume_list.setItemWidget(item,row)
                if c and not self._selected_cover_url:
                    self._selected_cover_url=c
            if standalone_count:
                item=QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole,{'kind':'standalone','volume':None,'cover_url':self._main_cover_url or self._selected_cover_url or '','chapter_count':standalone_count})
                item.setSizeHint(QSize(0,72)); self.volume_list.addItem(item)
                label=f'Standalone Chapters  ·  {standalone_count} chapter' + ('' if standalone_count==1 else 's')
                row=VolumeRowWidget(label, self.volume_list, cover_loading=bool(self._main_cover_url or self._selected_cover_url))
                row.set_checked(bool(self._standalone_selected))
                row.toggled.connect(lambda checked, it=item: self._volume_row_toggled(it, checked))
                self.volume_list.setItemWidget(item,row)
        finally:
            self._volume_check_syncing=False
        self.clear_volume_btn.setEnabled(bool(total_entries) and bool(self._download_language_valid))
        if (self.start.text().strip() or self.end.text().strip()) and not self._range_syncing:
            self._range_inputs_changed()
        else:
            self._update_volume_selection_hint()
            self._update_preview_button_for_volume_selection()
        QTimer.singleShot(0,self._load_visible_volume_thumbs)

    def _load_visible_volume_thumbs(self):
        if self._closing or (self.volume_thumb_worker and self.volume_thumb_worker.isRunning()):
            return
        batch=[]; queued_urls=set()
        visible=list(self._visible_row_range(self.volume_list,66,4))
        if self._selected_cover_url:
            selected_raw=self._image_cache.get(self._selected_cover_url)
            if self._selected_cover_url in self._failed_image_urls:
                self.selected_cover.set_failed()
            elif selected_raw:
                big=self._pix_from_bytes(selected_raw,130,180)
                if big is not None: self.selected_cover.setPixmap(big)
                else: self.selected_cover.set_failed()
            else:
                self.selected_cover.set_loading()
                batch.append((self._selected_cover_url,[self._selected_cover_url+'.256.jpg',self._selected_cover_url]))
                queued_urls.add(self._selected_cover_url)
        for i in visible:
            item=self.volume_list.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if not isinstance(info,dict): continue
            url=info.get('cover_url') or ''
            if not url: continue
            if url in self._failed_image_urls:
                row=self.volume_list.itemWidget(item)
                if isinstance(row,VolumeRowWidget): row.set_cover(None)
                if url == self._selected_cover_url: self.selected_cover.set_failed()
                continue
            raw=self._image_cache.get(url)
            if raw:
                pix=self._pix_from_bytes(raw,42,58)
                row=self.volume_list.itemWidget(item)
                if isinstance(row, VolumeRowWidget): row.set_cover(pix)
                if url==self._selected_cover_url:
                    big=self._pix_from_bytes(raw,130,180)
                    if big is not None: self.selected_cover.setPixmap(big)
            elif not info.get('thumb_requested') and url not in queued_urls and len(batch) < COVER_BATCH_LIMIT:
                info['thumb_requested']=True; item.setData(Qt.ItemDataRole.UserRole,info)
                batch.append((url,[url+'.256.jpg',url])); queued_urls.add(url)
        # De-duplicate a cover that was added for both selected-cover and visible-row purposes.
        unique=[]; seen=set()
        for entry in batch:
            if entry[0] not in seen:
                seen.add(entry[0]); unique.append(entry)
        if not unique:
            return
        self._volume_cover_batch_token += 1; token=self._volume_cover_batch_token; generation=self._cover_generation
        # This worker likewise remains independent until its cooperative stop.
        worker=ImageBatchWorker(('volume',token,generation),unique,source=self.current_source); self.volume_thumb_worker=worker
        # Keep image decoding and all QWidget mutation on the dialog's GUI thread.
        worker.image_ready.connect(self._on_volume_thumb_ready)
        worker.image_failed.connect(self._on_volume_thumb_failed)
        worker.batch_done.connect(self._on_volume_thumb_batch_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_volume_thumb_ready(self, data):
        batch_id=data.get('batch_id') or ()
        _kind, token, generation=(batch_id + (None,None,None))[:3] if isinstance(batch_id,tuple) else (None,None,None)
        if self._closing or generation != self._cover_generation or token != self._volume_cover_batch_token:
            return
        url=data.get('key'); raw=data.get('raw')
        if not url or not raw: return
        self._image_cache[url]=raw
        for i in range(self.volume_list.count()):
            item=self.volume_list.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if isinstance(info,dict) and info.get('cover_url')==url:
                pix=self._pix_from_bytes(raw,42,58)
                row=self.volume_list.itemWidget(item)
                if isinstance(row, VolumeRowWidget): row.set_cover(pix)
        if url==self._selected_cover_url:
            big=self._pix_from_bytes(raw,130,180)
            if big is not None: self.selected_cover.setPixmap(big)
            else: self.selected_cover.set_failed()

    def _on_volume_thumb_failed(self, data):
        batch_id=data.get('batch_id') or ()
        _kind, token, generation=(batch_id + (None,None,None))[:3] if isinstance(batch_id,tuple) else (None,None,None)
        if self._closing or generation != self._cover_generation or token != self._volume_cover_batch_token:
            return
        url=data.get('key')
        if not url:
            return
        self._failed_image_urls.add(url)
        for i in range(self.volume_list.count()):
            item=self.volume_list.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if isinstance(info,dict) and info.get('cover_url') == url:
                row=self.volume_list.itemWidget(item)
                if isinstance(row,VolumeRowWidget):
                    row.set_cover(None)
        if url == self._selected_cover_url:
            self.selected_cover.set_failed()

    def _on_volume_thumb_batch_done(self, data):
        self.volume_thumb_worker=None
        if not self._closing:
            QTimer.singleShot(0,self._load_visible_volume_thumbs)

    def _layout_mode_changed(self, *args):
        enabled = self.page_layout.currentData() == 'paired_landscape'
        self.reading_direction.setEnabled(enabled)
        if hasattr(self, 'reading_direction_label'):
            self.reading_direction_label.setEnabled(enabled)
        if hasattr(self, 'portrait_btn'):
            self.portrait_btn.blockSignals(True); self.landscape_btn.blockSignals(True)
            self.portrait_btn.setChecked(not enabled); self.landscape_btn.setChecked(enabled)
            self.portrait_btn.blockSignals(False); self.landscape_btn.blockSignals(False)
        if hasattr(self, 'pairing_preview_btn'):
            self.pairing_preview_btn.setVisible(enabled)
            self.pairing_preview_btn.setText('Pairing Preview')
            self.pairing_preview_btn.setEnabled(enabled and bool(self.preview_data) and self.preview_signature == self.current_signature())
        if not enabled and self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_worker.cancel()
        self.invalidate_preview()

    def _invalidate_inflight_preview(self):
        if self._preview_build_signature is not None:
            self._preview_request_id += 1
            self._review_cancel_requested=True
            self._preview_build_signature = None
            for worker in list(self._preview_workers):
                if worker.isRunning():
                    worker.requestInterruption()
            # The obsolete worker no longer owns the Preview button. Allow the
            # user to immediately build a new preview for the current selection.
            if hasattr(self, 'preview_btn'):
                self._update_preview_button_for_volume_selection()

    def current_signature(self):
        return (
            self.workflow_mode, self.current_source_id, self.current_manga_url, self.title.text().strip(), self.author.text().strip(), self.series.text().strip(),
            self.language.currentData(), self.start.text().strip(), self.end.text().strip(), tuple(sorted(self._selected_volumes)), bool(self._standalone_selected), bool(self._using_entire_series),
            tuple(sorted(self._selected_chapter_ids)),
            self.covers.isChecked(), self.pad.isChecked(), self.page_layout.currentData(), self.reading_direction.currentData()
        )

    def _clear_preview_state(self, summary=None, keep_rows=False):
        self.preview_signature = None
        self.preview_data = None
        self.download_btn.setEnabled(False)
        if hasattr(self, 'pairing_preview_btn'):
            self.pairing_preview_btn.setEnabled(False)
        if hasattr(self, 'preview_table') and not keep_rows:
            self.preview_table.blockSignals(True)
            self.preview_table.setRowCount(0)
            self.preview_table.blockSignals(False)
            self.preview_table.setVisible(True)
        if summary is not None and hasattr(self, 'preview_summary'):
            self.preview_summary.setText(summary)

    def _schedule_silent_preview_refresh(self, delay=None):
        self._pending_auto_preview=True
        if not hasattr(self,'_preview_refresh_timer'):
            return
        self._preview_refresh_timer.start(int(self._auto_preview_delay_ms if delay is None else delay))

    def _run_silent_preview_refresh(self):
        if not self._pending_auto_preview:
            return
        if self._volume_plan_loading or not self.loaded_metadata or not self._download_language_valid:
            return
        if not self._has_volume_selection() or self._manual_range_invalid:
            self._pending_auto_preview=False
            self._clear_preview_state('', keep_rows=False)
            self._update_preview_button_for_volume_selection()
            return
        self._pending_auto_preview=False
        self.continue_preview(silent=True)

    def invalidate_preview(self, *args):
        current=self.current_signature()
        had_preview=bool(self.preview_data is not None or self.preview_signature is not None or self._preview_build_signature is not None)
        if self._preview_build_signature is not None and current != self._preview_build_signature:
            self._invalidate_inflight_preview()
        if not self._has_volume_selection() or self._manual_range_invalid:
            self._pending_auto_preview=False
            if hasattr(self,'_preview_refresh_timer'):
                self._preview_refresh_timer.stop()
            if had_preview:
                self._clear_preview_state('', keep_rows=False)
            self.download_btn.setEnabled(False)
            self._update_preview_button_for_volume_selection()
            return
        if self.preview_signature is not None and current != self.preview_signature:
            # Keep the existing rows visible while a replacement preview is built.
            # Downloading stays disabled until the replacement signature is current.
            self.download_btn.setEnabled(False)
            if hasattr(self,'pairing_preview_btn'):
                self.pairing_preview_btn.setEnabled(False)
            self._schedule_silent_preview_refresh()
        elif had_preview and self._preview_build_signature is None and self.preview_signature is None:
            self._schedule_silent_preview_refresh()
        self._update_preview_button_for_volume_selection()

    def add_log(self, text):
        if text:
            # Keep the activity history readable. Silent review refreshes can
            # otherwise emit the same state line several times in a row.
            if self.log.count() and self.log.item(self.log.count()-1).text() == text:
                return
            item = QListWidgetItem(text)
            key = text.casefold()
            if any(token in key for token in ('selected ', 'review ready', 'download complete', 'loaded mangadex metadata', 'using entire series', 'volume range set')):
                try:
                    from qt.core import QColor
                    item.setForeground(QColor(ORANGE))
                except Exception:
                    pass
            self.log.addItem(item)
            self.log.scrollToBottom()
            if any(token in key for token in ('failed', 'error:', 'unavailable', 'could not')):
                self._toggle_activity_log(True)

    def _toggle_activity_log(self, expanded=None):
        if expanded is None:
            expanded = not bool(getattr(self, '_activity_log_expanded', False))
        self._activity_log_expanded = bool(expanded)
        if hasattr(self, 'log'):
            self.log.setVisible(self._activity_log_expanded)
        if hasattr(self, 'log_toggle_btn'):
            self.log_toggle_btn.setText('Activity Log  ▾' if self._activity_log_expanded else 'Activity Log  ▸')

    def copy_log(self):
        lines = [self.log.item(i).text() for i in range(self.log.count())]
        QApplication.clipboard().setText('\n'.join(lines))
        self.progress_text.setText('Activity log copied to clipboard.')

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save MangaNana Activity Log', 'MangaNana-activity.txt', 'Text files (*.txt);;All files (*)')
        if not path:
            return
        try:
            lines = [self.log.item(i).text() for i in range(self.log.count())]
            Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
            self.progress_text.setText('Activity log saved.')
        except Exception as e:
            error_dialog(self, 'Save Log failed', str(e), show=True)

    def show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle('About MangaNana')
        box.setWindowIcon(self.icon)
        box.setIconPixmap(self.icon.pixmap(64, 64))
        box.setText(f'<b>{DISPLAY_VERSION} for Calibre</b>')
        box.setInformativeText(
            'Cross-platform manga downloader and Calibre importer.\n\n'
            f'Development commit: {GIT_COMMIT}\n'
            'Supported platforms: Windows, macOS, Linux\n'
            'Minimum Calibre version: 7.0\n'
            'Downloader: pure Python source adapters\n\n'
            'Interface localization support is prepared for future translations.'
        )
        box.exec()

    def open_preferences(self):
        current_download=self.language.currentData()
        d = PreferencesDialog(self)
        if d.exec() == QDialog.DialogCode.Accepted:
            available = (self.loaded_metadata or {}).get('available_languages') if self.loaded_metadata else None
            preferred_download=current_download if current_download else '__keep_unselected__'
            populate_download_languages(self.language, available=available, preferred=preferred_download)
            self.covers.setChecked(bool(prefs['include_volume_covers']))
            self.pad.setChecked(bool(prefs['zero_pad']))
            pli=self.page_layout.findData(prefs['page_layout']); self.page_layout.setCurrentIndex(max(0, pli))
            rdi=self.reading_direction.findData(prefs['reading_direction']); self.reading_direction.setCurrentIndex(max(0, rdi))
            self._layout_mode_changed()
            if self.loaded_metadata and self.language.currentData() != current_download:
                self._download_language_changed()
            self.add_log('Preferences updated.')

    def open_manga_sources(self):
        dialog = MangaSourcesDialog(SOURCE_REGISTRY, prefs, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            names = [
                source.display_name for source in enabled_sources(SOURCE_REGISTRY, prefs)
            ]
            summary = ', '.join(names) if names else 'none'
            self.add_log(f'General-search sources updated: {summary}.')

    def choose_alternate_title(self):
        md = self.loaded_metadata or {}
        rows = md.get('titles') or []
        if not rows:
            info_dialog(self, 'Alternate Titles', 'Load manga metadata first.', show=True)
            return
        d = QDialog(self)
        d.setWindowTitle('MangaNana - Alternate Titles')
        d.setWindowIcon(self.icon)
        d.resize(620, 420)
        root = QVBoxLayout(d)
        note = QLabel('Choose how this manga title is displayed in MangaNana and Calibre. This does not change the chapter download language.')
        note.setWordWrap(True); root.addWidget(note)
        lst = QListWidget(); lst.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel); lst.verticalScrollBar().setSingleStep(18); root.addWidget(lst, 1)
        preferred=prefs['language']
        rows=sorted(rows, key=lambda r: (0 if r.get('language')==preferred else 1 if r.get('language')=='en' else 2, 0 if r.get('primary') else 1, language_label(r.get('language')).casefold(), r.get('title','').casefold()))
        for row in rows:
            prefix = language_label(row.get('language'))
            kind = 'Primary' if row.get('primary') else 'Alternate'
            item_text = f"{prefix}  |  {kind}  |  {row.get('title', '')}"
            from qt.core import QListWidgetItem
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, row.get('title', ''))
            lst.addItem(item)
            if row.get('title') == self.title.text().strip():
                lst.setCurrentItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(d.accept); buttons.rejected.connect(d.reject)
        root.addWidget(buttons)
        lst.itemDoubleClicked.connect(lambda _item: d.accept())
        if d.exec() == QDialog.DialogCode.Accepted and lst.currentItem():
            title = str(lst.currentItem().data(Qt.ItemDataRole.UserRole) or '').strip()
            if title:
                self.title.setText(title)
                self.series.setText(title)
                self.selected_title.setText(title)
                self.add_log(f'Selected alternate title: {title}')

    def _style_volume_item(self, item):
        if item is None:
            return
        row=self.volume_list.itemWidget(item) if hasattr(self,'volume_list') else None
        if isinstance(row, VolumeRowWidget):
            info=item.data(Qt.ItemDataRole.UserRole) or {}
            if isinstance(info,dict) and info.get('kind') == 'chapter':
                row.set_checked(str(info.get('chapter_id') or '') in self._selected_chapter_ids)
                return
            if isinstance(info,dict) and info.get('kind') == 'standalone':
                row.set_checked(bool(self._standalone_selected))
                return
            value=float(info.get('volume')) if isinstance(info,dict) and info.get('volume') is not None else None
            row.set_checked(value in self._selected_volumes if value is not None else False)

    def _checked_volume_values(self):
        return sorted(set(float(v) for v in self._selected_volumes))

    def _available_volume_values(self):
        if self._current_plan is None:
            return []
        ans=[]
        for value in (self._current_plan.get('volumes') or []):
            try:
                ans.append(float(value))
            except Exception:
                pass
        return sorted(set(ans))

    def _set_action_role(self, button, role):
        if button.objectName() == role:
            return
        button.setObjectName(role)
        try:
            button.style().unpolish(button); button.style().polish(button); button.update()
        except Exception:
            pass

    def _update_workflow_actions(self):
        if not hasattr(self, 'preview_btn') or not hasattr(self, 'download_btn'):
            return
        has_selection = bool(self._has_volume_selection() and not self._manual_range_invalid and self._download_language_valid and not self._volume_plan_loading)
        active_build = self._preview_build_signature is not None and self._preview_build_signature == self.current_signature()
        review_current = bool(self.preview_data and self.preview_signature == self.current_signature())
        selected_downloads = int((self.preview_data or {}).get('selected_download_count', 0) or 0) if review_current else 0
        if not has_selection:
            self.preview_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self._set_action_role(self.preview_btn, 'secondaryAction')
            self._set_action_role(self.download_btn, 'tertiaryAction')
            if hasattr(self, 'workflow_hint'):
                self.workflow_hint.setText('Select at least one volume to continue.')
            return
        if active_build:
            self.preview_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self._set_action_role(self.preview_btn, 'primaryAction')
            self._set_action_role(self.download_btn, 'tertiaryAction')
            if hasattr(self, 'workflow_hint'):
                self.workflow_hint.setText('Building review…')
            return
        if review_current:
            self.preview_btn.setEnabled(True)
            self.download_btn.setEnabled(selected_downloads > 0)
            self._set_action_role(self.preview_btn, 'secondaryAction')
            self._set_action_role(self.download_btn, 'primaryAction' if selected_downloads > 0 else 'tertiaryAction')
            if hasattr(self, 'workflow_hint'):
                self.workflow_hint.setText('Review complete. Ready to download and add to Calibre.' if selected_downloads > 0 else 'Review complete. Nothing is selected for download.')
        else:
            self.preview_btn.setEnabled(True)
            self.download_btn.setEnabled(False)
            self._set_action_role(self.preview_btn, 'primaryAction')
            self._set_action_role(self.download_btn, 'tertiaryAction')
            if hasattr(self, 'workflow_hint'):
                count=len(self._selected_volumes) + (1 if self._standalone_selected else 0)
                noun='selection' if count == 1 else 'selections'
                self.workflow_hint.setText(f'{count} {noun} selected. Review to continue.')

    def _has_volume_selection(self):
        if self.workflow_mode == 'chapter':
            return bool(self._selected_chapter_ids)
        return bool(self._using_entire_series or self._selected_volumes or self._standalone_selected)

    def _update_preview_button_for_volume_selection(self):
        self._update_workflow_actions()

    def _manual_range_selection(self):
        s_txt=self.start.text().strip() if hasattr(self,'start') else ''
        e_txt=self.end.text().strip() if hasattr(self,'end') else ''
        if not s_txt and not e_txt:
            return 'empty', set(), ''
        try:
            s_val=float(s_txt) if s_txt else None
            e_val=float(e_txt) if e_txt else None
        except Exception:
            return 'invalid', set(), 'Start and End must be valid volume numbers.'
        if s_val is not None and e_val is not None and e_val < s_val:
            return 'invalid', set(), 'End volume must be greater than or equal to Start volume.'
        available=self._available_volume_values()
        if not available:
            return 'pending', set(), ''
        matching={v for v in available if (s_val is None or v >= s_val) and (e_val is None or v <= e_val)}
        if not matching:
            return 'invalid', set(), 'The entered range does not contain any available volumes.'
        return 'valid', matching, ''

    def _volume_row_toggled(self, item, checked):
        if self._volume_check_syncing or item is None:
            return
        info=item.data(Qt.ItemDataRole.UserRole) or {}
        if not isinstance(info,dict):
            return
        previous=set(self._selected_volumes); previous_chapters=set(self._selected_chapter_ids)
        previous_standalone=bool(self._standalone_selected)
        self._using_entire_series=False
        self._manual_range_invalid=False
        self._manual_range_error=''
        self._last_invalid_range_log_key=None
        if info.get('kind') == 'chapter':
            chapter_id=str(info.get('chapter_id') or '')
            if checked: self._selected_chapter_ids.add(chapter_id)
            else: self._selected_chapter_ids.discard(chapter_id)
        elif info.get('kind') == 'standalone':
            self._standalone_selected=bool(checked)
        elif info.get('volume') is not None:
            value=float(info.get('volume'))
            if checked:
                self._selected_volumes.add(value)
            else:
                self._selected_volumes.discard(value)
        else:
            return
        self._style_volume_item(item)
        # Exact row selection is canonical. Clear any manual range without letting
        # those text-change signals erase the row selections we just made.
        if self.start.text().strip() or self.end.text().strip():
            self._range_syncing=True
            try:
                self.start.clear(); self.end.clear()
            finally:
                self._range_syncing=False
        if previous != self._selected_volumes or previous_chapters != self._selected_chapter_ids or previous_standalone != self._standalone_selected:
            self._selected_volume=None
            self._update_volume_selection_hint()
            self._update_preview_button_for_volume_selection()
            self.invalidate_preview()
            labels=[f'{v:g}' for v in sorted(self._selected_volumes)]
            if self._standalone_selected:
                labels.append('Standalone Chapters')
            if self.workflow_mode == 'chapter':
                self.add_log(f'{len(self._selected_chapter_ids)} chapter' + ('' if len(self._selected_chapter_ids) == 1 else 's') + ' selected.' if self._selected_chapter_ids else 'No chapters selected.')
            else:
                self.add_log('Selected: '+', '.join(labels) if labels else 'No volumes selected.')

    def _volume_item_changed(self, item):
        return

    def _update_volume_selection_hint(self):
        if self.workflow_mode == 'chapter':
            count=len(self._selected_chapter_ids)
            total=len(self._chapter_plan_items or ())
            self.range_hint.setText(f'{count} chapter' + ('' if count==1 else 's') + f' selected of {total}.' if count else 'Select one or more chapters to continue.')
            self.range_hint.setStyleSheet(f'color:{ORANGE}; font-size:11px; font-weight:600;' if count else 'color:#8F9499; font-size:11px;')
            if hasattr(self, 'clear_volume_btn'):
                self.clear_volume_btn.setEnabled(bool(total) and bool(self._download_language_valid))
                self.clear_volume_btn.setText('Deselect All Chapters' if count else 'Select All Chapters')
            return
        s=self.start.text().strip() if hasattr(self,'start') else ''
        e=self.end.text().strip() if hasattr(self,'end') else ''
        selected_count=len(self._selected_volumes) + (1 if self._standalone_selected else 0)
        if self._using_entire_series and selected_count:
            numeric=len(self._selected_volumes)
            extra=' plus Standalone Chapters' if self._standalone_selected else ''
            self.range_hint.setText(f'Entire series selected: {numeric} volume' + ('' if numeric==1 else 's') + extra + '.')
            self.range_hint.setStyleSheet(f'color:{ORANGE}; font-size:11px; font-weight:600;')
        elif s or e:
            if self._manual_range_invalid:
                self.range_hint.setText('Volume range is not valid.')
                self.range_hint.setStyleSheet(f'color:{ORANGE}; font-size:11px; font-weight:600;')
            elif self._selected_volumes:
                count=len(self._selected_volumes)
                if s and e and s==e:
                    self.range_hint.setText(f'Volume {s} selected by range')
                else:
                    self.range_hint.setText(f'Volume range: {s or "start"} to {e or "end"} ({count} selected)')
                self.range_hint.setStyleSheet(f'color:{ORANGE}; font-size:11px; font-weight:600;')
            else:
                self.range_hint.setText('Checking volume range...')
                self.range_hint.setStyleSheet('color:#8F9499; font-size:11px;')
        elif selected_count:
            values=sorted(self._selected_volumes)
            shown=', '.join(f'{v:g}' for v in values[:8])
            if len(values) > 8:
                shown += f' +{len(values)-8} more'
            if self._standalone_selected:
                shown = (shown + ', ' if shown else '') + 'Standalone Chapters'
            self.range_hint.setText(f'{selected_count} selection' + ('' if selected_count==1 else 's') + f': {shown}')
            self.range_hint.setStyleSheet(f'color:{ORANGE}; font-size:11px; font-weight:600;')
        else:
            if 'volumes' not in self.current_source.capabilities:
                self.range_hint.setText('Select Standalone Chapters, or use Use Entire Series.')
            else:
                self.range_hint.setText('Select volumes from the list, or use the optional range shortcut above.')
            self.range_hint.setStyleSheet('color:#8F9499; font-size:11px;')
        if hasattr(self,'clear_volume_btn'):
            plan=self._current_plan or {}
            has_available=bool(self._available_volume_values() or int(plan.get('bonus_chapters') or 0)) and bool(self._download_language_valid)
            has_selection=bool(selected_count)
            self.clear_volume_btn.setEnabled(has_available)
            self.clear_volume_btn.setText('Deselect All' if has_selection else 'Use Entire Series')

    def _range_inputs_changed(self, *args):
        if self._range_syncing:
            self._update_volume_selection_hint()
            return
        previous=set(self._selected_volumes)
        previous_standalone=bool(self._standalone_selected)
        previous_entire=bool(self._using_entire_series)
        state, matching, error=self._manual_range_selection()
        self._using_entire_series=False
        self._manual_range_invalid=(state=='invalid')
        self._manual_range_error=error if state=='invalid' else ''
        # Manual range is explicitly for numbered volumes, so using it clears
        # a Standalone Chapters selection.
        self._standalone_selected=False
        if state=='valid':
            self._selected_volumes=set(matching)
            self._last_invalid_range_log_key=None
        elif state in ('empty','invalid'):
            self._selected_volumes.clear()
            if state=='empty':
                self._last_invalid_range_log_key=None
        self._volume_check_syncing=True
        try:
            for i in range(self.volume_list.count()):
                self._style_volume_item(self.volume_list.item(i))
        finally:
            self._volume_check_syncing=False
        self._selected_volume=None
        self._update_volume_selection_hint()
        self._update_preview_button_for_volume_selection()
        if previous != self._selected_volumes or previous_standalone != self._standalone_selected or previous_entire:
            self.invalidate_preview()
        elif self.preview_signature is not None and self.current_signature() != self.preview_signature:
            self.invalidate_preview()

    def _log_invalid_manual_range(self):
        if not self._manual_range_invalid:
            return
        key=(self.start.text().strip(), self.end.text().strip(), self._manual_range_error)
        if key == self._last_invalid_range_log_key:
            return
        self._last_invalid_range_log_key=key
        detail=self._manual_range_error or 'The entered volume range is not valid.'
        self.add_log('Volume range not valid: '+detail)

    def _deselect_all_volumes(self):
        had_selection=bool(self._selected_volumes or self._standalone_selected or self._using_entire_series or self.start.text().strip() or self.end.text().strip())
        self._range_syncing=True; self._volume_check_syncing=True
        try:
            self._selected_volume=None
            self._selected_volumes.clear()
            self._standalone_selected=False
            self._using_entire_series=False
            self._manual_range_invalid=False
            self._manual_range_error=''
            self._last_invalid_range_log_key=None
            self.start.clear(); self.end.clear(); self.volume_list.clearSelection()
            for i in range(self.volume_list.count()):
                self._style_volume_item(self.volume_list.item(i))
        finally:
            self._volume_check_syncing=False; self._range_syncing=False
        self._update_volume_selection_hint()
        self._update_preview_button_for_volume_selection()
        if had_selection or self.preview_signature is not None:
            self.invalidate_preview()
        if had_selection:
            self.add_log('All volumes deselected.')

    def _use_entire_series(self):
        # The footer button is state-aware: once anything is selected it becomes
        # a single, obvious way to clear the current volume selection.
        if self.workflow_mode == 'chapter':
            if self._selected_chapter_ids:
                self._selected_chapter_ids.clear()
                self._rebuild_volume_list(); self.invalidate_preview(); self.add_log('All chapters deselected.')
            else:
                self._selected_chapter_ids=chapter_selection_ids(self._chapter_plan_items)
                self._rebuild_volume_list(); self.invalidate_preview(); self.add_log(f'All {len(self._selected_chapter_ids)} chapters selected.')
            return
        if self._selected_volumes or self._standalone_selected:
            self._deselect_all_volumes()
            return
        available=self._available_volume_values()
        standalone_available=bool(int((self._current_plan or {}).get('bonus_chapters') or 0))
        if not available and not standalone_available:
            self.add_log('Entire series could not be selected because no downloadable content is available.')
            return
        previous=set(self._selected_volumes)
        previous_standalone=bool(self._standalone_selected)
        previous_entire=bool(self._using_entire_series)
        self._range_syncing=True; self._volume_check_syncing=True
        try:
            self._selected_volume=None
            self._selected_volumes=set(available)
            self._standalone_selected=standalone_available
            self._using_entire_series=True
            self._manual_range_invalid=False
            self._manual_range_error=''
            self._last_invalid_range_log_key=None
            self.start.clear(); self.end.clear(); self.volume_list.clearSelection()
            for i in range(self.volume_list.count()):
                self._style_volume_item(self.volume_list.item(i))
        finally:
            self._volume_check_syncing=False; self._range_syncing=False
        self._update_volume_selection_hint()
        self._update_preview_button_for_volume_selection()
        if previous != self._selected_volumes or previous_standalone != self._standalone_selected or not previous_entire:
            self.invalidate_preview()
        numeric=len(available)
        extra=' plus Standalone Chapters' if standalone_available else ''
        self.add_log(f'Entire series selected: {numeric} volume' + ('' if numeric==1 else 's') + extra + '.')

    def _install_range_focus_behavior(self):
        """Make the manual volume-range fields behave like transient form inputs.

        A click anywhere outside Start/End commits the current text and releases
        the text cursor. Enter also commits. Escape restores the value that was
        present when the active field received focus.
        """
        try:
            app=QApplication.instance()
            if app is not None and not self._range_event_filter_installed:
                app.installEventFilter(self)
                self._range_event_filter_installed=True
        except Exception:
            pass

    def _range_widget_or_child(self, watched):
        obj=watched
        while obj is not None:
            if obj is self.start or obj is self.end:
                return True
            try:
                obj=obj.parent()
            except Exception:
                break
        return False

    def _commit_range_edit(self):
        active=self.start if self.start.hasFocus() else self.end if self.end.hasFocus() else None
        if active is not None:
            active.clearFocus()
        self._range_inputs_changed()
        self._log_invalid_manual_range()

    def eventFilter(self, watched, event):
        try:
            et=event.type()
            if et == QEvent.Type.FocusIn and (watched is self.start or watched is self.end):
                self._range_edit_snapshot=(self.start.text(), self.end.text())
            elif et == QEvent.Type.KeyPress and (watched is self.start or watched is self.end):
                key=event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._commit_range_edit()
                    return True
                if key == Qt.Key.Key_Escape:
                    start_text,end_text=self._range_edit_snapshot
                    self._range_syncing=True
                    try:
                        self.start.setText(start_text); self.end.setText(end_text)
                    finally:
                        self._range_syncing=False
                    self._range_inputs_changed()
                    watched.clearFocus()
                    return True
            elif et == QEvent.Type.MouseButtonPress:
                if (self.start.hasFocus() or self.end.hasFocus()) and not self._range_widget_or_child(watched):
                    self._commit_range_edit()
        except Exception:
            pass
        return super().eventFilter(watched, event)

    def _restore_session(self):
        try:
            # Start discovery clean. Search text and pasted URLs are intentionally
            # not restored because stale values make the two entry workflows confusing.
            self.search_box.clear(); self.url.clear()
            mode=str(prefs.get('session_layout','') or '')
            if mode: self._choose_layout(mode)
            self.start.clear(); self.end.clear()
        except Exception:
            pass

    def _save_session(self):
        try:
            prefs['session_search']=''; prefs['session_url']=''; prefs['session_layout']=self.page_layout.currentData()
            prefs['include_volume_covers']=self.covers.isChecked(); prefs['zero_pad']=self.pad.isChecked(); prefs['reading_direction']=self.reading_direction.currentData()
            prefs['window_w']=self.width(); prefs['window_h']=self.height(); prefs.commit()
        except Exception:
            pass

    def _remove_range_focus_behavior(self):
        try:
            app=QApplication.instance()
            if app is not None and self._range_event_filter_installed:
                app.removeEventFilter(self)
        except Exception:
            pass
        self._range_event_filter_installed=False

    def closeEvent(self, event):
        self._closing=True
        for worker in self.search_workers.values():
            if worker.isRunning(): worker.requestInterruption()
        if self._search_resolution_worker and self._search_resolution_worker.isRunning():
            self._search_resolution_worker.requestInterruption()
        if hasattr(self,'_search_status_timer'): self._search_status_timer.stop()
        self._invalidate_inflight_preview()
        self._invalidate_cover_requests()
        if hasattr(self, '_cover_pulse_timer'): self._cover_pulse_timer.stop()
        self._restore_diagnostic_hook()
        self._remove_range_focus_behavior()
        self._save_session(); super().closeEvent(event)

    def reject(self):
        self._closing=True
        for worker in self.search_workers.values():
            if worker.isRunning(): worker.requestInterruption()
        if self._search_resolution_worker and self._search_resolution_worker.isRunning():
            self._search_resolution_worker.requestInterruption()
        if hasattr(self,'_search_status_timer'): self._search_status_timer.stop()
        self._invalidate_inflight_preview()
        self._invalidate_cover_requests()
        if hasattr(self, '_cover_pulse_timer'): self._cover_pulse_timer.stop()
        self._restore_diagnostic_hook()
        self._remove_range_focus_behavior()
        self._save_session(); super().reject()

    def parse_range(self):
        def p(x):
            x = x.text().strip()
            return float(x) if x else None
        s, e = p(self.start), p(self.end)
        if s is not None and e is not None and e < s:
            raise ValueError('End volume must be greater than or equal to Start volume.')
        return s, e

    def validate_details(self):
        url = self.current_manga_url.strip(); title = self.title.text().strip(); author = self.author.text().strip(); series = self.series.text().strip()
        if not self.current_source or self.current_source.parse_manga_ref(url) is None: raise ValueError('Enter a valid supported manga link.')
        if not title or not series: raise ValueError('Load a manga title first.')
        if not self.language.currentData(): raise ValueError('Choose an available Download Language before continuing.')
        if self._volume_plan_loading: raise ValueError('MangaNana is still checking chapters for the selected Download Language.')
        if not self._download_language_valid: raise ValueError(f'No downloadable chapters are available in {self.language.currentText()}. Choose another Download Language.')
        if self.workflow_mode not in ('volume','chapter'):
            raise ValueError('Choose Volumes or Chapters before continuing.')
        if self.workflow_mode == 'chapter':
            if not self._selected_chapter_ids:
                raise ValueError('Select at least one chapter or use Select All Chapters.')
            return url, title, author, series, None, None
        if self._manual_range_invalid:
            raise ValueError(self._manual_range_error or 'Volume range is not valid.')
        s, e = self.parse_range()
        if not self._has_volume_selection():
            raise ValueError('Select at least one available item, enter a valid volume range, or use Use Entire Series.')
        if self._current_plan is not None:
            vols=[float(v) for v in (self._current_plan.get('volumes') or [])]
            if self._selected_volumes:
                missing=sorted(v for v in self._selected_volumes if v not in set(vols))
                if missing:
                    raise ValueError('One or more checked volumes are no longer available for this language.')
            elif s is not None or e is not None:
                matching=[v for v in vols if (s is None or v >= s) and (e is None or v <= e)]
                if not matching:
                    raise ValueError('No downloadable volumes are available in the selected Volume Range for this language.')
        return url, title, author, series, s, e

    def existing_volumes(self, series):
        ans = set()
        try:
            for book_id in self.db.all_book_ids():
                s = self.db.field_for('series', book_id)
                if s and str(s).casefold() == series.casefold():
                    idx = self.db.field_for('series_index', book_id)
                    try:
                        if idx is not None: ans.add(float(idx))
                    except Exception: pass
        except Exception:
            pass
        return ans

    def existing_volume_ids(self, series):
        ans = {}
        try:
            for book_id in self.db.all_book_ids():
                s = self.db.field_for('series', book_id)
                if s and str(s).casefold() == series.casefold():
                    idx = self.db.field_for('series_index', book_id)
                    try:
                        if idx is not None: ans[float(idx)] = book_id
                    except Exception:
                        pass
        except Exception:
            pass
        return ans

    def effective_existing_for_policy(self, series):
        existing = self.existing_volumes(series)
        policy = prefs['duplicate_policy']
        if policy == 'replace':
            return set()
        if policy == 'ask' and existing:
            box = QMessageBox(self)
            box.setWindowTitle('Existing MangaNana volumes found')
            box.setWindowIcon(self.icon)
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(f'{len(existing)} existing volume(s) were found for this series.')
            box.setInformativeText('Skip them to protect your current Calibre books, or include them so their CBZ files can be replaced after download?')
            skip = box.addButton('Skip Existing', QMessageBox.ButtonRole.AcceptRole)
            replace = box.addButton('Include for Replacement', QMessageBox.ButtonRole.DestructiveRole)
            box.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is replace:
                self._session_replace_existing = True
                return set()
            if box.clickedButton() is skip:
                self._session_replace_existing = False
                return existing
            raise RuntimeError('Preview cancelled.')
        self._session_replace_existing = False
        return existing

    def continue_preview(self, silent=False):
        # QPushButton.clicked may pass a bool; a button click is never a silent refresh.
        if isinstance(silent, bool) is False:
            silent=False
        try:
            url, title, author, series, s, e = self.validate_details()
            exact=sorted(self._selected_volumes)
            fetch_s, fetch_e = s, e
            if exact and not self._using_entire_series:
                fetch_s, fetch_e = min(exact), max(exact)
            elif self._using_entire_series:
                fetch_s, fetch_e = None, None
            if silent:
                policy=prefs['duplicate_policy']
                existing=set() if policy=='replace' else self.existing_volumes(series)
            else:
                existing = self.effective_existing_for_policy(series)
            self.preview_panel.show()
            if self.width() < 1280:
                self.resize(1320, max(self.height(), 700))
            if not silent:
                self.work_progress_widget.setVisible(True)
                self.preview_table.setRowCount(0)
                self.preview_summary.setText(f'Loading {self.current_source.display_name} chapter information and checking your Calibre library...')
                self.progress.setDeterminateValue(0)
                self.progress_text.setText('Preparing Review...')
                self.add_log('Preparing Review...')
            self.preview_table.setVisible(True)
            self.preview_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self._preview_request_id += 1
            self._review_cancel_requested=False
            request_id=self._preview_request_id
            build_signature=self.current_signature()
            self._preview_build_signature=build_signature
            worker = PreviewWorker(self.current_source, url, title, author, series, self.language.currentData(), fetch_s, fetch_e,
                                   self.pad.isChecked(), existing, selected_volumes=None if self._using_entire_series else exact,
                                   include_standalone=bool(self._standalone_selected or self._using_entire_series),
                                   bytes_per_page=self._bytes_per_page_estimate,
                                   planned_chapters=self._chapter_plan_items if self.workflow_mode == 'chapter' else None,
                                   chapter_items=self._selected_chapter_ids if self.workflow_mode == 'chapter' else None)
            self.preview_worker = worker
            self._preview_workers.append(worker)
            worker.ready.connect(lambda d,rid=request_id,sig=build_signature: self.on_preview_ready(d,rid,sig))
            worker.failed.connect(lambda m,rid=request_id,sig=build_signature: self.on_preview_failed(m,rid,sig))
            worker.cancelled_ok.connect(lambda rid=request_id,sig=build_signature: self.on_preview_cancelled(rid,sig))
            worker.progress.connect(lambda p,t,rid=request_id,sig=build_signature:self.on_review_progress(p,t,rid,sig))
            worker.finished.connect(lambda w=worker:self._cleanup_worker(w,self._preview_workers))
            worker.finished.connect(lambda w=worker,rid=request_id,sig=build_signature:self._on_preview_worker_finished(w,rid,sig))
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except Exception as e:
            error_dialog(self, 'MangaNana', str(e), show=True)

    def on_review_progress(self, percent, text, request_id, build_signature):
        if self._review_cancel_requested or request_id != self._preview_request_id or build_signature != self.current_signature():
            return
        self.progress.setDeterminateValue(percent)
        self.progress_text.setText(text)

    def on_preview_ready(self, data, request_id=None, build_signature=None):
        if self._review_cancel_requested:
            return
        if request_id is not None and request_id != self._preview_request_id:
            return
        if build_signature is not None and build_signature != self.current_signature():
            return
        self._preview_build_signature = None
        self.progress.setDeterminateValue(100)
        self.cancel_btn.setEnabled(False)
        self._pending_auto_preview = False
        self.preview_data = data
        self.preview_signature = build_signature if build_signature is not None else self.current_signature()
        rows = data.get('rows') or []
        self.preview_table.blockSignals(True)
        self.preview_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            # Column 0 uses only the custom round selector. Keep a plain backing item
            # for row metadata, but never assign a Qt check state or Qt will also draw
            # the platform's square checkbox underneath the custom control.
            include = QTableWidgetItem('')
            include.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            include.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            include.setData(Qt.ItemDataRole.UserRole, item.get('volume'))
            self.preview_table.setItem(r, 0, include)
            item['selected'] = bool(not item['existing'])
            selector = PreviewUseSelector(checked=item['selected'], enabled=not item['existing'])
            selector.changed.connect(lambda checked, rr=r: self._preview_use_toggled(rr, checked))
            selector_host = QWidget()
            selector_layout = QHBoxLayout(selector_host); selector_layout.setContentsMargins(6,0,6,0); selector_layout.setSpacing(0)
            selector_layout.addStretch(1); selector_layout.addWidget(selector); selector_layout.addStretch(1)
            self.preview_table.setCellWidget(r, 0, selector_host)
            volume_label = item.get('volume_text') or ('Bonus' if item.get('volume') is None else f"Vol. {float(item['volume']):g}")
            if volume_label and not str(volume_label).lower().startswith(('vol', 'ch.', 'bonus', 'standalone')):
                volume_label = 'Vol. ' + str(volume_label)
            status_text = 'In Calibre' if item.get('existing') else ('Ready' if str(item.get('status') or '').lower() in ('will download','ready') else str(item.get('status') or 'Ready'))
            page_value=item.get('pages')
            source_label=item.get('source_name') or self.current_source.display_name
            vals = [volume_label, item['title'], source_label, format_page_count(page_value), status_text]
            for c, val in enumerate(vals, 1):
                cell=QTableWidgetItem(str(val)); cell.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                self.preview_table.setItem(r, c, cell)
        self.preview_table.blockSignals(False)
        self.preview_table.setVisible(True)
        self.refresh_preview_selection_summary()
        self._update_preview_button_for_volume_selection()
        can_download = int(self.preview_data.get('selected_download_count') or 0) > 0
        self._update_workflow_actions()
        self.pairing_preview_btn.setEnabled(can_download and self.page_layout.currentData() == 'paired_landscape')
        self.progress_text.setText('Review ready.' if can_download else 'All selected items already exist in Calibre.')
        if can_download:
            self.add_log('Review ready. Check the list on the right, then choose Download and Add to Calibre.')
        else:
            self.add_log('Nothing to download. Every selected item is already in Calibre.')
            info_dialog(self, 'MangaNana', 'All selected items already exist in Calibre. Nothing will be downloaded.', show=True)

    def _preview_use_toggled(self, row, checked):
        if not self.preview_data or row < 0 or row >= self.preview_table.rowCount():
            return
        rows = self.preview_data.get('rows') or []
        if row >= len(rows) or rows[row].get('existing'):
            return
        rows[row]['selected'] = bool(checked)
        self.refresh_preview_selection_summary()

    def preview_selection_changed(self, item):
        if item.column() != 0 or not self.preview_data:
            return
        self.refresh_preview_selection_summary()

    def refresh_preview_selection_summary(self):
        if not self.preview_data:
            return
        selected_volumes = []
        include_bonus = False
        selected_pages = 0
        selected_pages_unknown = False
        rows = self.preview_data.get('rows') or []
        selected_count = 0
        for r, row in enumerate(rows):
            checked = bool(row.get('selected', not row.get('existing')) and not row.get('existing'))
            row['selected'] = checked
            if checked:
                selected_count += 1
                if row.get('pages') is None:
                    selected_pages_unknown = True
                else:
                    selected_pages += int(row.get('pages') or 0)
                if row.get('volume') is None:
                    include_bonus = True
                else:
                    selected_volumes.append(float(row['volume']))
        selected_pages = None if selected_pages_unknown else selected_pages
        est = None if selected_pages is None else selected_pages * int(self._bytes_per_page_estimate)
        self.preview_data['selected_volumes'] = selected_volumes
        self.preview_data['include_bonus'] = include_bonus
        self.preview_data['selected_download_count'] = selected_count
        self.preview_data['selected_pages'] = selected_pages
        self.preview_data['selected_estimated_bytes'] = est
        est_s = 'Size unknown' if est is None else (f'~{est/(1024**3):.2f} GB' if est >= 1024**3 else f'~{est/(1024**2):.1f} MB')
        pages_s = format_page_count(selected_pages)
        existing_count = int(self.preview_data.get('existing_count', 0) or 0)
        layout_text = 'Landscape paired pages' if self.page_layout.currentData() == 'paired_landscape' else 'Portrait pages'
        language_text = self.language.currentText() or 'Unknown language'
        chapter_mode=bool(self.preview_data.get('chapter_mode'))
        standalone_selected=any(bool(r.get('selected')) and r.get('volume') is None for r in rows)
        if existing_count:
            first_line = f"{selected_count} to download   •   {existing_count} already in Calibre   •   {pages_s} pages   •   {est_s}"
        else:
            noun = 'chapter' if chapter_mode else ('item' if standalone_selected else 'volume')
            first_line = f"{selected_count} {noun}{'s' if selected_count != 1 else ''}   •   {pages_s} pages   •   {est_s}"
        self.preview_summary.setText(first_line + f"<br>{layout_text}   •   {language_text}")
        self._update_workflow_actions()
        if hasattr(self, 'pairing_preview_btn'):
            landscape = self.page_layout.currentData() == 'paired_landscape'
            self.pairing_preview_btn.setVisible(landscape)
            has_pairing_item=any(bool(r.get('selected')) for r in rows)
            self.pairing_preview_btn.setEnabled(landscape and has_pairing_item and self.preview_signature == self.current_signature())

    def on_preview_failed(self, msg, request_id=None, build_signature=None):
        if request_id is not None and request_id != self._preview_request_id:
            return
        if build_signature is not None and build_signature != self.current_signature():
            return
        self._preview_build_signature = None
        self.cancel_btn.setEnabled(False)
        self._update_preview_button_for_volume_selection()
        self.download_btn.setEnabled(False)
        self.preview_table.setVisible(True)
        self.preview_summary.setText('Preview could not be loaded.')
        self.progress_text.setText('Preview failed')
        error_dialog(self, 'Preview failed', msg, show=True)

    def on_preview_cancelled(self, request_id, build_signature):
        if request_id != self._preview_request_id or build_signature != self.current_signature():
            return
        self._preview_build_signature = None
        self._review_cancel_requested=False
        self.preview_worker = None
        self.progress.setDeterminateValue(0)
        self.progress_text.setText('Review preparation cancelled.')
        self.preview_summary.setText('Review preparation cancelled. Selected chapters are unchanged.')
        self.cancel_btn.setEnabled(False)
        self._update_preview_button_for_volume_selection()
        self._update_workflow_actions()
        self.add_log('Review preparation cancelled.')

    def _on_preview_worker_finished(self, worker, request_id, build_signature):
        if worker is self.preview_worker:
            self.preview_worker=None
        if (self._review_cancel_requested and request_id == self._preview_request_id and
                build_signature == self.current_signature()):
            self.on_preview_cancelled(request_id, build_signature)

    def open_pairing_preview(self):
        if self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_worker.cancel()
            self.pairing_preview_btn.setEnabled(False)
            self.progress_text.setText('Cancelling pairing preview...')
            return
        if self.page_layout.currentData() != 'paired_landscape':
            return
        if not self.preview_data or self.preview_signature != self.current_signature():
            error_dialog(self, 'Pairing preview', 'Choose Review first.', show=True); return
        selected = [r for r in (self.preview_data.get('rows') or []) if r.get('selected')]
        if not selected:
            error_dialog(self, 'Pairing preview', 'Select at least one review item.', show=True); return
        raw_volume=selected[0].get('volume')
        volume=float(raw_volume) if raw_volume is not None else None
        label='Standalone Chapters' if volume is None else f'Volume {volume:g}'
        self.pairing_preview_btn.setText('Cancel Preview')
        self.pairing_preview_btn.setEnabled(True)
        self.work_progress_widget.setVisible(True)
        self.progress.setValue(0)
        self.progress_text.setText(f'Building pairing preview for {label}...')
        self.add_log(f'Building pairing preview for {label}...')
        self.pairing_preview_worker = PairingPreviewWorker(self.current_source, self.current_manga_url, self.language.currentData(), volume, self.reading_direction.currentData())
        self.pairing_preview_worker.ready.connect(self.on_pairing_preview_ready)
        self.pairing_preview_worker.failed.connect(self.on_pairing_preview_failed)
        self.pairing_preview_worker.progress.connect(self.on_pairing_preview_progress)
        self.pairing_preview_worker.log.connect(self.add_log)
        self.pairing_preview_worker.cancelled_ok.connect(self.on_pairing_preview_cancelled)
        self.pairing_preview_worker.start()

    def on_pairing_preview_progress(self, pct, text):
        self.progress.setValue(pct)
        self.progress_text.setText(text)

    def _reset_pairing_preview_button(self):
        self.pairing_preview_btn.setText('Pairing Preview')
        landscape = self.page_layout.currentData() == 'paired_landscape'
        self.pairing_preview_btn.setVisible(landscape)
        has_pairing_item=bool(self.preview_data) and any(bool(r.get('selected')) for r in (self.preview_data.get('rows') or []))
        self.pairing_preview_btn.setEnabled(landscape and has_pairing_item and self.preview_signature == self.current_signature())

    def on_pairing_preview_ready(self, data):
        self._reset_pairing_preview_button()
        self.progress.setValue(100)
        self.progress_text.setText('Pairing preview ready.')
        PairingPreviewDialog(data, self).exec()

    def on_pairing_preview_cancelled(self):
        self._reset_pairing_preview_button()
        self.progress.setValue(0)
        self.progress_text.setText('Pairing preview cancelled.')
        self.add_log('Pairing preview cancelled. Temporary preview images were discarded.')

    def on_pairing_preview_failed(self, msg):
        self._reset_pairing_preview_button()
        self.progress.setValue(0)
        self.progress_text.setText('Pairing preview failed.')
        self.add_log(f'Pairing preview failed: {msg}')
        error_dialog(self, 'Pairing preview failed', msg, show=True)

    def maybe_offer_virtual_library(self):
        vls = dict(self.db.pref('virtual_libraries', {}) or {})
        if VL_NAME in vls or not prefs['ask_virtual_library']:
            return
        box = QMessageBox(self)
        box.setWindowTitle('MangaNana Virtual Library')
        box.setWindowIcon(self.icon)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText('Create a MangaNana Virtual Library?')
        box.setInformativeText('It will show books downloaded with MangaNana separately while keeping them in your normal calibre library.')
        create = box.addButton('Create Virtual Library', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('Not Now', QMessageBox.ButtonRole.RejectRole)
        dont = QCheckBox("Don't ask again")
        box.setCheckBox(dont)
        box.exec()
        if dont.isChecked(): prefs['ask_virtual_library'] = False
        if box.clickedButton() is create:
            vls[VL_NAME] = 'tags:="MangaNana"'
            self.db.set_pref('virtual_libraries', vls)
            self.add_log('Created MangaNana Virtual Library.')
            try:
                self.db.clear_search_caches()
            except Exception: pass

    def _set_download_ui_locked(self, locked):
        """Keep the visible configuration synchronized with the active job."""
        self._download_in_progress = bool(locked)
        controls = [
            self.search_box, self.search_btn, self.url, self.load_btn, self.browse_mangadex_btn,
            self.search_results, self.show_more_btn, self.alt_titles_btn, self.volume_list, self.clear_volume_btn,
            self.portrait_btn, self.landscape_btn, self.language, self.reading_direction,
            self.start, self.end, self.covers, self.pad, self.pairing_preview_btn,
            self.preferences_btn, self.sources_btn, self.about_btn,
        ]
        if locked:
            for control in controls:
                try: control.setEnabled(False)
                except Exception: pass
            self.preview_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.workflow_hint.setText('Download in progress. Settings are locked until it finishes or is cancelled.')
        else:
            for control in (self.search_box, self.search_btn, self.url, self.load_btn, self.browse_mangadex_btn, self.search_results, self.portrait_btn, self.landscape_btn, self.covers, self.pad, self.preferences_btn, self.sources_btn, self.about_btn):
                try: control.setEnabled(True)
                except Exception: pass
            try: self.show_more_btn.setEnabled(self.show_more_btn.isVisible())
            except Exception: pass
            try: self.alt_titles_btn.setEnabled(bool(self.loaded_metadata and self.loaded_metadata.get('titles')))
            except Exception: pass
            try: self.volume_list.setEnabled(bool(self._download_language_valid))
            except Exception: pass
            try: self.clear_volume_btn.setEnabled(bool(self._current_plan and (self._current_plan.get('volumes') or self._current_plan.get('bonus_chapters'))))
            except Exception: pass
            try:
                self.language.setEnabled(bool(self.loaded_metadata))
                paired = self.page_layout.currentData() == 'paired_landscape'
                self.reading_direction.setEnabled(paired)
                self.reading_direction_label.setEnabled(paired)
            except Exception: pass
            try:
                numeric = len(self._available_volume_values())
                self.start.setEnabled(numeric > 0); self.end.setEnabled(numeric > 0)
            except Exception: pass
            self.cancel_btn.setEnabled(False)
            self._update_workflow_actions()
            try: self._reset_pairing_preview_button()
            except Exception: pass

    def _check_download_disk_space(self):
        estimate = int((self.preview_data or {}).get('selected_estimated_bytes') or 0)
        if estimate <= 0:
            return
        try:
            free = shutil.disk_usage(tempfile.gettempdir()).free
        except Exception:
            return
        # Landscape processing and temporary source images can briefly require
        # considerably more room than the final CBZ itself. Only block when the
        # shortage is obvious rather than warning on marginal estimates.
        required = int(estimate * 2.0) + 256 * 1024 * 1024
        if free < required:
            need = required / (1024**3)
            have = free / (1024**3)
            raise RuntimeError(f'Not enough free temporary disk space for this job. About {need:.1f} GB is recommended; {have:.1f} GB is available.')

    def start_download(self):
        try:
            url, title, author, series, s, e = self.validate_details()
            if self.preview_signature != self.current_signature() or not self.preview_data:
                raise ValueError('The review is out of date. Choose Review again before downloading.')
            if int(self.preview_data.get('selected_download_count', self.preview_data.get('download_count', 0)) or 0) <= 0:
                info_dialog(self, 'MangaNana', 'No preview items are selected for download.', show=True)
                return
            self.maybe_offer_virtual_library()
            self._check_download_disk_space()
            replace_existing = bool(prefs['duplicate_policy'] == 'replace' or self._session_replace_existing)
            existing = set() if replace_existing else self.existing_volumes(series)
            self._active_replace_existing = replace_existing
            self._set_download_ui_locked(True)
            self._toggle_activity_log(True)
            self.work_progress_widget.setVisible(True)
            self.log.clear(); self.progress.setValue(0); self.progress_text.setText('Starting...')
            fetch_s, fetch_e = s, e
            if self._using_entire_series:
                fetch_s, fetch_e = None, None
            elif self._selected_volumes:
                fetch_s, fetch_e = min(self._selected_volumes), max(self._selected_volumes)
            self.worker = DownloadWorker(self.current_source, url, title, author, series, self.language.currentData(), fetch_s, fetch_e,
                                         self.covers.isChecked(), self.pad.isChecked(), existing,
                                         selected_volumes=self.preview_data.get('selected_volumes'),
                                         include_bonus=self.preview_data.get('include_bonus', True),
                                         page_layout=self.page_layout.currentData(),
                                         reading_direction=self.reading_direction.currentData(),
                                         main_cover_url=self._main_cover_url,
                                         chapter_jobs=[row.get('chapter') for row in (self.preview_data.get('rows') or [])
                                                       if row.get('selected') and row.get('kind') == 'chapter'] if self.workflow_mode == 'chapter' else None)
            self.worker.log.connect(self.add_log); self.worker.progress.connect(self.on_progress); self.worker.stats.connect(self.on_stats)
            self.worker.failed.connect(self.on_failed); self.worker.cancelled_ok.connect(self.on_cancelled); self.worker.finished_ok.connect(self.on_downloaded)
            self.worker.start()
        except Exception as e:
            if getattr(self, '_download_in_progress', False):
                self._set_download_ui_locked(False)
            error_dialog(self, 'MangaNana', str(e), show=True)

    def on_progress(self, pct, text):
        self.progress.setValue(pct); self.progress_text.setText(text)

    def on_stats(self, d):
        pct = int(d.get('percent') or 0)
        self.progress.setValue(pct)
        vol = d.get('volume')
        vi, vt = d.get('job_index', 0), d.get('job_total', 0)
        vd, vtot = d.get('volume_pages_done', 0), d.get('volume_pages_total', 0)
        done, total = d.get('pages_done', 0), d.get('pages_total', 0)
        parts = []
        if vol is not None:
            try: vol_s = f'{float(vol):g}'
            except Exception: vol_s = str(vol)
            if vtot:
                parts.append(f'Volume {vol_s} ({vi}/{vt}): {vd}/{vtot} pages')
            else:
                parts.append(f'Volume {vol_s} ({vi}/{vt})')
        if total:
            parts.append(f'Overall: {done}/{total} pages')
            parts.append(f'{pct}%')
        parts.append(format_speed(d.get('bytes_per_second')))
        eta = d.get('eta_seconds')
        parts.append('ETA ~' + format_eta(eta) if eta is not None else 'calculating ETA...')
        self.progress_text.setText('  |  '.join(parts))

    def cancel_download(self):
        active_search=[worker for worker in self.search_workers.values() if worker.isRunning()]
        if active_search:
            self._search_cancel_requested=True
            for worker in active_search: worker.requestInterruption()
            self.search_coordinator.cancel_remaining()
            settled,total=self._sync_provider_search_progress()
            self._search_request_id += 1
            self.search_workers={}
            self._search_status_timer.stop()
            self.search_btn.setEnabled(True); self.search_btn.setText('Search'); self.cancel_btn.setEnabled(False)
            more=any(self._search_has_more.values()); self.show_more_btn.setVisible(more); self.show_more_btn.setEnabled(more)
            self.search_progress_text.setText(f'Search cancelled: {settled}/{total} providers settled; completed results preserved.')
            self.add_log('Provider search cancelled. Results already returned were preserved.')
            return
        if self.preview_worker and self.preview_worker.isRunning():
            self._review_cancel_requested=True
            self.preview_worker.requestInterruption()
            self.cancel_btn.setEnabled(False)
            self.progress_text.setText('Cancelling review preparation after the current request...')
            self.add_log('Review cancellation requested.')
            return
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.progress_text.setText('Cancelling safely after the current request...')
            self.add_log('Cancellation requested. Finishing the current network/file operation, then cleaning temporary files...')

    def on_cancelled(self):
        self.worker = None
        self._set_download_ui_locked(False)
        self._update_preview_button_for_volume_selection()
        self._update_workflow_actions()
        self.cancel_btn.setEnabled(False)
        self.progress_text.setText('Cancelled. Temporary partial files were cleaned up.')
        self.add_log('Download cancelled. Temporary partial files were cleaned up; Calibre was not changed for unfinished volumes.')

    def on_failed(self, msg):
        self.worker = None
        self._record_diagnostic(RuntimeError, RuntimeError(msg), None, 'download')
        self._set_download_ui_locked(False)
        self._toggle_activity_log(True)
        self.add_log(f'ERROR: {msg}')
        self._update_preview_button_for_volume_selection()
        self._update_workflow_actions()
        self.cancel_btn.setEnabled(False)
        self.progress_text.setText('Failed')
        box = QMessageBox(self)
        box.setWindowTitle('MangaNana - Download failed')
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(msg)
        box.setInformativeText('You can choose Download and Add to Calibre again to retry the same reviewed selection.')
        box.exec()

    def _replace_existing_book(self, book_id, item, author, series, language):
        p = item['path']; v = item['volume']; title = item['title']
        self.db.add_format(book_id, 'CBZ', p, replace=True)
        updates = {'title': {book_id: title}, 'authors': {book_id: [author]}, 'series': {book_id: series}, 'languages': {book_id: [language]}}
        if v is not None:
            updates['series_index'] = {book_id: float(v)}
        for field, values in updates.items():
            try: self.db.set_field(field, values)
            except Exception: pass
        try:
            cp = item.get('cover_path')
            if cp and Path(cp).exists():
                self.db.set_cover({book_id: Path(cp).read_bytes()})
        except Exception:
            pass
        return book_id

    def show_manganana_library(self):
        try:
            self.gui.apply_virtual_library(VL_NAME)
            return
        except Exception:
            pass
        try:
            self.gui.search.set_search_string('tags:="MangaNana"')
        except Exception:
            pass

    def show_added_books(self, ids):
        try:
            self.gui.library_view.select_rows(set(ids))
        except Exception:
            self.show_manganana_library()

    def retry_failed(self, failed_volumes, failed_bonus=False):
        if not self.preview_data or self.preview_signature != self.current_signature():
            info_dialog(self, 'Retry failed volumes', 'The preview has changed. Build the preview again before retrying.', show=True)
            return
        self.preview_data['selected_volumes'] = [float(v) for v in failed_volumes]
        self.preview_data['include_bonus'] = bool(failed_bonus)
        self.preview_data['selected_download_count'] = len(failed_volumes) + (1 if failed_bonus else 0)
        self.add_log('Retrying failed download item(s)...')
        self.start_download()

    def completion_dialog(self, added, skipped, duplicates, pages, final_bytes, elapsed, ids, failures, failed_bonus=False):
        speed = final_bytes / elapsed if elapsed > 0 else 0
        size_s = f'{final_bytes/(1024**2):.1f} MB' if final_bytes < 1024**3 else f'{final_bytes/(1024**3):.2f} GB'
        box = QMessageBox(self)
        box.setWindowTitle('MangaNana - Complete')
        box.setWindowIcon(self.icon)
        box.setIcon(QMessageBox.Icon.Information if not failures else QMessageBox.Icon.Warning)
        box.setText('Download and Calibre import completed.' if not failures else 'Download completed with some failed items.')
        failed_text = ', '.join(str(x) for x in failures) if failures else 'None'
        box.setInformativeText(
            f'Books added or updated: {added}\n'
            f'Existing volumes skipped: {skipped}\n'
            f'Duplicates rejected by Calibre: {duplicates}\n'
            f'Failed items: {failed_text}\n'
            f'Pages downloaded: {pages}\n'
            f'Final CBZ size: {size_s}\n'
            f'Elapsed time: {format_eta(elapsed)}\n'
            f'Average speed: {format_speed(speed)}'
        )
        box.addButton('OK', QMessageBox.ButtonRole.AcceptRole)
        show_lib = box.addButton('Open MangaNana Library', QMessageBox.ButtonRole.ActionRole)
        show_added = box.addButton('Show Added Books', QMessageBox.ButtonRole.ActionRole) if ids else None
        retry = box.addButton('Retry Failed', QMessageBox.ButtonRole.ActionRole) if failures else None
        box.exec()
        clicked = box.clickedButton()
        if clicked is show_lib:
            self.show_manganana_library()
        elif show_added is not None and clicked is show_added:
            self.show_added_books(ids)
        elif retry is not None and clicked is retry:
            self.retry_failed(failures, failed_bonus)

    def on_downloaded(self, result):
        try:
            added = 0; duplicates = 0; added_ids = []
            existing_ids = self.existing_volume_ids(self.series.text().strip())
            replace_existing = bool(getattr(self, '_active_replace_existing', False))
            for item in result.get('files', []):
                p = item['path']; v = item['volume']; title = item['title']
                if replace_existing and v is not None and float(v) in existing_ids:
                    bid = self._replace_existing_book(existing_ids[float(v)], item, self.author.text().strip(), self.series.text().strip(), self.language.currentData())
                    added += 1; added_ids.append(bid)
                    self.add_log(f'Replaced existing Calibre CBZ for Volume {float(v):g}.')
                    continue
                mi = Metadata(title, [self.author.text().strip()])
                mi.series = self.series.text().strip()
                if v is not None: mi.series_index = float(v)
                mi.languages = [self.language.currentData()]
                mi.tags = [VL_TAG]
                mi.set_identifier(self.current_source_id, self.current_source.parse_manga_ref(self.current_manga_url))
                cp = item.get('cover_path')
                if cp and Path(cp).exists():
                    ext = Path(cp).suffix.lower().lstrip('.') or 'jpg'
                    if ext == 'jpeg': ext = 'jpg'
                    mi.cover_data = (ext, Path(cp).read_bytes())
                ids, dups = self.db.add_books([(mi, {'CBZ': p})], add_duplicates=False)
                added += len(ids); duplicates += len(dups); added_ids.extend(ids)
            try:
                self.gui.library_view.model().refresh(reset=True)
            except Exception:
                pass
            elapsed = float(result.get('elapsed') or 0)
            skipped = int(result.get('skipped') or 0)
            pages = int(result.get('pages') or 0)
            source_bytes = int(result.get('bytes') or 0)
            final_bytes = int(result.get('final_bytes') or 0)
            reviewed_estimate = int((self.preview_data or {}).get('selected_estimated_bytes') or 0)
            # Calibrate against the files the user actually receives, rather than
            # cumulative source/intermediate transfer bytes.
            if pages > 0 and final_bytes > 0:
                actual_bpp = final_bytes / float(pages)
                if 128*1024 <= actual_bpp <= 2*1024*1024:
                    self._bytes_per_page_estimate = int((self._bytes_per_page_estimate * 0.35) + (actual_bpp * 0.65))
                actual_s = f'{final_bytes/(1024**3):.2f} GB' if final_bytes >= 1024**3 else f'{final_bytes/(1024**2):.1f} MB'
                if reviewed_estimate > 0:
                    estimate_s = f'~{reviewed_estimate/(1024**3):.2f} GB' if reviewed_estimate >= 1024**3 else f'~{reviewed_estimate/(1024**2):.1f} MB'
                    self.add_log(f'Download size: estimated {estimate_s}; final CBZ size {actual_s}.')
                else:
                    self.add_log(f'Final CBZ size: {actual_s}.')
            failed_volumes = [float(v) for v in (result.get('failed_volumes') or [])]
            failed_bonus = bool(result.get('failed_bonus'))
            failed_labels = list(result.get('failed_labels') or [])
            self.progress.setValue(100 if not failed_labels else max(1, self.progress.value()))
            if failed_labels:
                self.progress_text.setText(f'Finished with issues. Added {added}, failed {len(failed_labels)}.')
            else:
                self.progress_text.setText(f'Complete. Added {added} book(s), skipped {skipped}.')
            self.add_log(f'Added or updated {added} book(s) in Calibre. Existing volumes skipped: {skipped}.')
            final_size_s = f'{final_bytes/(1024**3):.2f} GB' if final_bytes >= 1024**3 else f'{final_bytes/(1024**2):.1f} MB'
            if failed_labels:
                self.add_log('Failed items: ' + ', '.join(failed_labels))
                self.add_log(f'Finished with issues: {added} book(s) added or updated, {len(failed_labels)} failed, {final_size_s} final CBZ data.')
            else:
                self.add_log(f'Complete: {added} book(s) added or updated, {skipped} skipped, {final_size_s} final CBZ data, 0 failures.')
                self.add_log('Everything is complete. You can safely close MangaNana.')
            wd = result.get('workdir')
            if wd: shutil.rmtree(wd, ignore_errors=True)
            # Keep the preview valid when failures remain so Retry Failed can reuse it.
            if not failed_labels:
                self.preview_signature = None
                self.preview_data = None
                self.download_btn.setEnabled(False)
            if prefs['show_completion_summary']:
                self.completion_dialog(added, skipped, duplicates, pages, final_bytes, elapsed, added_ids, failed_volumes, failed_bonus)
        except Exception as e:
            error_dialog(self, 'Calibre import failed', str(e), show=True)
        finally:
            try:
                wd = result.get('workdir') if isinstance(result, dict) else None
                if wd: shutil.rmtree(wd, ignore_errors=True)
            except Exception:
                pass
            self.worker = None
            self._set_download_ui_locked(False)
            self._update_preview_button_for_volume_selection(); self.cancel_btn.setEnabled(False)

