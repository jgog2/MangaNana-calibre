"""MangaAnkā metadata covers. Independent of manga page processing and Qt.

Static artwork uses the supplied cover assets; title and number are dynamic.
Call on a worker thread. Keep mode returns the original bytes without decoding.
"""
from calibre_plugins.manganana.common.plugin_paths import plugin_root
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from threading import RLock
from calibre_plugins.manganana.common.bounded_cache import BoundedCache

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


COVER_MODES = (('Keep Existing Cover', 'keep'),
               ('Stamp Existing Cover', 'stamp'),
               ('Generate Cover', 'generate'))
CANVAS_SIZE = (880, 1200)
STAMP_SIZE = (144, 1200)
STRIP_X = CANVAS_SIZE[0] - STAMP_SIZE[0]
TITLE_BOX = (70, 177, 670, 422)
TITLE_STROKE = 3
BADGE_CENTER = (811, 1068)
PALETTE = dict(deep_ocean='#08131D', midnight_blue='#10253A',
               storm_blue='#1C3A52', sea_green='#3E7C72', seafoam='#66B7A8',
               deep_teal='#285A58', indigo='#242A46', off_white='#EEF3F1',
               mist_gray='#AAB8BD', lighthouse_red='#C94B4B', beacon_white='#F6F1E7')
LANCZOS = getattr(Image, 'Resampling', Image).LANCZOS
_title_widths=BoundedCache(1024*1024,4096,lambda row:row[1])
_title_width_lock=RLock()


@lru_cache(maxsize=4)
def _resource(name):
    path = 'assets/covers/' + name
    loader = globals().get('get_resources')  # Injected by Calibre's ZIP loader.
    if loader is not None:
        data = loader(path)
        if not data:
            raise FileNotFoundError(path)
        return data
    return (plugin_root() / path).read_bytes()


@lru_cache(maxsize=2)
def _template_pixels(data):
    """Immutable decoded bundled artwork; each compositor gets owned pixels."""
    with Image.open(BytesIO(data)) as image:
        image = image.convert('RGBA')
        return image.size, image.tobytes()


def _art(name):
    size, pixels = _template_pixels(_resource(name))
    return Image.frombytes('RGBA', size, pixels)


def _font(size):
    return ImageFont.truetype(BytesIO(_resource('BebasNeue-Regular.ttf')), size)


def _has_title_glyphs(font, text):
    """Reject FreeType's .notdef boxes without requiring another dependency."""
    missing = font.getmask('\uffff')
    signature = (missing.size, bytes(missing))
    return all(char.isspace() or (mask.size, bytes(mask)) != signature
               for char in set(text) for mask in (font.getmask(char),))


@lru_cache(maxsize=32)
def _title_font_path(text):
    # Cache paths, not large CJK font buffers or mutable shared FreeType faces.
    if _has_title_glyphs(_font(32), text):
        return None
    try:
        from calibre.utils.fonts.scanner import font_scanner
        family, faces = font_scanner.find_font_for_text(text)
        for face in faces:
            path = face['path']
            if _has_title_glyphs(ImageFont.truetype(path, 32), text):
                return path
    except (ImportError, TypeError, ValueError, KeyError, OSError):
        pass
    # Pillow-only callers and common operating-system font installations.
    for name in ('YuGothM.ttc', 'msgothic.ttc', 'Hiragino Sans W6.ttc',
                 'NotoSansCJK-Regular.ttc', 'NotoSansJP-Regular.ttf',
                 'DejaVuSans.ttf', 'arial.ttf'):
        try:
            font = ImageFont.truetype(name, 32)
            if _has_title_glyphs(font, text):
                return font.path
        except OSError:
            continue
    # Keep the historical rendering behavior if no installed font covers the
    # script; absence of a system font must not abort acquisition of the book.
    return None


def badge_text(*, output_kind='volume', volume=None, chapter_number=None,
               series_index=None, zero_pad=True):
    """Use the output book's identity, never a chapter's parent volume.

    A standalone collection has no single number. Series index is a fallback
    only when the explicit volume/chapter number is absent.
    """
    if output_kind not in ('volume', 'chapter'):
        return ''
    value = volume if output_kind == 'volume' else chapter_number
    if value is None or str(value).strip() == '':
        value = series_index
    try:
        raw = str(value).strip()
        if len(raw) > 32:
            return ''
        number = Decimal(raw)
        if not number.is_finite() or number < 0 or number.adjusted() > 7 or number.as_tuple().exponent < -4:
            return ''
        text = format(number.normalize(), 'f')
    except (InvalidOperation, ValueError, TypeError):
        return ''
    if zero_pad:
        whole, dot, fraction = text.partition('.')
        text = whole.zfill(2) + dot + fraction
    return text


def cover_title(title='', series=''):
    for value in (title, series, 'Untitled Manga'):
        text = ' '.join(str(value or '').split())
        if text:
            return text


def title_layout(text):
    """Fit visible glyph bounds inside the title area, with a readable floor."""
    text = text[:509].rstrip() + '...' if len(text) > 512 else text
    path = _title_font_path(text)
    width = TITLE_BOX[2] - TITLE_BOX[0] - 8
    height = TITLE_BOX[3] - TITLE_BOX[1] - 8
    probe = ImageDraw.Draw(Image.new('L', (1, 1)))
    floor_layout = None
    # Try the ceiling, then the floor. If even the floor cannot fit, wrapping
    # the same oversized title at every intermediate size is wasted work.
    for size in (114, 38, *range(112, 39, -2)):
        font = ImageFont.truetype(path, size) if path else _font(size)
        def fits(line):
            key=(path,size,TITLE_STROKE,line)
            with _title_width_lock:cached=_title_widths.get(key)
            if cached is None:
                box=probe.textbbox((0,0),line,font=font,stroke_width=TITLE_STROKE)
                cached=(box[2]-box[0],128+4*len(line)+4*len(str(path or '')))
                with _title_width_lock:_title_widths[key]=cached
            return cached[0] <= width
        lines = []; line = ''
        for word in text.split():
            candidate = (line + ' ' + word).strip()
            if fits(candidate):
                line = candidate
                continue
            if line:
                lines.append(line); line = ''
            # Break even an unspaced title without crossing the strip.
            for char in word:
                if line and not fits(line + char):
                    lines.append(line); line = ''
                line += char
        if line:
            lines.append(line)
        spacing = round(size * .22)
        block = '\n'.join(lines)
        bbox = probe.multiline_textbbox((0, 0), block, font=font, spacing=spacing, align='center', stroke_width=TITLE_STROKE)
        fits_box = bbox[2] - bbox[0] <= width and bbox[3] - bbox[1] <= height
        if size == 38:
            if not fits_box:
                break
            floor_layout = (block, font, spacing, bbox)
        elif fits_box:
            return block, font, spacing, bbox
    if floor_layout is not None:
        return floor_layout
    # Pathological metadata remains bounded and readable instead of microscopic.
    while len(lines) > 1:
        lines.pop()
        tail = lines[-1].rstrip('. ') + '...'
        while not fits(tail):
            tail = tail[:-4] + '...'
        block = '\n'.join(lines[:-1] + [tail])
        bbox = probe.multiline_textbbox((0, 0), block, font=font, spacing=spacing, align='center', stroke_width=TITLE_STROKE)
        if bbox[3] - bbox[1] <= height:
            return block, font, spacing, bbox
    return block, font, spacing, bbox


@lru_cache(maxsize=4)
def _title_raster(text):
    """Immutable cropped ink only; never share mutable images or font faces."""
    block, font, spacing, bbox = title_layout(text)
    x = (TITLE_BOX[0] + TITLE_BOX[2] - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = (TITLE_BOX[1] + TITLE_BOX[3] - (bbox[3] - bbox[1])) / 2 - bbox[1]
    layer = Image.new('RGBA', CANVAS_SIZE)
    draw = ImageDraw.Draw(layer)
    draw.multiline_text((x, y), block, font=font, spacing=spacing, align='center',
                        fill=PALETTE['off_white'], stroke_width=TITLE_STROKE,
                        stroke_fill=PALETTE['deep_ocean'])
    ink = layer.getbbox()
    if not ink:return None
    text_art=layer.crop(ink)
    return text_art.size,text_art.tobytes()


@lru_cache(maxsize=4)
def _title_glow_raster(text):
    """Immutable cropped glow; reuse the same blur for equal rendered titles."""
    raster=_title_raster(text)
    if not raster:return None
    layer=Image.new('RGBA',CANVAS_SIZE)
    text_art=Image.frombytes('RGBA',raster[0],raster[1])
    position=(round((TITLE_BOX[0]+TITLE_BOX[2]-text_art.width)/2),
              round((TITLE_BOX[1]+TITLE_BOX[3]-text_art.height)/2))
    layer.alpha_composite(text_art,position)
    glow = Image.new('RGBA', CANVAS_SIZE, PALETTE['deep_ocean'])
    glow.putalpha(layer.getchannel('A').filter(ImageFilter.GaussianBlur(4)).point(lambda a: a // 5))
    bounds=glow.getbbox()
    if not bounds:return None
    cropped=glow.crop(bounds)
    return bounds[:2],cropped.size,cropped.tobytes()


def _draw_title(canvas, text):
    # Keep two compositing passes: combining layers can change integer rounding.
    glow=_title_glow_raster(text)
    if glow:canvas.alpha_composite(Image.frombytes('RGBA',glow[1],glow[2]),glow[0])
    raster=_title_raster(text)
    if raster:
        text_art=Image.frombytes('RGBA',raster[0],raster[1])
        position=(round((TITLE_BOX[0]+TITLE_BOX[2]-text_art.width)/2),
                  round((TITLE_BOX[1]+TITLE_BOX[3]-text_art.height)/2))
        canvas.alpha_composite(text_art,position)


def render_cover_image(original=None, *, mode='keep', title='', series='',
                 output_kind='volume', volume=None, chapter_number=None,
                 series_index=None, zero_pad=True):
    """Render owned RGB pixels for workers without an encode/decode round trip."""
    if mode == 'keep':
        if not original:return None
        with Image.open(BytesIO(original)) as source:
            return ImageOps.exif_transpose(source).convert('RGB')
    if mode not in ('stamp', 'generate'):
        raise ValueError('Unknown cover mode: ' + str(mode))
    if mode == 'stamp' and not original:
        return None
    canvas = Image.new('RGBA', CANVAS_SIZE, PALETTE['midnight_blue'])
    if mode == 'stamp':
        with Image.open(BytesIO(original)) as source:
            art = ImageOps.exif_transpose(source).convert('RGBA')
            art = ImageOps.fit(art, CANVAS_SIZE, method=LANCZOS)
            canvas.alpha_composite(art)
    else:
        background = _art('background.png')
        if background.size != CANVAS_SIZE:
            raise ValueError('Cover background must be 880 × 1200 pixels')
        canvas.alpha_composite(background)
        _draw_title(canvas, cover_title(title, series))
    # Preserve the complete supplied strip, including its right border.
    stamp = _art('stamp.png')
    if stamp.size != STAMP_SIZE:
        raise ValueError('Cover stamp must be 144 × 1200 pixels')
    canvas.alpha_composite(stamp, (STRIP_X, 0))
    number = badge_text(output_kind=output_kind, volume=volume,
                        chapter_number=chapter_number, series_index=series_index,
                        zero_pad=zero_pad)
    if number:
        draw = ImageDraw.Draw(canvas)
        for size in range(118, 15, -2):
            font = _font(size)
            box = draw.textbbox((0, 0), number, font=font)
            if box[2] - box[0] <= 100 and box[3] - box[1] <= 86:
                break
        # Very long numeric identifiers have no useful thumbnail representation.
        if box[2] - box[0] <= 100:
            x = BADGE_CENTER[0] - (box[2] + box[0]) / 2 + 1
            y = BADGE_CENTER[1] - (box[3] + box[1]) / 2
            draw.text((x, y), number, font=font, fill=PALETTE['beacon_white'])
    return canvas.convert('RGB')


def render_cover(original=None, *, mode='keep', title='', series='',
                 output_kind='volume', volume=None, chapter_number=None,
                 series_index=None, zero_pad=True):
    """Return the original bytes for keep, or the full-quality branded PNG."""
    if mode=='keep':return original
    canvas=render_cover_image(original,mode=mode,title=title,series=series,
        output_kind=output_kind,volume=volume,chapter_number=chapter_number,
        series_index=series_index,zero_pad=zero_pad)
    if canvas is None:return None
    out = BytesIO()
    canvas.save(out, 'PNG')
    return out.getvalue()
