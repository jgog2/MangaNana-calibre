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
    QPainter, QColor, QPen, QTimer, QEvent, pyqtSignal, QGraphicsDropShadowEffect, QHeaderView, QSizePolicy,
    QStackedWidget, QDesktopServices, QUrl, QStyle, QStyleOptionButton
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
from calibre_plugins.manganana.canonical_identity import edition_display_label, edition_identity, group_canonical_results, merge_calibre_tags, normalize_identity_text
from calibre_plugins.manganana.search_ranking import (
    AcquisitionFitness, MatchTier, match_result, present_search_candidate,
    rank_canonical_results, rank_provider_results,
)
from calibre_plugins.manganana.search_resolution import inventory_is_eligible, resolve_search_group
from calibre_plugins.manganana.enrichment_sources import DEFAULT_ENRICHMENT_REGISTRY
from calibre_plugins.manganana.enrichment_matching import (
    enrich_content_results, propagate_trusted_family_work_facts,
    resolve_canonical_work_facts, trusted_alias_for_query,
)
from calibre_plugins.manganana.search_cache import (
    HARD_LIMIT_BYTES, SearchMetadataCache, default_cache_path, final_search_records,
    query_cache_key,
)
from calibre_plugins.manganana.search_barrier import ProviderDisplayBarrier
from calibre_plugins.manganana.provider_branding import (
    edition_badge_spec, format_rating_label, provider_badge_spec,
    safe_provider_public_url, source_badge_specs,
)
from calibre_plugins.manganana.inventory_comparison import compare_inventories, inspect_source_inventory
from calibre_plugins.manganana.cross_source_fallback import build_cross_source_plan
from calibre_plugins.manganana.chapter_workflow import chapter_label, chapter_output_title, chapter_series_index, chapter_sort_key, chapter_selection_ids
from calibre_plugins.manganana.chapter_output import (
    ChapterOutputMode, VolumeEvidenceSource, normalize_volume_identifier,
    plan_chapter_outputs, resolve_group_cover_url, resolve_volume_evidence,
    validate_manual_assignments,
)
from calibre_plugins.manganana.title_metadata import meaningful_alternate_titles, normalize_title_rows, title_language_label
from calibre_plugins.manganana.manga_load_context import MangaLoadContext, take_manga_load_context
from calibre_plugins.manganana.version_info import DISPLAY_VERSION, SHORT_VERSION_LABEL, USER_AGENT
from calibre_plugins.manganana.workflow_state import HighPriestessState, volume_selection_hint
from calibre_plugins.manganana.diagnostics import write_diagnostic_report
from calibre_plugins.manganana.reference_integration import (
    ReferenceMetadataService, canonical_publication_context, canonical_reference_alias,
    chapter_metadata_label, fallback_source_label,
)
from calibre_plugins.manganana.publication_manifest import (
    PublicationManifestBuilder, build_publication_projection,
)
from calibre_plugins.manganana.unified_volume import (
    build_unified_volume_plan, selected_unified_volume_groups,
)
try:
    from calibre_plugins.manganana.build_info import GIT_COMMIT
except ImportError:
    GIT_COMMIT = 'source'

ORANGE = '#FF6740'
COVER_BATCH_LIMIT = 8
SEARCH_RESULT_ROW_HEIGHT = 96
SEARCH_RESOLUTION_LIMIT = 8
SEARCH_QUALIFICATION_LIMIT = 3
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
        combo.addItem('Select a manga', None)
        combo.setCurrentIndex(0)
        combo.setEnabled(False)
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
        combo.setEnabled(False)
    else:
        for label, code in ordered:
            combo.addItem(label, code)
        idx = combo.findData(preferred)
        # If the preferred language is unavailable, immediately choose the first
        # language MangaDex reports as downloadable rather than blocking workflow.
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.setEnabled(True)
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
ENRICHMENT_REGISTRY = DEFAULT_ENRICHMENT_REGISTRY


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


class EnrichmentSearchWorker(QThread):
    """Optional metadata work, isolated from content-source progress."""
    ready = pyqtSignal(object)

    def __init__(self, request_id, registry, query):
        super().__init__()
        self.request_id = request_id
        self.registry = registry
        self.query = query

    def run(self):
        def check_cancel():
            if self.isInterruptionRequested():
                raise InterruptedError('External enrichment cancelled.')
        try:
            candidates, errors = self.registry.search(
                self.query, timeout=5.0, check_cancel=check_cancel,
            )
            check_cancel()
            self.ready.emit({
                'request_id': self.request_id, 'query': self.query,
                'candidates': candidates, 'errors': errors,
            })
        except InterruptedError:
            return
        except Exception as exc:
            self.ready.emit({
                'request_id': self.request_id, 'query': self.query,
                'candidates': (), 'errors': {'enrichment': str(exc)},
            })


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


class SelectedFallbackWorker(QThread):
    """Inspect compatible peers without replacing the clicked provider record."""
    ready = pyqtSignal(object)

    def __init__(self, request_id, registry, selected, candidates, language, workflow, parent=None):
        super().__init__(parent)
        self.request_id=request_id; self.registry=registry; self.selected=dict(selected or {})
        self.candidates=tuple(dict(row) for row in candidates or ())
        self.language=language or 'en'; self.workflow=workflow

    def run(self):
        inventories=[]
        try:
            for candidate in self.candidates:
                if self.isInterruptionRequested(): return
                source=self.registry.get(candidate.get('source_id'))
                if source is not None:
                    inventories.append(inspect_source_inventory(source,candidate,self.language,workflow=self.workflow))
            selected_key=(str(self.selected.get('source_id') or ''),str(self.selected.get('id') or self.selected.get('url') or ''))
            primary=next((row for row in inventories if (
                row.source_id,
                str((row.result or {}).get('id') or (row.result or {}).get('url') or ''),
            ) == selected_key),None)
            fallback=build_cross_source_plan(
                inventories,self.registry,primary=primary,workflow=self.workflow,
            ) if primary is not None and self.workflow == 'chapter' and len(inventories) > 1 else None
            self.ready.emit({'request_id':self.request_id,'inventories':tuple(inventories),'fallback_plan':fallback})
        except Exception as exc:
            self.ready.emit({'request_id':self.request_id,'inventories':tuple(inventories),'error':str(exc)})


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
            # Do not expose aggregate-only volume rows. Finalization and Download
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
                             'source_id':self.source.source_id,'plan':plan,'covers':covers,
                             'cover_error':cover_error,'chapters':chapters or []})
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


class ReferenceLookupWorker(QThread):
    """Resolve post-selection reference metadata without blocking provider inventory."""
    ready = pyqtSignal(object)

    def __init__(self, request_id, generation, work_id, evidence, cache, parent=None):
        super().__init__(parent)
        self.request_id=request_id; self.generation=generation; self.work_id=str(work_id or '')
        self.evidence=dict(evidence or {}); self.cache=cache

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            result=ReferenceMetadataService(self.cache).lookup(
                self.work_id,self.evidence,should_cancel=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.ready.emit({'request_id':self.request_id,'generation':self.generation,
                                 'work_id':self.work_id,'result':result})
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.ready.emit({'request_id':self.request_id,'generation':self.generation,
                                 'work_id':self.work_id,'error':str(exc)})


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

    def __init__(self, source, url, title, author, series, language, start, end, covers, zero_pad, existing_volumes, selected_volumes=None, include_bonus=True, page_layout='original_pages', reading_direction='rtl', main_cover_url='', volume_covers=None, chapter_jobs=None, chapter_output_groups=None):
        super().__init__()
        self.source = source
        self.source_name = source.display_name
        self.url, self.title, self.author, self.series = url, title, author, series
        self.main_cover_url = main_cover_url or ''
        self.volume_covers = dict(volume_covers or {})
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
        if chapter_output_groups is None and self.chapter_jobs:
            chapter_output_groups=tuple({
                'kind':'chapter','identifier':str(row.get('chapter') or ''),
                'volume':None,'mode':ChapterOutputMode.INDIVIDUAL_CHAPTERS.value,
                'chapters':[dict(row)],
            } for row in self.chapter_jobs)
        self.chapter_output_groups=tuple(dict(group) for group in chapter_output_groups or ())

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
            if self.chapter_output_groups:
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

            covers = dict(self.volume_covers)
            if self.covers and not covers:
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
                    cover_url = resolve_group_cover_url(
                        'volume', vol, covers, self.main_cover_url, group,
                    )
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
        jobs=list(self.chapter_output_groups)
        selected_provider_covers=dict(self.volume_covers)
        if self.covers and not selected_provider_covers and any(str(job.get('kind') or '') == 'volume' for job in jobs):
            try:
                selected_provider_covers=self.source.get_volume_covers(self.url)
            except Exception as exc:
                self.log.emit(f'Warning: volume-cover metadata unavailable: {exc}')
        planned_pages=sum(int(row.get('pages') or 0) for job in jobs for row in job.get('chapters') or ())
        state={'pages_done':0,'pages_total':planned_pages,'bytes':0,'started':time.time(),'volume_done':0}
        outputs=[]; failures=[]
        self.log.emit(f'Chapter output plan: {len(jobs)} CBZ file(s).')
        for index, job in enumerate(jobs, 1):
            self._check_cancel(); state['volume_done']=0
            group=tuple(sorted((dict(row) for row in job.get('chapters') or ()),key=chapter_sort_key))
            if not group:
                continue
            kind=str(job.get('kind') or 'chapter')
            volume=job.get('volume')
            if kind == 'volume':
                volume=float(volume if volume is not None else job.get('identifier'))
                label=f'Volume {volume:g}'
                final_title=f'{self.title} (Vol. {fmt_volume(volume,self.zero_pad)})'
            elif kind == 'standalone':
                volume=None
                label='Standalone Chapters'
                final_title=f'{self.title} (Standalone Chapters)'
            else:
                volume=None; chapter=group[0]
                label=f'Chapter {chapter_label(chapter, self.zero_pad)}'
                final_title=chapter_output_title(self.title, chapter, self.zero_pad)
            output=Path(work) / (safe_filename(final_title) + '.cbz')
            source_names=', '.join(dict.fromkeys(str(row.get('_source_name') or self.source_name) for row in group))
            self.log.emit(f'Starting {label} [{source_names}]...')
            before_done=state['pages_done']; before_bytes=state['bytes']
            try:
                cover_url=resolve_group_cover_url(
                    kind, volume, selected_provider_covers, self.main_cover_url, group,
                )
                cover_path=self._download_group(group, output, final_title, volume,
                                                 cover_url, state, index, len(jobs),
                                                 sum(int(row.get('pages') or 0) for row in group),
                                                 chapter_number=group[0].get('chapter') if kind == 'chapter' else None)
                _validate_cbz_output(output, self.page_layout)
                output_index=(volume if kind == 'volume' else
                              (chapter_series_index(group[0]) if kind == 'chapter' else None))
                outputs.append({'path':str(output),'volume':output_index,
                                'title':final_title,'cover_path':cover_path,'kind':kind,
                                'chapter_number':group[0].get('chapter') if kind == 'chapter' else None,
                                'source_id':group[0].get('_source_id'),'chapter_count':len(group)})
            except Exception as exc:
                if self.cancelled: raise
                output.unlink(missing_ok=True); state['pages_done']=before_done; state['bytes']=before_bytes
                failures.append({'volume':volume,'kind':kind,'label':label,'error':str(exc)})
                self.log.emit(f'FAILED {label}: {exc}')
        final_bytes=sum(Path(item['path']).stat().st_size for item in outputs if Path(item['path']).exists())
        self.finished_ok.emit({'files':outputs,'skipped':0,'elapsed':time.time()-t0,'workdir':work,
                              'pages':state['pages_done'],'planned_pages':state['pages_total'],'bytes':state['bytes'],
                              'final_bytes':final_bytes,'failed_volumes':[item['volume'] for item in failures if item.get('volume') is not None],
                              'failed_bonus':any(item.get('kind') == 'standalone' for item in failures),
                              'failed_labels':[item['label'] for item in failures],'failures':failures})


class PreviewWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled_ok = pyqtSignal()
    progress = pyqtSignal(int, str)

    def __init__(self, source, url, title, author, series, language, start, end, zero_pad, existing_volumes, replacement_volumes=(), selected_volumes=None, include_standalone=False, bytes_per_page=450*1024, planned_chapters=None, chapter_items=None, chapter_output_plan=None):
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
        self.replacements = set(replacement_volumes)
        self.selected_volumes = None if selected_volumes is None else set(float(v) for v in selected_volumes)
        self.include_standalone = bool(include_standalone)
        self.bytes_per_page = max(128*1024, min(2*1024*1024, int(bytes_per_page or 450*1024)))
        self.planned_chapters=tuple(planned_chapters or ())
        self.chapter_items=None if chapter_items is None else set(chapter_items)
        self.chapter_output_plan=None if chapter_output_plan is None else tuple(dict(group) for group in chapter_output_plan)

    def run(self):
        try:
            self._check_cancel()
            if self.chapter_output_plan is not None or (hasattr(self, 'chapter_items') and self.chapter_items is not None):
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
                existing=volume in self.existing
                replacement=volume in self.replacements
                rows.append({
                    'title': final_title,
                    'author': self.author,
                    'volume': volume,
                    'volume_text': f'{volume:g}',
                    'series': self.series,
                    'status': 'Already in Calibre' if existing else ('Replace Existing' if replacement else 'Will download'),
                    'pages': pages,
                    'existing': existing,
                    'replacement': replacement,
                    'source_id': self.source.source_id,
                    'source_name': self.source.display_name,
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
                    'replacement': False,
                    'source_id': self.source.source_id,
                    'source_name': self.source.display_name,
                })

            to_download = [r for r in rows if not r['existing']]
            pages = None if any(r['pages'] is None for r in to_download) else sum(r['pages'] for r in to_download)
            estimate = None if pages is None else pages * self.bytes_per_page
            self.ready.emit({
                'rows': rows,
                'existing_count': sum(1 for r in rows if r['existing']),
                'replacement_count': sum(1 for r in rows if r.get('replacement')),
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
        if self.chapter_output_plan is None:
            selected=set(self.chapter_items)
            groups=[{'kind':'chapter','identifier':str(chapter.get('chapter') or ''),'volume':None,'mode':ChapterOutputMode.INDIVIDUAL_CHAPTERS.value,'chapters':[chapter]}
                    for chapter in self.planned_chapters if str(chapter.get('id') or '') in selected]
        else:
            groups=list(self.chapter_output_plan)
        rows=[]; total=sum(len(group.get('chapters') or ()) for group in groups); done=0
        for group in groups:
            group_chapters=tuple(sorted((dict(row) for row in group.get('chapters') or ()),key=chapter_sort_key))
            group_pages=0; unknown=False; source_names=[]
            for chapter in group_chapters:
                self._check_cancel(); chapter_id=str(chapter.get('id') or '')
                source=SOURCE_REGISTRY.get(chapter.get('_source_id')) or self.source
                source_names.append(source.display_name)
                pages=chapter.get('pages')
                if pages is None:
                    try:
                        manifest=source.get_page_manifest(chapter_id) or {}; pages=len(manifest.get('full') or [])
                        self._check_cancel()
                    except Exception:
                        self._check_cancel(); pages=None
                if pages is None: unknown=True
                else: group_pages += int(pages)
                done += 1
                self.progress.emit(int(done*100/max(1,total)),review_manifest_progress(source.display_name,done,total))
            kind=str(group.get('kind') or 'chapter'); volume=group.get('volume')
            if kind == 'volume':
                volume=float(volume if volume is not None else group.get('identifier'))
                title=f'{self.title} (Vol. {fmt_volume(volume,self.zero_pad)})'; volume_text=f'{volume:g}'
            elif kind == 'standalone':
                volume=None; title=f'{self.title} (Standalone Chapters)'; volume_text='Standalone'
            else:
                chapter=group_chapters[0]; title=chapter_output_title(self.title,chapter,self.zero_pad)
                volume=None; volume_text=f'Ch. {chapter_label(chapter,self.zero_pad)}'
            existing=bool(kind == 'volume' and volume in self.existing)
            replacement=bool(kind == 'volume' and volume in self.replacements)
            source_ids=tuple(dict.fromkeys(str(chapter.get('_source_id') or self.source.source_id) for chapter in group_chapters))
            rows.append({'title':title,'author':self.author,'volume':volume,'volume_text':volume_text,
                         'series':self.series,'status':'Already in Calibre' if existing else ('Replace Existing' if replacement else 'Will download'),
                         'pages':None if unknown else group_pages,'existing':existing,'kind':kind,
                         'replacement':replacement,'source_ids':source_ids,
                         'chapter':group_chapters[0] if kind == 'chapter' else None,'group':dict(group),
                         'chapter_count':len(group_chapters),'source_name':', '.join(dict.fromkeys(source_names))})
        to_download=[row for row in rows if not row['existing']]
        pages=None if any(row['pages'] is None for row in to_download) else sum(row['pages'] for row in to_download)
        self._check_cancel()
        self.ready.emit({'rows':rows,'existing_count':sum(1 for row in rows if row['existing']),
                         'replacement_count':sum(1 for row in rows if row.get('replacement')),
                         'download_count':len(to_download),'pages':pages,
                         'estimated_bytes':None if pages is None else pages*self.bytes_per_page,
                          'chapter_mode':True,
                          'chapter_output_mode':groups[0].get('mode') if groups else ChapterOutputMode.INDIVIDUAL_CHAPTERS.value})


class PairingPreviewWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    cancelled_ok = pyqtSignal()

    def __init__(self, source, url, language, volume, direction, planned_chapters=None,
                 layout='paired_landscape', sample_label=''):
        super().__init__()
        self.source = source
        self.url, self.language, self.volume, self.direction = url, language, volume, direction
        self.cancelled = False
        self.planned_chapters=tuple(dict(row) for row in planned_chapters or ())
        self.layout=str(layout or 'original_pages')
        self.sample_label=str(sample_label or '')
        self._orientation_verification_cache = {}

    def cancel(self):
        self.cancelled = True

    def _check_cancel(self):
        if self.cancelled:
            raise InterruptedError()

    def _fetch_preview_page(self, source, saver_url, full_url, page_number):
        """Fetch a data-saver page with transient retries, then fall back to full quality."""
        return source.fetch_preview_page(
            saver_url, full_url, page_number,
            log=self.log.emit, check_cancel=self._check_cancel,
        )

    def run(self):
        started = time.monotonic()
        try:
            chapters = list(self.planned_chapters)
            if not chapters:
                chapters = self.source.get_chapters(self.url, self.language, self.volume, self.volume)
                chapters = [c for c in chapters if c.get('volume') == self.volume]
            if not chapters:
                raise RuntimeError('No chapters were found for the selected preview item.')

            base_limit = 12
            hard_limit = 14
            self.log.emit(f'Live Preview starts with a bounded sample of up to {base_limit} source pages.')
            self.log.emit(f'Preview mode: using {self.source.display_name} reduced-quality images when available.')

            # Build a lightweight ordered page queue first. This lets the sample
            # request one or two extra source pages only when its current ending
            # would be an artificial isolated page caused by the sample boundary.
            page_refs=[]
            for chap_num, chapter in enumerate(chapters, 1):
                self._check_cancel()
                chapter_source=SOURCE_REGISTRY.get(chapter.get('_source_id')) or self.source
                ch_label=chapter.get('chapter') or 'unnumbered'
                ch_title=str(chapter.get('title') or '').strip()
                manifest=chapter_source.get_page_manifest(chapter['id'])
                full_urls=manifest.get('full') or []
                saver_urls=manifest.get('data_saver') or list(full_urls)
                if len(full_urls) != len(saver_urls):
                    raise RuntimeError(f'MangaDex returned mismatched preview page lists for Chapter {ch_label}.')
                for page_in_chapter, saver_url in enumerate(saver_urls, 1):
                    page_refs.append((chap_num, ch_label, ch_title, page_in_chapter, len(saver_urls), saver_url, full_urls[page_in_chapter-1], chapter_source))
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
                    chap_num, ch_label, ch_title, page_in_chapter, chapter_pages, saver_url, full_url, chapter_source = page_refs[len(records)]
                    if announced_chapter != chap_num:
                        announced_chapter=chap_num
                        self.log.emit(f'Preview: Chapter {chap_num} of {len(chapters)} (Chapter {ch_label})...')
                    page_no=len(records)+1
                    t0=time.monotonic()
                    blob, used_fallback=self._fetch_preview_page(chapter_source, saver_url, full_url, page_no)
                    orientation_verification=None
                    if not used_fallback and 'data_saver' in chapter_source.capabilities and saver_url != full_url:
                        try:
                            blob, verified_full, orientation_verification = _select_verified_preview_source(
                                blob,
                                full_url,
                                lambda url: chapter_source.fetch_binary(
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
            if self.layout == 'paired_landscape':
                pages,stats=build_landscape_pages(records,self.direction,log=self.log.emit,detailed=True)
                # Extend only when a bounded landscape sample would otherwise end
                # on an artificial incomplete pair.
                while pages and pages[-1][2] == 'ISOLATED' and len(records) < min(hard_limit,len(page_refs)):
                    target=len(records)+1
                    self.log.emit('Preview sample ended on an incomplete pair; sampling one additional source page.')
                    fetch_until(target)
                    pages,stats=build_landscape_pages(records,self.direction,log=self.log.emit,detailed=True)
            else:
                pages=[(record['ext'],record['blob'],'INDIVIDUAL') for record in records]
                stats={'individuals':len(pages),'spreads':0,'pairs':0,'isolated':0}

            self._check_cancel()
            if fallback_count:
                self.log.emit(f'Preview download complete. {fallback_count} page(s) used full-quality fallback.')
            else:
                self.log.emit('Preview download complete. All pages used reduced-quality images.')
            self.progress.emit(85,f'Analyzing page layout... {len(records)} source pages')
            self.log.emit(f'Analyzing {len(records)} pages...')
            if self.layout == 'paired_landscape':
                self.log.emit(f"Preview layout: {stats.get('spreads',0)} original spreads, {stats.get('pairs',0)} paired pages, {stats.get('isolated',0)} isolated pages.")
            else:
                self.log.emit(f"Preview layout: {len(pages)} individual portrait pages.")
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
            layout_label='landscape pages' if self.layout == 'paired_landscape' else 'portrait pages'
            self.log.emit(f'Live Preview ready. {len(records)} source pages → {total_out} {layout_label}. Completed in {elapsed:.1f}s.')
            label=self.sample_label or ('Selected Chapters' if self.volume is None else f'Volume {self.volume:g}')
            self.ready.emit({'volume':self.volume,'label':label,'layout':self.layout,
                             'thumbs':thumbs,'stats':stats,'source_pages':len(records),
                             'output_pages':total_out})
        except InterruptedError:
            self.cancelled_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))


class PreferencesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MangaNana Preferences')
        self.resize(620, 690)
        self.setStyleSheet(
            'QGroupBox { margin-top:18px; padding:16px 12px 12px 12px; } '
            'QGroupBox::title { subcontrol-origin:margin; left:14px; padding:0 7px; }'
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(18,16,18,16); root.setSpacing(12)

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
        self.duplicate_policy = QComboBox()
        self.duplicate_policy.addItem('Skip existing (Recommended)', 'skip')
        self.duplicate_policy.addItem('Ask when existing volumes are found', 'ask')
        self.duplicate_policy.addItem('Replace existing CBZ files', 'replace')
        dpi = self.duplicate_policy.findData(prefs['duplicate_policy'])
        if dpi >= 0: self.duplicate_policy.setCurrentIndex(dpi)
        bl.addWidget(self.ask_vl)
        bl.addWidget(self.summary)
        bl.addWidget(self.adult_search)
        dpform = QFormLayout(); dpform.addRow('Existing volumes:', self.duplicate_policy); bl.addLayout(dpform)
        existing_note = QLabel('Existing numbered volumes are skipped automatically unless this setting chooses another action.')
        existing_note.setWordWrap(True); existing_note.setStyleSheet('color:#bdbdbd; font-size:11px;')
        bl.addWidget(existing_note)
        root.addWidget(behavior)

        enrichment = QGroupBox('Search Enrichment')
        enrichment_layout = QVBoxLayout(enrichment)
        self.search_enrichment = QCheckBox('Use external manga metadata to improve search results')
        self.search_enrichment.setChecked(bool(prefs['search_enrichment']))
        enrichment_layout.addWidget(self.search_enrichment)
        sources = QLabel('Sources: AniList, Kitsu')
        sources.setStyleSheet('color:#AEB2B6; font-size:10px;')
        enrichment_layout.addWidget(sources)
        root.addWidget(enrichment)

        cache_group = QGroupBox('Search & Metadata Cache')
        cache_layout = QVBoxLayout(cache_group)
        self.clear_search_cache_btn = QPushButton('Clear Search Cache')
        self.clear_search_cache_btn.clicked.connect(self._clear_search_cache)
        cache_layout.addWidget(self.clear_search_cache_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.cache_size_label = QLabel('')
        self.cache_size_label.setStyleSheet('color:#AEB2B6; font-size:10px;')
        cache_layout.addWidget(self.cache_size_label)
        root.addWidget(cache_group)
        self._cache = SearchMetadataCache(default_cache_path(config_dir))
        self.cache_cleared = False
        self._refresh_cache_size()

        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _refresh_cache_size(self):
        self.cache_size_label.setText(
            f'Cache size: {self._cache.size_megabytes():.1f} MB of {HARD_LIMIT_BYTES / (1024 * 1024):.0f} MB'
        )

    def _clear_search_cache(self):
        answer = QMessageBox.question(
            self, 'Clear Search Cache',
            'Clear MangaNana search and metadata cache?\n\n'
            'MangaNana will rebuild search and enrichment information as you search again. '
            'Downloads, Calibre books, manga-source settings, preferences, and provider icons are not affected.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._cache.clear()
            self.cache_cleared = True
            self._refresh_cache_size()
        except Exception as exc:
            error_dialog(self, 'Clear Search Cache failed', str(exc), show=True)

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
        prefs['search_enrichment'] = self.search_enrichment.isChecked()
        prefs['duplicate_policy'] = self.duplicate_policy.currentData()
        try:
            prefs.commit()
        except Exception:
            pass
        self._cache.close()
        super().accept()

    def reject(self):
        self._cache.close()
        super().reject()


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


class VolumeResolutionRowWidget(QFrame):
    """Non-selectable in-pane activity state for real volume resolution work."""

    def __init__(self, title, detail='', compact=False, parent=None):
        super().__init__(parent)
        self.setObjectName('volumeResolutionRow')
        layout=QHBoxLayout(self); layout.setContentsMargins(12,10,12,10); layout.setSpacing(12)
        self.activity=CoverLoadingLabel(self); self.activity.setFixedSize(34,34)
        self.activity.setStyleSheet('background:#17191B; border:0; border-radius:17px;')
        self.activity.set_loading()
        layout.addWidget(self.activity,0,Qt.AlignmentFlag.AlignVCenter)
        text_host=QWidget(self); text_layout=QVBoxLayout(text_host)
        text_layout.setContentsMargins(0,0,0,0); text_layout.setSpacing(2)
        primary=QLabel(str(title or 'Resolving volumes…')); primary.setWordWrap(True)
        primary.setStyleSheet('color:#F1F1F1; font-size:12px; font-weight:700;')
        text_layout.addWidget(primary)
        if detail:
            secondary=QLabel(str(detail)); secondary.setWordWrap(True)
            secondary.setStyleSheet('color:#9FA5AA; font-size:10px;')
            text_layout.addWidget(secondary)
        layout.addWidget(text_host,1,Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumHeight(58 if compact else 88)
        self.setStyleSheet('QFrame#volumeResolutionRow { background:#121416; border:1px solid #34393E; border-radius:6px; }')


class FocusClearingFrame(QFrame):
    """Let ordinary empty-page clicks release an active editor naturally."""

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def mousePressEvent(self,event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)


class VolumeRowWidget(QFrame):
    """Compact volume selector row with a right-side round multi-select control."""
    toggled = pyqtSignal(bool)

    def __init__(self, title, parent=None, cover_loading=False, provider_spec=None):
        super().__init__(parent)
        self._checked_state = None
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
        if provider_spec:
            row.addWidget(ProviderBadgeWidget(provider_spec,self,effects=False),0,Qt.AlignmentFlag.AlignVCenter)
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
        if self._checked_state is checked and not emit_signal:
            return
        self._checked_state=checked
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


def _safe_qss_color(value, fallback):
    text=str(value or '')
    return text if re.fullmatch(r'#[0-9A-Fa-f]{6}',text) else fallback


def _pill_stylesheet(accent, text_color='#FFFFFF'):
    """Return one parser-safe stylesheet for shared provider/status pills."""
    accent=_safe_qss_color(accent,'#555B61')
    text_color=_safe_qss_color(text_color,'#FFFFFF')
    return (
        f'QPushButton {{ color:{text_color}; background-color:#211E1D; '
        f'border:1px solid {accent}; border-radius:9px; padding:2px 7px; '
        'font-size:9px; font-weight:700; }} '
        f'QPushButton:hover {{ background-color:#2A2321; border:1px solid {accent}; }} '
        f'QPushButton:disabled {{ color:{text_color}; background-color:#211E1D; '
        f'border:1px solid {accent}; }}'
    )


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


class ProviderBadgeWidget(QPushButton):
    """Shared provider/edition pill with optional browser-only navigation."""
    ICON_SIZE = 16

    def __init__(self, spec, parent=None, effects=True):
        super().__init__(parent)
        spec = dict(spec or {})
        self.public_url=safe_provider_public_url(spec.get('source_id'),spec.get('public_url'))
        accent = _safe_qss_color(spec.get('accent_color'),'#555B61')
        text_color = _safe_qss_color(spec.get('text_color'),'#FFFFFF')
        kind=str(spec.get('kind') or 'source')
        prefix='Edition' if kind == 'edition' else 'Provider'
        self.setAccessibleName(f"{prefix}: {spec.get('text') or prefix}")
        self.setAutoDefault(False); self.setDefault(False); self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(_pill_stylesheet(accent,text_color))
        if effects:
            glow = QGraphicsDropShadowEffect(self)
            glow_color = QColor(accent); glow_color.setAlpha(105)
            glow.setColor(glow_color); glow.setBlurRadius(7); glow.setOffset(0, 0)
            self.setGraphicsEffect(glow)
        pixmap = _provider_icon_pixmap(spec.get('icon_path'))
        if pixmap is not None:
            self.setIcon(QIcon(pixmap.scaled(
                QSize(self.ICON_SIZE, self.ICON_SIZE),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )))
            self.setIconSize(QSize(self.ICON_SIZE,self.ICON_SIZE))
        self.setText(spec.get('text') or prefix)
        self.setMinimumHeight(22)
        if self.public_url:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setAccessibleDescription('Open this exact provider title page in the default browser.')
            self.clicked.connect(self._open_public_url)
        else:
            # Non-interactive pills remain part of their containing row's hit area.
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)

    def _open_public_url(self):
        if self.public_url:
            QDesktopServices.openUrl(QUrl(self.public_url))


class SourceStatusButton(QPushButton):
    """Clickable provider pill; failure state exposes provider-local retry."""
    def __init__(self, source_id, display_name, status='pending', parent=None):
        super().__init__(parent)
        self.source_id=str(source_id or '')
        self.setAutoDefault(False); self.setDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        spec=provider_badge_spec(self.source_id,display_name)
        failed=status == 'failed'; searching=status in ('pending','running')
        accent='#D94B4B' if failed else spec.get('accent_color') or '#555B61'
        suffix='  ↻' if failed else ('  …' if searching else '')
        self.setText((spec.get('text') or display_name or self.source_id) + suffix)
        self.setStyleSheet(_pill_stylesheet(accent))
        self.setEnabled(failed)
        if failed:
            self.setAccessibleDescription(f'{display_name} search failed. Activate to retry this source.')


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

        self.ask_equivalent_sources = QCheckBox('Ask when multiple equivalent sources are available')
        self.ask_equivalent_sources.setChecked(bool(preferences['ask_equivalent_sources']))
        self.ask_equivalent_sources.setAccessibleDescription(
            'Prompts only when usable providers remain materially equivalent after resolution.'
        )
        root.addWidget(self.ask_equivalent_sources)

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
        self.preferences['ask_equivalent_sources'] = self.ask_equivalent_sources.isChecked()
        try:
            self.preferences.commit()
        except Exception:
            pass
        super().accept()


class SearchResultRowWidget(QFrame):
    """Compact search row that does not claim unresolved sources are usable."""
    activated = pyqtSignal()

    def __init__(self, title, author, confirmed_sources=(), badge='', rating='', parent=None, cover_loading=False):
        super().__init__(parent)
        self._edition_badge=str(badge or '')
        self.setMinimumHeight(SEARCH_RESULT_ROW_HEIGHT - 2)
        row=QHBoxLayout(self); row.setContentsMargins(6,5,8,5); row.setSpacing(9)
        self.cover=CoverLoadingLabel(); self.cover.setFixedSize(48,70); self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setStyleSheet('background:#17191B; color:#FF6740; border-radius:4px; font-size:11px; font-weight:800;')
        if cover_loading: self.cover.set_loading(style='pulse')
        else: self.cover.set_failed()
        row.addWidget(self.cover,0,Qt.AlignmentFlag.AlignVCenter)
        details=QVBoxLayout(); details.setContentsMargins(0,1,0,1); details.setSpacing(2)
        self.details = details
        self._base_title = str(title or 'Untitled')
        self.title_label=QLabel(self._base_title); self.title_label.setStyleSheet('color:#F1F1F1; font-size:12px; font-weight:700;')
        self.title_label.setWordWrap(True); details.addWidget(self.title_label)
        rating_text=format_rating_label(rating)
        self.rating_label=QLabel(rating_text)
        self.rating_label.setStyleSheet('color:#D7B06A; font-size:10px; font-weight:600;')
        self.rating_label.setVisible(bool(rating_text))
        metadata=QHBoxLayout(); metadata.setContentsMargins(0,0,0,0); metadata.setSpacing(7)
        metadata.addWidget(self.rating_label)
        self.author_label=QLabel(str(author or '')); self.author_label.setStyleSheet('color:#A9ADB1; font-size:10px;')
        self.author_label.setVisible(bool(author)); metadata.addWidget(self.author_label); metadata.addStretch(1)
        details.addLayout(metadata)
        self.source_state_widget = None
        self.set_source_state(confirmed_sources)
        details.addStretch(1); row.addLayout(details,1)

    def mousePressEvent(self,event):
        self.activated.emit()
        event.accept()

    def set_source_state(self, confirmed_sources=(), language_note='', unresolved_text='Searching sources…'):
        if self.source_state_widget is not None:
            self.details.removeWidget(self.source_state_widget)
            self.source_state_widget.deleteLater()
        host = QWidget(self)
        state = QVBoxLayout(host); state.setContentsMargins(0,0,0,0); state.setSpacing(2)
        if confirmed_sources:
            chips=QHBoxLayout(); chips.setContentsMargins(0,0,0,0); chips.setSpacing(5)
            source_ids=[]; source_names=[]; public_urls=[]
            for source in confirmed_sources:
                if isinstance(source,dict):
                    source_ids.append(source.get('source_id') or '')
                    source_names.append(source.get('source_name') or source.get('display_name') or '')
                    public_urls.append(source.get('url') or source.get('source_url') or '')
                else:
                    values=tuple(source)
                    source_ids.append(values[0] if values else '')
                    source_names.append(values[1] if len(values)>1 else '')
                    public_urls.append(values[2] if len(values)>2 else '')
            for spec in source_badge_specs(source_names, source_ids, public_urls):
                chips.addWidget(ProviderBadgeWidget(spec,self),0,Qt.AlignmentFlag.AlignVCenter)
            if self._edition_badge:
                chips.addWidget(ProviderBadgeWidget(edition_badge_spec(self._edition_badge),self),0,Qt.AlignmentFlag.AlignVCenter)
            chips.addStretch(1); state.addLayout(chips)
        else:
            unresolved = ProviderBadgeWidget({
                'text':unresolved_text,'kind':'neutral','accent_color':'#555B61',
                'text_color':'#B7BBC0','icon_path':'',
            },self)
            state.addWidget(unresolved,0,Qt.AlignmentFlag.AlignLeft)
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

    def set_enrichment_metadata(self, title='', author='', rating=''):
        """Attach optional metadata without replacing or moving this provider row."""
        rating = format_rating_label(rating)
        self.title_label.setText(title or self._base_title)
        self.author_label.setText(author or '')
        self.author_label.setVisible(bool(author))
        self.rating_label.setText(rating)
        self.rating_label.setVisible(bool(rating))


class ManualChapterVolumeDialog(QDialog):
    """Focused multi-row assignment editor for Chapter-mode volume outputs."""

    def __init__(self, chapters, assignments=None, parent=None):
        super().__init__(parent)
        self.chapters = tuple(sorted((dict(row) for row in chapters or ()), key=chapter_sort_key))
        self.assignments = dict(assignments or {})
        self.setWindowTitle('MangaNana - Group Chapters into Volumes')
        self.resize(680, 520)
        root = QVBoxLayout(self)
        note = QLabel('Select one or more chapters, enter a volume number, then assign them. Every chapter must be assigned.')
        note.setWordWrap(True); root.addWidget(note)
        self.table = QTableWidget(len(self.chapters), 3)
        self.table.setHorizontalHeaderLabels(['Chapter', 'Source', 'Volume'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.volume_input = QLineEdit(); self.volume_input.setPlaceholderText('Volume number')
        self.assign_btn = QPushButton('Assign Selected to Volume')
        self.clear_btn = QPushButton('Clear Assignment')
        actions.addWidget(self.volume_input, 1); actions.addWidget(self.assign_btn); actions.addWidget(self.clear_btn)
        root.addLayout(actions)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept); self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self.assign_btn.clicked.connect(self._assign_selected)
        self.clear_btn.clicked.connect(self._clear_selected)
        self.volume_input.returnPressed.connect(self._assign_selected)
        self._refresh()

    def _selected_rows(self):
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def _refresh(self):
        for row_index, chapter in enumerate(self.chapters):
            chapter_id = str(chapter.get('id') or '')
            values = (
                f'Chapter {chapter_label(chapter)}' + (f' · {chapter.get("title")}' if chapter.get('title') else ''),
                str(chapter.get('_source_name') or chapter.get('_source_id') or ''),
                str(self.assignments.get(chapter_id) or 'Unassigned'),
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            validate_manual_assignments(self.chapters, self.assignments)
        )

    def _assign_selected(self):
        volume = normalize_volume_identifier(self.volume_input.text())
        if volume is None:
            error_dialog(self, 'Invalid volume', 'Enter a valid numeric volume identifier.', show=True)
            return
        for row_index in self._selected_rows():
            self.assignments[str(self.chapters[row_index].get('id') or '')] = volume
        self._refresh()

    def _clear_selected(self):
        for row_index in self._selected_rows():
            self.assignments.pop(str(self.chapters[row_index].get('id') or ''), None)
        self._refresh()


class MangaNanaProgressBar(QProgressBar):
    """Standard solid progress bar with an explicit determinate helper."""
    def setDeterminateValue(self, value):
        """Keep workflow progress static, solid, left-anchored, and determinate."""
        self.setRange(0, 100)
        self.setValue(value)


class MangaSelectionCheckBox(QCheckBox):
    """Native checkbox behavior with MangaNana's round orange selector."""

    def paintEvent(self,event):
        super().paintEvent(event)
        option=QStyleOptionButton(); self.initStyleOption(option)
        rect=self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator,option,self)
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        painter.fillRect(rect,QColor('#191C1F'))
        checked=self.isChecked(); enabled=self.isEnabled()
        border=QColor(ORANGE if checked or self.underMouse() else ('#555B61' if enabled else '#3A3F44'))
        fill=QColor(ORANGE if checked else '#121416')
        painter.setPen(QPen(border,2 if checked else 1)); painter.setBrush(fill)
        painter.drawEllipse(rect.adjusted(1,1,-1,-1))
        if checked:
            font=painter.font(); font.setBold(True); font.setPixelSize(max(10,rect.height()-5)); painter.setFont(font)
            painter.setPen(QColor('#FFFFFF'))
            painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,'✓')
        painter.end()


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
        self._live_preview_samples = {}
        self._active_preview_sample_key = None
        self._review_focus_row = 0
        self._live_preview_stale = False
        self.preview_data = None
        self.preview_signature = None
        self._applied_metadata = {'title':'','series':'','author':''}
        self._metadata_pending = False
        self._syncing_metadata_fields = False
        self._preview_request_id = 0
        self._preview_build_signature = None
        self.loaded_metadata = None
        self.current_manga_url = ''
        self.current_source = MANGADEX_SOURCE
        self.current_source_id = MANGADEX_SOURCE.source_id
        self._loaded_covers = {}
        self._main_cover_url = ''
        self._provider_main_cover_url = ''
        self._reference_volume_covers = {}
        self._reference_bundle = {}
        self._publication_manifest = None
        self._pending_search_url = ''
        self._pending_source_id = ''
        self._pending_search_cover_url = ''
        self._pending_search_result = {}
        self._pending_search_language = ''
        self._last_discovery_kind = None
        self._last_discovery_value = ''
        self._manga_load_contexts = {}
        self._current_plan = None
        self.workflow_mode = None
        self.workflow_state = HighPriestessState(
            download_language=str(prefs['language'] or 'en'),
            prefer_colored=bool(prefs['prefer_colored']),
        )
        self._mode_generation = 0
        self._chapter_plan_items = ()
        self._chapter_acquisition_items = ()
        self._volume_acquisition_items = ()
        self._native_volume_plan = None
        self._chapter_acquisition_error = ''
        self._pending_cross_source_plan = None
        self._selected_chapter_ids = set()
        self._selected_resolution_inventories = ()
        self._selected_work_id = ''
        self._selected_edition = 'original'
        self._chapter_volume_evidence = None
        self._manual_volume_assignments = {}
        self._chapter_output_mode = ChapterOutputMode.INDIVIDUAL_CHAPTERS
        self._chapter_output_syncing = False
        self._chapter_output_user_selected = False
        self._download_language_valid = False
        self._volume_plan_loading = False
        self._session_replace_existing = False
        self._last_retry_context = None
        self._download_in_progress = False
        self._search_cache = {}
        self._metadata_search_cache = SearchMetadataCache(default_cache_path(config_dir))
        self._download_availability_cache = {}
        self._manga_cache = {}
        self._plan_cache = {}
        self._image_cache = {}
        self._scaled_pixmap_cache = {}
        self._failed_image_urls = set()
        self._search_page_size = 20
        self._search_query = ''
        self._search_raw_results = []
        self._search_content_results = []
        self._external_candidates = ()
        self._late_enrichment_by_provider = {}
        self._enrichment_worker = None
        self._enrichment_request_id = 0
        self._enrichment_received = False
        self._reference_worker = None
        self._reference_request_id = 0
        self._active_query_cache_key = ''
        self._search_loaded_stale_cache = False
        self._alias_retried_sources = set()
        self._search_user_interacted = False
        self._search_offsets = {}
        self._search_has_more = {}
        self._search_total = 0
        self._search_request_id = 0
        self._search_cancel_requested = False
        self._search_started_at = 0.0
        self._search_provider_ids = ()
        self._search_ranked_groups = ()
        self._search_resolutions = {}
        self._search_resolution_complete = False
        self._search_display_barrier = ProviderDisplayBarrier(())
        self._search_barrier_consumed = False
        self._search_resolution_request_id = 0
        self._search_resolution_worker = None
        self._search_resolution_metadata_cache = {}
        self._search_resolution_inventory_cache = self._metadata_search_cache
        self._manga_request_id = 0
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
        self._review_cancel_requested = False
        self._live_preview_request_id = 0
        self.search_worker = None
        self.search_workers = {}
        self.search_coordinator = SourceCoordinator(SOURCE_REGISTRY)
        self.inventory_comparison_worker = None
        self._inventory_comparison_request_id = 0
        self._selected_fallback_worker = None
        self._selected_fallback_request_id = 0
        self._active_fallback_source = None
        self._last_inventory_decision = None
        self.search_thumb_worker = None
        self.volume_thumb_worker = None
        # Role-specific attributes can be retired as soon as intent changes,
        # but the QThread itself must remain strongly owned through finished.
        self._async_workers = set()
        self._cover_generation = 0
        self._search_cover_batch_token = 0
        self._volume_cover_batch_token = 0
        self._closing = False
        self._manga_workers = []
        self._plan_workers = []
        self.setWindowTitle(f'{DISPLAY_VERSION} for calibre')
        self.setWindowIcon(icon)
        self.resize(int(prefs.get('window_w', 1500) or 1500), int(prefs.get('window_h', 950) or 950))
        self.setMinimumSize(1200, 760)
        self.build_ui()
        self._search_status_timer=QTimer(self); self._search_status_timer.setInterval(1000)
        self._search_status_timer.timeout.connect(self._update_search_status)
        self._cover_pulse_timer=QTimer(self); self._cover_pulse_timer.setInterval(170)
        self._cover_pulse_timer.timeout.connect(self._refresh_visible_cover_pulses)
        self._cover_pulse_timer.start()
        self._install_diagnostic_hook()
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
        for widget, row_height in ((self.search_results,SEARCH_RESULT_ROW_HEIGHT), (self.volume_list,72)):
            for index in self._visible_row_range(widget,row_height,1):
                row=widget.itemWidget(widget.item(index))
                cover=getattr(row, 'cover', None)
                if isinstance(cover,CoverLoadingLabel) and cover._loading and cover._loading_style == 'pulse':
                    cover._phase=(cover._phase + 1) % 16
                    cover.update()

    def _set_edition_badge(self, text=None):
        text = str(text or '').strip()
        if not hasattr(self,'edition_badge_layout'):
            return
        while self.edition_badge_layout.count():
            item=self.edition_badge_layout.takeAt(0); widget=item.widget()
            if widget is not None: widget.deleteLater()
        if text:
            self.edition_badge_layout.addWidget(ProviderBadgeWidget(
                edition_badge_spec(text),self.edition_badge_host
            ))
        self.edition_badge_host.setVisible(bool(text))

    def _set_selected_source_badge(self, source_id='', display_name='', public_url=''):
        if not hasattr(self,'selected_source_layout'):
            return
        while self.selected_source_layout.count():
            item=self.selected_source_layout.takeAt(0); widget=item.widget()
            if widget is not None:
                widget.deleteLater()
        if source_id or display_name:
            self.selected_source_layout.addWidget(ProviderBadgeWidget(
                provider_badge_spec(source_id,display_name,public_url),self.selected_source_host
            ))

    def _set_selected_optional_text(self, label, text, prefix='', limit=280):
        text=' '.join(str(text or '').split())
        if limit and len(text) > limit:
            text=text[:limit].rsplit(' ',1)[0].rstrip(' ,.;:') + '…'
        label.setText((prefix + text) if text else '')
        label.setVisible(bool(text))

    def _refresh_selected_details(self, metadata=None):
        metadata=dict(metadata or self.loaded_metadata or {})
        description=str(metadata.get('description') or '').strip()
        self._set_selected_optional_text(
            self.selected_synopsis,description,'Description: ',None
        )
        # The label lives inside this initially-hidden scroll area, so
        # QLabel.isVisible() is false until the parent itself is shown.
        self.selected_synopsis_scroll.setVisible(bool(description))
        current=str(metadata.get('title') or '').casefold()
        aliases=[]
        for value in metadata.get('alternate_titles') or ():
            value=str(value or '').strip()
            if value and value.casefold() != current and value not in aliases:
                aliases.append(value)
        self._set_selected_optional_text(
            self.selected_aliases,' · '.join(aliases[:3]),'Aliases: ',150
        )
        self._set_selected_optional_text(
            self.selected_tags,' · '.join(str(tag) for tag in tuple(metadata.get('tags') or ())[:6]),'',110
        )

    def _apply_work_level_enrichment(self, metadata, overlay):
        """Apply only trusted work facts; provider/acquisition facts stay local."""
        overlay=dict(overlay or {})
        description=str(overlay.get('work_description') or '').strip()
        if description:
            metadata['description']=description
        tags=tuple(overlay.get('work_tags') or ())
        if tags:
            metadata['tags']=list(tags)
        canonical_author=str(overlay.get('canonical_author') or '').strip()
        if canonical_author:
            metadata['author']=canonical_author
        return metadata

    def _apply_selected_enrichment(self, overlay):
        """Apply already-returned enrichment to the selected card only."""
        rating=format_rating_label((overlay or {}).get('rating_display'))
        self.selected_rating.setText(rating); self.selected_rating.setVisible(bool(rating))
        if not self.loaded_metadata:
            return
        previous_author=str(self.loaded_metadata.get('author') or '')
        self._apply_work_level_enrichment(self.loaded_metadata,overlay)
        rows=list(self.loaded_metadata.get('titles') or ())
        rows.extend((overlay or {}).get('structured_titles') or ())
        for alias in (overlay or {}).get('alternate_titles') or ():
            rows.append({'title':alias,'language':'','primary':False,'provenance':'enrichment'})
        normalized=list(normalize_title_rows(rows,self.loaded_metadata.get('title') or ''))
        self.loaded_metadata['titles']=normalized
        self.loaded_metadata['alternate_titles']=[
            row.get('title') for row in normalized
            if str(row.get('title') or '').casefold() != str(self.loaded_metadata.get('title') or '').casefold()
        ]
        self.alt_titles_btn.setEnabled(bool(self.loaded_metadata['alternate_titles']))
        if self.loaded_metadata.get('author') != previous_author:
            self.selected_author.setText(self.loaded_metadata.get('author') or '')
            if not self._metadata_pending:
                self._set_applied_metadata(
                    self.loaded_metadata.get('title') or '',self.loaded_metadata.get('author') or '',
                    self.loaded_metadata.get('title') or '',sync_fields=True,
                )
        self._refresh_selected_details(self.loaded_metadata)
        if self._publication_manifest:
            builder=self._publication_manifest_builder()
            builder.apply_enrichment(overlay)
            self._promote_publication_manifest(builder)

    def _publication_manifest_builder(self):
        metadata=dict(self.loaded_metadata or {})
        aliases=list(metadata.get('alternate_titles') or ())
        aliases.extend(str(row.get('title') or '') for row in metadata.get('titles') or () if isinstance(row,dict))
        work={
            'canonical_identity':self._selected_work_id,
            'title':metadata.get('title') or '',
            'aliases':aliases,
            'creator':metadata.get('author') or '',
            'creator_source':'provider',
            'language':self._pending_search_language or '',
        }
        return PublicationManifestBuilder(
            work,self._selected_edition,existing=self._publication_manifest,
        )

    def _promote_publication_manifest(self, builder):
        preferred_language=(self.language.currentData() if hasattr(self,'language') else '') or self._pending_search_language or prefs['language']
        manifest=builder.build(preferred_language)
        generation=getattr(self,'_workflow_inventory_generation',-1)
        if not self.workflow_state.apply_publication_manifest(generation,manifest):
            return None
        self._publication_manifest=manifest
        return manifest

    def _seed_publication_manifest(self, provider_description='', enrichment=None):
        builder=self._publication_manifest_builder()
        builder.add_description(provider_description,'provider')
        builder.apply_enrichment(enrichment or {})
        return self._promote_publication_manifest(builder)

    def _project_inventory_through_publication_manifest(self, inventory):
        rows=tuple(dict(row) for row in inventory or ())
        builder=self._publication_manifest_builder()
        by_source={}
        for row in rows:
            source_id=str(row.get('_source_id') or row.get('source_id') or self.current_source_id or 'provider')
            by_source.setdefault(source_id,[]).append(row)
        for source_id,source_rows in by_source.items():
            builder.apply_provider_inventory(source_rows,source_id)
        manifest=self._promote_publication_manifest(builder)
        selected_record=self.workflow_state.selected_provider_record or {}
        return build_publication_projection(
            rows,manifest,
            selected_provider=str(selected_record.get('source_id') or ''),
            default_acquisition_provider=self.current_source_id,
        )

    @staticmethod
    def _terminal_structure_state(manifest):
        state=next((row for row in (manifest.source_states if manifest else ())
                    if row.source == 'wikipedia'),None)
        if state and state.status == 'valid_stale':
            return 'valid_stale'
        if state and state.status in ('valid_with_data','valid_complete','valid_partial'):
            return 'valid'
        if state and state.status in (
                'unsupported_layout','supported_empty','unmatched','ambiguous','unsupported_segment',
                'ambiguous_collection','conflict'):
            return 'unsupported'
        return 'terminal_failure'

    def _set_chapter_preparing(self, message):
        if self.workflow_mode != 'chapter':
            return
        self._download_language_valid=False
        self.volume_list.setEnabled(False); self.select_all_btn.setEnabled(False)
        self.clear_volume_btn.setEnabled(False); self.preview_btn.setEnabled(False)
        self.meta_summary.setText(message)
        self._show_volume_empty_message(message)

    @staticmethod
    def _provider_display_name(source_id):
        source=SOURCE_REGISTRY.get(source_id)
        return source.display_name if source else str(source_id or 'Unknown')

    def _log_publication_projection(self, projection):
        coverage=projection.coverage
        if not coverage['provider_chapters']:
            return
        acquisitions=' + '.join(self._provider_display_name(value)
                                 for value in coverage['acquisition_providers']) or 'Unknown'
        selected=self._provider_display_name(coverage['selected_provider'])
        self.add_log(
            f'Acquisition projection: {coverage["resolved_chapters"]}/{coverage["provider_chapters"]} resolved. '
            f'Provider explicit: {coverage["provider_explicit"]}; '
            f'Reference explicit: {coverage["reference_explicit"]}; '
            f'Derived fractional: {coverage["derived_fractional"]}; '
            f'Derived pre-Chapter-1: {coverage["derived_pre_chapter_one"]}; '
            f'Unmapped: {coverage["unmapped_provider_chapters"]}. '
            f'Acquisition: {acquisitions}. Selected provider: {selected}.'
        )

    def _try_finalize_chapter_projection(self):
        if self.workflow_mode != 'chapter' or not self.workflow_state.chapter_projection_ready:
            if (self.workflow_mode == 'chapter' and
                    self.workflow_state.chapter_acquisition_state in ('ready','terminal_failure') and
                    self.workflow_state.chapter_structure_state == 'pending'):
                self._set_chapter_preparing('Resolving publication structure…')
            return False
        projection=self._project_inventory_through_publication_manifest(
            self.workflow_state.pending_chapter_inventory
        )
        rows=tuple(sorted(projection.rows,key=chapter_sort_key))
        generation=getattr(self,'_workflow_inventory_generation',-1)
        if not self.workflow_state.freeze_chapter_projection(
                generation,self._volume_plan_request_id,projection,rows):
            return False
        self._chapter_plan_items=rows
        self._current_plan={'volumes': [], 'bonus_chapters': len(rows)}
        self._download_language_valid=bool(rows)
        self._refresh_chapter_output_options()
        self._rebuild_volume_list(); self.volume_list.setEnabled(self._download_language_valid)
        self._update_preview_button_for_volume_selection()
        self._set_selected_inventory_count(len(rows))
        self._log_publication_projection(projection)
        if rows:
            self.meta_summary.setText(
                f'{len(rows)} chapter' + ('' if len(rows) == 1 else 's') +
                f' available in {self.language.currentText()}.'
            )
            self.add_log(f'Chapter browser ready: {len(rows)} chapters in {self.language.currentText()}.')
        else:
            message=(self._chapter_acquisition_error or
                     'No downloadable chapters were found for Chapter mode.')
            self.meta_summary.setText(message); self._show_volume_empty_message(message)
        return True

    def _refresh_unified_volume_plan(self):
        """Project only selected-provider acquisition rows into Volume groups."""
        if (self.workflow_mode != 'volume' or not self._volume_acquisition_items or
                self._native_volume_plan is None or not self._publication_manifest):
            return False
        projection=self._project_inventory_through_publication_manifest(
            self._volume_acquisition_items
        )
        plan=build_unified_volume_plan(
            self._native_volume_plan,self._volume_acquisition_items,projection,
            self.current_source_id,self.current_source.display_name,
        )
        generation=getattr(self,'_workflow_inventory_generation',-1)
        if not self.workflow_state.finalize_volume_inventory(
                generation,self._volume_plan_request_id,
                plan.get('native_volume_count'),plan.get('derived_volume_count'),
                plan.get('unmapped_chapter_count')):
            return False
        self._apply_volume_plan(self._volume_plan_request_id,self.language.currentData(),plan)
        self._log_publication_projection(projection)
        native=int(plan.get('native_volume_count') or 0)
        derived=int(plan.get('derived_volume_count') or 0)
        unmapped=int(plan.get('unmapped_chapter_count') or 0)
        self.add_log(
            f'Unified Volume inventory: {native} native, {derived} derived; '
            f'{unmapped} unmapped chapter' + ('' if unmapped == 1 else 's') + '.'
        )
        return True

    def _volume_resolution_pending(self):
        return (self.workflow_mode == 'volume' and
                self.workflow_state.volume_presentation_state in (
                    'loading_acquisition','resolving_publication','building_groups'))

    def _append_volume_resolution_row(self, title, detail='', compact=False):
        item=QListWidgetItem(); item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setSizeHint(QSize(0,62 if compact else 94)); self.volume_list.addItem(item)
        self.volume_list.setItemWidget(
            item,VolumeResolutionRowWidget(title,detail,compact,self.volume_list)
        )

    def _show_volume_acquisition_loading(self):
        if self.workflow_mode != 'volume':
            return
        self._volume_check_syncing=True
        try:
            self.volume_list.clear()
            self._append_volume_resolution_row('Loading volumes…','Reading downloadable provider inventory')
        finally:
            self._volume_check_syncing=False
        self.volume_list.setEnabled(True); self.volume_count_label.clear()
        self.select_all_btn.setEnabled(False); self.clear_volume_btn.setEnabled(False)
        self.preview_btn.setEnabled(False); self.start.setEnabled(False); self.end.setEnabled(False)
        self.range_hint.setText('Loading downloadable volume information…')
        self._set_selected_inventory_count(0)

    def _show_pending_volume_resolution(self):
        """Hide provisional standalone rows while real publication work is pending."""
        plan=dict(self._native_volume_plan or {})
        native=tuple(plan.get('volumes') or ())
        standalone=int(plan.get('bonus_chapters') or 0)
        self._volume_plan_loading=False
        if native:
            provisional=dict(plan); provisional['bonus_chapters']=0
            self._apply_volume_plan(
                self._volume_plan_request_id,self.language.currentData(),provisional,
                announce_ready=False,
            )
            self._append_volume_resolution_row(
                'Finding additional volumes…',
                f'Evaluating {standalone} ungrouped chapter' + ('' if standalone == 1 else 's'),
                compact=True,
            )
            count=len(native); self.volume_count_label.setText(
                f'{count} volume' + ('' if count == 1 else 's') + ' · Finding additional volumes…'
            )
            self.range_hint.setText('Native volumes are selectable; additional grouping is still resolving.')
        else:
            self._current_plan=None; self._download_language_valid=False
            self._selected_volumes.clear(); self._standalone_selected=False
            self.workflow_state.apply_inventory(
                getattr(self,'_workflow_inventory_generation',-1),()
            )
            self._volume_check_syncing=True
            try:
                self.volume_list.clear()
                self._append_volume_resolution_row(
                    'Resolving volumes…','Matching downloadable chapters to published volumes'
                )
            finally:
                self._volume_check_syncing=False
            self.volume_list.setEnabled(True); self.volume_count_label.setText('Resolving volumes…')
            self.select_all_btn.setEnabled(False); self.clear_volume_btn.setEnabled(False)
            self.start.setEnabled(False); self.end.setEnabled(False)
            self.range_hint.setText('Volume grouping is still resolving…')
            self.selected_inventory_summary.setText('Resolving volumes…')
            self.selected_inventory_summary.setVisible(True)
        self.preview_btn.setEnabled(False); self._update_workflow_actions()

    def _finalize_pending_volume_fallback(self):
        if (self.workflow_mode != 'volume' or self._native_volume_plan is None or
                self.workflow_state.volume_acquisition_state != 'ready'):
            return False
        plan=self._native_volume_plan
        native=len(plan.get('volumes') or ())
        standalone=int(plan.get('bonus_chapters') or 0)
        generation=getattr(self,'_workflow_inventory_generation',-1)
        if not self.workflow_state.finalize_volume_inventory(
                generation,self._volume_plan_request_id,native,0,standalone):
            return False
        self._apply_volume_plan(self._volume_plan_request_id,self.language.currentData(),plan)
        return True

    def _reset_reference_lookup(self):
        self._reference_request_id += 1
        worker=getattr(self,'_reference_worker',None)
        if worker and worker.isRunning():
            worker.requestInterruption()
        self._reference_worker=None
        self._reference_bundle={}; self._reference_volume_covers={}; self._publication_manifest=None

    def _start_reference_lookup(self):
        if not self.loaded_metadata:
            return
        self._reference_request_id += 1
        request_id=self._reference_request_id
        generation=self.workflow_state.selected_record_load_generation
        self.workflow_state.begin_publication_resolution(generation)
        rows=tuple(self.loaded_metadata.get('titles') or ())
        aliases=list(self.loaded_metadata.get('alternate_titles') or ())
        aliases.extend(str(row.get('title') or '') for row in rows if isinstance(row,dict))
        canonical_alias=canonical_reference_alias(self.loaded_metadata.get('title') or '',self._external_candidates)
        trusted_alias=trusted_alias_for_query(self.loaded_metadata.get('title') or '',self._external_candidates)
        if canonical_alias:
            aliases.append(canonical_alias)
        if trusted_alias:
            aliases.append(trusted_alias)
        pending=dict(self._pending_search_result or {})
        reference_aliases=tuple(dict.fromkeys(
            value for value in (
                *(pending.get('canonical_aliases') or ()), canonical_alias, trusted_alias,
            ) if str(value or '').strip()
        ))
        context=canonical_publication_context(self._selected_work_id,{
            'canonical_title':pending.get('canonical_title') or self.loaded_metadata.get('title') or '',
            'trusted_aliases':reference_aliases,
            'canonical_author':pending.get('canonical_author') or self.loaded_metadata.get('author') or '',
            'canonical_creators':pending.get('canonical_creators') or (),
            'canonical_creator_aliases':pending.get('canonical_creator_aliases') or (),
            'provider_author':pending.get('_provider_native_author') or pending.get('author') or '',
            'edition':self._selected_edition,
            'identity_confidence':pending.get('_canonical_identity_confidence') or '',
        })
        if context.shareable:
            evidence=context.lookup_evidence()
            evidence['requested_language']=self.language.currentData() or ''
            self.add_log(
                f'Publication context: {context.canonical_title} / {context.edition_profile}. '
                f'Reference key: {context.reference_key}.'
            )
        else:
            evidence={
                'title':self.loaded_metadata.get('title') or '',
                'aliases':tuple(dict.fromkeys(value for value in aliases if str(value or '').strip())),
                'author':self.loaded_metadata.get('author') or '',
                'edition':self._selected_edition,
            }
        record=self.workflow_state.selected_provider_record or {}
        work_id=context.reference_key or self._selected_work_id or repr(self._provider_record_identity(record))
        worker=self._retain_async_worker(ReferenceLookupWorker(
            request_id,generation,work_id,evidence,self._metadata_search_cache,
        ))
        self._reference_worker=worker
        worker.ready.connect(self._on_reference_lookup_ready)
        worker.finished.connect(lambda w=worker:self._reference_lookup_finished(w))
        worker.start()

    def _reference_lookup_finished(self, worker):
        if self._reference_worker is worker:
            self._reference_worker=None

    def _on_reference_lookup_ready(self, payload):
        if (payload.get('request_id') != self._reference_request_id or
                payload.get('generation') != self.workflow_state.selected_record_load_generation or
                not self.loaded_metadata):
            return
        if self.workflow_mode == 'chapter' and self.workflow_state.chapter_presentation_frozen:
            return
        if payload.get('error'):
            self.add_log('Reference metadata unavailable: '+str(payload.get('error')))
            self.workflow_state.settle_publication_resolution(payload.get('generation'))
            if self.workflow_mode == 'chapter':
                self.workflow_state.settle_publication_structure(
                    payload.get('generation'),'terminal_failure'
                )
                self._try_finalize_chapter_projection()
            elif self.workflow_mode == 'volume':
                self._finalize_pending_volume_fallback()
            return
        bundle=dict(payload.get('result') or {}); self._reference_bundle=bundle
        for source_id,message in dict(bundle.get('errors') or {}).items():
            self.add_log(f'[{source_id}] Reference metadata unavailable: {message}')

        wikipedia=dict(bundle.get('wikipedia') or {})
        book=dict(bundle.get('bookwalker') or {})
        google=dict(bundle.get('google_books') or {})
        errors=dict(bundle.get('errors') or {})
        if not wikipedia and errors.get('wikipedia'):
            wikipedia={'status':'transient_failure','error':errors['wikipedia']}
        if not book and errors.get('bookwalker'):
            book={'status':'transient_failure','error':errors['bookwalker']}
        builder=self._publication_manifest_builder()
        builder.apply_wikipedia(wikipedia).apply_bookwalker(book).apply_google_books(google).apply_enrichment(self._pending_search_result or {})
        manifest=self._promote_publication_manifest(builder)
        if manifest is None:
            return
        if not self.workflow_state.settle_publication_resolution(payload.get('generation')):
            return
        if self.workflow_mode == 'chapter':
            if not self.workflow_state.settle_publication_structure(
                    payload.get('generation'),self._terminal_structure_state(manifest)):
                return

        description=manifest.display.description
        if description.present:
            self.loaded_metadata['description']=description.value
            self._refresh_selected_details(self.loaded_metadata)

        reference_covers={}
        for volume in manifest.volumes:
            if volume.cover and volume.cover.artwork_type == 'exact_volume':
                try:
                    reference_covers[float(volume.key)]=volume.cover.url
                except (TypeError,ValueError):
                    continue
        self._reference_volume_covers=reference_covers
        self._loaded_covers.update(reference_covers)
        edition_art=manifest.display.edition_artwork
        if edition_art:
            self._main_cover_url=str(edition_art.url); self._selected_cover_url=self._main_cover_url

        wikipedia_state=next((row for row in manifest.source_states if row.source == 'wikipedia'),None)
        self.add_log(f'Publication manifest ready: {manifest.work.title or "selected work"}.')
        wikipedia_status=str(wikipedia_state.status if wikipedia_state else
                             wikipedia.get('status') or 'unresolved')
        if wikipedia_status in ('valid_with_data','valid_complete','valid_partial','valid_stale'):
            collection=dict(wikipedia.get('collection') or {})
            root=dict(collection.get('root') or {})
            root_title=(root.get('title') or wikipedia.get('structure_page') or
                        dict(wikipedia.get('match') or {}).get('title') or 'unknown')
            safe_rows=int(collection.get('safe_aggregated_records') or
                          len(wikipedia.get('chapters') or ()))
            quarantined=int(collection.get('quarantined_records') or 0)
            stale=' (last-known-good)' if wikipedia_state and wikipedia_state.cache_state == 'last_known_good' else ''
            partial=' (explicit partial collection)' if wikipedia_status == 'valid_partial' else ''
            self.add_log(f'Wikipedia publication-structure evidence ready{partial}{stale}.')
            self.add_log(
                f'Wikipedia structure: Root: {root_title}; Safe rows: {safe_rows}; '
                f'Volumes: {len(wikipedia.get("volumes") or ())}' +
                (f'; Quarantined: {quarantined}.' if quarantined else '.')
            )
        elif wikipedia_status == 'supported_empty':
            self.add_log('Wikipedia publication structure recognized, but no usable structural rows were produced.')
        elif wikipedia_status == 'unmatched':
            self.add_log('No matching Wikipedia publication root found.')
        elif wikipedia_status in ('ambiguous','ambiguous_collection'):
            self.add_log('Wikipedia publication root remained ambiguous.')
        elif wikipedia_status == 'unsupported_layout':
            self.add_log('Wikipedia publication layout unsupported; provider metadata retained.')
        elif wikipedia_status in ('unsupported_segment','conflict'):
            self.add_log(
                f'Structure: Wikipedia {wikipedia_status.replace("_"," ")}; '
                'provider metadata retained.'
            )
        elif wikipedia_status in ('rate_limited','transient_failure'):
            self.add_log(
                f'Wikipedia publication structure {wikipedia_status.replace("_"," ")}; '
                'no incomplete collection was promoted.'
            )
        else:
            self.add_log('Wikipedia publication structure unresolved; provider metadata retained.')
        bookwalker_cover_count=sum(
            dict(row or {}).get('source') == 'bookwalker' or not dict(row or {}).get('source')
            for row in book.get('covers') or ()
        )
        catalog=dict(book.get('catalog') or {})
        book_range=''
        if catalog.get('minimum_volume') and catalog.get('maximum_volume'):
            book_range=f'; Vol.{catalog["minimum_volume"]}–{catalog["maximum_volume"]}'
        gaps=int(catalog.get('gap_count') or 0)
        pages=int(catalog.get('pages_fetched') or 0)
        if catalog.get('complete') and catalog.get('canonical_complete') is False:
            catalog_state='raw catalog complete; canonical catalog rejected'
        else:
            catalog_state='catalog complete' if catalog.get('complete') else 'catalog partial'
        self.add_log(
            f'BOOK☆WALKER: {bookwalker_cover_count} exact volume covers{book_range}' +
            (f'; {gaps} gaps' if gaps else '') +
            (f'; {pages} page(s); {catalog_state}.' if pages else '.')
        )
        book_match=dict(book.get('match') or {})
        if book:
            self.add_log(
                f'BOOK☆WALKER reference: {book.get("cache_state") or "resolved"}, '
                f'{book_match.get("publication_id") or "unmatched"}, {len(reference_covers)} exact covers.'
            )
            if book.get('cache_state') == 'compatible_hit':
                self.add_log('BOOK☆WALKER reference reused from compatible validated publication identity.')
        if wikipedia.get('cache_state') == 'compatible_hit':
            self.add_log('Wikipedia reference reused from compatible validated publication identity.')
        if google:
            candidates=tuple(google.get('candidates') or ()); covers=tuple(google.get('covers') or ())
            exact=sum(str(row.get('classification') or '').startswith('EXACT_STANDARD') for row in candidates)
            rejected=sum(not row.get('accepted') for row in candidates)
            google_status=str(google.get('status') or '')
            if google_status == 'unavailable_no_api_key':
                self.add_log('Google Books artwork lookup unavailable: no API key configured.')
            elif google_status == 'disabled_by_configuration':
                self.add_log('Google Books artwork fallback disabled by configuration.')
            elif google_status in ('unavailable_publication_context','disabled'):
                self.add_log('Google Books artwork fallback unavailable for this publication context.')
            elif google_status == 'no_remaining_artwork_gaps':
                self.add_log('Google Books: no remaining exact-volume artwork gaps.')
            elif google_status in ('no_compatible_exact_covers','no_discovery_candidates'):
                self.add_log('Google Books artwork fallback: no compatible exact covers found.')
            elif google_status in ('transient_failure','rate_limited'):
                self.add_log(f'Google Books: {google_status.replace("_"," ")}; no incomplete result promoted.')
            elif candidates and not covers:
                self.add_log('Google Books artwork fallback: no compatible exact covers found.')
            elif covers:
                self.add_log(
                    f'Google Books artwork fallback: {len(covers)} exact volume cover(s).'
                )
            else:
                self.add_log(
                    f'Google Books: {len(google.get("target_volumes") or ())} artwork gaps evaluated; '
                    f'{exact} exact English manifestations; {len(covers)} usable exact covers added; '
                    f'{rejected} candidates rejected or retained diagnostically.'
                )

        if self.workflow_mode == 'chapter':
            self._try_finalize_chapter_projection()
        else:
            if not self._refresh_unified_volume_plan():
                self._rebuild_volume_list()
        QTimer.singleShot(0,self._load_visible_volume_thumbs)
        if book or wikipedia:
            self.add_log('Reference metadata retained the acquisition source.')

    def _calibre_work_tags(self, existing=()):
        return merge_calibre_tags(existing,(self.loaded_metadata or {}).get('tags') or (),VL_TAG)

    def _existing_calibre_tags(self, book_id):
        try:
            return tuple(self.db.field_for('tags',book_id) or ())
        except Exception:
            try:
                return tuple(self.db.new_api.field_for('tags',book_id) or ())
            except Exception:
                return ()

    def _set_selected_inventory_count(self, count=0):
        if not hasattr(self,'selected_inventory_summary'):
            return
        count=max(0,int(count or 0))
        noun=('chapter' if self.workflow_mode == 'chapter' else 'volume')
        self.selected_inventory_summary.setText(
            f'{count} {noun}' + ('' if count == 1 else 's') + ' available' if count else ''
        )
        self.selected_inventory_summary.setVisible(bool(count))

    def _clear_selected_details(self):
        for label in (
                self.selected_inventory_summary,self.selected_synopsis,
                self.selected_aliases,self.selected_tags):
            label.clear(); label.setVisible(False)
        if hasattr(self,'selected_synopsis_scroll'):
            self.selected_synopsis_scroll.setVisible(False)

    def _provider_url_for_source(self,source_id):
        """Resolve only already-known provider title URLs; never synthesize one."""
        source_id=str(source_id or '')
        candidates=[]
        if source_id == self.current_source_id:
            candidates.append(self.current_manga_url)
        pending=self._pending_search_result or {}
        if str(pending.get('source_id') or '') == source_id:
            candidates.append(pending.get('url') or pending.get('source_url'))
        for inventory in self._selected_resolution_inventories or ():
            if str(getattr(inventory,'source_id','') or '') == source_id:
                result=getattr(inventory,'result',{}) or {}
                candidates.append(result.get('url') or result.get('source_url'))
        for candidate in candidates:
            safe=safe_provider_public_url(source_id,candidate)
            if safe:
                return safe
        return ''

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
                background:#1B1E21; color:#D8D8D8; border:1px solid #41464B; border-radius:6px;
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
            QCheckBox#mangaSelectionToggle {{ spacing:8px; color:#E7E7E7; font-weight:600; }}
            QProgressBar {{ border:1px solid #3A3F44; border-radius:5px; background:#151719; min-height:11px; }}
            QProgressBar::chunk {{ background:{ORANGE}; border-radius:4px; }}
            QHeaderView::section {{ background:#202428; color:#D8D8D8; border:0; border-bottom:1px solid #383D42; padding:6px; }}
            QTableWidget {{ gridline-color:#292D31; }}
        """)

    def _sync_discovery_top_heights(self):
        try:
            panels=[self._search_top_panel, self._selected_top_panel]
            target=max(p.sizeHint().height() for p in panels)
            for panel in panels:
                panel.setFixedHeight(target)
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

    def _card(self,clear_focus=False):
        f = FocusClearingFrame() if clear_focus else QFrame(); f.setObjectName('card')
        return f

    def _book_gutter(self):
        gutter=QFrame(); gutter.setObjectName('bookGutter'); gutter.setFixedWidth(12)
        gutter.setStyleSheet(
            'QFrame#bookGutter { background:#0D0F10; border-left:1px solid #303438; '
            'border-right:1px solid #25292D; border-radius:4px; }'
        )
        return gutter

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

        # A three-column grid keeps branding on the exact shell center while the
        # independently right-aligned version label occupies the final column.
        header = QGridLayout(); header.setContentsMargins(0,0,0,0); header.setHorizontalSpacing(0)
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
        header.addWidget(brand_group,0,1,Qt.AlignmentFlag.AlignCenter)
        ver = QLabel(SHORT_VERSION_LABEL)
        ver.adjustSize(); ver.setMinimumWidth(ver.sizeHint().width() + 8)
        ver.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ver.setStyleSheet('color:#777; font-size:10px; font-weight:700;')
        header.addWidget(ver,0,2,Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.setColumnStretch(0,1); header.setColumnStretch(2,1)
        shell.addLayout(header)

        stage_header=QHBoxLayout(); stage_header.setSpacing(22)
        stage_header.addStretch(1)
        self.stage_labels={}
        for index,(key,text) in enumerate((
                ('choose_manga','Choose Manga'),('book_customization','Book Customization'),('finalization','Finalization'))):
            label=QLabel(text); label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet('font-size:16px; font-weight:700; color:#F2F2F2; padding:3px 7px;')
            self.stage_labels[key]=label; stage_header.addWidget(label)
            if index < 2:
                separator=QLabel('/'); separator.setStyleSheet('font-size:18px; color:#F2F2F2;')
                stage_header.addWidget(separator)
        stage_header.addStretch(1)
        shell.addLayout(stage_header)

        self.stage_stack=QStackedWidget()
        shell.addWidget(self.stage_stack,1)

        # CHOOSE MANGA: the same two-card/one-gutter book geometry as later stages.
        left = QWidget(); left.setMinimumWidth(520)
        discovery = QHBoxLayout(left); discovery.setContentsMargins(0,0,0,0); discovery.setSpacing(10)
        search_page=self._card()
        lv = QVBoxLayout(search_page); lv.setContentsMargins(14,14,14,14); lv.setSpacing(9)
        lv.addWidget(self.heading('Choose Manga'))

        search_col = QVBoxLayout(); search_col.setSpacing(7)
        lv.addLayout(search_col,1)
        search_top = QWidget()
        search_top_l = QVBoxLayout(search_top); search_top_l.setContentsMargins(0,0,0,0); search_top_l.setSpacing(7)
        mode_label=QLabel('Mode'); mode_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;')
        mode_row=QHBoxLayout(); mode_row.addWidget(mode_label)
        self.volume_mode_btn=QPushButton('Volumes'); self.chapter_mode_btn=QPushButton('Chapters')
        for button in (self.volume_mode_btn, self.chapter_mode_btn):
            button.setCheckable(True); button.setObjectName('modeChoice')
            # Enter in the search field must not activate the dialog's first
            # push button (Volumes) as an implicit default action.
            button.setAutoDefault(False); button.setDefault(False)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(button.sizeHint().width() + 12)
        self.volume_mode_btn.clicked.connect(lambda: self._set_workflow_mode('volume'))
        self.chapter_mode_btn.clicked.connect(lambda: self._set_workflow_mode('chapter'))
        mode_row.addWidget(self.volume_mode_btn); mode_row.addWidget(self.chapter_mode_btn); mode_row.addStretch(1); search_top_l.addLayout(mode_row)
        search_label=QLabel('Search'); search_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;'); search_top_l.addWidget(search_label)
        search_row = QHBoxLayout()
        self.search_box = QLineEdit(); self.search_box.setPlaceholderText('Search manga sources...')
        self.search_box.textChanged.connect(self.workflow_state.set_pending_query)
        self.search_btn = QPushButton('Search'); self.search_btn.setObjectName('secondaryAction'); self.search_btn.clicked.connect(lambda: self.search_mangadex(True))
        self.search_box.returnPressed.connect(lambda: self.search_mangadex(True))
        self.prefer_colored = MangaSelectionCheckBox('Prefer Colored')
        self.prefer_colored.setObjectName('mangaSelectionToggle')
        self.prefer_colored.setChecked(bool(prefs['prefer_colored']))
        self.prefer_colored.toggled.connect(self._prefer_colored_changed)
        search_row.addWidget(self.search_box,1); search_row.addWidget(self.search_btn); search_top_l.addLayout(search_row)
        language_row=QHBoxLayout(); self.download_language_label=QLabel('Download Language')
        self.language=CappedComboBox(max_popup_rows=12); populate_download_languages(self.language, available=None, preferred=prefs['language'])
        language_row.addWidget(self.download_language_label); language_row.addWidget(self.language,1)
        search_top_l.addLayout(language_row)
        search_top_l.addWidget(self.prefer_colored)
        self.mode_helper=QLabel('Choose Volumes or Chapters to begin.')
        self.mode_helper.setStyleSheet('color:#8F9499; font-size:11px;')
        search_top_l.addWidget(self.mode_helper)

        direct_label=QLabel('Direct Link'); direct_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;'); search_top_l.addWidget(direct_label)
        urlrow=QHBoxLayout(); self.url = QLineEdit(); self.url.setPlaceholderText('Paste a supported manga link...')
        self.load_btn = QPushButton('Load'); self.load_btn.setObjectName('secondaryAction'); self.load_btn.clicked.connect(self.load_metadata); self.url.returnPressed.connect(self.load_metadata)
        urlrow.addWidget(self.url,1); urlrow.addWidget(self.load_btn); search_top_l.addLayout(urlrow)
        self._search_top_panel = search_top
        search_col.addWidget(search_top)

        search_results_header=QWidget(); search_results_header.setFixedHeight(36)
        search_results_head=QHBoxLayout(search_results_header); search_results_head.setContentsMargins(0,0,0,0); search_results_head.setSpacing(6)
        self.search_results_label=QLabel('Search Results'); self.search_results_label.setStyleSheet('font-size:11px; font-weight:700; color:#D8D8D8;')
        search_results_head.addWidget(self.search_results_label)
        self.source_status_host=QWidget(); self.source_status_layout=QHBoxLayout(self.source_status_host); self.source_status_layout.setContentsMargins(0,0,0,0); self.source_status_layout.setSpacing(4)
        search_results_head.addWidget(self.source_status_host); search_results_head.addStretch(1); search_col.addWidget(search_results_header)
        self.search_results = QListWidget(); self.search_results.setMinimumHeight(300)
        self.search_results.setIconSize(QSize(78,108)); self.search_results.setSpacing(3); self.search_results.setWordWrap(True)
        self.search_results.setUniformItemSizes(True)
        self.search_results.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.search_results.verticalScrollBar().setSingleStep(14)
        self.search_results.itemClicked.connect(self.use_search_result)
        self.search_results.verticalScrollBar().valueChanged.connect(lambda _v: self._load_visible_search_thumbs())
        search_col.addWidget(self.search_results,1)
        # Keep the paging action in normal layout flow below the scrolling list.
        # A dedicated spacer prevents the final result row from visually touching
        # or appearing underneath the button when the window is vertically tight.
        search_footer=QWidget(); search_footer.setFixedHeight(54)
        search_footer_l=QVBoxLayout(search_footer); search_footer_l.setContentsMargins(0,7,0,7); search_footer_l.setSpacing(0)
        self.show_more_btn=QPushButton('Show More Results'); self.show_more_btn.setObjectName('tertiaryAction'); self.show_more_btn.setFixedHeight(32); self.show_more_btn.setVisible(False); self.show_more_btn.clicked.connect(self._show_more_search_results)
        search_footer_l.addWidget(self.show_more_btn)
        search_col.addWidget(search_footer)
        discovery.addWidget(search_page,1)
        discovery.addWidget(self._book_gutter())

        selected_page=self._card()
        selected_col=QVBoxLayout(selected_page); selected_col.setContentsMargins(14,14,14,14); selected_col.setSpacing(7)
        selected_col.addWidget(self.heading('Selected Manga'))
        selected_top = QWidget(); selected_top.setObjectName('selectedMangaCard'); selected_top.setStyleSheet('QWidget#selectedMangaCard { background:#171A1D; border:1px solid #2C3136; border-radius:7px; }')
        selected_top_l = QVBoxLayout(selected_top); selected_top_l.setContentsMargins(8,7,8,8); selected_top_l.setSpacing(7)
        # Let Qt derive the card's minimum height from its cover, metadata and
        # Alternate Title control. The inventory header is a sibling below it,
        # never an overlay that may consume this button's hit area.
        selected_top_l.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.title=QLineEdit(); self.author=QLineEdit(); self.series=QLineEdit(); self.title.hide(); self.author.hide(); self.series.hide()
        self.alt_titles_btn=QPushButton('Alternate Title...'); self.alt_titles_btn.setObjectName('tertiaryAction'); self.alt_titles_btn.setFixedHeight(32); self.alt_titles_btn.setEnabled(False); self.alt_titles_btn.setVisible(False); self.alt_titles_btn.clicked.connect(self.choose_alternate_title)
        self.selected_cover=CoverLoadingLabel(); self.selected_cover.setFixedSize(150,210); self.selected_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selected_cover.setStyleSheet('background:#121416; color:#FF6740; border:1px solid #34393e; border-radius:6px; font-size:11px; font-weight:800;'); self.selected_cover.setVisible(False)
        self.selected_title=QLabel('No manga selected'); self.selected_title.setWordWrap(True); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignCenter); self.selected_title.setStyleSheet('font-size:12px; font-weight:600; color:#777;')
        self.selected_author=QLabel(''); self.selected_author.setStyleSheet('color:#aaa;')
        self.selected_rating=QLabel(''); self.selected_rating.setStyleSheet('color:#D7B06A; font-size:10px; font-weight:700;')
        self.selected_rating.setVisible(False)
        self.selected_inventory_summary=QLabel(''); self.selected_inventory_summary.setStyleSheet('color:#C7CBCF; font-size:10px; font-weight:600;'); self.selected_inventory_summary.setVisible(False)
        self.selected_synopsis=QLabel(''); self.selected_synopsis.setWordWrap(True); self.selected_synopsis.setStyleSheet('color:#B8BDC2; font-size:10px;'); self.selected_synopsis.setVisible(False)
        self.selected_synopsis_scroll=QScrollArea(); self.selected_synopsis_scroll.setWidgetResizable(True); self.selected_synopsis_scroll.setFrameShape(QFrame.Shape.NoFrame); self.selected_synopsis_scroll.setMaximumHeight(62); self.selected_synopsis_scroll.setMinimumHeight(42); self.selected_synopsis_scroll.setWidget(self.selected_synopsis); self.selected_synopsis_scroll.setVisible(False)
        self.selected_aliases=QLabel(''); self.selected_aliases.setWordWrap(True); self.selected_aliases.setMaximumHeight(34); self.selected_aliases.setStyleSheet('color:#9FA5AA; font-size:9px;'); self.selected_aliases.setVisible(False)
        self.selected_tags=QLabel(''); self.selected_tags.setWordWrap(False); self.selected_tags.setStyleSheet('color:#D6A46C; font-size:9px;'); self.selected_tags.setVisible(False)
        self.edition_badge_host=QWidget(); self.edition_badge_layout=QHBoxLayout(self.edition_badge_host); self.edition_badge_layout.setContentsMargins(0,0,0,0)
        self.edition_badge_host.setVisible(False)
        self.availability_badge=QLabel('Unavailable'); self.availability_badge.setAlignment(Qt.AlignmentFlag.AlignCenter); self.availability_badge.setVisible(False)
        self.availability_badge.setStyleSheet('color:#B7BBC0; border:1px solid #555B61; border-radius:7px; background:#151719; padding:2px 7px; font-weight:700; font-size:11px;')
        selected=QHBoxLayout(); selected.setContentsMargins(0,0,0,0); selected.addWidget(self.selected_cover)
        seltext=QVBoxLayout(); seltext.setContentsMargins(0,0,0,0); seltext.addWidget(self.selected_title); seltext.addWidget(self.selected_author); seltext.addWidget(self.selected_rating)
        badge_row=QHBoxLayout(); badge_row.setContentsMargins(0,0,0,0)
        self.selected_source_host=QWidget(); self.selected_source_layout=QHBoxLayout(self.selected_source_host); self.selected_source_layout.setContentsMargins(0,0,0,0)
        badge_row.addWidget(self.selected_source_host); badge_row.addWidget(self.edition_badge_host); badge_row.addWidget(self.availability_badge); badge_row.addStretch(1); seltext.addLayout(badge_row)
        seltext.addWidget(self.selected_inventory_summary); seltext.addWidget(self.selected_synopsis_scroll)
        seltext.addWidget(self.selected_aliases); seltext.addWidget(self.selected_tags)
        seltext.addStretch(1)
        selected.addLayout(seltext,1); selected_top_l.addLayout(selected,1)
        self._selected_top_panel = selected_top
        selected_col.addWidget(selected_top)

        vols_header=QWidget(); vols_header.setFixedHeight(36)
        vols_head=QHBoxLayout(vols_header); vols_head.setContentsMargins(0,0,0,0); vols_head.setSpacing(6); self.inventory_heading=self.heading('Manga'); vols_head.addWidget(self.inventory_heading); vols_head.addStretch(1)
        self.volume_count_label=QLabel(''); self.volume_count_label.setStyleSheet('color:#999; font-size:11px;'); vols_head.addWidget(self.volume_count_label)
        self.select_all_btn=QPushButton('Select All'); self.select_all_btn.setObjectName('tertiaryAction'); self.select_all_btn.setEnabled(False); self.select_all_btn.clicked.connect(self._select_all_inventory)
        self.clear_volume_btn=QPushButton('Clear'); self.clear_volume_btn.setObjectName('tertiaryAction'); self.clear_volume_btn.setEnabled(False); self.clear_volume_btn.clicked.connect(self._clear_inventory_selection)
        vols_head.addWidget(self.select_all_btn); vols_head.addWidget(self.clear_volume_btn); selected_col.addWidget(vols_header)
        self.volume_list=QListWidget(); self.volume_list.setMinimumHeight(185); self.volume_list.setEnabled(False)
        self.volume_list.setSpacing(3); self.volume_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel); self.volume_list.verticalScrollBar().setSingleStep(18)
        self.volume_list.verticalScrollBar().valueChanged.connect(lambda _v: self._load_visible_volume_thumbs()); selected_col.addWidget(self.volume_list,1)
        # Hidden compatibility values keep the downloader's established call
        # shape while High Priestess removes the obsolete Volume Range UI.
        self.start=QLineEdit(); self.end=QLineEdit(); self.start.hide(); self.end.hide()
        self.range_hint=QLabel('Choose Volumes or Chapters to begin.')
        self.range_hint.setWordWrap(True); self.range_hint.setMinimumHeight(18); self.range_hint.setStyleSheet('color:#8F9499; font-size:11px;')
        selected_col.addWidget(self.range_hint)
        self.meta_summary=QLabel(''); self.meta_summary.setVisible(False)
        discovery.addWidget(selected_page,1)
        self._choose_stage_panel=left
        self.stage_stack.addWidget(left)

        # BOOK CUSTOMIZATION: reading/layout choices and explicit inline preview.
        center=QWidget(); output_pages=QHBoxLayout(center); output_pages.setContentsMargins(0,0,0,0); output_pages.setSpacing(10)
        settings_left=self._card(); cv=QVBoxLayout(settings_left); cv.setContentsMargins(18,16,18,16); cv.setSpacing(10)
        cv.addWidget(self.heading('Reading & Layout'))
        cv.addWidget(QLabel('Output Layout'))
        choices=QHBoxLayout(); choices.setSpacing(7)
        self.portrait_btn=QPushButton('PORTRAIT\nIndividual Pages'); self.portrait_btn.setObjectName('layoutChoice'); self.portrait_btn.setCheckable(True)
        self.landscape_btn=QPushButton('LANDSCAPE\nPaired Pages'); self.landscape_btn.setObjectName('layoutChoice'); self.landscape_btn.setCheckable(True)
        self.portrait_btn.setIcon(self._layout_icon(False)); self.landscape_btn.setIcon(self._layout_icon(True)); self.portrait_btn.setIconSize(QSize(38,28)); self.landscape_btn.setIconSize(QSize(38,28))
        choices.addWidget(self.portrait_btn,1); choices.addWidget(self.landscape_btn,1); cv.addLayout(choices)
        self.page_layout=QComboBox(); self.page_layout.addItem('Portrait (Individual Pages)','original_pages'); self.page_layout.addItem('Landscape (Paired Pages)','paired_landscape')
        pli=self.page_layout.findData(prefs['page_layout']); self.page_layout.setCurrentIndex(max(0,pli)); self.page_layout.hide()
        self.portrait_btn.clicked.connect(lambda: self._choose_layout('original_pages'))
        self.landscape_btn.clicked.connect(lambda: self._choose_layout('paired_landscape'))

        self.reading_direction_label=QLabel('Reading Direction')
        self.reading_direction=QComboBox(); self.reading_direction.addItem('Right to Left (Manga)','rtl'); self.reading_direction.addItem('Left to Right','ltr')
        rdi=self.reading_direction.findData(prefs['reading_direction']); self.reading_direction.setCurrentIndex(max(0,rdi))
        cv.addWidget(self.reading_direction_label); cv.addWidget(self.reading_direction); cv.addStretch(1)

        live_right=self._card(); live_layout=QVBoxLayout(live_right); live_layout.setContentsMargins(22,18,22,18); live_layout.setSpacing(10)
        live_layout.addWidget(self.heading('Live eReader Preview'))
        self.live_preview_status=QLabel('Preview is optional and off. Enable it to download a small bounded sample.')
        self.live_preview_status.setWordWrap(True); self.live_preview_status.setStyleSheet('color:#B8B8B8; font-size:12px;')
        live_layout.addWidget(self.live_preview_status)
        self.pairing_preview_btn=QPushButton('Enable Live Preview'); self.pairing_preview_btn.setObjectName('secondaryAction'); self.pairing_preview_btn.setEnabled(False); self.pairing_preview_btn.clicked.connect(self.open_pairing_preview)
        live_layout.addWidget(self.pairing_preview_btn,0,Qt.AlignmentFlag.AlignLeft)
        self.live_preview_empty=QLabel('No preview sample loaded.\n\nPreview is never required to continue.')
        self.live_preview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter); self.live_preview_empty.setWordWrap(True)
        self.live_preview_empty.setMinimumHeight(220); self.live_preview_empty.setStyleSheet('background:#121416; color:#777; border:1px solid #34393E; border-radius:7px;')
        live_layout.addWidget(self.live_preview_empty,1)
        self.live_preview_scroll=QScrollArea(); self.live_preview_scroll.setWidgetResizable(True); self.live_preview_scroll.setVisible(False)
        self.live_preview_body=QWidget(); self.live_preview_grid=QGridLayout(self.live_preview_body); self.live_preview_grid.setContentsMargins(8,8,8,8); self.live_preview_grid.setSpacing(8)
        self.live_preview_scroll.setWidget(self.live_preview_body); live_layout.addWidget(self.live_preview_scroll,1)
        # Compatibility name retained for state/status helpers; this is an inline
        # Stage 2 surface, not a separate preview window.
        self.live_preview_surface=self.live_preview_empty
        output_pages.addWidget(settings_left,1); output_pages.addWidget(self._book_gutter()); output_pages.addWidget(live_right,1)
        self._book_customization_stage_panel=center
        self.stage_stack.addWidget(center)

        # FINALIZATION: book creation/bulk metadata and factual final outputs.
        right=QWidget(); final_pages=QHBoxLayout(right); final_pages.setContentsMargins(0,0,0,0); final_pages.setSpacing(10)
        settings_right=self._card(clear_focus=True); bcv=QVBoxLayout(settings_right); bcv.setContentsMargins(18,16,18,16); bcv.setSpacing(10)
        bcv.addWidget(self.heading('Book Creation & Metadata'))
        self.chapter_output_widget=QWidget(); chapter_output_layout=QVBoxLayout(self.chapter_output_widget); chapter_output_layout.setContentsMargins(0,0,0,0); chapter_output_layout.setSpacing(6)
        chapter_output_layout.addWidget(QLabel('Chapter Output'))
        self.chapter_output_combo=QComboBox()
        self.chapter_output_combo.addItem('Build CBZs from Volume Data', ChapterOutputMode.DETECTED_VOLUMES.value)
        self.chapter_output_combo.addItem('Manually Group Chapters into Volumes', ChapterOutputMode.MANUAL_VOLUMES.value)
        self.chapter_output_combo.addItem('Save Each Chapter as Its Own CBZ', ChapterOutputMode.INDIVIDUAL_CHAPTERS.value)
        self.chapter_output_combo.currentIndexChanged.connect(self._chapter_output_mode_changed)
        chapter_output_layout.addWidget(self.chapter_output_combo)
        self.chapter_output_reason=QLabel(''); self.chapter_output_reason.setWordWrap(True); self.chapter_output_reason.setStyleSheet('color:#A9ADB1; font-size:11px;')
        chapter_output_layout.addWidget(self.chapter_output_reason)
        manual_summary_row=QHBoxLayout(); self.manual_group_summary=QLabel(''); self.manual_group_summary.setStyleSheet('color:#D8D8D8; font-size:11px;')
        self.edit_manual_groups_btn=QPushButton('Edit Groups'); self.edit_manual_groups_btn.setObjectName('tertiaryAction'); self.edit_manual_groups_btn.clicked.connect(self._edit_manual_groups)
        manual_summary_row.addWidget(self.manual_group_summary,1); manual_summary_row.addWidget(self.edit_manual_groups_btn)
        chapter_output_layout.addLayout(manual_summary_row)
        self.chapter_output_widget.setVisible(False); bcv.addWidget(self.chapter_output_widget)
        self.volume_output_note=QLabel('Selected volumes will be created as individual CBZ files.')
        self.volume_output_note.setWordWrap(True); self.volume_output_note.setStyleSheet('color:#D8D8D8; font-size:12px;')
        bcv.addWidget(self.volume_output_note)
        self.covers=QCheckBox('Use source volume cover in Calibre metadata'); self.covers.setChecked(prefs['include_volume_covers'])
        self.pad=QCheckBox('Zero-pad volume numbers (Recommended)'); self.pad.setChecked(prefs['zero_pad'])
        for metadata_field in (self.title,self.series,self.author):
            metadata_field.setMinimumWidth(360)
            metadata_field.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        metadata_form=QFormLayout(); metadata_form.setSpacing(8)
        metadata_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        metadata_form.addRow('Title',self.title); metadata_form.addRow('Series',self.series); metadata_form.addRow('Author',self.author)
        self.title.show(); self.series.show(); self.author.show(); bcv.addLayout(metadata_form)
        metadata_actions=QHBoxLayout()
        self.apply_metadata_btn=QPushButton('Apply Metadata'); self.apply_metadata_btn.setObjectName('secondaryAction'); self.apply_metadata_btn.setEnabled(False); self.apply_metadata_btn.clicked.connect(self.apply_metadata)
        self.metadata_pending_label=QLabel('Metadata applied'); self.metadata_pending_label.setStyleSheet('color:#8F9499; font-size:11px;')
        metadata_actions.addWidget(self.apply_metadata_btn); metadata_actions.addWidget(self.metadata_pending_label); metadata_actions.addStretch(1)
        bcv.addLayout(metadata_actions)
        bcv.addWidget(self.alt_titles_btn); bcv.addWidget(self.covers); bcv.addWidget(self.pad)
        dest=QLabel(f'Calibre library\n{getattr(self.gui.current_db,"library_path","Current calibre library")}')
        dest.setWordWrap(True); dest.setStyleSheet('color:#A8A8A8; padding-top:4px;')
        bcv.addWidget(QLabel('Destination')); bcv.addWidget(dest)
        self.rebuild_finalization_btn=QPushButton('Refresh Final Outputs'); self.rebuild_finalization_btn.setObjectName('secondaryAction'); self.rebuild_finalization_btn.setVisible(False); self.rebuild_finalization_btn.clicked.connect(self.continue_preview)
        bcv.addWidget(self.rebuild_finalization_btn,0,Qt.AlignmentFlag.AlignLeft); bcv.addStretch(1)
        review_left=self._card(clear_focus=True); rv=QVBoxLayout(review_left); rv.setContentsMargins(16,14,16,14); rv.setSpacing(8)
        preview_header_box=QWidget(); preview_header_box.setFixedHeight(38)
        preview_head=QHBoxLayout(preview_header_box); preview_head.setContentsMargins(0,0,0,0); preview_head.setAlignment(Qt.AlignmentFlag.AlignTop)
        preview_title=self.heading('Final Outputs')
        preview_head.addWidget(preview_title,0,Qt.AlignmentFlag.AlignTop); preview_head.addStretch(1)
        rv.addWidget(preview_header_box)
        self.preview_summary=QLabel('Final Outputs will be prepared after Next: Finalization.')
        self.preview_summary.setWordWrap(True); self.preview_summary.setMinimumHeight(66); self.preview_summary.setMaximumHeight(86); self.preview_summary.setAlignment(Qt.AlignmentFlag.AlignTop); self.preview_summary.setStyleSheet('color:#B8B8B8;')
        rv.addWidget(self.preview_summary)
        self.preview_table=QTableWidget(0,7); self.preview_table.setHorizontalHeaderLabels(['Use','Cover','Type','Title','Source','Pages','Status'])
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers); self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.cellClicked.connect(self._review_focus_changed)
        self.preview_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel); self.preview_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.preview_table.setAlternatingRowColors(True); self.preview_table.verticalHeader().setVisible(False)
        self.preview_table.verticalHeader().setMinimumSectionSize(76); self.preview_table.verticalHeader().setDefaultSectionSize(80)
        ph=self.preview_table.horizontalHeader(); ph.setStretchLastSection(False); ph.setMinimumSectionSize(36); ph.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setFixedHeight(36)
        ph.setStyleSheet('QHeaderView::section { background:#202428; color:#D8D8D8; border:0; border-right:1px solid #383D42; border-bottom:1px solid #383D42; padding:8px 6px; }')
        # Keep the Use column wide enough for the 22px round selector plus breathing room.
        ph.setSectionResizeMode(0,QHeaderView.ResizeMode.Fixed)
        self.preview_table.setColumnWidth(0,54)
        ph.setSectionResizeMode(1,QHeaderView.ResizeMode.Fixed); self.preview_table.setColumnWidth(1,58)
        ph.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        ph.setSectionResizeMode(4,QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(5,QHeaderView.ResizeMode.ResizeToContents)
        ph.setSectionResizeMode(6,QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.setVisible(True)
        rv.addWidget(self.preview_table,1)

        final_pages.addWidget(settings_right,1); final_pages.addWidget(self._book_gutter()); final_pages.addWidget(review_left,1)
        self._finalization_stage_panel=right
        self.stage_stack.addWidget(right)

        # Provider-search progress owns only Stage 1 search tasks. Preview,
        # Finalization, and download work use a separate strip in the same card.
        self.progress_card=self._card(); pv=QVBoxLayout(self.progress_card); pv.setContentsMargins(12,7,12,8); pv.setSpacing(5)
        self.search_progress_widget=QWidget(); search_progress_layout=QVBoxLayout(self.search_progress_widget); search_progress_layout.setContentsMargins(0,0,0,0); search_progress_layout.setSpacing(5)
        search_statrow=QHBoxLayout(); self.search_progress_text=QLabel('Search ready'); self.search_progress_text.setStyleSheet('color:#D8D8D8; font-size:11px;')
        search_statrow.addWidget(self.search_progress_text); search_statrow.addStretch(1); search_progress_layout.addLayout(search_statrow)
        self.search_progress=MangaNanaProgressBar(); self.search_progress.setRange(0,1); self.search_progress.setValue(0); self.search_progress.setTextVisible(False); self.search_progress.setVisible(False); search_progress_layout.addWidget(self.search_progress)
        self.search_progress_widget.setVisible(False); pv.addWidget(self.search_progress_widget)
        self.work_progress_widget=QWidget(); work_layout=QVBoxLayout(self.work_progress_widget); work_layout.setContentsMargins(0,3,0,0); work_layout.setSpacing(5)
        statrow=QHBoxLayout(); self.progress_text=QLabel('Ready'); self.progress_text.setStyleSheet('color:#D8D8D8; font-size:11px;')
        statrow.addWidget(self.progress_text); statrow.addStretch(1); work_layout.addLayout(statrow)
        self.progress=MangaNanaProgressBar(); self.progress.setRange(0,100); self.progress.setValue(0); self.progress.setTextVisible(False); work_layout.addWidget(self.progress)
        self.work_progress_widget.setVisible(False); pv.addWidget(self.work_progress_widget)
        self._search_progress_active=False; self._work_progress_active=False
        self.progress_card.setVisible(False); shell.addWidget(self.progress_card)

        activity=self._card(); av=QVBoxLayout(activity); av.setContentsMargins(12,8,12,9); av.setSpacing(5)
        loghead=QHBoxLayout()
        self.log_toggle_btn=QPushButton('Activity Log  ▸'); self.log_toggle_btn.setObjectName('tertiaryAction'); self.log_toggle_btn.setFlat(True); self.log_toggle_btn.setStyleSheet('QPushButton { text-align:left; padding:4px 6px; border:0; color:#DADADA; font-size:11px; font-weight:700; background:transparent; } QPushButton:hover { color:#FFFFFF; }')
        self.log_toggle_btn.clicked.connect(lambda _checked=False: self._toggle_activity_log())
        loghead.addWidget(self.log_toggle_btn)
        self.activity_status=QLabel('Ready'); self.activity_status.setStyleSheet('color:#9EA3A8; font-size:11px;')
        loghead.addWidget(self.activity_status,1); loghead.addStretch(1)
        self.copy_log_btn=QPushButton('Copy Log'); self.copy_log_btn.setObjectName('tertiaryAction'); self.copy_log_btn.clicked.connect(self.copy_log)
        self.save_log_btn=QPushButton('Save Log'); self.save_log_btn.setObjectName('tertiaryAction'); self.save_log_btn.clicked.connect(self.save_log)
        loghead.addWidget(self.copy_log_btn); loghead.addWidget(self.save_log_btn); av.addLayout(loghead)
        self.log=QListWidget(); self.log.setMaximumHeight(105); self.log.setVisible(False); av.addWidget(self.log); self._activity_log_expanded=False
        shell.addWidget(activity)

        self.workflow_hint=QLabel('Choose Volumes or Chapters to begin.')
        self.workflow_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.workflow_hint.setStyleSheet('color:#9EA3A8; font-size:11px; padding:0 4px 2px 4px;')
        shell.addWidget(self.workflow_hint)

        actions=QHBoxLayout()
        self.back_btn=QPushButton('← Back'); self.back_btn.setObjectName('tertiaryAction'); self.back_btn.clicked.connect(self._back_stage)
        self.preview_btn=QPushButton('Next: Book Customization →'); self.preview_btn.setObjectName('primaryAction'); self.preview_btn.clicked.connect(self._advance_stage); self.preview_btn.setEnabled(False)
        self.download_btn=QPushButton('Download && Add to Calibre'); self.download_btn.setObjectName('primaryAction'); self.download_btn.clicked.connect(self.start_download); self.download_btn.setEnabled(False)
        self.cancel_btn=QPushButton('Cancel'); self.cancel_btn.setObjectName('tertiaryAction'); self.cancel_btn.setEnabled(False); self.cancel_btn.clicked.connect(self.cancel_download)
        self.preferences_btn=QPushButton('Preferences...'); self.preferences_btn.setObjectName('tertiaryAction'); self.preferences_btn.clicked.connect(self.open_preferences)
        self.sources_btn=QPushButton('Manga Sources'); self.sources_btn.setObjectName('tertiaryAction'); self.sources_btn.clicked.connect(self.open_manga_sources)
        self.about_btn=QPushButton('About'); self.about_btn.setObjectName('tertiaryAction'); self.about_btn.clicked.connect(self.show_about)
        actions.addWidget(self.back_btn); actions.addWidget(self.preferences_btn); actions.addWidget(self.sources_btn); actions.addWidget(self.about_btn); actions.addStretch(1); actions.addWidget(self.cancel_btn); actions.addWidget(self.preview_btn); actions.addWidget(self.download_btn)
        shell.addLayout(actions)

        # Match the discovery cards after Qt has calculated the active font/DPI size.
        QTimer.singleShot(0, self._sync_discovery_top_heights)

        watched=[self.title,self.author,self.series]
        for widget in watched: widget.textChanged.connect(self._bulk_metadata_changed)
        self.language.currentIndexChanged.connect(self._download_language_changed); self.covers.toggled.connect(self.invalidate_preview); self.pad.toggled.connect(self.invalidate_preview)
        self.page_layout.currentIndexChanged.connect(self._layout_mode_changed); self.reading_direction.currentIndexChanged.connect(self.invalidate_preview)
        self._layout_mode_changed(); self._update_volume_selection_hint()
        self.search_box.setEnabled(False); self.search_btn.setEnabled(False)
        self.url.setEnabled(False); self.load_btn.setEnabled(False)
        self._set_stage('choose_manga')

    def _set_stage(self, stage):
        self.workflow_state.go_to(stage)
        panels={
            'choose_manga':self._choose_stage_panel,
            'book_customization':self._book_customization_stage_panel,
            'finalization':self._finalization_stage_panel,
        }
        self.stage_stack.setCurrentWidget(panels[stage])
        for key,label in self.stage_labels.items():
            color=ORANGE if key == stage else '#F2F2F2'
            underline=f'border-bottom:2px solid {ORANGE};' if key == stage else 'border-bottom:2px solid transparent;'
            label.setStyleSheet(f'font-size:16px; font-weight:700; color:{color}; padding:3px 7px; {underline}')
        self.back_btn.setVisible(stage != 'choose_manga')
        self.preview_btn.setVisible(stage != 'finalization')
        self.download_btn.setVisible(stage == 'finalization')
        self.cancel_btn.setVisible(self.cancel_btn.isEnabled())
        self._sync_progress_visibility()
        if stage == 'choose_manga':
            self.preview_btn.setText('Next: Book Customization →')
        elif stage == 'book_customization':
            self.preview_btn.setText('Next: Finalization →')
            # Eligibility comes from the inherited current state, not a fresh
            # Portrait/Landscape click in this visit.
            self._update_live_preview_action()
        self._update_workflow_actions()

    def _sync_progress_visibility(self):
        search_visible=bool(self._search_progress_active and self.workflow_state.stage == 'choose_manga')
        work_visible=bool(self._work_progress_active)
        self.search_progress_widget.setVisible(search_visible)
        self.work_progress_widget.setVisible(work_visible)
        self.progress_card.setVisible(search_visible or work_visible)

    def _set_search_progress_visible(self, visible):
        self._search_progress_active=bool(visible)
        self._sync_progress_visibility()

    def _set_work_progress_visible(self, visible):
        self._work_progress_active=bool(visible)
        self._sync_progress_visibility()

    def _set_cancel_action(self, enabled, label='Cancel'):
        self.cancel_btn.setText(str(label or 'Cancel'))
        self.cancel_btn.setEnabled(bool(enabled))
        self.cancel_btn.setVisible(bool(enabled))

    def _advance_stage(self):
        if self.workflow_state.stage == 'choose_manga':
            try:
                self.validate_details()
            except Exception as exc:
                self.workflow_hint.setText(str(exc))
                return
            self._set_stage('book_customization')
            self.workflow_hint.setText('Choose reading layout. Live Preview is optional.')
            return
        if self.workflow_state.stage == 'book_customization':
            try:
                self.validate_details()
            except Exception as exc:
                self.workflow_hint.setText(str(exc))
                return
            self._set_stage('finalization')
            self.workflow_hint.setText('Preparing Finalization…')
            self.continue_preview()

    def _back_stage(self):
        if self.workflow_state.stage == 'finalization':
            self._invalidate_inflight_preview()
            self._set_stage('book_customization')
            self.workflow_hint.setText('Book Customization restored. Finalization will rebuild only after Next.')
        elif self.workflow_state.stage == 'book_customization':
            self._set_stage('choose_manga')
            self.workflow_hint.setText('Search results, provider selection, and inventory choices preserved.')

    def _clear_active_provider_selection(self, message='No manga selected'):
        self._manga_request_id += 1; self._volume_plan_request_id += 1
        self._selected_fallback_request_id += 1
        if self._selected_fallback_worker and self._selected_fallback_worker.isRunning():
            self._selected_fallback_worker.requestInterruption()
        self._selected_fallback_worker=None; self._active_fallback_source=None
        self.workflow_state.clear_selection()
        self.loaded_metadata=None; self.current_manga_url=''; self._current_plan=None
        self._chapter_plan_items=(); self._chapter_acquisition_items=(); self._volume_acquisition_items=(); self._native_volume_plan=None; self._chapter_acquisition_error=''; self._selected_chapter_ids.clear(); self._selected_volumes.clear()
        self._standalone_selected=False; self._using_entire_series=False
        self._download_language_valid=False; self._loaded_covers={}; self._main_cover_url=''
        self._set_applied_metadata('','','')
        self.selected_cover.clear(); self.selected_cover.setVisible(False)
        self.selected_title.setText('No manga selected'); self.selected_author.clear(); self.selected_rating.clear(); self.selected_rating.setVisible(False)
        self._clear_selected_details()
        self._set_selected_source_badge(); self._set_edition_badge(''); self.availability_badge.setVisible(False)
        self.volume_list.clear(); self.volume_list.setEnabled(False); self.select_all_btn.setEnabled(False); self.clear_volume_btn.setEnabled(False)
        self.preview_btn.setEnabled(False); self.download_btn.setEnabled(False)
        self.workflow_hint.setText(message)

    def _set_workflow_mode(self, mode):
        """Choose an explicit workflow and discard mode-specific stale state."""
        if mode not in ('volume', 'chapter'):
            return
        if self.workflow_mode == mode:
            self.volume_mode_btn.setChecked(mode == 'volume'); self.chapter_mode_btn.setChecked(mode == 'chapter')
            return
        if (self.loaded_metadata and self.current_manga_url and self._publication_manifest and
                self._reference_bundle and self._reference_worker is None):
            self._switch_resolved_workflow_mode(mode)
            return
        self.workflow_mode=mode
        self.workflow_state.change_mode(mode)
        self._invalidate_cover_requests()
        self._mode_generation += 1
        self._search_request_id += 1; self._inventory_comparison_request_id += 1
        self._search_resolution_request_id += 1; self._enrichment_request_id += 1
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
        if self._enrichment_worker and self._enrichment_worker.isRunning():
            self._enrichment_worker.requestInterruption()
        self._enrichment_worker=None; self._external_candidates=(); self._late_enrichment_by_provider={}
        if self.inventory_comparison_worker and self.inventory_comparison_worker.isRunning():
            self.inventory_comparison_worker.requestInterruption()
        self.inventory_comparison_worker=None
        if self._selected_fallback_worker and self._selected_fallback_worker.isRunning():
            self._selected_fallback_worker.requestInterruption()
        self._selected_fallback_worker=None; self._selected_fallback_request_id += 1
        self._active_fallback_source=None
        self.volume_mode_btn.setChecked(mode == 'volume'); self.chapter_mode_btn.setChecked(mode == 'chapter')
        self.search_box.setEnabled(True); self.search_btn.setEnabled(True); self.url.setEnabled(True); self.load_btn.setEnabled(True)
        self._chapter_plan_items=(); self._chapter_acquisition_items=(); self._volume_acquisition_items=(); self._native_volume_plan=None; self._chapter_acquisition_error=''; self._selected_chapter_ids.clear(); self._pending_cross_source_plan=None
        self._selected_resolution_inventories=(); self._selected_work_id=''; self._selected_edition='original'
        self._chapter_volume_evidence=None; self._manual_volume_assignments={}
        self._chapter_output_mode=ChapterOutputMode.INDIVIDUAL_CHAPTERS
        self._chapter_output_user_selected=False
        self._invalidate_inflight_preview()
        if self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_worker.cancel()
        self._selected_volumes.clear(); self._standalone_selected=False; self._using_entire_series=False
        self._current_plan=None; self._download_language_valid=False; self._last_inventory_decision=None
        self.loaded_metadata=None; self.current_manga_url=''; self._loaded_covers={}; self._main_cover_url=''
        self._pending_search_language=''
        self.search_results.clear(); self._search_content_results=[]; self._search_raw_results=[]; self.show_more_btn.setVisible(False)
        self._set_applied_metadata('','',''); self.selected_cover.clear(); self.selected_cover.setVisible(False)
        self.selected_title.setText('No manga selected'); self.selected_author.clear(); self.selected_rating.clear(); self.selected_rating.setVisible(False); self._set_selected_source_badge(); self._set_edition_badge(''); self.availability_badge.setVisible(False)
        self._clear_selected_details()
        self.volume_list.clear(); self.volume_list.setEnabled(False); self.select_all_btn.setEnabled(False); self.clear_volume_btn.setEnabled(False)
        self.inventory_heading.setText('Volumes' if mode == 'volume' else 'Chapters')
        self.chapter_output_widget.setVisible(mode == 'chapter')
        self.volume_output_note.setVisible(mode == 'volume')
        self._refresh_chapter_output_options()
        self.covers.setText('Use series cover in Calibre metadata' if mode == 'chapter' else 'Use source volume cover in Calibre metadata')
        self.pad.setText('Zero-pad chapter numbers (Recommended)' if mode == 'chapter' else 'Zero-pad volume numbers (Recommended)')
        self._clear_preview_state('Final Outputs will be prepared after Next: Finalization.')
        self._reset_live_preview('Content changed. Enable Live Preview after selecting a manga and inventory.')
        self._set_cancel_action(False)
        self.meta_summary.clear(); self.search_progress.setRange(0,1); self.search_progress.setValue(0); self._set_search_progress_visible(False); self.search_progress_text.setText(f'{mode.title()} mode selected. Search again to load availability.')
        self._set_work_progress_visible(False)
        mode_name='Volumes' if mode == 'volume' else 'Chapters'
        self.workflow_hint.setText(f'Mode changed to {mode_name}. Search again to find {mode[:-1] if mode.endswith("s") else mode}-compatible results.')
        self.mode_helper.setText(f'Mode changed to {mode_name}. Search again to find {mode}-compatible results.')
        self.add_log(f'{mode.title()} mode selected.')

    def _switch_resolved_workflow_mode(self, mode):
        """Reuse a fully resolved selected work without repeating discovery."""
        record=dict(self.workflow_state.selected_provider_record or {})
        if not record:
            provider_id=self.current_source.parse_manga_ref(self.current_manga_url)
            record={'source_id':self.current_source_id,'source_name':self.current_source.display_name,
                    'id':str(provider_id or self.current_manga_url),'url':self.current_manga_url,
                    'title':self.loaded_metadata.get('title') or 'Untitled'}
        manifest=self._publication_manifest
        self.workflow_mode=mode; self._mode_generation += 1
        self.workflow_state.change_mode(mode)
        self._workflow_inventory_generation=self.workflow_state.select_provider(record)
        self.workflow_state.apply_publication_manifest(self._workflow_inventory_generation,manifest)
        self.workflow_state.settle_publication_resolution(self._workflow_inventory_generation)
        self.volume_mode_btn.setChecked(mode == 'volume'); self.chapter_mode_btn.setChecked(mode == 'chapter')
        self._volume_plan_request_id += 1
        for worker in list(self._plan_workers):
            if worker.isRunning(): worker.requestInterruption()
        self._invalidate_inflight_preview(); self._clear_preview_state('Final Outputs will rebuild after Next: Finalization.')
        self._reset_live_preview('Content changed. Enable Live Preview after selecting inventory.')
        self._selected_volumes.clear(); self._selected_chapter_ids.clear()
        self._standalone_selected=False; self._using_entire_series=False
        self._current_plan=None; self._chapter_plan_items=(); self._chapter_acquisition_items=()
        self._volume_acquisition_items=(); self._native_volume_plan=None
        self._chapter_acquisition_error=''; self._chapter_volume_evidence=None
        self._manual_volume_assignments={}; self._chapter_output_user_selected=False
        self._download_language_valid=False
        self.volume_list.clear(); self.volume_list.setEnabled(False)
        self.inventory_heading.setText('Volumes' if mode == 'volume' else 'Chapters')
        self.chapter_output_widget.setVisible(mode == 'chapter'); self.volume_output_note.setVisible(mode == 'volume')
        self._refresh_chapter_output_options()
        self.covers.setText('Use series cover in Calibre metadata' if mode == 'chapter' else 'Use source volume cover in Calibre metadata')
        self.pad.setText('Zero-pad chapter numbers (Recommended)' if mode == 'chapter' else 'Zero-pad volume numbers (Recommended)')
        self.mode_helper.setText(f'{mode.title()} mode selected for the resolved manga; cached metadata and artwork retained.')
        self.add_log(f'{mode.title()} mode selected; resolved publication metadata reused.')
        self._load_volume_plan()

    def _choose_layout(self, mode):
        idx=self.page_layout.findData(mode)
        if idx >= 0 and self.page_layout.currentIndex() != idx:
            self.page_layout.setCurrentIndex(idx)
        else:
            self._layout_mode_changed()

    def _prefer_colored_changed(self, checked):
        prefs['prefer_colored'] = bool(checked)
        self.workflow_state.prefer_colored = bool(checked)
        try:
            prefs.commit()
        except Exception:
            pass
        # Prefer Colored is a local ordering preference.  It never promotes
        # pending widget text to an executed query and never starts networking.
        if self._search_query and self._search_raw_results and not self.search_workers:
            self._render_provider_search_results()
            QTimer.singleShot(0,self._load_visible_search_thumbs)

    def _search_score(self, query, title, author=''):
        return MangaDexSearchWorker.score(query, title)

    def _cleanup_worker(self, worker, collection):
        try:
            if worker in collection:
                collection.remove(worker)
        except Exception:
            pass

    def _retain_async_worker(self, worker):
        """Own a browsing worker through QThread.finished."""
        self._async_workers.add(worker)
        worker.finished.connect(lambda w=worker:self._release_async_worker(w))
        return worker

    def _release_async_worker(self, worker):
        self._async_workers.discard(worker)
        worker.deleteLater()

    def _interrupt_async_workers(self):
        for worker in tuple(self._async_workers):
            if worker.isRunning():
                worker.requestInterruption()

    def search_mangadex(self, reset=True, expected_generation=None):
        """Compatibility name for the provider-neutral coordinated search."""
        if self.workflow_mode not in ('volume', 'chapter'):
            info_dialog(self, 'Choose workflow', 'Choose Volumes or Chapters before searching.', show=True)
            return
        if expected_generation is not None and expected_generation != self._mode_generation:
            return
        mode=self.workflow_mode; generation=self._mode_generation
        self._diagnostic_operation='provider search'
        query=(self.search_box.text().strip() if reset else self._search_query)
        if not query:
            return
        if any(worker.isRunning() for worker in self.search_workers.values()):
            return
        if reset:
            participating = enabled_sources(SOURCE_REGISTRY, prefs)
            if not participating:
                self.search_btn.setEnabled(True); self.search_btn.setText('Search')
                self._set_cancel_action(False); self.show_more_btn.setVisible(False)
                self.search_progress.setRange(0,1); self.search_progress.setValue(0)
                self._set_search_progress_visible(False)
                self.search_progress_text.setText('No manga sources are enabled.')
                self.workflow_hint.setText('Open Manga Sources to enable at least one source.')
                return
            self.search_coordinator = SourceCoordinator(SOURCE_REGISTRY, participating)
            self.workflow_state.set_pending_query(query)
            self._workflow_search_generation=self.workflow_state.execute_search(
                source.source_id for source in participating
            )
        self._search_request_id += 1; search_request_id=self._search_request_id
        self._search_resolution_request_id += 1
        self._search_resolution_complete=False
        if self._search_resolution_worker and self._search_resolution_worker.isRunning():
            self._search_resolution_worker.requestInterruption()
        self._search_resolution_worker=None; self._search_resolutions={}; self._search_ranked_groups=()
        self._search_cancel_requested=False; self._search_started_at=time.monotonic()
        if reset:
            self._last_discovery_kind='search'; self._last_discovery_value=query
            # A fetch failure is transient UI state, never durable provider
            # metadata. A normal new search retries the exact record.
            self._failed_image_urls.clear()
            self._pending_search_language=''
            self._search_query=query
            self._search_resolution_complete=False
            self._active_query_cache_key=query_cache_key(
                query, mode, prefs['language'], prefs['show_adult_search_results'],
                (source.source_id for source in self.search_coordinator.sources),
                prefs['prefer_colored'], prefs['search_enrichment'],
            )
            hit=self._metadata_search_cache.get_query_snapshot(self._active_query_cache_key)
            snapshot=dict(hit.value) if hit is not None else {}
            if hit is not None and hit.fresh and snapshot.get('final') and not final_search_records(snapshot):
                self._metadata_search_cache.delete('query_snapshot',self._active_query_cache_key)
                hit=None; snapshot={}
            self._search_offsets={source.source_id:0 for source in self.search_coordinator.sources}
            self._search_has_more={source.source_id:False for source in self.search_coordinator.sources}
            self.search_coordinator.reset()
            self._search_content_results=[]
            self._search_raw_results=[]
            self._external_candidates=()
            self._late_enrichment_by_provider={}
            self._enrichment_received=not bool(prefs['search_enrichment'])
            self._alias_retried_sources=set()
            self._search_user_interacted=False
            self._search_loaded_stale_cache=False
            self.search_results.clear()
            self.show_more_btn.setVisible(False)
            if hit is not None and hit.fresh and snapshot.get('final'):
                self._search_content_results=list(
                    snapshot.get('provider_candidates') or snapshot.get('content_results') or ()
                )
                # Final cards are the stable canonical/fitness facts produced
                # by the cold path. Re-rank those facts under current session
                # preferences instead of rebuilding from weaker provider rows.
                self._search_raw_results=list(final_search_records(snapshot))
                self._render_provider_search_results()
                cached_states={
                    str(row.get('source_id') or ''):str(row.get('status') or 'complete')
                    for row in snapshot.get('provider_states') or ()
                }
                for source_id in self.workflow_state.enabled_sources:
                    cached_status=cached_states.get(source_id,'complete')
                    if cached_status == 'failed':
                        self.search_coordinator.fail(source_id,'Cached provider failure')
                        terminal='failure'
                    else:
                        self.search_coordinator.complete(source_id,{'rows':[]})
                        terminal='success'
                    self.workflow_state.settle_provider(
                        self._workflow_search_generation,source_id,terminal
                    )
                self.workflow_state.publish_search_results(
                    self._workflow_search_generation,self._search_content_results
                )
                self._search_offsets.update({str(k):int(v) for k,v in dict(snapshot.get('offsets') or {}).items()})
                self._search_has_more.update({str(k):bool(v) for k,v in dict(snapshot.get('has_more') or {}).items()})
                self.search_btn.setEnabled(True); self.search_btn.setText('Search')
                self._set_cancel_action(False)
                more=any(self._search_has_more.values())
                self.show_more_btn.setVisible(more); self.show_more_btn.setEnabled(more)
                self.search_progress.setRange(0,max(1,len(self.search_coordinator.sources)))
                self.search_progress.setValue(len(self.search_coordinator.sources))
                self._set_search_progress_visible(False)
                self.search_progress.setVisible(False)
                self.search_progress_text.setText('Loaded a fresh cached search result.')
                self._refresh_source_status_pills()
                self._search_resolution_complete=True
                # A warm snapshot contains cover identities, not image bytes.
                # Re-enter the normal visible-row acquisition path after the
                # rows exist so a restart or an evicted pixmap can recover.
                QTimer.singleShot(0,self._load_visible_search_thumbs)
                return
        self.search_btn.setEnabled(False); self.search_btn.setText('Searching...'); self._set_cancel_action(True,'Cancel Search')
        self.show_more_btn.setEnabled(False)
        participating_sources=tuple(
            source for source in self.search_coordinator.sources
            if reset or self._search_has_more.get(source.source_id)
        )
        self._search_provider_ids=tuple(source.source_id for source in participating_sources)
        self._search_display_barrier=ProviderDisplayBarrier(self._search_provider_ids)
        self._search_barrier_consumed=False
        self.search_progress.setRange(0,max(1,len(participating_sources)))
        self.search_progress.setValue(0)
        self._set_search_progress_visible(True)
        self.search_progress.setVisible(True)
        self.search_progress_text.setText('Searching sources…')
        self.search_results_label.setText('Search Results')
        self._search_status_timer.start()
        include_adult=bool(prefs['show_adult_search_results'])
        started=0
        for source in participating_sources:
            offset=self._search_offsets.get(source.source_id,0)
            key=(source.source_id,query.casefold(),offset,self._search_page_size,include_adult,prefs['language'])
            self.search_coordinator.mark_running(source.source_id)
            worker=self._retain_async_worker(SourceSearchWorker(
                source,query,offset,self._search_page_size,include_adult,
                prefs['language'],self._download_availability_cache,
            ))
            self.search_workers[source.source_id]=worker
            worker.ready.connect(lambda payload,k=key,m=mode,g=generation,r=search_request_id:self._on_search_ready(k,payload,m,g,r))
            worker.failed.connect(lambda payload,m=mode,g=generation,r=search_request_id:self._on_search_failed(payload,m,g,r))
            worker.finished.connect(lambda sid=source.source_id,w=worker,m=mode,g=generation,r=search_request_id:self._search_worker_finished(sid,w,m,g,r))
            worker.start(); started += 1
        if reset and bool(prefs['search_enrichment']):
            self._enrichment_request_id += 1
            enrichment_request_id=self._enrichment_request_id
            worker=self._retain_async_worker(EnrichmentSearchWorker(
                enrichment_request_id,ENRICHMENT_REGISTRY,query
            ))
            self._enrichment_worker=worker
            worker.ready.connect(lambda payload,m=mode,g=generation:self._on_enrichment_ready(payload,m,g))
            worker.finished.connect(lambda w=worker:self._enrichment_finished(w))
            worker.start()
        if not started:
            self._finish_coordinated_search()

    def _on_search_ready(self, key, payload, mode=None, generation=None, request_id=None):
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        source_id=payload.get('source_id')
        data=self.search_coordinator.complete(source_id,payload.get('data') or {})
        self._search_display_barrier.settle(source_id,'success',data)
        if reset_generation := getattr(self,'_workflow_search_generation',None):
            self.workflow_state.settle_provider(reset_generation,source_id,'success')
        self._sync_provider_search_progress()
        self._search_cache[key]=data

    def _apply_search_page(self, data):
        context_query=data.get('context_query') or data.get('query')
        if context_query != self._search_query:
            return
        existing={(row.get('source_id'),row.get('id')) for row in self._search_content_results}
        page_offset=int(data.get('offset') or 0)
        for page_index,row in enumerate(data.get('rows') or []):
            mid=row.get('id')
            source_id=row.get('source_id') or data.get('source_id')
            identity=(source_id,mid)
            if not mid or identity in existing:
                continue
            source=SOURCE_REGISTRY.get(source_id)
            url=row.get('url') or (f'https://mangadex.org/title/{mid}' if source_id=='mangadex' else '')
            normalized=dict(row)
            normalized.update({'id':mid,'url':url,'cover_url':row.get('cover_url') or '',
                               'source_id':source_id,'source_name':row.get('source_name') or data.get('source_name'),
                               '_provider_result_order':page_offset+page_index})
            mapping=self._metadata_search_cache.get_provider_mapping(source_id,mid)
            if mapping is not None:
                normalized.update(dict(mapping.value or {}))
            self._search_content_results.append(normalized)
            existing.add(identity)
        source_id=data.get('source_id')
        alias_retry=bool(data.get('alias_retry'))
        if not alias_retry:
            fetched=int(data.get('fetched_count') if data.get('fetched_count') is not None else len(data.get('rows') or []))
            next_offset=data.get('next_offset')
            self._search_offsets[source_id]=int(next_offset if next_offset is not None else int(data.get('offset') or 0)+fetched)
            more=bool(data.get('has_more'))
            self._search_has_more[source_id]=more
        else:
            more=self._search_has_more.get(source_id,False)
        self.show_more_btn.setText('Show More Results')
        request_query=str(data.get('request_query') or data.get('query') or self._search_query)
        action=f'Alias retry “{request_query}” returned' if alias_retry else 'Search returned'
        parts=[f'[{data.get("source_name")}] {action} {len(data.get("rows") or [])} result(s) for “{request_query}”.']
        if more: parts.append('More results are available from this provider.')
        if not prefs['show_adult_search_results']: parts.append('Adult content excluded.')
        filtered=int(data.get('filtered_doujinshi') or 0)
        empty_filtered=int(data.get('filtered_empty') or 0)
        if empty_filtered: parts.append(f'{empty_filtered} title(s) with no downloadable chapters filtered.')
        if filtered: parts.append(f'{filtered} doujinshi result(s) filtered while filling this page.')
        self.add_log(' '.join(parts))

    def _rebuild_enriched_results(self, render=True):
        """Rebuild provider facts; enrichment is a metadata-only overlay."""
        self._search_resolution_complete=False
        self._search_raw_results=[dict(row) for row in self._search_content_results]
        if render:
            self._render_provider_search_results()

    def _apply_late_search_enrichment(self, render=True):
        """Prepare enrichment overlays; rendering is opt-in for stale snapshots only."""
        if not self._external_candidates or not bool(prefs['search_enrichment']):
            return
        enriched=tuple(enrich_content_results(
            self._search_content_results,self._external_candidates,
        ))
        overlays={}
        for row in enriched:
            key=(str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or ''))
            if not all(key):
                continue
            overlays[key]=dict(row)
            if row.get('external_ids'):
                try:
                    self._metadata_search_cache.put_provider_mapping(
                        key[0],key[1],{
                            'external_ids':row.get('external_ids'),
                            'alternate_titles':row.get('alternate_titles') or (),
                            'work_family_id':row.get('work_family_id'),
                            'work_description':row.get('work_description') or '',
                            'work_tags':row.get('work_tags') or (),
                            'canonical_author':row.get('canonical_author') or '',
                            'canonical_creators':row.get('canonical_creators') or (),
                            'canonical_creator_provenance':row.get('canonical_creator_provenance') or '',
                            'canonical_creator_aliases':row.get('canonical_creator_aliases') or (),
                            'canonical_title':row.get('canonical_title') or '',
                            'canonical_aliases':row.get('canonical_aliases') or (),
                            'canonical_work_id':row.get('canonical_work_id') or '',
                        },
                    )
                except Exception:
                    pass
        self._late_enrichment_by_provider=overlays
        if not render:
            return
        # QListWidget order and the exact provider keys are deliberately left
        # untouched. Only metadata on the already-visible cards is enriched.
        for index in range(self.search_results.count()):
            item=self.search_results.item(index); current=item.data(Qt.ItemDataRole.UserRole) or {}
            key=(str(current.get('source_id') or ''),str(current.get('id') or current.get('url') or ''))
            overlay=overlays.get(key)
            if overlay is None:
                continue
            presentation=present_search_candidate(
                current,overlay,current.get('_acquisition_fitness') or AcquisitionFitness.UNKNOWN,
                current.get('_qualification_status') or 'unqualified',
                current.get('_qualification_chapter_count') or 0,
            )
            merged=presentation.as_record()
            merged['source_id']=key[0]
            merged['id']=current.get('id')
            merged['url']=current.get('url')
            merged['provider_key']=current.get('provider_key')
            merged['resolution_state']=current.get('resolution_state')
            item.setData(Qt.ItemDataRole.UserRole,merged)
            widget=self.search_results.itemWidget(item)
            if isinstance(widget,SearchResultRowWidget):
                widget.set_enrichment_metadata(
                    merged.get('title') or '',merged.get('author') or '',
                    merged.get('rating_display') or '',
                )
            selected=self.workflow_state.selected_provider_record or {}
            selected_key=(
                str(selected.get('source_id') or ''),
                str(selected.get('id') or selected.get('url') or ''),
            )
            if selected_key == key:
                self._pending_search_result.update(merged)
                if self.loaded_metadata:
                    self._apply_selected_enrichment(merged)

    def _on_enrichment_ready(self, payload, mode=None, generation=None):
        if (payload.get('request_id') != self._enrichment_request_id or
                payload.get('query') != self._search_query or
                mode != self.workflow_mode or generation != self._mode_generation):
            return
        self._external_candidates=tuple(payload.get('candidates') or ())
        self._enrichment_received=True
        for candidate in self._external_candidates:
            try:
                self._metadata_search_cache.put_external_candidate(candidate)
            except Exception:
                pass
        for service,message in dict(payload.get('errors') or {}).items():
            self.add_log(f'[{service}] Optional search enrichment unavailable: {message}')
        if self._external_candidates and not self._search_user_interacted:
            self.add_log(f'External search enrichment matched {len(self._external_candidates)} bounded candidate(s).')
        self._apply_late_search_enrichment(render=False)
        self._finish_coordinated_search()

    def _enrichment_finished(self, worker):
        if self._enrichment_worker is worker:
            self._enrichment_worker=None
            if not self._enrichment_received:
                self._enrichment_received=True
            self._finish_coordinated_search()

    def _maybe_start_alias_retries(self, mode=None, generation=None):
        if self.search_workers or mode != self.workflow_mode or generation != self._mode_generation:
            return False
        alias=trusted_alias_for_query(self._search_query,self._external_candidates)
        if not alias:
            normalized=normalize_identity_text(self._search_query)
            # One bounded prefix retry repairs exact single-token searches when
            # a provider only exposes the work through a broader family query.
            # Final ranking still uses the original query, so broad noise is gated.
            if ' ' not in normalized and len(normalized) >= 8:
                alias=normalized[:4]
        if not alias or normalize_identity_text(alias) == normalize_identity_text(self._search_query):
            return False
        started=0; started_ids=[]; request_id=self._search_request_id
        for source in self.search_coordinator.sources:
            if source.source_id in self._alias_retried_sources:
                continue
            provider_rows=[row for row in self._search_content_results if row.get('source_id') == source.source_id]
            # Alias retries repair genuinely empty provider searches. Weak
            # provider-local rows remain visible and must not be overwritten.
            if provider_rows:
                continue
            self._alias_retried_sources.add(source.source_id)
            self.search_coordinator.mark_running(source.source_id)
            worker=self._retain_async_worker(SourceSearchWorker(
                source,alias,0,self._search_page_size,bool(prefs['show_adult_search_results']),
                prefs['language'],self._download_availability_cache,
            ))
            self.search_workers[source.source_id]=worker
            worker.ready.connect(lambda payload,m=mode,g=generation,r=request_id:self._on_alias_search_ready(payload,m,g,r))
            worker.failed.connect(lambda payload,a=alias,m=mode,g=generation,r=request_id:self._on_alias_search_failed(payload,a,m,g,r))
            worker.finished.connect(lambda sid=source.source_id,w=worker,m=mode,g=generation,r=request_id:self._search_worker_finished(sid,w,m,g,r))
            worker.start(); started += 1; started_ids.append(source.source_id)
        if started:
            self._search_display_barrier=ProviderDisplayBarrier(started_ids)
            self._search_barrier_consumed=False
            self._search_provider_ids=tuple(started_ids)
            self._search_resolution_request_id += 1
            if self._search_resolution_worker and self._search_resolution_worker.isRunning():
                self._search_resolution_worker.requestInterruption()
            self._search_resolution_worker=None; self._search_resolutions={}
            self.search_btn.setEnabled(False); self.search_btn.setText('Searching...'); self._set_cancel_action(True,'Cancel Search')
            self._search_status_timer.start()
            self.add_log(f'Using one trusted alias retry (“{alias}”) for {started} weak/empty content source(s).')
        return bool(started)

    def _on_alias_search_ready(self, payload, mode=None, generation=None, request_id=None):
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        source_id=payload.get('source_id')
        page=dict(payload.get('data') or {})
        page['request_query']=str(page.get('query') or '')
        page['context_query']=self._search_query
        page['alias_retry']=True
        page['has_more']=False
        data=self.search_coordinator.complete(source_id,page,preserve_existing=True)
        self._search_display_barrier.settle(source_id,'success',data)
        self._sync_provider_search_progress()

    def _on_alias_search_failed(self, payload, alias, mode=None, generation=None, request_id=None):
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        source_id=payload.get('source_id'); source=SOURCE_REGISTRY.get(source_id)
        self.search_coordinator.fail(source_id,payload.get('error'),preserve_existing=True)
        self._search_display_barrier.settle(source_id,'failure')
        state_generation=getattr(self,'_workflow_search_generation',None)
        if state_generation is not None:
            self.workflow_state.settle_provider(state_generation,source_id,'failure')
        self._sync_provider_search_progress()
        self.add_log(
            f'[{source.display_name if source else source_id}] Alias retry “{alias}” failed: '
            f'{payload.get("error") or "unknown provider error"}'
        )

    def _store_query_snapshot(self):
        if (not self._active_query_cache_key or not self._search_content_results or
                not getattr(self, '_search_resolution_complete', False) or
                self.search_results.count() <= 0 or
                self._search_loaded_stale_cache):
            return
        try:
            final_cards=[{'provider_record':dict(ranked.result)} for ranked in self._ranked_provider_results()]
            self._metadata_search_cache.put_query_snapshot(self._active_query_cache_key,{
                'contract':'provider-candidates-v1',
                'final':True,
                'provider_candidates':self._search_content_results,
                'content_results':self._search_content_results,
                'display_results':self._search_raw_results,
                'offsets':self._search_offsets,
                'has_more':self._search_has_more,
                'provider_states':self.search_coordinator.snapshot().get('providers') or (),
                'final_result_count':self.search_results.count(),
                'final_cards':final_cards,
            })
        except Exception as exc:
            self.add_log(f'Search cache update skipped safely: {exc}')

    def _canonical_search_key(self, group):
        identities=tuple(sorted(
            (str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or ''))
            for row in group.results
        ))
        return (edition_identity(group.results[0]) if group.results else 'original',identities)

    def _qualification_for_provider(self, row):
        """Return categorical acquisition facts for one provider card."""
        source_id=str((row or {}).get('source_id') or '')
        for ranked in self._search_ranked_groups:
            if not any(str(candidate.get('source_id') or '') == source_id and
                       str(candidate.get('id') or candidate.get('url') or '') ==
                       str((row or {}).get('id') or (row or {}).get('url') or '')
                       for candidate in ranked.group.results):
                continue
            resolution=self._search_resolutions.get(self._canonical_search_key(ranked.group))
            if resolution is None:
                return AcquisitionFitness.UNKNOWN,'qualification_failed',0
            eligible=tuple(inventory for inventory in resolution.inventories
                           if inventory_is_eligible(inventory,self.workflow_mode))
            own=next((inventory for inventory in resolution.inventories
                      if inventory.source_id == source_id),None)
            if own and inventory_is_eligible(own,self.workflow_mode):
                fitness=AcquisitionFitness.DIRECT if own.complete else AcquisitionFitness.PARTIAL
                return fitness,'qualified',own.chapter_count
            if eligible:
                return AcquisitionFitness.FALLBACK_ONLY,'fallback_available',0
            if own and own.error:
                return AcquisitionFitness.UNKNOWN,'transient_failure',0
            return AcquisitionFitness.UNAVAILABLE,'qualified_unavailable',0
        return AcquisitionFitness.UNKNOWN,'unqualified',0

    def _search_presentations(self):
        presentations=[]
        canonical_overlays={}
        groups=group_canonical_results(self._search_raw_results)
        work_facts=resolve_canonical_work_facts(groups,self._late_enrichment_by_provider)
        for group in groups:
            if group.confidence != 'high':
                continue
            group_key=tuple(sorted(
                (str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or ''))
                for row in group.results
            ))
            facts=work_facts.get(group_key)
            canonical_id=(
                'canonical:' + normalize_identity_text(group.display_title) + ':' +
                edition_identity(group.results[0])
            )
            for candidate in group.results:
                key=(str(candidate.get('source_id') or ''),
                     str(candidate.get('id') or candidate.get('url') or ''))
                canonical_overlays[key]={
                    'work_family_id':canonical_id,
                    'canonical_title':group.display_title,
                }
                if facts:
                    canonical_overlays[key].update({
                        'canonical_work_id':facts.canonical_work_id,
                        'canonical_title':facts.canonical_title or group.display_title,
                        'canonical_author':facts.creator,
                        'canonical_creator_provenance':facts.creator_provenance,
                        'canonical_creator_conflicted':facts.creator_conflicted,
                        'canonical_creator_aliases':facts.creator_aliases,
                        'canonical_creators':facts.creators,
                    })
        prepared=[]
        for raw in self._search_raw_results:
            key=(str(raw.get('source_id') or ''),str(raw.get('id') or raw.get('url') or ''))
            fitness,status,chapters=self._qualification_for_provider(raw)
            if fitness is AcquisitionFitness.UNKNOWN and raw.get('_qualification_status'):
                try:
                    fitness=AcquisitionFitness(str(raw.get('_acquisition_fitness') or 'unknown'))
                except ValueError:
                    fitness=AcquisitionFitness.UNKNOWN
                status=str(raw.get('_qualification_status') or status)
                chapters=max(0,int(raw.get('_qualification_chapter_count') or 0))
            overlay=dict(self._late_enrichment_by_provider.get(key) or {})
            overlay.update(canonical_overlays.get(key) or {})
            combined=dict(raw); combined.update(overlay)
            prepared.append((raw,combined,fitness,status,chapters))
        propagated=propagate_trusted_family_work_facts(
            combined for _raw,combined,_fitness,_status,_chapters in prepared
        )
        for (raw,_combined,fitness,status,chapters),overlay in zip(prepared,propagated):
            presentations.append(present_search_candidate(
                raw,overlay,fitness,status,chapters,
            ))
        return tuple(presentations)

    def _ranked_provider_results(self):
        return rank_provider_results(
            self._search_query,(row.as_record() for row in self._search_presentations()),
            bool(prefs['prefer_colored'])
        )

    def _ranked_search_groups(self, final=False):
        """Legacy canonical view retained for non-visible fallback helpers."""
        rows=list(rank_canonical_results(
            self._search_query,self._search_raw_results,bool(prefs['prefer_colored'])
        ))[:SEARCH_RESOLUTION_LIMIT]
        if not final:
            return tuple(rows)
        eligible=[]
        for ranked in rows:
            resolution=self._search_resolutions.get(self._canonical_search_key(ranked.group))
            if resolution and resolution.usable:
                base=tuple(ranked.sort_key)
                eligible.append((base[:4] + (1 if resolution.language_fallback else 0,) + base[4:],ranked))
        return tuple(ranked for _key,ranked in sorted(eligible,key=lambda row:row[0]))

    def _render_provider_search_results(self):
        selected_info=self.search_results.currentItem().data(Qt.ItemDataRole.UserRole) if self.search_results.currentItem() else {}
        selected_key=(selected_info.get('source_id'),selected_info.get('id') or selected_info.get('url')) if isinstance(selected_info,dict) else None
        scroll_value=self.search_results.verticalScrollBar().value()
        ranked_results=self._ranked_provider_results()
        self.search_results.clear()
        for ranked in ranked_results:
            primary=dict(ranked.result)
            provider_key=(str(primary.get('source_id') or ''),str(primary.get('id') or primary.get('url') or ''))
            primary['badge']=primary.get('badge') or edition_display_label(primary)
            primary['provider_key']=ranked.provider_key
            primary['match_tier']=int(ranked.match.tier)
            primary['rank_sort_key']=ranked.sort_key
            primary['resolution_state']='provider_local'
            item=QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole,primary)
            item.setSizeHint(QSize(0,SEARCH_RESULT_ROW_HEIGHT))
            self.search_results.addItem(item)
            row=SearchResultRowWidget(
                primary.get('title') or 'Untitled',primary.get('author') or '',
                badge=primary.get('badge') or '',rating=primary.get('rating_display') or '',
                parent=self.search_results,cover_loading=bool(primary.get('cover_url')),
            )
            row.set_source_state(((primary.get('source_id'),primary.get('source_name') or primary.get('source_id'),primary.get('url') or ''),))
            row.activated.connect(lambda it=item:self.use_search_result(it))
            self.search_results.setItemWidget(item,row)
            if ranked.provider_key == selected_key:
                self.search_results.setCurrentItem(item)
        self.search_results.verticalScrollBar().setValue(scroll_value)

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
            choice_required=bool(
                resolution and resolution.usable and prefs['ask_equivalent_sources'] and
                resolution.decision and resolution.decision.ambiguous
            )
            info['resolution_state']=('choice_required' if choice_required else 'resolved') if resolution and resolution.usable else 'unresolved'
            info['resolution']=resolution
            item.setData(Qt.ItemDataRole.UserRole, info)
            title=group.display_title or 'Untitled'; author=primary.get('author') or ''; badge=primary.get('badge') or ''
            item.setSizeHint(QSize(0,SEARCH_RESULT_ROW_HEIGHT))
            self.search_results.addItem(item)
            confirmed=()
            language_note=''
            if resolution and resolution.usable:
                names={row.source_id:row.source_name for row in resolution.inventories}
                choice_required=bool(
                    prefs['ask_equivalent_sources'] and resolution.decision and
                    resolution.decision.ambiguous
                )
                if not choice_required:
                    confirmed=((resolution.primary.source_id,names.get(resolution.primary.source_id) or resolution.primary.source_name,primary.get('url') or ''),)
                if resolution.language_fallback:
                    language_note=f'{language_label(resolution.preferred_language)} unavailable · {language_label(resolution.language)} available'
            row=SearchResultRowWidget(
                title, author, badge=badge, rating=primary.get('rating_display') or '', parent=self.search_results,
                cover_loading=bool(primary.get('cover_url')),
            )
            if confirmed:
                row.set_source_state(confirmed,language_note)
            elif resolution and resolution.usable:
                row.set_source_state((),language_note,'Equivalent sources available')
            row.activated.connect(lambda it=item:self.use_search_result(it))
            self.search_results.setItemWidget(item,row)
            if group_key == selected_key:
                self.search_results.setCurrentItem(item)
        self.search_results.verticalScrollBar().setValue(scroll_value)

    def _render_fresh_cached_snapshot(self, snapshot):
        self.search_results.clear()
        for primary in final_search_records(snapshot):
            primary=dict(primary)
            primary['resolution_state']='cached_final'; primary['cached_final']=True
            primary['provider_key']=(primary.get('source_id'),primary.get('id') or primary.get('url'))
            item=QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole,primary); item.setSizeHint(QSize(0,SEARCH_RESULT_ROW_HEIGHT))
            self.search_results.addItem(item)
            row=SearchResultRowWidget(
                primary.get('title') or 'Untitled',primary.get('author') or '',
                badge=primary.get('badge') or '',rating=primary.get('rating_display') or '',
                parent=self.search_results,cover_loading=False,
            )
            row.set_source_state(((primary.get('source_id'),primary.get('source_name') or primary.get('source_id'),primary.get('url') or ''),))
            row.activated.connect(lambda it=item:self.use_search_result(it))
            self.search_results.setItemWidget(item,row)

    def _on_search_failed(self, data, mode=None, generation=None, request_id=None):
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        source_id=data.get('source_id'); source=SOURCE_REGISTRY.get(source_id)
        self.search_coordinator.fail(source_id,data.get('error'))
        self._search_display_barrier.settle(source_id,'failure')
        self._sync_provider_search_progress()
        self.add_log(f'[{source.display_name if source else source_id}] Search failed: {data.get("error")}')

    def _search_worker_finished(self, source_id, completed_worker=None, mode=None, generation=None, request_id=None):
        worker=self.search_workers.get(source_id)
        if worker is completed_worker:
            self.search_workers.pop(source_id,None)
        if mode != self.workflow_mode or generation != self._mode_generation or request_id != self._search_request_id:
            return
        if not self._search_display_barrier.is_terminal(source_id):
            self._search_display_barrier.settle(source_id,'cancelled')
            state_generation=getattr(self,'_workflow_search_generation',None)
            if state_generation is not None:
                self.workflow_state.settle_provider(state_generation,source_id,'cancelled')
        self._finish_coordinated_search()

    def _sync_provider_search_progress(self):
        settled,total=settled_provider_progress(
            self.search_coordinator.snapshot(), self._search_provider_ids,
        )
        self.search_progress.setRange(0,max(1,total))
        self.search_progress.setValue(settled if total else 0)
        self._refresh_source_status_pills()
        return settled,total

    def _refresh_source_status_pills(self):
        if not hasattr(self,'source_status_layout'):
            return
        while self.source_status_layout.count():
            item=self.source_status_layout.takeAt(0)
            widget=item.widget()
            if widget is not None:
                widget.deleteLater()
        for provider in self.search_coordinator.snapshot().get('providers') or ():
            pill=SourceStatusButton(
                provider.get('source_id'),provider.get('display_name'),provider.get('status'),
                self.source_status_host,
            )
            if provider.get('status') == 'failed':
                pill.clicked.connect(
                    lambda _checked=False,sid=provider.get('source_id'):self._retry_failed_source(sid)
                )
            self.source_status_layout.addWidget(pill)

    def _retry_failed_source(self, source_id):
        if self.search_workers or not self._search_query:
            return
        provider=next((row for row in self.search_coordinator.snapshot().get('providers') or () if row.get('source_id') == source_id),None)
        source=SOURCE_REGISTRY.get(source_id)
        if not provider or provider.get('status') != 'failed' or source is None:
            return
        self._search_request_id += 1; request_id=self._search_request_id
        self._search_resolution_complete=False
        self._search_provider_ids=(source_id,)
        self._search_display_barrier=ProviderDisplayBarrier((source_id,))
        self._search_barrier_consumed=False
        self.search_coordinator.mark_running(source_id)
        if source_id in self.workflow_state.provider_search_states:
            self.workflow_state.provider_search_states[source_id]='searching'
        key=(source_id,self._search_query.casefold(),0,self._search_page_size,bool(prefs['show_adult_search_results']),prefs['language'])
        worker=self._retain_async_worker(SourceSearchWorker(
            source,self._search_query,0,self._search_page_size,
            bool(prefs['show_adult_search_results']),prefs['language'],
            self._download_availability_cache,
        ))
        self.search_workers[source_id]=worker
        mode=self.workflow_mode; generation=self._mode_generation
        worker.ready.connect(lambda payload,k=key,m=mode,g=generation,r=request_id:self._on_search_ready(k,payload,m,g,r))
        worker.failed.connect(lambda payload,m=mode,g=generation,r=request_id:self._on_search_failed(payload,m,g,r))
        worker.finished.connect(lambda sid=source_id,w=worker,m=mode,g=generation,r=request_id:self._search_worker_finished(sid,w,m,g,r))
        self.search_btn.setEnabled(False); self.search_btn.setText('Searching...')
        self._set_cancel_action(True,'Cancel Search')
        self._set_search_progress_visible(True)
        self.search_progress.setVisible(True)
        self.search_progress_text.setText(f'Retrying {source.display_name}…')
        self._refresh_source_status_pills(); worker.start()

    def _finish_coordinated_search(self):
        if self.search_workers:
            self._sync_provider_search_progress()
            self.search_progress_text.setText('Searching sources…')
            return
        if not self._search_display_barrier.complete:
            return
        if not self._search_barrier_consumed:
            for data in self._search_display_barrier.ordered_successes():
                self._apply_search_page(data)
            self._search_barrier_consumed=True
            self._rebuild_enriched_results(render=False)
        if bool(prefs['search_enrichment']) and not self._enrichment_received:
            self.search_progress_text.setText('Resolving canonical work facts…')
            self._set_search_progress_visible(True)
            self.search_progress.setVisible(True)
            return
        self._apply_late_search_enrichment(render=False)
        if self._search_resolution_complete:
            return
        snap=self.search_coordinator.snapshot()
        self._search_status_timer.stop()
        self._sync_provider_search_progress()
        self._set_search_progress_visible(False)
        self.search_progress.setVisible(False)
        self.search_btn.setEnabled(True); self.search_btn.setText('Search'); self._set_cancel_action(False)
        more=any(self._search_has_more.values())
        self.show_more_btn.setVisible(more); self.show_more_btn.setEnabled(more)
        ranked_provider_results=self._ranked_provider_results()
        if snap['all_failed'] and not ranked_provider_results:
            self.search_progress_text.setText('Search failed: all providers failed.')
        else:
            failures=sum(provider.get('status') == 'failed' for provider in snap['providers'])
            suffix=f' ({failures} failed)' if failures else ''
            blocked=[p.get('display_name') for p in snap['providers'] if p.get('status')=='failed' and 'access blocked by site protection' in str(p.get('error') or '').casefold()]
            blocked_suffix=(' · '+', '.join(blocked)+' — Access blocked by site protection') if blocked else ''
            self.search_progress_text.setText(f'Search complete: {snap["completed"]}/{snap["total"]} providers{suffix}{blocked_suffix}')
        if not ranked_provider_results:
            self._search_resolution_complete=True
            if self._active_query_cache_key:
                self._metadata_search_cache.delete('query_snapshot',self._active_query_cache_key)
            if self._search_cancel_requested:
                self.search_progress_text.setText('Search cancelled; completed provider responses were reconciled.')
            elif snap['all_failed']:
                self.search_progress_text.setText('All enabled sources failed. Use a red source pill to retry.')
            else:
                self.search_progress_text.setText(
                    f'No results were returned for “{self._search_query}”. Try another title, alternate title, or Direct Link.'
                )
        else:
            self._search_ranked_groups=tuple(
                ranked for ranked in self._ranked_search_groups(False)
                if ranked.group.confidence == 'high' and len(ranked.group.results) > 1
            )[:SEARCH_QUALIFICATION_LIMIT]
            if self._search_ranked_groups:
                self.search_progress_text.setText('Checking availability…')
                self.search_results.clear()
                self._set_search_progress_visible(True)
                self.search_progress.setVisible(True)
                self.search_btn.setEnabled(False)
                self._start_search_resolution()
                return
            self._render_provider_search_results()
            self._search_resolution_complete=True
            self.search_results_label.setText(f'Results for “{self._search_query}”')
            self.workflow_state.publish_search_results(
                getattr(self,'_workflow_search_generation',0),
                (ranked.result for ranked in ranked_provider_results),
            )
            self.search_progress_text.setText(f'Results for “{self._search_query}”')
            self._store_query_snapshot()
            QTimer.singleShot(0,self._load_visible_search_thumbs)

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
        worker=self._retain_async_worker(SearchResolutionWorker(
            request_id,SOURCE_REGISTRY,entries,prefs['language'],mode,
            self._search_resolution_metadata_cache,self._search_resolution_inventory_cache,
            prefs['show_adult_search_results'],
        ))
        self._search_resolution_worker=worker
        worker.resolved.connect(lambda payload,m=mode,g=generation:self._on_search_resolution(payload,m,g))
        worker.finished.connect(lambda w=worker,r=request_id,m=mode,g=generation:self._search_resolution_finished(w,r,m,g))
        worker.start()

    def _on_search_resolution(self, payload, mode=None, generation=None):
        if (payload.get('request_id') != self._search_resolution_request_id or
                mode != self.workflow_mode or generation != self._mode_generation):
            return
        group_key=payload.get('group_key')
        resolution=payload.get('resolution')
        if payload.get('error') or not resolution:
            self._search_resolutions[group_key]=None
            message=payload.get('error') or getattr(resolution,'error','') or 'no usable source'
            self.add_log(f'Availability qualification remained unknown: {message}')
            return
        self._search_resolutions[group_key]=resolution

    def _search_resolution_finished(self, worker, request_id, mode=None, generation=None):
        if self._search_resolution_worker is worker:
            self._search_resolution_worker=None
        if (request_id != self._search_resolution_request_id or
                mode != self.workflow_mode or generation != self._mode_generation):
            return
        self._render_provider_search_results()
        self._search_resolution_complete=True
        self._set_search_progress_visible(False)
        self.search_progress.setVisible(False)
        self.search_btn.setEnabled(True); self.search_btn.setText('Search')
        self.search_progress_text.setText('Search complete.')
        ranked_provider_results=self._ranked_provider_results()
        self.workflow_state.publish_search_results(
            getattr(self,'_workflow_search_generation',0),
            (ranked.result for ranked in ranked_provider_results),
        )
        self._store_query_snapshot()
        QTimer.singleShot(0,self._load_visible_search_thumbs)

    def _show_more_search_results(self):
        self.search_mangadex(False)

    def _update_search_status(self):
        if self.search_workers and not self._search_cancel_requested:
            self._sync_provider_search_progress()
            self.search_progress_text.setText('Searching sources…')

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

    def _pix_for_url(self, url, w, h):
        key=(str(url or ''),int(w),int(h))
        if not key[0]:
            return None
        if key not in self._scaled_pixmap_cache:
            raw=self._image_cache.get(key[0])
            self._scaled_pixmap_cache[key]=self._pix_from_bytes(raw,w,h) if raw else None
        return self._scaled_pixmap_cache.get(key)

    def _store_image_bytes(self, url, raw):
        url=str(url)
        self._image_cache[url] = raw
        self._failed_image_urls.discard(url)
        for key in tuple(self._scaled_pixmap_cache):
            if key[0] == url:
                self._scaled_pixmap_cache.pop(key,None)

    def _load_visible_search_thumbs(self):
        if self._closing or (self.search_thumb_worker and self.search_thumb_worker.isRunning()):
            return
        batch=[]; queued_urls=set()
        for i in self._visible_row_range(self.search_results,SEARCH_RESULT_ROW_HEIGHT,4):
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
                pix=self._pix_for_url(url,48,70)
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
        worker=self._retain_async_worker(ImageBatchWorker(('search',token,generation),batch))
        self.search_thumb_worker=worker
        # Bound QObject methods are queued onto this dialog's GUI thread.
        worker.image_ready.connect(self._on_search_thumb_ready)
        worker.image_failed.connect(self._on_search_thumb_failed)
        worker.finished.connect(lambda w=worker:self._on_search_thumb_finished(w))
        worker.start()

    def _on_search_thumb_ready(self, data):
        batch_id=data.get('batch_id') or ()
        _kind, token, generation=(batch_id + (None,None,None))[:3] if isinstance(batch_id,tuple) else (None,None,None)
        if self._closing or generation != self._cover_generation or token != self._search_cover_batch_token:
            return
        url=data.get('key'); raw=data.get('raw')
        if not url or not raw:
            return
        self._store_image_bytes(url,raw)
        for i in range(self.search_results.count()):
            item=self.search_results.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if isinstance(info,dict) and info.get('cover_url')==url:
                pix=self._pix_for_url(url,48,70)
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

    def _on_search_thumb_finished(self, worker):
        if self.search_thumb_worker is worker:
            self.search_thumb_worker=None
        if not self._closing:
            QTimer.singleShot(0,self._load_visible_search_thumbs)

    def use_search_result(self, item=None):
        if item is None: item=self.search_results.currentItem()
        if item is None: return
        info=item.data(Qt.ItemDataRole.UserRole) or {}
        resolution=info.get('resolution') if isinstance(info,dict) else None
        if info.get('resolution_state') in ('provider_local','cached_final') and not resolution:
            self._search_user_interacted=True
            self._workflow_inventory_generation=self.workflow_state.select_provider(info)
            self._pending_cross_source_plan=None
            self._selected_resolution_inventories=()
            self._selected_work_id=str(info.get('canonical_work_id') or '')
            self._selected_edition=edition_identity(info)
            self._pending_search_language=str(info.get('language') or prefs['language'])
            self._begin_search_result(info)
            self._start_selected_fallback_planning(info)
            return
        if info.get('resolution_state') not in ('resolved','choice_required') or not resolution or not resolution.usable:
            self.add_log('This result is still checking usable sources.')
            return
        self._search_user_interacted=True
        selected=resolution.primary
        fallback_plan=resolution.fallback_plan
        if info.get('resolution_state') == 'choice_required':
            selected=self._choose_ambiguous_inventory(info,resolution.decision)
            if selected is None:
                return
            fallback_plan=build_cross_source_plan(
                resolution.inventories,SOURCE_REGISTRY,primary=selected,
                workflow=self.workflow_mode,
            ) if self.workflow_mode == 'chapter' else None
        self._last_inventory_decision=resolution.decision
        self._selected_resolution_inventories=tuple(resolution.inventories)
        self._selected_work_id=str(info.get('canonical_work_id') or '')
        self._selected_edition=selected.edition
        self._pending_cross_source_plan=fallback_plan if self.workflow_mode == 'chapter' else None
        self._pending_search_language=resolution.language
        for inventory in resolution.inventories:
            self.add_log(f'[{inventory.source_name}] Inventory ({inventory.language or "unknown language"}): {inventory.summary}.')
        self.add_log(f'Primary source: {selected.source_name}.')
        if fallback_plan and fallback_plan.fallback_items and fallback_plan.can_execute:
            self.add_log(fallback_plan.notice)
        self._workflow_inventory_generation=self.workflow_state.select_provider(selected.result)
        self._begin_search_result(selected.result)

    @staticmethod
    def _provider_record_identity(record):
        row=dict(record or {})
        return (str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or ''))

    def _compatible_fallback_candidates(self, selected):
        """Return only high-confidence canonical peers for the clicked record."""
        selected_key=self._provider_record_identity(selected)
        if not all(selected_key):
            return ()
        rows=[]
        for original in self._search_raw_results or self._search_content_results:
            row=dict(original)
            key=self._provider_record_identity(row)
            row.update(self._late_enrichment_by_provider.get(key) or {})
            rows.append(row)
        if selected_key not in {self._provider_record_identity(row) for row in rows}:
            rows.append(dict(selected))
        for group in group_canonical_results(rows):
            if selected_key in {self._provider_record_identity(row) for row in group.results}:
                return tuple(dict(row) for row in group.results)
        return ()

    def _start_selected_fallback_planning(self, selected):
        """Plan safe Chapter-mode fallback without replacing the clicked record."""
        self._selected_fallback_request_id += 1
        if self._selected_fallback_worker and self._selected_fallback_worker.isRunning():
            self._selected_fallback_worker.requestInterruption()
        self._selected_fallback_worker=None; self._active_fallback_source=None
        candidates=self._compatible_fallback_candidates(selected)
        if self.workflow_mode != 'chapter' or len(candidates) < 2:
            return
        request_id=self._selected_fallback_request_id
        selected_key=self._provider_record_identity(selected)
        mode=self.workflow_mode; generation=self._mode_generation
        worker=self._retain_async_worker(SelectedFallbackWorker(
            request_id,SOURCE_REGISTRY,selected,candidates,
            prefs['language'],self.workflow_mode,
        ))
        self._selected_fallback_worker=worker
        worker.ready.connect(
            lambda payload,k=selected_key,m=mode,g=generation:
            self._on_selected_fallback_ready(payload,k,m,g)
        )
        worker.finished.connect(lambda w=worker:self._selected_fallback_finished(w))
        worker.start()

    def _selected_fallback_finished(self, worker):
        if self._selected_fallback_worker is worker:
            self._selected_fallback_worker=None

    def _on_selected_fallback_ready(self, payload, selected_key, mode, generation):
        current=self.workflow_state.selected_provider_record or {}
        if (payload.get('request_id') != self._selected_fallback_request_id or
                mode != self.workflow_mode or generation != self._mode_generation or
                self._provider_record_identity(current) != selected_key):
            return
        self._selected_fallback_worker=None
        inventories=tuple(payload.get('inventories') or ())
        self._selected_resolution_inventories=inventories
        if payload.get('error'):
            self.add_log(f'Compatible fallback inspection unavailable: {payload["error"]}')
            if (self.loaded_metadata and self._chapter_acquisition_items and
                    self.language.currentData()):
                self._apply_chapter_plan(
                    self._volume_plan_request_id,self.language.currentData(),
                    self._chapter_acquisition_items,
                )
            return
        for inventory in inventories:
            self.add_log(f'[{inventory.source_name}] Inventory ({inventory.language or "unknown language"}): {inventory.summary}.')
        plan=payload.get('fallback_plan')
        if (not plan or not plan.can_execute or
                plan.primary_source_id != selected_key[0]):
            if (self.loaded_metadata and self._chapter_acquisition_items and
                    not self._volume_plan_loading and self.language.currentData()):
                self._apply_chapter_plan(
                    self._volume_plan_request_id,self.language.currentData(),
                    self._chapter_acquisition_items,
                )
            return
        self._pending_cross_source_plan=plan
        if plan.fallback_items:
            self.add_log(plan.notice)
        primary_items=tuple(item for item in plan.items if item.reason == 'primary')
        if not primary_items and plan.fallback_items:
            fallback=plan.fallback_items[0]
            self._active_fallback_source=(fallback.source_id,f'{fallback.source_name} (fallback)')
            self.add_log(f'[{plan.primary_source_name}] Chapter inventory failed. Falling back to {fallback.source_name}.')
            self.workflow_hint.setText(
                f'Selected provider: {plan.primary_source_name}. Acquisition fallback: {fallback.source_name}.'
            )
        if (self.loaded_metadata and not self._volume_plan_loading and
                self.current_source_id == selected_key[0] and
                self.language.currentData() == plan.language):
            self._apply_chapter_plan(
                self._volume_plan_request_id,plan.language,self._chapter_acquisition_items
            )

    def _start_inventory_comparison(self, group_info, candidates):
        if self.inventory_comparison_worker and self.inventory_comparison_worker.isRunning():
            self.inventory_comparison_worker.requestInterruption()
        self._inventory_comparison_request_id += 1
        self._last_inventory_decision=None
        request_id=self._inventory_comparison_request_id
        mode=self.workflow_mode; generation=self._mode_generation
        self.search_results.setEnabled(False)
        self.workflow_hint.setText('Checking provider inventories...')
        worker=self._retain_async_worker(InventoryComparisonWorker(
            SOURCE_REGISTRY,candidates,prefs['language'],self.workflow_mode
        ))
        self.inventory_comparison_worker=worker
        worker.progress.connect(lambda done,total,text,rid=request_id,m=mode,g=generation:self._on_inventory_comparison_progress(rid,done,total,text,m,g))
        worker.ready.connect(lambda decision,rid=request_id,info=dict(group_info),m=mode,g=generation:self._on_inventory_comparison_ready(rid,info,decision,m,g))
        worker.failed.connect(lambda message,rid=request_id,m=mode,g=generation:self._on_inventory_comparison_failed(rid,message,m,g))
        worker.finished.connect(lambda w=worker:self._inventory_comparison_finished(w))
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
            self.add_log(f'[{inventory.source_name}] Inventory ({inventory.language or "unknown language"}): {inventory.summary}.')
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
        equivalent=tuple(decision.equivalent_inventories or decision.inventories)
        comparison='\n'.join(f'{row.source_name}: {row.summary}' for row in equivalent)
        box.setInformativeText(
            'MangaNana identified one canonical series, but no provider is clearly better.\n\n'
            + comparison + '\n\nChoose which provider to use. Inventories will not be combined.'
        )
        buttons=[]
        for inventory in equivalent:
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
        self._reset_reference_lookup()
        self._active_fallback_source=None
        self._pending_search_result=dict(info) if isinstance(info,dict) else {}
        self._pending_search_url=info.get('url') or ('https://mangadex.org/title/'+str(mid))
        self._pending_source_id=info.get('source_id') or MANGADEX_SOURCE.source_id
        self._pending_search_cover_url=(info.get('cover_url') or '') if isinstance(info,dict) else ''
        self._selected_cover_url=''; self._main_cover_url=''
        self.selected_cover.clear()
        self._invalidate_inflight_preview()
        self._clear_preview_state('Final Outputs will rebuild after Next: Finalization.')
        self.preview_btn.setEnabled(False); self.download_btn.setEnabled(False)
        self._selected_volumes.clear(); self._standalone_selected=False; self._using_entire_series=False; self.volume_list.clear(); self.volume_list.setEnabled(False); self.volume_count_label.clear(); self.select_all_btn.setEnabled(False); self.clear_volume_btn.setEnabled(False)
        self.selected_cover.setVisible(True); self.alt_titles_btn.setVisible(False); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop); self.selected_title.setStyleSheet('font-size:15px; font-weight:700;'); self.selected_title.setText('Loading manga...'); self.selected_author.setText(''); self.selected_rating.clear(); self.selected_rating.setVisible(False); self._set_edition_badge(''); self.availability_badge.setVisible(False)
        self._clear_selected_details()
        source=SOURCE_REGISTRY.get(self._pending_source_id)
        self._set_selected_source_badge(self._pending_source_id,source.display_name if source else self._pending_source_id,self._pending_search_url)
        if self._pending_search_cover_url:
            raw=self._image_cache.get(self._pending_search_cover_url)
            if raw:
                pix=self._pix_for_url(self._pending_search_cover_url,150,210)
                if pix is not None: self.selected_cover.setPixmap(pix)
                else: self.selected_cover.set_failed()
            else:
                self.selected_cover.set_loading()
        else:
            self.selected_cover.set_failed()
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
            self._active_fallback_source=None
            self._selected_fallback_request_id += 1
            if self._selected_fallback_worker and self._selected_fallback_worker.isRunning():
                self._selected_fallback_worker.requestInterruption()
            self._selected_fallback_worker=None
        if discovery_kind == 'direct':
            self._reset_reference_lookup()
            self._pending_search_result={}; self._pending_search_cover_url=''; self._pending_search_url=''
            self._selected_resolution_inventories=(); self._selected_work_id=''; self._selected_edition='original'
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
            self._enrichment_request_id += 1
            for search_worker in self.search_workers.values():
                if search_worker.isRunning(): search_worker.requestInterruption()
            if self.search_workers:
                self.search_coordinator.cancel_remaining(); self._sync_provider_search_progress()
            self.search_workers={}; self._search_status_timer.stop()
            if self._search_resolution_worker and self._search_resolution_worker.isRunning():
                self._search_resolution_worker.requestInterruption()
            self._search_resolution_worker=None
            if self._enrichment_worker and self._enrichment_worker.isRunning():
                self._enrichment_worker.requestInterruption()
            self._enrichment_worker=None
            self.search_btn.setEnabled(True); self.search_btn.setText('Search')
        self._manga_request_id += 1
        self._invalidate_cover_requests()
        request_id=self._manga_request_id
        self._manga_load_contexts.clear()
        self._manga_load_contexts[request_id]=MangaLoadContext(
            discovery_kind,url,
            self._pending_search_language if discovery_kind == 'search' else '',
        )
        self.current_manga_url=url
        self.current_source=source; self.current_source_id=source.source_id
        self._invalidate_inflight_preview()
        self._clear_preview_state('Final Outputs will rebuild after Next: Finalization.')
        self.load_btn.setEnabled(False); self.load_btn.setText('Loading...'); self.preview_btn.setEnabled(False)
        self.alt_titles_btn.setEnabled(False)
        self.selected_cover.setVisible(True); self.alt_titles_btn.setVisible(False); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop); self.selected_title.setStyleSheet('font-size:15px; font-weight:700;'); self.selected_title.setText('Loading manga...'); self.selected_author.setText(''); self.selected_rating.clear(); self.selected_rating.setVisible(False); self._set_edition_badge(''); self.availability_badge.setVisible(False)
        self._clear_selected_details()
        self.volume_list.clear(); self.volume_list.setEnabled(False); self.volume_count_label.clear(); self.meta_summary.setText(f'Loading {source.display_name} metadata...')
        if not self._pending_search_cover_url or url != self._pending_search_url:
            self.selected_cover.set_loading()
        populate_download_languages(self.language, available=None, preferred=prefs['language'])
        self._current_plan=None; self._chapter_plan_items=(); self._chapter_acquisition_items=(); self._volume_acquisition_items=(); self._native_volume_plan=None; self._chapter_acquisition_error=''; self._selected_chapter_ids.clear(); self._download_language_valid=False; self._volume_plan_loading=False; self._selected_volumes.clear(); self._standalone_selected=False; self._using_entire_series=False
        self._chapter_volume_evidence=None; self._manual_volume_assignments={}; self._chapter_output_user_selected=False
        self._refresh_chapter_output_options()
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
        self._manga_load_contexts.pop(data.get('request_id'), None)
        self.loaded_metadata=None; self.alt_titles_btn.setEnabled(False); self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self._record_diagnostic(RuntimeError, RuntimeError(data.get('error') or 'Unknown source error.'), None, 'metadata load')
        self.load_btn.setEnabled(True); self.load_btn.setText('Load')
        self.selected_cover.set_failed(); self.selected_cover.setVisible(False); self.alt_titles_btn.setVisible(False); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignCenter); self.selected_title.setStyleSheet('font-size:12px; font-weight:600; color:#777;'); self.selected_title.setText('No manga selected'); self.meta_summary.clear()
        self._clear_selected_details()
        error_dialog(self,'Metadata error',data.get('error') or 'Unknown source error.',show=True)

    def _apply_loaded_manga(self, request_id, data):
        if request_id != self._manga_request_id:
            return
        load_context=take_manga_load_context(self._manga_load_contexts,request_id)
        discovery_kind=load_context.discovery_kind
        discovery_value=load_context.discovery_value
        requested_language=load_context.requested_language
        md=data.get('metadata') or {}
        if md.get('adult') and not prefs['show_adult_search_results']:
            self.loaded_metadata=None; self.current_manga_url=''; self._current_plan=None; self._chapter_plan_items=(); self._chapter_acquisition_items=(); self._chapter_acquisition_error=''; self._selected_chapter_ids.clear()
            self.title.clear(); self.author.clear(); self.series.clear(); self.volume_list.clear(); self.volume_list.setEnabled(False)
            self.load_btn.setEnabled(True); self.load_btn.setText('Load'); self.preview_btn.setEnabled(False)
            self.selected_cover.set_failed(); self.selected_cover.setVisible(False); self.alt_titles_btn.setVisible(False)
            self.selected_title.setAlignment(Qt.AlignmentFlag.AlignCenter); self.selected_title.setText('No manga selected')
            self._clear_selected_details()
            self.meta_summary.setText('Adult title blocked by the current search preference.')
            self.add_log(f'[{data.get("source_id") or "Source"}] Adult title blocked by preference after metadata validation.')
            error_dialog(self,'Adult title hidden','Enable “Show 18+ search results” in Preferences to load this title.',show=True)
            return
        pending=dict(self._pending_search_result or {}) if discovery_kind != 'direct' else {}
        provider_description=str(md.get('description') or '').strip()
        if not md.get('author'):
            fallback_author=str(pending.get('author') or '').strip()
            if not fallback_author:
                fallback_author=next((str(value).strip() for value in pending.get('external_authors') or () if str(value).strip()),'')
            if fallback_author:
                md['author']=fallback_author
        self._apply_work_level_enrichment(md,pending)
        title_rows=list(md.get('titles') or ())
        title_rows.extend(pending.get('structured_titles') or ())
        for alias in pending.get('alternate_titles') or ():
            title_rows.append({'title':alias,'language':'','primary':False,'provenance':pending.get('source_id') or ''})
        md['titles']=list(normalize_title_rows(title_rows,md.get('title') or ''))
        self.loaded_metadata=md; self.current_manga_url=data.get('url') or self.current_manga_url
        if discovery_kind == 'direct' and discovery_value:
            self._last_discovery_kind=discovery_kind; self._last_discovery_value=discovery_value
        self.current_source=SOURCE_REGISTRY.get(data.get('source_id')) or self.current_source
        self.current_source_id=self.current_source.source_id
        self._set_selected_source_badge(self.current_source_id,self.current_source.display_name,self.current_manga_url)
        if discovery_kind == 'direct':
            provider_id=self.current_source.parse_manga_ref(self.current_manga_url) or md.get('uuid')
            direct_record={
                'source_id':self.current_source_id,'source_name':self.current_source.display_name,
                'id':str(provider_id or self.current_manga_url),'url':self.current_manga_url,
                'title':md.get('title') or 'Untitled','author':md.get('author') or '',
                'alternate_titles':list(md.get('alternate_titles') or ()),
                'cover_url':md.get('main_cover_url') or '','direct_loaded':True,
                '_provider_result_order':-1,
            }
            key=(direct_record['source_id'],direct_record['id'])
            self._search_content_results=[
                row for row in self._search_content_results
                if (row.get('source_id'),str(row.get('id') or row.get('url') or '')) != key
            ]
            self._search_content_results.insert(0,direct_record)
            self._search_raw_results=[dict(row) for row in self._search_content_results]
            self._render_provider_search_results()
            for index in range(self.search_results.count()):
                item=self.search_results.item(index); info=item.data(Qt.ItemDataRole.UserRole) or {}
                if (info.get('source_id'),str(info.get('id') or info.get('url') or '')) == key:
                    self.search_results.setCurrentItem(item); break
            self._workflow_inventory_generation=self.workflow_state.select_provider(direct_record)
        self._loaded_covers={}; self._reference_volume_covers={}; self._reference_bundle={}; self._publication_manifest=None
        self._provider_main_cover_url=md.get('main_cover_url') or (self._pending_search_cover_url if self.current_manga_url == self._pending_search_url else '')
        self._main_cover_url=self._provider_main_cover_url
        self._set_applied_metadata(md.get('title',''),md.get('author',''),md.get('title',''))
        self.selected_cover.setVisible(True); self.alt_titles_btn.setVisible(True); self.selected_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop); self.selected_title.setStyleSheet('font-size:15px; font-weight:700;'); self.selected_title.setText(md.get('title') or 'Untitled'); self.selected_author.setText(md.get('author') or '')
        selected_rating=format_rating_label((self._pending_search_result or {}).get('rating_display'))
        self.selected_rating.setText(selected_rating); self.selected_rating.setVisible(bool(selected_rating))
        self._refresh_selected_details(md)
        if not self._main_cover_url:
            self.selected_cover.set_failed()
        edition_evidence=dict(self._pending_search_result if discovery_kind != 'direct' else {})
        edition_evidence.update({
            'title':md.get('title') or edition_evidence.get('title'),
            'full_title':' '.join(x.get('title','') for x in md.get('titles',[])),
        })
        self._selected_edition=edition_identity(edition_evidence)
        badge=edition_display_label(edition_evidence)
        alternate_rows=meaningful_alternate_titles(md.get('titles') or (),md.get('title') or '')
        self._set_edition_badge(badge); self.alt_titles_btn.setEnabled(bool(alternate_rows))
        available=md.get('available_languages') or []
        self.availability_badge.setVisible(not bool(available))
        populate_download_languages(self.language, available=available, preferred=requested_language or prefs['language'])
        self._seed_publication_manifest(provider_description,pending)
        self._start_reference_lookup()
        auto_fallback = bool(self.language.currentData() and self.language.currentData() != prefs['language'])
        self._selected_volume=None; self._selected_volumes.clear(); self._selected_chapter_ids.clear(); self._standalone_selected=False; self._using_entire_series=False; self._current_plan=None; self._chapter_plan_items=(); self._chapter_acquisition_items=(); self._volume_acquisition_items=(); self._native_volume_plan=None; self._chapter_acquisition_error=''; self._download_language_valid=False; self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self._rebuild_volume_list()
        self.load_btn.setEnabled(True); self.load_btn.setText('Load')
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
                self.select_all_btn.setEnabled(False); self.clear_volume_btn.setEnabled(False)
                self.add_log('No downloadable chapters are currently available for this title.')
        QTimer.singleShot(0,self._load_visible_volume_thumbs)

    def _download_language_changed(self, *args):
        self.invalidate_preview()
        if not self.loaded_metadata:
            return
        self._set_selected_inventory_count(0)
        self._selected_volumes.clear(); self._selected_chapter_ids.clear(); self._standalone_selected=False; self._using_entire_series=False; self._current_plan=None; self._chapter_plan_items=(); self._chapter_acquisition_items=(); self._volume_acquisition_items=(); self._native_volume_plan=None; self._chapter_acquisition_error=''; self._download_language_valid=False; self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self._chapter_volume_evidence=None; self._manual_volume_assignments={}; self._chapter_output_user_selected=False
        self._refresh_chapter_output_options()
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
        if self.workflow_mode == 'chapter':
            self.workflow_state.begin_chapter_preparation(
                getattr(self,'_workflow_inventory_generation',-1),request_id
            )
            self._set_chapter_preparing('Preparing chapters…')
            self.add_log('Preparing chapters: acquisition inventory and publication structure are resolving.')
        else:
            self.workflow_state.begin_volume_preparation(
                getattr(self,'_workflow_inventory_generation',-1),request_id
            )
        key=(self.workflow_mode,self.current_source_id,mid,lang)
        cached=self._plan_cache.get(key)
        self._volume_plan_loading=True; self.meta_summary.setText(f'Loading {self.language.currentText()} volume information...')
        if cached is not None:
            cached_data=dict(cached); cached_data['request_id']=request_id
            if self.workflow_mode == 'volume':
                self._apply_volume_plan_data(cached_data)
            else:
                QTimer.singleShot(0,lambda d=cached_data:self._apply_volume_plan_data(d))
            return
        if self.workflow_mode == 'volume':
            self._show_volume_acquisition_loading()
        worker=(VolumePlanWorker if self.workflow_mode == 'volume' else ChapterPlanWorker)(request_id,self.current_source,self.current_manga_url,lang,self)
        self._plan_workers.append(worker)
        worker.ready.connect(self._on_volume_plan_ready); worker.failed.connect(self._on_volume_plan_failed)
        worker.finished.connect(lambda w=worker:self._cleanup_worker(w,self._plan_workers)); worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_volume_plan_ready(self, data):
        if data.get('request_id') != self._volume_plan_request_id:
            return
        source=SOURCE_REGISTRY.get(data.get('source_id')) or self.current_source
        mid=source.parse_manga_ref(data.get('url') or '')
        response_mode='volume' if 'plan' in data else 'chapter'
        if mid:
            cached_payload={
                'url':data.get('url'),'language':data.get('language'),'plan':data.get('plan') or {},
                'source_id':source.source_id,'covers':data.get('covers') or {},'cover_error':data.get('cover_error') or '',
                'chapters':data.get('chapters') or [],
            }
            self._plan_cache[(response_mode,source.source_id,mid,data.get('language'))]=cached_payload
            chapters=tuple(data.get('chapters') or ())
            if chapters and response_mode == 'volume':
                other='chapter'
                other_payload=dict(cached_payload)
                self._plan_cache[(other,source.source_id,mid,data.get('language'))]=other_payload
        self._apply_volume_plan_data(data)

    def _apply_volume_plan_data(self, data):
        request_id=data.get('request_id'); language=data.get('language')
        if request_id != self._volume_plan_request_id or language != self.language.currentData():
            return
        self._loaded_covers=dict(data.get('covers') or {})
        self._loaded_covers.update(self._reference_volume_covers)
        if data.get('cover_error'):
            self.add_log('Volume-cover metadata unavailable: '+str(data.get('cover_error')))
        if self.workflow_mode == 'chapter':
            chapters=data.get('chapters') or []
            self._apply_chapter_plan(request_id,language,chapters)
        else:
            self._volume_acquisition_items=tuple(
                dict(row, _source_id=str(row.get('_source_id') or self.current_source_id),
                     _source_name=str(row.get('_source_name') or self.current_source.display_name))
                for row in data.get('chapters') or ()
            )
            self._native_volume_plan=dict(data.get('plan') or {})
            native=len(self._native_volume_plan.get('volumes') or ())
            standalone=int(self._native_volume_plan.get('bonus_chapters') or 0)
            generation=getattr(self,'_workflow_inventory_generation',-1)
            if not self.workflow_state.settle_volume_acquisition(
                    generation,request_id,native,standalone):
                return
            if not standalone:
                self.workflow_state.finalize_volume_inventory(
                    generation,request_id,native,0,0
                )
                self._apply_volume_plan(request_id,language,self._native_volume_plan)
            elif self.workflow_state.publication_resolution_state == 'terminal':
                if not self._refresh_unified_volume_plan():
                    self._finalize_pending_volume_fallback()
            else:
                self._show_pending_volume_resolution()

    def _apply_volume_plan(self, request_id, language, plan, announce_ready=True):
        if request_id != self._volume_plan_request_id or language != self.language.currentData():
            return
        self._volume_plan_loading=False; self._current_plan=plan
        if plan.get('aggregate_error'):
            self.add_log(f'[{self.current_source.display_name}] Aggregate lookup warning: '+str(plan.get('aggregate_error')))
        if plan.get('feed_error'):
            self.add_log(f'[{self.current_source.display_name}] Chapter-feed lookup warning: '+str(plan.get('feed_error')))
        chapter_total=sum(int(v or 0) for v in (plan.get('chapters_by_volume') or {}).values()) + int(plan.get('bonus_chapters') or 0)
        self._download_language_valid=chapter_total > 0
        inventory_rows=[{'id':f'volume:{float(volume):g}','volume':float(volume)} for volume in plan.get('volumes') or ()]
        if int(plan.get('bonus_chapters') or 0):
            inventory_rows.append({'id':'standalone','volume':None})
        self.workflow_state.apply_inventory(
            getattr(self,'_workflow_inventory_generation',-1),inventory_rows
        )
        self._rebuild_volume_list(); self.volume_list.setEnabled(self._download_language_valid)
        self._update_preview_button_for_volume_selection()
        if self._download_language_valid and self.preview_data is None:
            self.preview_summary.setText('Final Outputs will be prepared after Next: Finalization.')
        if self._download_language_valid:
            self.availability_badge.setVisible(False)
            numeric=len(plan.get('volumes') or [])
            extras=int(plan.get('bonus_chapters') or 0)
            self._set_selected_inventory_count(numeric + (1 if extras else 0))
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
            if announce_ready:
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
            acquisition_items=tuple(sorted(items, key=chapter_sort_key))
            if planned.fallback_items:
                self.add_log(planned.notice)
        else:
            acquisition_items=tuple(sorted((dict(row) for row in chapters or ()), key=chapter_sort_key))
        self._chapter_acquisition_items=acquisition_items
        if self._selected_fallback_worker and self._selected_fallback_worker.isRunning():
            self._set_chapter_preparing('Preparing acquisition fallback…')
            return
        generation=getattr(self,'_workflow_inventory_generation',-1)
        if not self.workflow_state.settle_chapter_acquisition(
                generation,request_id,'ready',acquisition_items):
            return
        self._try_finalize_chapter_projection()

    def _on_volume_plan_failed(self, data):
        if data.get('request_id') != self._volume_plan_request_id:
            return
        if self.workflow_mode == 'chapter':
            self._volume_plan_loading=False; self._chapter_acquisition_items=()
            self._chapter_acquisition_error='Chapter information could not be loaded. Try the language again.'
            generation=getattr(self,'_workflow_inventory_generation',-1)
            if self.workflow_state.settle_chapter_acquisition(
                    generation,self._volume_plan_request_id,'terminal_failure',()):
                self._try_finalize_chapter_projection()
            self._record_diagnostic(RuntimeError, RuntimeError(data.get('error') or 'Unknown error'), None, self._diagnostic_operation)
            self.add_log('Chapter browser unavailable: '+str(data.get('error') or 'Unknown error'))
            return
        self._volume_plan_loading=False; self._download_language_valid=False; self.volume_list.setEnabled(False); self.preview_btn.setEnabled(False)
        self.workflow_state.fail_volume_preparation(
            getattr(self,'_workflow_inventory_generation',-1),self._volume_plan_request_id
        )
        self._set_selected_inventory_count(0)
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

    def _chapter_inventory_cover_url(self, chapter):
        """Choose only artwork already present in current inventory state."""
        publication_cover=str(chapter.get('_publication_cover_url') or '').strip()
        if publication_cover:
            return publication_cover
        edition_art=(self._publication_manifest.display.edition_artwork
                     if self._publication_manifest else None)
        if edition_art and edition_art.url:
            return edition_art.url
        direct=str(chapter.get('cover_url') or '').strip()
        if direct:
            return direct
        try:
            volume=float(chapter.get('volume'))
        except (TypeError,ValueError):
            volume=None
        if volume is not None:
            parent_cover=(self._loaded_covers or {}).get(volume)
            if parent_cover:
                return parent_cover
        return self._main_cover_url or ''

    @staticmethod
    def _chapter_inventory_artwork_identity(chapter, cover_url):
        """Bind a chapter row to immutable artwork, never to its list index."""
        exact=str(chapter.get('_publication_cover_identity') or '').strip()
        if exact and str(chapter.get('_publication_cover_url') or '').strip() == str(cover_url or '').strip():
            return exact
        return 'url:' + str(cover_url or '').strip()

    @staticmethod
    def _row_accepts_artwork_callback(info, url):
        """A callback may update only the artwork identity it requested."""
        if not isinstance(info,dict) or str(info.get('cover_url') or '') != str(url or ''):
            return False
        identity=str(info.get('artwork_identity') or '')
        return not identity or identity == 'url:'+str(url) or identity.endswith('|'+str(url))

    def _rebuild_volume_list(self):
        self._volume_check_syncing=True
        self.volume_list.setUpdatesEnabled(False)
        try:
            self.volume_list.clear(); self.selected_cover.clear()
            if self.workflow_mode == 'chapter':
                rows=tuple(self._chapter_plan_items or ())
                valid=chapter_selection_ids(rows)
                self._selected_chapter_ids.intersection_update(valid)
                self.volume_count_label.setText(f'{len(rows)} chapter' + ('' if len(rows)==1 else 's') if rows else '')
                for chapter in rows:
                    chapter_id=str(chapter.get('id') or '')
                    source_id=str(chapter.get('_source_id') or self.current_source_id)
                    source_name=str(chapter.get('_source_name') or self.current_source.display_name)
                    source_url=self._provider_url_for_source(source_id)
                    cover_url=self._chapter_inventory_cover_url(chapter)
                    artwork_identity=self._chapter_inventory_artwork_identity(chapter,cover_url)
                    item=QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, {'kind':'chapter','chapter':chapter,'chapter_id':chapter_id,
                                                           'cover_url':cover_url,'artwork_identity':artwork_identity,
                                                           'source_id':source_id,'source_url':source_url})
                    item.setSizeHint(QSize(0,72)); self.volume_list.addItem(item)
                    label=chapter_metadata_label(chapter,self.pad.isChecked())
                    source_name=fallback_source_label(source_name,chapter.get('_fallback_reason'))
                    row=VolumeRowWidget(label, self.volume_list, cover_loading=bool(cover_url),
                                        provider_spec=provider_badge_spec(source_id,source_name,source_url))
                    row.set_checked(chapter_id in self._selected_chapter_ids)
                    row.toggled.connect(lambda checked, it=item: self._volume_row_toggled(it, checked))
                    self.volume_list.setItemWidget(item,row)
                self.select_all_btn.setEnabled(bool(rows) and self._download_language_valid)
                self.clear_volume_btn.setEnabled(False)
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
            group_by_volume={float(group.get('volume')):group for group in plan.get('volume_groups') or ()
                             if group.get('kind') == 'volume' and group.get('volume') is not None}
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
                grouping_provenance=str((group_by_volume.get(float(v)) or {}).get('provenance') or 'native')
                item=QListWidgetItem()
                source_url=self._provider_url_for_source(self.current_source_id)
                item.setData(Qt.ItemDataRole.UserRole,{'kind':'volume','volume':float(v),'cover_url':c,
                                                       'source_id':self.current_source_id,'source_url':source_url,
                                                       'grouping_provenance':grouping_provenance})
                item.setSizeHint(QSize(0,72)); self.volume_list.addItem(item)
                row=VolumeRowWidget(f'Volume {v:g}', self.volume_list, cover_loading=bool(c),
                                    provider_spec=provider_badge_spec(self.current_source_id,self.current_source.display_name,source_url))
                row.set_checked(float(v) in self._selected_volumes)
                row.toggled.connect(lambda checked, it=item: self._volume_row_toggled(it, checked))
                self.volume_list.setItemWidget(item,row)
                if c and not self._selected_cover_url:
                    self._selected_cover_url=c
            if standalone_count:
                item=QListWidgetItem()
                source_url=self._provider_url_for_source(self.current_source_id)
                item.setData(Qt.ItemDataRole.UserRole,{'kind':'standalone','volume':None,'cover_url':self._main_cover_url or self._selected_cover_url or '','chapter_count':standalone_count,
                                                       'source_id':self.current_source_id,'source_url':source_url})
                item.setSizeHint(QSize(0,72)); self.volume_list.addItem(item)
                label=f'Standalone Chapters  ·  {standalone_count} chapter' + ('' if standalone_count==1 else 's')
                row=VolumeRowWidget(label, self.volume_list, cover_loading=bool(self._main_cover_url or self._selected_cover_url),
                                    provider_spec=provider_badge_spec(self.current_source_id,self.current_source.display_name,source_url))
                row.set_checked(bool(self._standalone_selected))
                row.toggled.connect(lambda checked, it=item: self._volume_row_toggled(it, checked))
                self.volume_list.setItemWidget(item,row)
        finally:
            self._volume_check_syncing=False
            self.volume_list.setUpdatesEnabled(True)
        self.select_all_btn.setEnabled(bool(total_entries) and bool(self._download_language_valid))
        self.clear_volume_btn.setEnabled(False)
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
                big=self._pix_for_url(self._selected_cover_url,150,210)
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
                pix=self._pix_for_url(url,42,58)
                row=self.volume_list.itemWidget(item)
                if isinstance(row, VolumeRowWidget): row.set_cover(pix)
                if url==self._selected_cover_url:
                    big=self._pix_for_url(url,150,210)
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
        worker=self._retain_async_worker(ImageBatchWorker(
            ('volume',token,generation),unique,source=self.current_source
        ))
        self.volume_thumb_worker=worker
        # Keep image decoding and all QWidget mutation on the dialog's GUI thread.
        worker.image_ready.connect(self._on_volume_thumb_ready)
        worker.image_failed.connect(self._on_volume_thumb_failed)
        worker.finished.connect(lambda w=worker:self._on_volume_thumb_finished(w))
        worker.start()

    def _on_volume_thumb_ready(self, data):
        batch_id=data.get('batch_id') or ()
        _kind, token, generation=(batch_id + (None,None,None))[:3] if isinstance(batch_id,tuple) else (None,None,None)
        if self._closing or generation != self._cover_generation or token != self._volume_cover_batch_token:
            return
        url=data.get('key'); raw=data.get('raw')
        if not url or not raw: return
        self._store_image_bytes(url,raw)
        for i in range(self.volume_list.count()):
            item=self.volume_list.item(i); info=item.data(Qt.ItemDataRole.UserRole) or {}
            if self._row_accepts_artwork_callback(info,url):
                pix=self._pix_for_url(url,42,58)
                row=self.volume_list.itemWidget(item)
                if isinstance(row, VolumeRowWidget): row.set_cover(pix)
        if url==self._selected_cover_url:
            big=self._pix_for_url(url,150,210)
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

    def _on_volume_thumb_finished(self, worker):
        if self.volume_thumb_worker is worker:
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
            self.pairing_preview_btn.setVisible(True)
            self._update_live_preview_action()
        self.invalidate_preview()

    def _selected_chapter_rows(self):
        selected=set(self._selected_chapter_ids)
        return tuple(
            dict(row) for row in self._chapter_plan_items or ()
            if str(row.get('id') or '') in selected
        )

    def _volume_evidence_sources(self):
        sources=[]
        for inventory in self._selected_resolution_inventories or ():
            sources.append(VolumeEvidenceSource(
                inventory.source_id, self._selected_work_id,
                inventory.edition, tuple(inventory.chapter_records or ()),
            ))
        # Direct loads and single-provider searches can always use explicit
        # mappings already present on the selected page inventory.
        sources.append(VolumeEvidenceSource(
            self.current_source_id, self._selected_work_id,
            self._selected_edition, tuple(self._chapter_plan_items or ()),
        ))
        return tuple(sources)

    def _refresh_chapter_output_options(self):
        if not hasattr(self,'chapter_output_combo'):
            return
        selected=self._selected_chapter_rows() if self.workflow_mode == 'chapter' else ()
        self._chapter_volume_evidence=resolve_volume_evidence(
            selected,self._volume_evidence_sources(),page_source_id=self.current_source_id,
            page_work_id=self._selected_work_id,page_edition=self._selected_edition,
        ) if selected else None
        automatic=bool(self._chapter_volume_evidence and self._chapter_volume_evidence.available)
        model_item=self.chapter_output_combo.model().item(0)
        if model_item is not None:
            model_item.setEnabled(automatic)
        if self.workflow_mode != 'chapter':
            desired=ChapterOutputMode.INDIVIDUAL_CHAPTERS
        elif self._chapter_output_user_selected:
            desired=self._chapter_output_mode
            if desired is ChapterOutputMode.DETECTED_VOLUMES and not automatic:
                desired=ChapterOutputMode.INDIVIDUAL_CHAPTERS
                self._chapter_output_user_selected=False
            elif desired is ChapterOutputMode.MANUAL_VOLUMES and not validate_manual_assignments(selected,self._manual_volume_assignments):
                desired=ChapterOutputMode.INDIVIDUAL_CHAPTERS
                self._chapter_output_user_selected=False
        else:
            desired=ChapterOutputMode.DETECTED_VOLUMES if automatic else ChapterOutputMode.INDIVIDUAL_CHAPTERS
        self._chapter_output_mode=desired
        self._chapter_output_syncing=True
        try:
            index=self.chapter_output_combo.findData(desired.value)
            self.chapter_output_combo.setCurrentIndex(max(0,index))
        finally:
            self._chapter_output_syncing=False
        if hasattr(self,'chapter_output_reason'):
            evidence_reason=(self._chapter_volume_evidence.reason if self._chapter_volume_evidence else '')
            self.chapter_output_reason.setText(
                evidence_reason if automatic and self._chapter_volume_evidence.unassigned else
                ('' if automatic else (evidence_reason or 'Volume data unavailable for this selection.'))
            )
        manual_active=(
            desired is ChapterOutputMode.MANUAL_VOLUMES and
            validate_manual_assignments(selected,self._manual_volume_assignments)
        )
        if hasattr(self,'manual_group_summary'):
            volumes={str(value) for value in self._manual_volume_assignments.values()} if manual_active else set()
            self.manual_group_summary.setText(
                f'Manual Groups · {len(volumes)} volume' + ('' if len(volumes)==1 else 's') +
                f' from {len(selected)} chapters' if manual_active else ''
            )
            self.manual_group_summary.setVisible(manual_active)
            self.edit_manual_groups_btn.setVisible(manual_active)

    def _chapter_output_mode_changed(self, index):
        if self._chapter_output_syncing or self.workflow_mode != 'chapter':
            return
        value=self.chapter_output_combo.itemData(index)
        try:
            selected_mode=ChapterOutputMode(str(value))
        except ValueError:
            return
        previous=self._chapter_output_mode
        if selected_mode is ChapterOutputMode.DETECTED_VOLUMES and not (
                self._chapter_volume_evidence and self._chapter_volume_evidence.available):
            self._refresh_chapter_output_options(); return
        if selected_mode is ChapterOutputMode.MANUAL_VOLUMES:
            if not self._edit_manual_groups():
                self._chapter_output_syncing=True
                try:
                    self.chapter_output_combo.setCurrentIndex(self.chapter_output_combo.findData(previous.value))
                finally:
                    self._chapter_output_syncing=False
                return
        self._chapter_output_mode=selected_mode
        self._chapter_output_user_selected=True
        self.invalidate_preview()
        self._refresh_chapter_output_options()

    def _edit_manual_groups(self, *_args):
        selected=self._selected_chapter_rows()
        dialog=ManualChapterVolumeDialog(selected,self._manual_volume_assignments,self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self._manual_volume_assignments=dict(dialog.assignments)
        self._chapter_output_mode=ChapterOutputMode.MANUAL_VOLUMES
        self._chapter_output_user_selected=True
        self.invalidate_preview()
        self._refresh_chapter_output_options()
        return True

    def _build_chapter_output_plan(self):
        return tuple(group.to_record() for group in plan_chapter_outputs(
            self._selected_chapter_rows(),self._chapter_output_mode,
            evidence=self._chapter_volume_evidence,
            manual_assignments=self._manual_volume_assignments,
        ))

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

    def _applied_metadata_values(self):
        data=dict(self._applied_metadata or {})
        return (
            str(data.get('title') or '').strip(),
            str(data.get('author') or '').strip(),
            str(data.get('series') or '').strip(),
        )

    def _set_applied_metadata(self,title,author,series,sync_fields=True):
        self._applied_metadata={'title':str(title or '').strip(),'author':str(author or '').strip(),'series':str(series or '').strip()}
        if sync_fields and hasattr(self,'title'):
            self._syncing_metadata_fields=True
            try:
                for widget,value in ((self.title,title),(self.author,author),(self.series,series)):
                    widget.blockSignals(True); widget.setText(str(value or '')); widget.blockSignals(False)
            finally:
                self._syncing_metadata_fields=False
        self._metadata_pending=False
        if hasattr(self,'apply_metadata_btn'):
            self.apply_metadata_btn.setEnabled(False)
            self.metadata_pending_label.setText('Metadata applied')
            self.metadata_pending_label.setStyleSheet('color:#8F9499; font-size:11px;')

    def current_signature(self):
        applied_title,applied_author,applied_series=self._applied_metadata_values()
        return (
            self.workflow_mode, self.current_source_id, self.current_manga_url, applied_title, applied_author, applied_series,
            self.language.currentData(), self.start.text().strip(), self.end.text().strip(), tuple(sorted(self._selected_volumes)), bool(self._standalone_selected), bool(self._using_entire_series),
            tuple(sorted(self._selected_chapter_ids)),
            self._chapter_output_mode.value,
            tuple(sorted((str(key),str(value)) for key,value in self._manual_volume_assignments.items())),
            self.covers.isChecked(), self.pad.isChecked(), self.page_layout.currentData(), self.reading_direction.currentData()
        )

    def _clear_preview_state(self, summary=None, keep_rows=False):
        self.preview_signature = None
        self.preview_data = None
        self.download_btn.setEnabled(False)
        if hasattr(self, 'preview_table') and not keep_rows:
            self.preview_table.blockSignals(True)
            self.preview_table.setRowCount(0)
            self.preview_table.blockSignals(False)
            self.preview_table.setVisible(True)
        if summary is not None and hasattr(self, 'preview_summary'):
            self.preview_summary.setText(summary)

    def _live_preview_signature_value(self):
        selection=(tuple(sorted(self._selected_chapter_ids)) if self.workflow_mode == 'chapter'
                   else (tuple(sorted(self._selected_volumes)),bool(self._standalone_selected)))
        return (self.workflow_mode,self.current_source_id,self.current_manga_url,
                self.language.currentData(),selection,self.page_layout.currentData(),
                self.reading_direction.currentData())

    def _reset_live_preview(self, message='Preview is optional and off.'):
        self._live_preview_request_id += 1
        if self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_worker.cancel()
        self.pairing_preview_worker=None
        self._active_preview_sample_key=None
        self._live_preview_stale=False
        self.workflow_state.preview_state='off'; self.workflow_state.preview_stale=False
        if hasattr(self,'live_preview_status'):
            self.live_preview_status.setText(message)
            self.live_preview_empty.setText('No preview sample loaded.\n\nPreview is never required to continue.')
            self.live_preview_empty.setVisible(True); self.live_preview_scroll.setVisible(False)
            self._update_live_preview_action()

    def _mark_live_preview_stale(self):
        if self.workflow_state.preview_state == 'off' and not self._active_preview_sample_key:
            return
        self._live_preview_request_id += 1
        if self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_worker.cancel()
        self.pairing_preview_worker=None
        self._live_preview_stale=True
        self.workflow_state.preview_state='stale'; self.workflow_state.preview_stale=True
        self._update_live_preview_action()

    def invalidate_preview(self, *args):
        if self.workflow_mode == 'chapter':
            selection=tuple(sorted(self._selected_chapter_ids))
        else:
            selection=tuple(f'volume:{value:g}' for value in sorted(self._selected_volumes))
            if self._standalone_selected:
                selection += ('standalone',)
            if self._using_entire_series:
                selection += ('entire-series',)
        self.workflow_state.set_inventory_selection(selection)
        current=self.current_signature()
        if (self._active_preview_sample_key is not None and
                self._active_preview_sample_key != self._live_preview_signature_value()):
            self._mark_live_preview_stale()
        if self._preview_build_signature is not None and current != self._preview_build_signature:
            self._invalidate_inflight_preview()
        self.workflow_state.invalidate_downstream()
        self.download_btn.setEnabled(False)
        if hasattr(self,'rebuild_finalization_btn'):
            self.rebuild_finalization_btn.setVisible(self.workflow_state.stage == 'finalization')
        if self.workflow_state.stage == 'finalization':
            self.workflow_hint.setText('Final Outputs are out of date. Refresh them to continue.')
        self._update_preview_button_for_volume_selection()

    def _bulk_metadata_changed(self, *_args):
        if self._syncing_metadata_fields:
            return
        applied_title,applied_author,applied_series=self._applied_metadata_values()
        pending=(self.title.text().strip(),self.author.text().strip(),self.series.text().strip())
        self._metadata_pending=pending != (applied_title,applied_author,applied_series)
        if hasattr(self,'apply_metadata_btn'):
            can_apply=bool(self._metadata_pending and pending[0] and pending[2] and self.preview_data and self._preview_build_signature is None)
            self.apply_metadata_btn.setEnabled(can_apply)
            self.metadata_pending_label.setText('Unapplied metadata edits' if self._metadata_pending else 'Metadata applied')
            self.metadata_pending_label.setStyleSheet(
                f'color:{ORANGE}; font-size:11px; font-weight:650;' if self._metadata_pending
                else 'color:#8F9499; font-size:11px;'
            )
        self._update_workflow_actions()

    def apply_metadata(self):
        if not self.preview_data or self._preview_build_signature is not None:
            return
        base=self.title.text().strip(); author=self.author.text().strip(); series=self.series.text().strip()
        if not base or not series:
            self.metadata_pending_label.setText('Title and Series are required.')
            return
        self._set_applied_metadata(base,author,series,sync_fields=False)
        rows=self.preview_data.get('rows') or []
        for index,row in enumerate(rows):
            if row.get('kind') == 'chapter' and row.get('chapter'):
                row['title']=chapter_output_title(base,row['chapter'],self.pad.isChecked())
            elif row.get('volume') is not None:
                row['title']=f'{base} (Vol. {fmt_volume(row["volume"],self.pad.isChecked())})'
            else:
                row['title']=f'{base} (Standalone Chapters)'
            row['author']=author; row['series']=series
            cell=self.preview_table.item(index,3)
            if cell is not None: cell.setText(row['title'])
        self.preview_signature=self.current_signature()
        self.workflow_state.set_finalization_plan(tuple(dict(row) for row in rows))
        self.refresh_preview_selection_summary()
        self.add_log('Applied bulk Title, Series, and Author metadata to Final Outputs.')
        self._update_workflow_actions()

    def add_log(self, text):
        if text:
            if hasattr(self,'activity_status'):
                compact=str(text).replace('\n',' ').strip()
                self.activity_status.setText(compact[:150] + ('…' if len(compact) > 150 else ''))
            # Keep the activity history readable when callbacks repeat a state.
            if self.log.count() and self.log.item(self.log.count()-1).text() == text:
                return
            item = QListWidgetItem(text)
            key = text.casefold()
            if any(token in key for token in ('selected ', 'finalization ready', 'download complete', 'loaded mangadex metadata', 'all selected')):
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
        enrichment_was_enabled=bool(prefs['search_enrichment'])
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
            if enrichment_was_enabled and not bool(prefs['search_enrichment']):
                self._enrichment_request_id += 1
                if self._enrichment_worker and self._enrichment_worker.isRunning():
                    self._enrichment_worker.requestInterruption()
                self._enrichment_worker=None; self._external_candidates=(); self._enrichment_received=True
                self._rebuild_enriched_results()
            if d.cache_cleared:
                self._search_cache.clear(); self._download_availability_cache.clear()
                self._search_resolution_metadata_cache.clear()
                self._active_query_cache_key=''
                self.add_log('Search and metadata cache cleared; the next search will be cold.')
            self.add_log('Preferences updated.')

    def open_manga_sources(self):
        before=tuple(source.source_id for source in enabled_sources(SOURCE_REGISTRY,prefs))
        dialog = MangaSourcesDialog(SOURCE_REGISTRY, prefs, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            enabled=tuple(enabled_sources(SOURCE_REGISTRY,prefs))
            enabled_ids=tuple(source.source_id for source in enabled)
            names = [source.display_name for source in enabled]
            summary = ', '.join(names) if names else 'none'
            self.add_log(f'General-search sources updated: {summary}.')
            disabled=set(before)-set(enabled_ids)
            newly_enabled=set(enabled_ids)-set(before)
            if disabled:
                self._search_content_results=[row for row in self._search_content_results if row.get('source_id') not in disabled]
                self._search_raw_results=[row for row in self._search_raw_results if row.get('source_id') not in disabled]
                self.workflow_state.apply_source_configuration(enabled_ids)
                if self.current_source_id in disabled:
                    self._clear_active_provider_selection('Selected source was disabled. Choose another result.')
                self._render_provider_search_results()
            if newly_enabled:
                self.workflow_hint.setText('Sources changed. Search again to include newly enabled sources.')

    def choose_alternate_title(self):
        md = self.loaded_metadata or {}
        rows = list(meaningful_alternate_titles(md.get('titles') or (),self.title.text().strip()))
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
        rows=sorted(rows, key=lambda r: (0 if r.get('language')==preferred else 1 if r.get('language')=='en' else 2, 0 if r.get('primary') else 1, title_language_label(r).casefold(), r.get('title','').casefold()))
        for row in rows:
            prefix = title_language_label(row)
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
                self.add_log(f'Selected alternate title as pending metadata: {title}')

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

    def _restyle_inventory_rows(self):
        """Apply a bulk selection state in one repaint batch."""
        was_syncing=self._volume_check_syncing
        self._volume_check_syncing=True
        self.volume_list.setUpdatesEnabled(False)
        try:
            for index in range(self.volume_list.count()):
                self._style_volume_item(self.volume_list.item(index))
        finally:
            self.volume_list.setUpdatesEnabled(True)
            self._volume_check_syncing=was_syncing
        self.volume_list.viewport().update()

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
        has_selection = bool(self._has_volume_selection() and not self._manual_range_invalid and
                             self._download_language_valid and not self._volume_plan_loading and
                             not self._volume_resolution_pending())
        stage=self.workflow_state.stage
        if stage == 'choose_manga':
            self.download_btn.setEnabled(False)
            self._set_action_role(self.preview_btn,'primaryAction')
            if self.workflow_mode not in ('volume','chapter'):
                self.preview_btn.setEnabled(False); self.workflow_hint.setText('Choose Volumes or Chapters to begin.')
            elif not self.loaded_metadata:
                self.preview_btn.setEnabled(False); self.workflow_hint.setText('Search for and select a manga.')
            elif self._volume_resolution_pending():
                self.preview_btn.setEnabled(False); self.workflow_hint.setText('Resolving stable volume inventory…')
            elif not has_selection:
                noun='chapter' if self.workflow_mode == 'chapter' else 'volume'
                self.preview_btn.setEnabled(False); self.workflow_hint.setText(f'Select at least one {noun} to continue.')
            else:
                self.preview_btn.setEnabled(True); self.workflow_hint.clear()
            return
        if stage == 'book_customization':
            self.preview_btn.setEnabled(has_selection)
            self.download_btn.setEnabled(False)
            self._set_action_role(self.preview_btn,'primaryAction')
            if self._volume_resolution_pending():
                self.workflow_hint.setText('Return to Choose Manga while volume inventory finishes resolving.')
            else:
                self.workflow_hint.setText('Live Preview is optional.' if has_selection else 'Return to Choose Manga and select content.')
            return
        active_build = self._preview_build_signature is not None and self._preview_build_signature == self.current_signature()
        finalization_current = bool(self.preview_data and self.preview_signature == self.current_signature() and not self.workflow_state.finalization_stale)
        selected_downloads = int((self.preview_data or {}).get('selected_download_count', 0) or 0) if finalization_current else 0
        if not has_selection:
            self.download_btn.setEnabled(False)
            self._set_action_role(self.download_btn, 'tertiaryAction')
            self.workflow_hint.setText('Return to Choose Manga and select content.')
            return
        if active_build:
            self.download_btn.setEnabled(False)
            self._set_action_role(self.download_btn, 'tertiaryAction')
            self.workflow_hint.setText('Preparing Finalization…')
            return
        if self._metadata_pending:
            self.download_btn.setEnabled(False)
            self._set_action_role(self.download_btn,'tertiaryAction')
            self.workflow_hint.setText('Apply pending metadata edits before downloading.')
            return
        if finalization_current:
            self.download_btn.setEnabled(selected_downloads > 0)
            self._set_action_role(self.download_btn, 'primaryAction' if selected_downloads > 0 else 'tertiaryAction')
            self.workflow_hint.setText('' if selected_downloads > 0 else 'Nothing is selected for download.')
        else:
            self.download_btn.setEnabled(False)
            self._set_action_role(self.download_btn, 'tertiaryAction')
            self.workflow_hint.setText('Final Outputs are out of date. Refresh them to continue.')

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
            if self.workflow_mode == 'chapter':
                self._chapter_output_user_selected=False
                self._manual_volume_assignments={
                    key:value for key,value in self._manual_volume_assignments.items()
                    if key in self._selected_chapter_ids
                }
                self._refresh_chapter_output_options()
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
        if self.workflow_mode not in ('volume','chapter'):
            self.range_hint.setText('Choose Volumes or Chapters to begin.')
            self.range_hint.setStyleSheet('color:#8F9499; font-size:11px;')
            if hasattr(self,'clear_volume_btn'):
                self.select_all_btn.setEnabled(False); self.clear_volume_btn.setEnabled(False)
            return
        if self.workflow_mode == 'chapter':
            count=len(self._selected_chapter_ids)
            total=len(self._chapter_plan_items or ())
            self.range_hint.setText(f'{count} chapter' + ('' if count==1 else 's') + f' selected of {total}.' if count else 'Select at least one chapter to continue.')
            self.range_hint.setStyleSheet(f'color:{ORANGE}; font-size:11px; font-weight:600;' if count else 'color:#8F9499; font-size:11px;')
            if hasattr(self, 'clear_volume_btn'):
                self.select_all_btn.setEnabled(bool(total) and bool(self._download_language_valid))
                self.clear_volume_btn.setEnabled(bool(count))
            return
        selected_count=len(self._selected_volumes) + (1 if self._standalone_selected else 0)
        if self._using_entire_series and selected_count:
            numeric=len(self._selected_volumes)
            extra=' plus Standalone Chapters' if self._standalone_selected else ''
            self.range_hint.setText(f'{selected_count} item' + ('' if selected_count==1 else 's') + f' selected: {numeric} volume' + ('' if numeric==1 else 's') + extra + '.')
            self.range_hint.setStyleSheet(f'color:{ORANGE}; font-size:11px; font-weight:600;')
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
            plan=self._current_plan or {}
            has_numbered=bool(self._available_volume_values())
            has_standalone=bool(int(plan.get('bonus_chapters') or 0))
            self.range_hint.setText(volume_selection_hint(has_numbered,has_standalone))
            self.range_hint.setStyleSheet('color:#8F9499; font-size:11px;')
        if hasattr(self,'clear_volume_btn'):
            plan=self._current_plan or {}
            has_available=bool(self._available_volume_values() or int(plan.get('bonus_chapters') or 0)) and bool(self._download_language_valid)
            has_selection=bool(selected_count)
            self.select_all_btn.setEnabled(has_available)
            self.clear_volume_btn.setEnabled(has_selection)

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

    def _clear_inventory_selection(self):
        if self.workflow_mode == 'chapter':
            if not self._selected_chapter_ids:
                return
            self._selected_chapter_ids.clear()
            self._chapter_output_user_selected=False; self._manual_volume_assignments={}; self._refresh_chapter_output_options()
            self._restyle_inventory_rows()
            self._update_volume_selection_hint(); self.invalidate_preview(); self.add_log('All chapters cleared.')
            return
        self._deselect_all_volumes()

    def _select_all_inventory(self):
        if self.workflow_mode == 'chapter':
            selected=chapter_selection_ids(self._chapter_plan_items)
            if selected == self._selected_chapter_ids:
                return
            self._selected_chapter_ids=selected
            self._chapter_output_user_selected=False; self._refresh_chapter_output_options()
            self._restyle_inventory_rows()
            self._update_volume_selection_hint(); self.invalidate_preview(); self.add_log(f'All {len(selected)} chapters selected.')
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
        self.add_log(f'All selected: {numeric} volume' + ('' if numeric==1 else 's') + extra + '.')

    def _use_entire_series(self):
        """Compatibility wrapper for older signal/test references."""
        self._select_all_inventory()

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
        self._interrupt_async_workers()
        for worker in self.search_workers.values():
            if worker.isRunning(): worker.requestInterruption()
        if self._search_resolution_worker and self._search_resolution_worker.isRunning():
            self._search_resolution_worker.requestInterruption()
        if self._selected_fallback_worker and self._selected_fallback_worker.isRunning():
            self._selected_fallback_worker.requestInterruption()
        if hasattr(self,'_search_status_timer'): self._search_status_timer.stop()
        self._invalidate_inflight_preview()
        self._invalidate_cover_requests()
        if hasattr(self, '_cover_pulse_timer'): self._cover_pulse_timer.stop()
        self._restore_diagnostic_hook()
        self._remove_range_focus_behavior()
        self._metadata_search_cache.close()
        self._save_session(); super().closeEvent(event)

    def reject(self):
        self._closing=True
        self._interrupt_async_workers()
        for worker in self.search_workers.values():
            if worker.isRunning(): worker.requestInterruption()
        if self._search_resolution_worker and self._search_resolution_worker.isRunning():
            self._search_resolution_worker.requestInterruption()
        if self._selected_fallback_worker and self._selected_fallback_worker.isRunning():
            self._selected_fallback_worker.requestInterruption()
        if self._enrichment_worker and self._enrichment_worker.isRunning():
            self._enrichment_worker.requestInterruption()
        if hasattr(self,'_search_status_timer'): self._search_status_timer.stop()
        self._invalidate_inflight_preview()
        self._invalidate_cover_requests()
        if hasattr(self, '_cover_pulse_timer'): self._cover_pulse_timer.stop()
        self._restore_diagnostic_hook()
        self._remove_range_focus_behavior()
        self._metadata_search_cache.close()
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
        title,author,series=self._applied_metadata_values()
        url = self.current_manga_url.strip()
        if not self.current_source or self.current_source.parse_manga_ref(url) is None: raise ValueError('Enter a valid supported manga link.')
        if not title or not series: raise ValueError('Load a manga title first.')
        if not self.language.currentData(): raise ValueError('Choose an available Download Language before continuing.')
        if self._volume_plan_loading: raise ValueError('MangaNana is still checking chapters for the selected Download Language.')
        if self._volume_resolution_pending():
            raise ValueError('MangaNana is still matching downloadable chapters to published volumes.')
        if not self._download_language_valid: raise ValueError(f'No downloadable chapters are available in {self.language.currentText()}. Choose another Download Language.')
        if self.workflow_mode not in ('volume','chapter'):
            raise ValueError('Choose Volumes or Chapters before continuing.')
        if self.workflow_mode == 'chapter':
            if not self._selected_chapter_ids:
                raise ValueError('Select at least one chapter to continue.')
            return url, title, author, series, None, None
        if not self._has_volume_selection():
            raise ValueError('Select at least one volume to continue.')
        if self._current_plan is not None:
            vols=[float(v) for v in (self._current_plan.get('volumes') or [])]
            if self._selected_volumes:
                missing=sorted(v for v in self._selected_volumes if v not in set(vols))
                if missing:
                    raise ValueError('One or more checked volumes are no longer available for this language.')
        return url, title, author, series, None, None

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
            self._session_replace_existing = True
            return set(), existing
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
                return set(), existing
            if box.clickedButton() is skip:
                self._session_replace_existing = False
                return existing, set()
            raise RuntimeError('Preview cancelled.')
        self._session_replace_existing = False
        return existing, set()

    def continue_preview(self, *_args):
        if self.workflow_state.stage != 'finalization':
            return
        try:
            url, title, author, series, s, e = self.validate_details()
            exact=sorted(self._selected_volumes)
            fetch_s, fetch_e = s, e
            if exact and not self._using_entire_series:
                fetch_s, fetch_e = min(exact), max(exact)
            elif self._using_entire_series:
                fetch_s, fetch_e = None, None
            existing,replacements = self.effective_existing_for_policy(series)
            if self.width() < 1280:
                self.resize(1320, max(self.height(), 700))
            self._set_work_progress_visible(True)
            self.preview_table.setRowCount(0)
            self.preview_summary.setText(f'Loading {self.current_source.display_name} chapter information and checking your Calibre library...')
            self.progress.setDeterminateValue(0)
            self.progress_text.setText('Preparing Finalization...')
            self.add_log('Preparing Finalization...')
            self.preview_table.setVisible(True)
            self.preview_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self.rebuild_finalization_btn.setVisible(False)
            self._set_cancel_action(True,'Cancel Finalization Preparation')
            self._preview_request_id += 1
            self._review_cancel_requested=False
            request_id=self._preview_request_id
            build_signature=self.current_signature()
            self._preview_build_signature=build_signature
            if self.workflow_mode == 'chapter':
                chapter_output_plan=self._build_chapter_output_plan()
            elif (self._current_plan or {}).get('requires_grouped_output'):
                selected=(self._current_plan or {}).get('volumes') if self._using_entire_series else exact
                chapter_output_plan=selected_unified_volume_groups(
                    self._current_plan,selected,
                    bool(self._standalone_selected or self._using_entire_series),
                )
            else:
                chapter_output_plan=None
            worker = PreviewWorker(self.current_source, url, title, author, series, self.language.currentData(), fetch_s, fetch_e,
                                   self.pad.isChecked(), existing, replacements, selected_volumes=None if self._using_entire_series else exact,
                                   include_standalone=bool(self._standalone_selected or self._using_entire_series),
                                   bytes_per_page=self._bytes_per_page_estimate,
                                   planned_chapters=self._chapter_plan_items if self.workflow_mode == 'chapter' else None,
                                   chapter_items=self._selected_chapter_ids if self.workflow_mode == 'chapter' else None,
                                   chapter_output_plan=chapter_output_plan)
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
        if (self.workflow_state.stage != 'finalization' or self._review_cancel_requested or
                request_id != self._preview_request_id or build_signature != self.current_signature()):
            return
        self.progress.setDeterminateValue(percent)
        self.progress_text.setText(text)

    def _planned_output_cover_url(self,row):
        """Mirror the downloader's already-resolved cover choice without fetching."""
        if not self.covers.isChecked():
            return ''
        if row.get('kind') == 'volume' or row.get('volume') is not None:
            try:
                volume=float(row.get('volume'))
            except Exception:
                volume=None
            if volume is not None:
                group=dict(row.get('group') or {})
                return resolve_group_cover_url(
                    'volume', volume, self._loaded_covers, self._main_cover_url,
                    group.get('chapters') or (),
                )
        return self._main_cover_url or ''

    def _final_output_cover_widget(self,row):
        host=QWidget(); layout=QHBoxLayout(host); layout.setContentsMargins(4,4,4,4); layout.setSpacing(0)
        cover=QLabel('—'); cover.setAlignment(Qt.AlignmentFlag.AlignCenter); cover.setFixedSize(44,62)
        cover.setStyleSheet('background:#121416; color:#72777C; border:1px solid #34393E; border-radius:4px; font-size:10px;')
        cover_url=row.get('cover_url') or ''
        raw=self._image_cache.get(cover_url) if cover_url else None
        if raw:
            pixmap=self._pix_for_url(cover_url,44,62)
            if pixmap is not None:
                cover.setText(''); cover.setPixmap(pixmap)
        layout.addStretch(1); layout.addWidget(cover); layout.addStretch(1)
        return host

    def _final_output_source_widget(self,row):
        host=QWidget(); layout=QHBoxLayout(host); layout.setContentsMargins(4,2,4,2); layout.setSpacing(4)
        source_ids=tuple(row.get('source_ids') or ())
        if not source_ids:
            source_ids=(str(row.get('source_id') or self.current_source_id),)
        for source_id in source_ids:
            source=SOURCE_REGISTRY.get(source_id)
            display_name=source.display_name if source else str(row.get('source_name') or source_id)
            layout.addWidget(ProviderBadgeWidget(provider_badge_spec(
                source_id,display_name,self._provider_url_for_source(source_id)
            ),host))
        layout.addStretch(1)
        return host

    def on_preview_ready(self, data, request_id=None, build_signature=None):
        if self.workflow_state.stage != 'finalization' or self._review_cancel_requested:
            return
        if request_id is not None and request_id != self._preview_request_id:
            return
        if build_signature is not None and build_signature != self.current_signature():
            return
        self._preview_build_signature = None
        self.progress.setDeterminateValue(100)
        self._set_cancel_action(False)
        self.preview_data = data
        self.preview_signature = build_signature if build_signature is not None else self.current_signature()
        rows = data.get('rows') or []
        self.preview_table.blockSignals(True)
        self.preview_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            self.preview_table.setRowHeight(r,80)
            item['cover_url']=self._planned_output_cover_url(item)
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
            self.preview_table.setCellWidget(r,1,self._final_output_cover_widget(item))
            volume_label = item.get('volume_text') or ('Bonus' if item.get('volume') is None else f"Vol. {float(item['volume']):g}")
            if volume_label and not str(volume_label).lower().startswith(('vol', 'ch.', 'bonus', 'standalone')):
                volume_label = 'Vol. ' + str(volume_label)
            status_text = 'In Calibre' if item.get('existing') else ('Ready' if str(item.get('status') or '').lower() in ('will download','ready') else str(item.get('status') or 'Ready'))
            page_value=item.get('pages')
            source_label=item.get('source_name') or self.current_source.display_name
            vals = [volume_label, item['title'], source_label, format_page_count(page_value), status_text]
            for c, val in enumerate(vals, 2):
                cell=QTableWidgetItem(str(val)); cell.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                self.preview_table.setItem(r, c, cell)
            self.preview_table.setCellWidget(r,4,self._final_output_source_widget(item))
        self.preview_table.blockSignals(False)
        self.preview_table.setVisible(True)
        self._review_focus_row=0
        if rows:
            self.preview_table.selectRow(0)
        self.workflow_state.set_finalization_plan(tuple(dict(row) for row in rows))
        self.refresh_preview_selection_summary()
        self._bulk_metadata_changed()
        self._update_preview_button_for_volume_selection()
        can_download = int(self.preview_data.get('selected_download_count') or 0) > 0
        self._update_workflow_actions()
        self._update_live_preview_action()
        self.progress_text.setText('Finalization ready.' if can_download else 'All selected items already exist in Calibre.')
        if can_download:
            self.add_log('Finalization ready. Check Final Outputs, then choose Download & Add to Calibre.')
        else:
            self.add_log('Nothing to download. Every selected item is already in Calibre.')
            info_dialog(self, 'MangaNana', 'All selected items already exist in Calibre. Nothing will be downloaded.', show=True)
        self.rebuild_finalization_btn.setVisible(False)
        self._set_work_progress_visible(False)

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
        replacement_count = int(self.preview_data.get('replacement_count', 0) or 0)
        layout_text = 'Landscape paired pages' if self.page_layout.currentData() == 'paired_landscape' else 'Portrait pages'
        language_text = self.language.currentText() or 'Unknown language'
        chapter_mode=bool(self.preview_data.get('chapter_mode'))
        standalone_selected=any(bool(r.get('selected')) and r.get('volume') is None for r in rows)
        if existing_count or replacement_count:
            work_label=f'{selected_count} to create'
            replacement_label=f'   •   {replacement_count} replacing' if replacement_count else ''
            existing_label=f'   •   {existing_count} skipped' if existing_count else ''
            first_line = f"{work_label}{replacement_label}{existing_label}   •   {pages_s} pages   •   {est_s}"
        else:
            grouped_chapters=chapter_mode and self.preview_data.get('chapter_output_mode') != ChapterOutputMode.INDIVIDUAL_CHAPTERS.value
            noun = 'volume' if grouped_chapters else ('chapter' if chapter_mode else ('item' if standalone_selected else 'volume'))
            first_line = f"{selected_count} {noun}{'s' if selected_count != 1 else ''}   •   {pages_s} pages   •   {est_s}"
        self.preview_summary.setText(first_line + f"<br>{layout_text}   •   {language_text}")
        self._update_workflow_actions()
        if hasattr(self, 'pairing_preview_btn'):
            self._update_live_preview_action()

    def on_preview_failed(self, msg, request_id=None, build_signature=None):
        if self.workflow_state.stage != 'finalization' or (request_id is not None and request_id != self._preview_request_id):
            return
        if build_signature is not None and build_signature != self.current_signature():
            return
        self._preview_build_signature = None
        self._set_cancel_action(False)
        self._update_preview_button_for_volume_selection()
        self.download_btn.setEnabled(False)
        self.preview_table.setVisible(True)
        self.preview_summary.setText('Final Outputs could not be prepared.')
        self.progress_text.setText('Finalization preparation failed')
        self.workflow_hint.setText(str(msg))
        self.rebuild_finalization_btn.setVisible(True)
        self.add_log(f'Finalization preparation failed: {msg}')
        self._set_work_progress_visible(False)

    def on_preview_cancelled(self, request_id, build_signature):
        if (self.workflow_state.stage != 'finalization' or request_id != self._preview_request_id or
                build_signature != self.current_signature()):
            return
        self._preview_build_signature = None
        self._review_cancel_requested=False
        self.preview_worker = None
        self.progress.setDeterminateValue(0)
        self.progress_text.setText('Finalization preparation cancelled.')
        self.preview_summary.setText('Finalization preparation cancelled. Upstream selections are unchanged.')
        self._set_cancel_action(False)
        self._update_preview_button_for_volume_selection()
        self._update_workflow_actions()
        self.rebuild_finalization_btn.setVisible(True)
        self.add_log('Finalization preparation cancelled.')
        self._set_work_progress_visible(False)

    def _on_preview_worker_finished(self, worker, request_id, build_signature):
        if worker is self.preview_worker:
            self.preview_worker=None
        if (self._review_cancel_requested and request_id == self._preview_request_id and
                build_signature == self.current_signature()):
            self.on_preview_cancelled(request_id, build_signature)

    def _review_focus_changed(self, row, _column):
        self._review_focus_row=max(0,int(row))

    def _focused_review_item(self):
        rows=list((self.preview_data or {}).get('rows') or ())
        if not rows:
            return None
        row=min(max(0,int(self._review_focus_row)),len(rows)-1)
        focused=rows[row]
        if focused.get('selected') and not focused.get('existing'):
            return focused
        return next((item for item in rows if item.get('selected') and not item.get('existing')),None)

    def _preview_sample_target(self):
        if not self._has_volume_selection() or not self.loaded_metadata:
            return None
        if self.workflow_mode == 'chapter':
            chapters=self._selected_chapter_rows()
            return {'volume':None,'label':'Selected Chapters','chapters':chapters} if chapters else None
        if self._selected_volumes:
            volume=min(self._selected_volumes)
            return {'volume':volume,'label':f'Volume {volume:g}','chapters':()}
        if self._standalone_selected:
            return {'volume':None,'label':'Standalone Chapters','chapters':()}
        return None

    def _preview_sample_key(self, _item=None):
        return self._live_preview_signature_value() if self._preview_sample_target() else None

    def _update_live_preview_action(self, focused_change=False):
        if not hasattr(self,'pairing_preview_btn'):
            return
        target=self._preview_sample_target(); key=self._preview_sample_key()
        self.pairing_preview_btn.setVisible(True)
        self.pairing_preview_btn.setEnabled(bool(target))
        if self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_btn.setText('Cancel Preview')
            self.live_preview_status.setText('Loading a bounded preview sample…')
        elif not target:
            self.pairing_preview_btn.setText('Enable Live Preview')
            self.live_preview_status.setText('Select manga content on Choose Manga before enabling preview.')
        elif self.workflow_state.preview_state == 'failed':
            self.pairing_preview_btn.setText('Retry Preview')
            self.live_preview_status.setText('Preview sample could not be loaded. Retry when convenient; Finalization remains available.')
        elif self._live_preview_stale:
            self.pairing_preview_btn.setText('Refresh Preview')
            self.live_preview_status.setText('Preview settings or content changed. Refresh explicitly when you want a new sample.')
        elif key in self._live_preview_samples and self.workflow_state.preview_state == 'ready':
            self.pairing_preview_btn.setText('Refresh Preview')
            self.live_preview_status.setText('A bounded preview sample is shown below. Refresh only when you want to download it again.')
        else:
            self.pairing_preview_btn.setText('Enable Live Preview')
            self.live_preview_status.setText('Preview is optional and off. Enable it to download a small bounded sample.')

    def open_pairing_preview(self):
        if self.pairing_preview_worker and self.pairing_preview_worker.isRunning():
            self.pairing_preview_worker.cancel()
            self._live_preview_request_id += 1
            self.progress_text.setText('Cancelling Live Preview...')
            self._set_work_progress_visible(False)
            self.pairing_preview_btn.setText('Enable Live Preview')
            return
        if self.workflow_state.stage != 'book_customization':
            return
        target=self._preview_sample_target()
        if not target:
            self.live_preview_status.setText('Select manga content on Choose Manga before enabling preview.')
            return
        sample_key=self._preview_sample_key(); volume=target['volume']; label=target['label']
        planned_chapters=tuple(target.get('chapters') or ())
        self._live_preview_request_id += 1; request_id=self._live_preview_request_id
        self._active_preview_sample_key=sample_key
        self.pairing_preview_btn.setText('Cancel Preview')
        self.pairing_preview_btn.setEnabled(True)
        self._set_work_progress_visible(True)
        self.progress.setValue(0)
        self.progress_text.setText(f'Building Live Preview for {label}...')
        self.add_log(f'Building Live Preview for {label}...')
        self.pairing_preview_worker = PairingPreviewWorker(
            self.current_source,self.current_manga_url,self.language.currentData(),volume,
            self.reading_direction.currentData(),planned_chapters,
            layout=self.page_layout.currentData(),sample_label=label,
        )
        self.pairing_preview_worker.ready.connect(lambda data,rid=request_id,key=sample_key:self.on_pairing_preview_ready(data,rid,key))
        self.pairing_preview_worker.failed.connect(lambda msg,rid=request_id,key=sample_key:self.on_pairing_preview_failed(msg,rid,key))
        self.pairing_preview_worker.progress.connect(lambda pct,text,rid=request_id,key=sample_key:self.on_pairing_preview_progress(pct,text,rid,key))
        self.pairing_preview_worker.log.connect(self.add_log)
        self.pairing_preview_worker.cancelled_ok.connect(lambda rid=request_id:self.on_pairing_preview_cancelled(rid))
        self.pairing_preview_worker.start()

    def on_pairing_preview_progress(self, pct, text, request_id=None, sample_key=None):
        if (request_id != self._live_preview_request_id or sample_key != self._live_preview_signature_value() or
                self.workflow_state.stage != 'book_customization'):
            return
        self.progress.setValue(pct)
        self.progress_text.setText(text)

    def _reset_pairing_preview_button(self):
        self._update_live_preview_action()

    def _render_live_preview(self, data):
        while self.live_preview_grid.count():
            item=self.live_preview_grid.takeAt(0); widget=item.widget()
            if widget is not None: widget.deleteLater()
        for index,(number,blob,_kind) in enumerate(data.get('thumbs') or ()):
            cell=QFrame(); layout=QVBoxLayout(cell); layout.setContentsMargins(4,4,4,4)
            pic=QLabel(); pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap=QPixmap(); pixmap.loadFromData(blob); pic.setPixmap(pixmap)
            caption=QLabel(f'Output page {number}'); caption.setAlignment(Qt.AlignmentFlag.AlignCenter); caption.setStyleSheet('color:#AEB3B8; font-size:10px;')
            layout.addWidget(pic); layout.addWidget(caption)
            self.live_preview_grid.addWidget(cell,index//2,index%2)
        self.live_preview_empty.setVisible(False); self.live_preview_scroll.setVisible(True)

    def on_pairing_preview_ready(self, data, request_id=None, sample_key=None):
        if (request_id != self._live_preview_request_id or sample_key != self._live_preview_signature_value() or
                self.workflow_state.stage != 'book_customization'):
            return
        self._live_preview_samples[sample_key]=data
        self._active_preview_sample_key=sample_key
        self._live_preview_stale=False
        self.workflow_state.mark_preview_ready()
        self._render_live_preview(data)
        self._reset_pairing_preview_button()
        self.progress_text.setText('Live Preview ready.')
        self._set_work_progress_visible(False)

    def on_pairing_preview_cancelled(self, request_id=None):
        if request_id != self._live_preview_request_id:
            return
        self._reset_pairing_preview_button()
        self.progress.setValue(0)
        self.progress_text.setText('Live Preview cancelled.')
        self._set_work_progress_visible(False)
        self.add_log('Live Preview cancelled. Temporary preview images were discarded.')

    def on_pairing_preview_failed(self, msg, request_id=None, sample_key=None):
        if request_id != self._live_preview_request_id or sample_key != self._live_preview_signature_value():
            return
        self.workflow_state.mark_preview_failed()
        self.live_preview_status.setText('Preview sample could not be loaded. Retry when convenient; Finalization remains available.')
        self._reset_pairing_preview_button()
        self.progress.setValue(0)
        self.progress_text.setText('Live Preview failed.')
        self._set_work_progress_visible(False)
        self.add_log(f'Live Preview failed: {msg}')

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
            self.search_box, self.prefer_colored, self.search_btn, self.url, self.load_btn,
            self.search_results, self.show_more_btn, self.alt_titles_btn, self.volume_list, self.select_all_btn, self.clear_volume_btn,
            self.portrait_btn, self.landscape_btn, self.language, self.reading_direction,
            self.start, self.end, self.covers, self.pad, self.pairing_preview_btn,
            self.chapter_output_combo, self.title, self.series, self.author, self.apply_metadata_btn,
            self.preferences_btn, self.sources_btn, self.about_btn,
        ]
        if locked:
            for control in controls:
                try: control.setEnabled(False)
                except Exception: pass
            self.preview_btn.setEnabled(False)
            self.download_btn.setEnabled(False)
            self._set_cancel_action(True,'Cancel Download')
            self.workflow_hint.setText('Download in progress. Settings are locked until it finishes or is cancelled.')
        else:
            for control in (
                self.search_box, self.prefer_colored, self.search_btn, self.url, self.load_btn,
                self.search_results, self.portrait_btn, self.landscape_btn, self.covers,
                self.pad, self.chapter_output_combo, self.title, self.series, self.author,
                self.preferences_btn, self.sources_btn, self.about_btn,
            ):
                try: control.setEnabled(True)
                except Exception: pass
            try: self.show_more_btn.setEnabled(self.show_more_btn.isVisible())
            except Exception: pass
            try: self.alt_titles_btn.setEnabled(bool(self.loaded_metadata and self.loaded_metadata.get('titles')))
            except Exception: pass
            try: self.volume_list.setEnabled(bool(self._download_language_valid))
            except Exception: pass
            try: self._update_volume_selection_hint()
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
            self._set_cancel_action(False)
            self._update_workflow_actions()
            try: self._reset_pairing_preview_button()
            except Exception: pass
            try: self._bulk_metadata_changed()
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
                raise ValueError('Final Outputs are out of date. Refresh them before downloading.')
            if int(self.preview_data.get('selected_download_count', self.preview_data.get('download_count', 0)) or 0) <= 0:
                info_dialog(self, 'MangaNana', 'No Final Outputs are selected for download.', show=True)
                return
            self.maybe_offer_virtual_library()
            self._check_download_disk_space()
            replace_existing = bool(prefs['duplicate_policy'] == 'replace' or self._session_replace_existing)
            existing = set() if replace_existing else self.existing_volumes(series)
            self._active_replace_existing = replace_existing
            self._set_download_ui_locked(True)
            self._toggle_activity_log(True)
            self._set_work_progress_visible(True)
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
                                          volume_covers=self._loaded_covers,
                                          chapter_output_groups=[row.get('group') for row in (self.preview_data.get('rows') or [])
                                                                 if row.get('selected') and row.get('group')] or None)
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
            for source_id in self._search_display_barrier.source_ids:
                if not self._search_display_barrier.is_terminal(source_id):
                    self._search_display_barrier.settle(source_id,'cancelled')
            settled,total=self._sync_provider_search_progress()
            self._search_request_id += 1; self._enrichment_request_id += 1
            if self._enrichment_worker and self._enrichment_worker.isRunning():
                self._enrichment_worker.requestInterruption()
            self._enrichment_worker=None
            self._enrichment_received=True
            self.search_workers={}
            self._search_status_timer.stop()
            self.search_btn.setEnabled(True); self.search_btn.setText('Search'); self._set_cancel_action(False)
            more=any(self._search_has_more.values()); self.show_more_btn.setVisible(more); self.show_more_btn.setEnabled(more)
            self.add_log('Provider search cancelled with all providers settled; completed results preserved for final reconciliation.')
            self._finish_coordinated_search()
            return
        if self.preview_worker and self.preview_worker.isRunning():
            self._review_cancel_requested=True
            self.preview_worker.requestInterruption()
            self._set_cancel_action(False)
            self.progress_text.setText('Cancelling Finalization preparation after the current request...')
            self.add_log('Finalization cancellation requested.')
            return
        if self.worker:
            self.worker.cancel()
            self._set_cancel_action(False)
            self.progress_text.setText('Cancelling safely after the current request...')
            self.add_log('Cancellation requested. Finishing the current network/file operation, then cleaning temporary files...')

    def on_cancelled(self):
        self.worker = None
        self._set_download_ui_locked(False)
        self._update_preview_button_for_volume_selection()
        self._update_workflow_actions()
        self._set_cancel_action(False)
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
        self._set_cancel_action(False)
        self.progress_text.setText('Failed')
        box = QMessageBox(self)
        box.setWindowTitle('MangaNana - Download failed')
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(msg)
        box.setInformativeText('You can choose Download & Add to Calibre again to retry the same finalized selection.')
        box.exec()

    def _replace_existing_book(self, book_id, item, author, series, language):
        p = item['path']; v = item['volume']; title = item['title']
        self.db.add_format(book_id, 'CBZ', p, replace=True)
        updates = {
            'title': {book_id: title}, 'authors': {book_id: [author]},
            'series': {book_id: series}, 'languages': {book_id: [language]},
            'tags': {book_id: list(self._calibre_work_tags(self._existing_calibre_tags(book_id)))},
        }
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
            info_dialog(self, 'Retry failed volumes', 'Final Outputs have changed. Refresh them before retrying.', show=True)
            return
        self.preview_data['selected_volumes'] = [float(v) for v in failed_volumes]
        self.preview_data['include_bonus'] = bool(failed_bonus)
        self.preview_data['selected_download_count'] = len(failed_volumes) + (1 if failed_bonus else 0)
        self.add_log('Retrying failed download item(s)...')
        self.start_download()

    def completion_dialog(self, added, skipped, duplicates, pages, final_bytes, elapsed, ids, failures, failed_bonus=False, import_anomalies=()):
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
            f'Unclassified Calibre import responses: {len(import_anomalies or ())}\n'
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
            added = 0; duplicates = 0; added_ids = []; import_anomalies = []
            _title,applied_author,applied_series=self._applied_metadata_values()
            existing_ids = self.existing_volume_ids(applied_series)
            replace_existing = bool(getattr(self, '_active_replace_existing', False))
            for item in result.get('files', []):
                p = item['path']; v = item['volume']; title = item['title']
                if replace_existing and v is not None and float(v) in existing_ids:
                    bid = self._replace_existing_book(existing_ids[float(v)], item, applied_author, applied_series, self.language.currentData())
                    added += 1; added_ids.append(bid)
                    self.add_log(f'Replaced existing Calibre CBZ for Volume {float(v):g}.')
                    continue
                mi = Metadata(title, [applied_author])
                mi.series = applied_series
                if v is not None: mi.series_index = float(v)
                mi.languages = [self.language.currentData()]
                mi.tags = list(self._calibre_work_tags())
                mi.set_identifier(self.current_source_id, self.current_source.parse_manga_ref(self.current_manga_url))
                cp = item.get('cover_path')
                if cp and Path(cp).exists():
                    ext = Path(cp).suffix.lower().lstrip('.') or 'jpg'
                    if ext == 'jpeg': ext = 'jpg'
                    mi.cover_data = (ext, Path(cp).read_bytes())
                ids, dups = self.db.add_books([(mi, {'CBZ': p})], add_duplicates=False)
                added += len(ids); duplicates += len(dups); added_ids.extend(ids)
                if ids:
                    self.add_log(f'Calibre confirmed import of {title}.')
                elif dups:
                    self.add_log(f'Calibre classified {title} as already present/duplicate; no new book ID was created.')
                else:
                    import_anomalies.append(title)
                    self.add_log(f'ERROR: Calibre returned neither a new book ID nor a duplicate classification for {title}.')
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
            if import_anomalies:
                self.add_log('Calibre import outcome requires investigation for: ' + ', '.join(import_anomalies))
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
                self.completion_dialog(added, skipped, duplicates, pages, final_bytes, elapsed, added_ids, failed_volumes, failed_bonus, import_anomalies)
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
            self._update_preview_button_for_volume_selection(); self._set_cancel_action(False)

