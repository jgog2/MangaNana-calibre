"""Pure Pillow helpers for the experimental Kaleido surface lab.

The CFA and grain fields are generated in canonical device coordinates.  This
module has no Qt or MangaNana production dependencies.
"""
from functools import lru_cache
from copy import deepcopy

from PIL import Image, ImageChops, ImageDraw


PORTRAIT = "portrait"
LANDSCAPE = "landscape"
CFA_LAYOUT_NAME = "3x3 diagonal RGB approximation"
DEFAULT_SURFACE = {
    "cfa_enabled": False,
    "cfa_strength": 0.0,
    "mirror_cfa_horizontal": False,
    "micro_grain_enabled": False,
    "grain_strength": 0.0,
}


def normalized_surface(profile):
    """Return backward-compatible experimental settings without mutating JSON."""
    result = dict(DEFAULT_SURFACE)
    stored = profile.get("kaleido_surface") or {}
    result["cfa_enabled"] = bool(stored.get("cfa_enabled", False))
    result["cfa_strength"] = max(0.0, min(0.35, float(stored.get("cfa_strength", 0.0))))
    result["mirror_cfa_horizontal"] = bool(stored.get("mirror_cfa_horizontal", False))
    result["micro_grain_enabled"] = bool(stored.get("micro_grain_enabled", False))
    result["grain_strength"] = max(0.0, min(4.0, float(stored.get("grain_strength", 0.0))))
    return result


def merge_lab_profile(profile, defaults):
    """Fill old lab schemas from current defaults while preserving stored values."""
    if not isinstance(profile, dict) or profile.get("profile_id") != defaults.get("profile_id"):
        raise ValueError("This lab currently accepts only the Kobo Libra Colour 100% profile.")

    def merge(base, override):
        result = deepcopy(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    result = merge(defaults, profile)
    # Missing experimental data must always mean disabled, regardless of what a
    # future default tuning file happens to contain.
    result["kaleido_surface"] = normalized_surface(profile)
    return result


def cfa_index(x, y, orientation=PORTRAIT, portrait_height=1680,
              mirror_cfa_horizontal=False, portrait_width=1264):
    """Return R=0/G=1/B=2 for a physical-panel coordinate.

    Portrait is canonical: (x - y) % 3.  Landscape is that canonical panel
    rotated 90 degrees clockwise, matching the lab's portrait-to-landscape
    physical-device rotation.
    """
    x, y = int(x), int(y)
    if orientation == PORTRAIT:
        portrait_x, portrait_y = x, y
    elif orientation == LANDSCAPE:
        portrait_x = y
        portrait_y = int(portrait_height) - 1 - x
    else:
        raise ValueError(f"Unsupported device orientation: {orientation}")
    if mirror_cfa_horizontal:
        portrait_x = int(portrait_width) - 1 - portrait_x
    return (portrait_x - portrait_y) % 3


@lru_cache(maxsize=24)
def _cfa_mask_bytes(width, height, orientation, color_index, portrait_height,
                    mirror_cfa_horizontal, portrait_width):
    rows = []
    for y in range(height):
        pattern = bytes(
            255 if cfa_index(x, y, orientation, portrait_height,
                             mirror_cfa_horizontal, portrait_width) == color_index else 0
            for x in range(3)
        )
        row = (pattern * ((width + 2) // 3))[:width]
        rows.append(row)
    return b"".join(rows)


def apply_cfa_modulation(image, strength, orientation=PORTRAIT, portrait_height=1680,
                         mirror_cfa_horizontal=False, portrait_width=1264):
    """Apply mean-preserving diagonal RGB modulation to calibrated RGB pixels."""
    strength = max(0.0, min(0.35, float(strength)))
    if strength == 0.0:
        return image
    source = image.convert("RGB")
    high = 1.0 + 2.0 * strength
    low = 1.0 - strength
    high_lut = [max(0, min(255, round(value * high))) for value in range(256)]
    low_lut = [max(0, min(255, round(value * low))) for value in range(256)]
    channels = []
    for color_index, channel in enumerate(source.split()):
        mask = Image.frombytes(
            "L", source.size,
            _cfa_mask_bytes(source.width, source.height, orientation,
                            color_index, int(portrait_height),
                            bool(mirror_cfa_horizontal), int(portrait_width)),
        )
        channels.append(Image.composite(channel.point(high_lut), channel.point(low_lut), mask))
    return Image.merge("RGB", tuple(channels))


def _coordinate_hash(x, y):
    """Stable 32-bit coordinate hash; no small repeating texture tile."""
    value = ((int(x) * 0x1F123BB5) ^ (int(y) * 0x5F356495) ^ 0xA3C59AC3) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value & 0xFF


@lru_cache(maxsize=6)
def _portrait_grain_bytes(width, height):
    return bytes(_coordinate_hash(x, y) for y in range(height) for x in range(width))


@lru_cache(maxsize=6)
def _grain_bytes(width, height, orientation):
    if orientation == PORTRAIT:
        return _portrait_grain_bytes(width, height)
    if orientation == LANDSCAPE:
        # Generate once in canonical portrait coordinates, then rotate the
        # physical panel field clockwise with the device.
        portrait = Image.frombytes("L", (height, width), _portrait_grain_bytes(height, width))
        return portrait.rotate(-90, expand=True).tobytes()
    raise ValueError(f"Unsupported device orientation: {orientation}")


def apply_micro_grain(image, strength, orientation=PORTRAIT):
    """Add deterministic achromatic device-coordinate grain in RGB code values."""
    strength = max(0.0, min(4.0, float(strength)))
    if strength == 0.0:
        return image
    source = image.convert("RGB")
    field = Image.frombytes("L", source.size, _grain_bytes(source.width, source.height, orientation))
    lut = [max(0, min(255, 128 + round((value - 127.5) * strength / 127.5)))
           for value in range(256)]
    delta = field.point(lut)
    return ImageChops.add(source, Image.merge("RGB", (delta, delta, delta)), scale=1.0, offset=-128)


def apply_kaleido_surface(image, surface, orientation=PORTRAIT, portrait_height=1680,
                          portrait_width=1264):
    """Apply enabled experimental stages in CFA -> grain order."""
    out = image
    if surface.get("cfa_enabled", False):
        out = apply_cfa_modulation(
            out, surface.get("cfa_strength", 0.0), orientation, portrait_height,
            surface.get("mirror_cfa_horizontal", False), portrait_width)
    if surface.get("micro_grain_enabled", False):
        out = apply_micro_grain(out, surface.get("grain_strength", 0.0), orientation)
    return out


def diagnostic_image(size=(720, 960)):
    """Generate a lab-only flat-color, grayscale, text, and thin-line target."""
    width, height = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    colors = (
        ("WHITE", (255, 255, 255)), ("50% GRAY", (128, 128, 128)),
        ("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)), ("BLUE", (0, 0, 255)),
        ("CYAN", (0, 255, 255)), ("MAGENTA", (255, 0, 255)),
        ("YELLOW", (255, 255, 0)),
    )
    columns, rows = 2, 4
    cell_w, cell_h = width // columns, (height * 3 // 4) // rows
    for index, (label, color) in enumerate(colors):
        x, y = (index % columns) * cell_w, (index // columns) * cell_h
        draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), fill=color, outline="black")
        text_color = "white" if max(color) < 180 else "black"
        draw.text((x + 10, y + 10), label, fill=text_color)
    lower = cell_h * rows
    draw.rectangle((0, lower, width - 1, height - 1), fill="white", outline="black")
    draw.text((12, lower + 12), "BLACK TEXT / THIN LINES", fill="black")
    for offset in range(0, min(180, height - lower - 50), 6):
        draw.line((12, lower + 42 + offset, width - 12, lower + 42 + offset), fill="black", width=1)
    return image
