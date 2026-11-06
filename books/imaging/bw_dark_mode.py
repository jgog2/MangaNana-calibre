"""Conservative, bounded classification of original reading-page color."""
from io import BytesIO
import math
from PIL import Image, ImageOps


def monochrome(source, check_cancel=None):
    """Return eligibility, never infer it from processed/grayscale output.

    Analyze at most 256² pixels. Ignore near-black saturation instability.
    Strong color: >=18% saturation, >=12 chroma, >=0.05% of usable pixels.
    Moderate color: >=8% saturation, >=10 chroma, >=1% of usable pixels.
    Broad uncertain tint (>=6% saturation/chroma 10 over 5%) also preserves.
    """
    if check_cancel: check_cancel()
    try:
        if isinstance(source, Image.Image):
            sample = source.copy()
        else:
            with Image.open(BytesIO(source)) as image:
                sample = image.copy()
        sample.thumbnail((256, 256), Image.Resampling.BOX)
        if sample.mode in ('RGBA', 'LA', 'P'):
            rgba = sample.convert('RGBA')
            background = Image.new('RGBA', rgba.size, 'white')
            sample = Image.alpha_composite(background, rgba)
        sample = sample.convert('RGB')
        usable = strong = moderate = uncertain = dark_uncertain = 0
        for i, (r, g, b) in enumerate(sample.getdata()):
            if i % 4096 == 0 and check_cancel: check_cancel()
            high, low = max(r, g, b), min(r, g, b)
            if high < 32:
                dark_uncertain += high - low >= 8
                continue
            usable += 1
            chroma = high - low
            saturation = chroma / high
            strong += chroma >= 12 and saturation >= .18
            moderate += chroma >= 10 and saturation >= .08
            uncertain += chroma >= 10 and saturation >= .06
        if not usable: return not dark_uncertain
        return not (strong >= max(2, math.ceil(usable * .0005)) or
                    moderate >= max(2, math.ceil(usable * .01)) or
                    uncertain >= max(2, math.ceil(usable * .05)))
    except InterruptedError:
        raise
    except (OSError, ValueError, TypeError):
        return False


def invert_composed(image, check_cancel=None):
    if check_cancel: check_cancel()
    if image.mode in ('RGBA', 'LA') or image.mode == 'P' and 'transparency' in image.info:
        rgba = image.convert('RGBA')
        image = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba)
    result = ImageOps.invert(image.convert('L' if image.mode == 'L' else 'RGB'))
    if check_cancel: check_cancel()
    return result
