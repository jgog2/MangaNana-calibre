"""MangaAnkā metadata covers. Independent of manga page processing and Qt.

Static artwork is exported from the supplied PSD; title and number are dynamic.
Call on a worker thread. Keep mode returns the original bytes without decoding.
"""
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


COVER_MODES = (('Keep Existing Cover', 'keep'),
               ('Stamp Existing Cover', 'stamp'),
               ('Generate Cover', 'generate'))
CANVAS_SIZE = (880, 1200)
STRIP_X = 740
ANCHOR_POSITION = (123, 437)
TITLE_BOX = (70, 177, 670, 422)
BADGE_CENTER = (811, 1068)
PALETTE = dict(deep_ocean='#08131D', midnight_blue='#10253A',
               storm_blue='#1C3A52', sea_green='#3E7C72', seafoam='#66B7A8',
               deep_teal='#285A58', indigo='#242A46', off_white='#EEF3F1',
               mist_gray='#AAB8BD', lighthouse_red='#C94B4B', beacon_white='#F6F1E7')
LANCZOS = getattr(Image, 'Resampling', Image).LANCZOS


@lru_cache(maxsize=4)
def _resource(name):
    path = 'assets/covers/' + name
    loader = globals().get('get_resources')  # Injected by Calibre's ZIP loader.
    if loader is not None:
        data = loader(path)
        if not data:
            raise FileNotFoundError(path)
        return data
    return (Path(__file__).resolve().parent / path).read_bytes()


def _art(name):
    with Image.open(BytesIO(_resource(name))) as image:
        return image.convert('RGBA')


def _font(size):
    return ImageFont.truetype(BytesIO(_resource('BebasNeue-Regular.ttf')), size)


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
    """Fit wrapped text inside the PSD title area, with a readable size floor."""
    text = text[:509].rstrip() + '...' if len(text) > 512 else text
    width = TITLE_BOX[2] - TITLE_BOX[0] - 8
    height = TITLE_BOX[3] - TITLE_BOX[1] - 8
    probe = ImageDraw.Draw(Image.new('L', (1, 1)))
    for size in range(114, 37, -2):
        font = _font(size)
        lines = []; line = ''
        for word in text.split():
            candidate = (line + ' ' + word).strip()
            if probe.textbbox((0, 0), candidate, font=font)[2] <= width:
                line = candidate
                continue
            if line:
                lines.append(line); line = ''
            # Break even an unspaced title without crossing the strip.
            for char in word:
                if line and probe.textbbox((0, 0), line + char, font=font)[2] > width:
                    lines.append(line); line = ''
                line += char
        if line:
            lines.append(line)
        spacing = round(size * .22)
        block = '\n'.join(lines)
        bbox = probe.multiline_textbbox((0, 0), block, font=font, spacing=spacing, align='center', stroke_width=2)
        if bbox[3] - bbox[1] <= height:
            return block, font, spacing, bbox
    # Pathological metadata remains bounded and readable instead of microscopic.
    while len(lines) > 1:
        lines.pop()
        tail = lines[-1].rstrip('. ') + '...'
        while probe.textbbox((0, 0), tail, font=font)[2] > width:
            tail = tail[:-4] + '...'
        block = '\n'.join(lines[:-1] + [tail])
        bbox = probe.multiline_textbbox((0, 0), block, font=font, spacing=spacing, align='center', stroke_width=2)
        if bbox[3] - bbox[1] <= height:
            return block, font, spacing, bbox
    return block, font, spacing, bbox


def _draw_title(canvas, text):
    block, font, spacing, bbox = title_layout(text)
    x = (TITLE_BOX[0] + TITLE_BOX[2] - (bbox[2] - bbox[0])) / 2 - bbox[0]
    y = TITLE_BOX[1] - bbox[1]
    layer = Image.new('RGBA', CANVAS_SIZE)
    draw = ImageDraw.Draw(layer)
    draw.multiline_text((x, y), block, font=font, spacing=spacing, align='center',
                        fill=PALETTE['lighthouse_red'], stroke_width=2,
                        stroke_fill=PALETTE['deep_ocean'])
    glow = Image.new('RGBA', CANVAS_SIZE, PALETTE['beacon_white'])
    glow.putalpha(layer.getchannel('A').filter(ImageFilter.GaussianBlur(4)).point(lambda a: a // 5))
    canvas.alpha_composite(glow)
    canvas.alpha_composite(layer)


def render_cover(original=None, *, mode='keep', title='', series='',
                 output_kind='volume', volume=None, chapter_number=None,
                 series_index=None, zero_pad=True):
    """Return PNG bytes for branded modes, unchanged bytes for keep, or None.

    A missing stamp source yields no cover; it never silently switches modes.
    A generated cover needs no source image. No page settings enter this API.
    """
    if mode == 'keep':
        return original
    if mode not in ('stamp', 'generate'):
        raise ValueError('Unknown cover mode: ' + str(mode))
    if mode == 'stamp' and not original:
        return None
    canvas = Image.new('RGBA', CANVAS_SIZE, PALETTE['midnight_blue'])
    if mode == 'stamp':
        with Image.open(BytesIO(original)) as source:
            art = ImageOps.exif_transpose(source).convert('RGBA')
            art = ImageOps.fit(art, (STRIP_X, CANVAS_SIZE[1]), method=LANCZOS)
            canvas.alpha_composite(art)
    else:
        canvas.alpha_composite(_art('background.png'))
        canvas.alpha_composite(_art('anchor.png'), ANCHOR_POSITION)
        _draw_title(canvas, cover_title(title, series))
    # The PSD stamp already contains the wordmark and empty circular badge.
    canvas.alpha_composite(_art('stamp.png'), (STRIP_X, 0))
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
            x = BADGE_CENTER[0] - (box[2] + box[0]) / 2
            y = BADGE_CENTER[1] - (box[3] + box[1]) / 2
            draw.text((x, y), number, font=font, fill=PALETTE['beacon_white'])
    out = BytesIO()
    canvas.convert('RGB').save(out, 'PNG')
    return out.getvalue()
