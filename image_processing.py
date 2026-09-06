"""Reading pages: layout -> grayscale -> Brightness -> Gamma -> Contrast
-> Saturation (unless grayscale) -> Sharpness -> Output Depth / diffusion -> encode.

No provider, Qt, preferences, or cover dependencies. Neutral images/bytes are
returned unchanged. Callers normalize EXIF before layout and this transform.
"""
from dataclasses import dataclass
from io import BytesIO
import math

from PIL import Image, ImageEnhance
try:
    from .dithering import quantize
except ImportError:  # Standalone deterministic tests; Calibre uses the package.
    from dithering import quantize


@dataclass(frozen=True)
class ProcessingSettings:
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    grayscale: bool = False
    output_depth: int = 0
    dithering: str = 'off'
    dither_strength: float = 1.0
    brightness: float = 1.0
    sharpness: float = 1.0

    def __post_init__(self):
        for value, low, high in ((self.contrast, .5, 2), (self.saturation, .2, 3),
                                 (self.gamma, .5, 2.5), (self.brightness, .25, 2),
                                 (self.sharpness, 0, 2)):
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError('Processing setting outside supported range.')
        if self.output_depth not in ((0, 16, 8, 4, 2) if self.grayscale else (0, 16, 8, 4)):
            raise ValueError('Unsupported output depth.')
        if self.dithering not in ('off', 'floyd-steinberg', 'atkinson', 'sierra-lite'):
            raise ValueError('Unsupported dithering algorithm.')
        if not math.isfinite(self.dither_strength) or not 0 <= self.dither_strength <= 2:
            raise ValueError('Dither strength outside 0–200%.')

    @property
    def neutral(self):
        return (self.contrast == self.saturation == self.gamma
                == self.brightness == self.sharpness == 1.0
                and not self.grayscale and self.output_depth == 0)


def apply_processing(image, settings, check_cancel=None, working_ceiling=None):
    """Return transformed pixels without mutating input; alpha is never adjusted."""
    if (settings is None or settings.neutral) and working_ceiling is None:
        return image
    settings = settings or ProcessingSettings()
    if image.mode == 'P':
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
    if working_ceiling is not None:
        # Overview only: bound pixels before expensive adjustments/diffusion.
        # thumbnail preserves aspect ratio and never enlarges the processed page.
        image = image.copy()
        image.thumbnail(working_ceiling, getattr(Image, 'Resampling', Image).LANCZOS)
    alpha = image.getchannel('A') if image.mode in ('RGBA', 'LA') else None
    mode = 'L' if settings.grayscale or image.mode in ('L', 'LA') else 'RGB'
    result = image.convert(mode)
    if settings.brightness != 1:
        result = ImageEnhance.Brightness(result).enhance(settings.brightness)
    if settings.gamma != 1:
        # MangaNana UI: left/darker, neutral 1.00, right/brighter.
        lut = [round(255 * (value / 255) ** (1.0 / settings.gamma)) for value in range(256)]
        result = result.point(lut * len(result.getbands()))
    if settings.contrast != 1:
        result = ImageEnhance.Contrast(result).enhance(settings.contrast)
    if not settings.grayscale and settings.saturation != 1:
        result = ImageEnhance.Color(result).enhance(settings.saturation)
    if settings.sharpness != 1:
        result = ImageEnhance.Sharpness(result).enhance(settings.sharpness)
    result = quantize(result, settings.output_depth, settings.dithering,
                      settings.dither_strength, check_cancel=check_cancel)
    if alpha is not None:
        result.putalpha(alpha)
    return result


def process_page_blob(blob, ext, settings, check_cancel=None):
    """Preserve neutral Portrait bytes; otherwise encode once in source format."""
    if settings is None or settings.neutral:
        return blob
    with Image.open(BytesIO(blob)) as source:
        fmt = (source.format or '').upper()
        result = apply_processing(source, settings, check_cancel=check_cancel)
        out = BytesIO()
        if fmt == 'PNG':
            result.save(out, 'PNG')
        elif fmt == 'WEBP':
            result.save(out, 'WEBP', quality=95)
        else:
            result.convert('RGB').save(out, 'JPEG', quality=95, subsampling=0)
        return out.getvalue()
