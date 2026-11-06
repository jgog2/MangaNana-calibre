"""Pure preview-only screen emulation for MangaNana.

This module intentionally contains no Qt, provider, preferences, CBZ, or
Calibre logic. The Kobo Libra Colour values are the frozen manually-qualified
100% frontlight, ComfortLight warmth 0 profile.
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Mapping, Optional, Tuple

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


NONE_PROFILE_ID = "none"
KOBO_LIBRA_COLOUR_PROFILE_ID = "kobo_libra_colour"
KOBO_PANEL_SOFTNESS_RADIUS = 0.10

PORTRAIT_LAYOUT = "original_pages"
LANDSCAPE_LAYOUT = "paired_landscape"


@dataclass(frozen=True)
class HueAnchor:
    hue_degrees: float
    lightness_percent: float
    saturation_percent: float


@dataclass(frozen=True)
class ScreenEmulationProfile:
    profile_id: str
    display_name: str
    native_portrait: Tuple[int, int]
    native_landscape: Tuple[int, int]
    bw_ppi: int
    color_ppi: int
    frontlight_percent: int
    comfortlight_warmth: int
    black_floor: int
    white_ceiling: int
    gamma: float
    saturation: float
    red_gain: float
    green_gain: float
    blue_gain: float
    chroma_resolution_percent: int
    softness_radius: float
    hue_corrections_enabled: bool
    hue_saturation_gate_percent: float
    hue_anchors: Tuple[HueAnchor, ...]
    cfa_enabled: bool
    cfa_strength: float
    mirror_cfa_horizontal: bool
    micro_grain_enabled: bool
    grain_strength: float


KOBO_LIBRA_COLOUR = ScreenEmulationProfile(
    profile_id=KOBO_LIBRA_COLOUR_PROFILE_ID,
    display_name="Kobo Libra Colour",
    native_portrait=(1264, 1680),
    native_landscape=(1680, 1264),
    bw_ppi=300,
    color_ppi=150,
    frontlight_percent=100,
    comfortlight_warmth=0,
    black_floor=62,
    white_ceiling=232,
    gamma=1.05,
    saturation=0.22,
    red_gain=1.03,
    green_gain=1.00,
    blue_gain=0.92,
    chroma_resolution_percent=50,
    softness_radius=KOBO_PANEL_SOFTNESS_RADIUS,
    hue_corrections_enabled=False,
    hue_saturation_gate_percent=25.0,
    hue_anchors=(
        HueAnchor(0, 0.0, 0.0),
        HueAnchor(30, 0.0, 0.0),
        HueAnchor(60, 0.0, 0.0),
        HueAnchor(120, 0.0, 0.0),
        HueAnchor(180, 0.0, 0.0),
        HueAnchor(240, 0.0, 0.0),
        HueAnchor(270, 0.0, 0.0),
        HueAnchor(300, 0.0, 0.0),
    ),
    cfa_enabled=True,
    cfa_strength=0.10,
    mirror_cfa_horizontal=True,
    micro_grain_enabled=True,
    grain_strength=1.0,
)

PROFILES: Mapping[str, ScreenEmulationProfile] = {
    KOBO_LIBRA_COLOUR.profile_id: KOBO_LIBRA_COLOUR,
}


@dataclass(frozen=True)
class EmulatedDetail:
    image: Image.Image
    screen_size: Tuple[int, int]
    profile_id: str
    display_name: str
    layout: str


def _check(check_cancel: Optional[Callable[[], None]]) -> None:
    if check_cancel is not None:
        check_cancel()


def profile_for(profile_id: str) -> Optional[ScreenEmulationProfile]:
    if not profile_id or profile_id == NONE_PROFILE_ID:
        return None
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown screen emulation profile: {profile_id}") from exc


def native_screen_size(profile: ScreenEmulationProfile, layout: str) -> Tuple[int, int]:
    if layout == LANDSCAPE_LAYOUT:
        return profile.native_landscape
    if layout == PORTRAIT_LAYOUT:
        return profile.native_portrait
    raise ValueError(f"Unsupported output layout for screen emulation: {layout}")


def contain_on_canvas(
    image: Image.Image,
    target_size: Tuple[int, int],
    check_cancel: Optional[Callable[[], None]] = None,
) -> Image.Image:
    _check(check_cancel)
    image = image.convert("RGB")
    fitted = ImageOps.contain(image, target_size, Image.Resampling.LANCZOS)
    _check(check_cancel)
    canvas = Image.new("RGB", target_size, "white")
    x = (target_size[0] - fitted.width) // 2
    y = (target_size[1] - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    return canvas


def reduce_chroma_resolution(
    image: Image.Image,
    percent: float,
    check_cancel: Optional[Callable[[], None]] = None,
) -> Image.Image:
    _check(check_cancel)
    percent = max(1, min(100, int(round(percent))))
    if percent >= 100:
        return image
    ycbcr = image.convert("YCbCr")
    y, cb, cr = ycbcr.split()
    dw = max(1, round(image.width * percent / 100.0))
    dh = max(1, round(image.height * percent / 100.0))
    cb = cb.resize((dw, dh), Image.Resampling.BILINEAR)
    cr = cr.resize((dw, dh), Image.Resampling.BILINEAR)
    _check(check_cancel)
    cb = cb.resize(image.size, Image.Resampling.BILINEAR)
    cr = cr.resize(image.size, Image.Resampling.BILINEAR)
    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def apply_tone(image: Image.Image, profile: ScreenEmulationProfile) -> Image.Image:
    black_floor = max(0, min(254, int(round(profile.black_floor))))
    white_ceiling = max(black_floor + 1, min(255, int(round(profile.white_ceiling))))
    gamma = max(0.25, min(4.0, float(profile.gamma)))
    lut = []
    for value in range(256):
        normalized = value / 255.0
        corrected = normalized ** (1.0 / gamma)
        mapped = black_floor + corrected * (white_ceiling - black_floor)
        lut.append(max(0, min(255, round(mapped))))
    return image.point(lut * 3)


def apply_channel_gains(image: Image.Image, profile: ScreenEmulationProfile) -> Image.Image:
    r, g, b = image.split()

    def adjusted(channel: Image.Image, factor: float) -> Image.Image:
        factor = max(0.25, min(2.0, float(factor)))
        lut = [max(0, min(255, round(i * factor))) for i in range(256)]
        return channel.point(lut)

    return Image.merge(
        "RGB",
        (
            adjusted(r, profile.red_gain),
            adjusted(g, profile.green_gain),
            adjusted(b, profile.blue_gain),
        ),
    )


def circular_hue_weight(hue_byte: int, center_degrees: float, half_width_degrees: float = 35.0) -> int:
    hue_degrees = hue_byte * (360.0 / 255.0)
    distance = abs(hue_degrees - center_degrees)
    distance = min(distance, 360.0 - distance)
    weight = max(0.0, 1.0 - distance / half_width_degrees)
    return round(weight * 255)


def saturation_gate_weight(sat_byte: int, threshold_percent: float) -> int:
    threshold = max(0.0, min(99.0, float(threshold_percent))) * 2.55
    if sat_byte <= threshold:
        return 0
    remaining = max(1.0, 255.0 - threshold)
    return round(255.0 * (sat_byte - threshold) / remaining)


def apply_hue_corrections(
    image: Image.Image,
    profile: ScreenEmulationProfile,
    check_cancel: Optional[Callable[[], None]] = None,
) -> Image.Image:
    """Preserve the manually-qualified lab's exact hue correction semantics."""
    if not profile.hue_corrections_enabled:
        return image
    out = image.convert("RGB")
    hsv = out.convert("HSV")
    h_channel, s_channel, _ = hsv.split()
    saturation_mask = s_channel.point(
        lambda s: saturation_gate_weight(s, profile.hue_saturation_gate_percent)
    )

    for anchor in profile.hue_anchors:
        _check(check_cancel)
        lightness = float(anchor.lightness_percent)
        saturation = float(anchor.saturation_percent)
        if abs(lightness) < 1e-9 and abs(saturation) < 1e-9:
            continue
        hue_mask = h_channel.point(
            lambda h, center=anchor.hue_degrees: circular_hue_weight(h, center)
        )
        mask = ImageChops.multiply(hue_mask, saturation_mask)
        adjusted = out
        if abs(saturation) >= 1e-9:
            adjusted = ImageEnhance.Color(adjusted).enhance(
                max(0.0, 1.0 + saturation / 100.0)
            )
        if abs(lightness) >= 1e-9:
            adjusted = ImageEnhance.Brightness(adjusted).enhance(
                max(0.0, 1.0 + lightness / 100.0)
            )
        out = Image.composite(adjusted, out, mask)
    return out


def cfa_index(
    x: int,
    y: int,
    layout: str,
    portrait_width: int = 1264,
    portrait_height: int = 1680,
    mirror_horizontal: bool = True,
) -> int:
    """R=0/G=1/B=2 in canonical portrait physical-panel coordinates."""
    if layout == PORTRAIT_LAYOUT:
        portrait_x, portrait_y = int(x), int(y)
    elif layout == LANDSCAPE_LAYOUT:
        portrait_x = int(y)
        portrait_y = int(portrait_height) - 1 - int(x)
    else:
        raise ValueError(f"Unsupported output layout for CFA: {layout}")
    if mirror_horizontal:
        portrait_x = int(portrait_width) - 1 - portrait_x
    return (portrait_x - portrait_y) % 3


@lru_cache(maxsize=12)
def _cfa_mask_bytes(
    width: int,
    height: int,
    layout: str,
    color_index: int,
    portrait_width: int,
    portrait_height: int,
    mirror_horizontal: bool,
) -> bytes:
    rows = []
    for y in range(height):
        pattern = bytes(
            255 if cfa_index(x, y, layout, portrait_width, portrait_height,
                             mirror_horizontal) == color_index else 0
            for x in range(3)
        )
        rows.append((pattern * ((width + 2) // 3))[:width])
    return b"".join(rows)


def apply_cfa_modulation(
    image: Image.Image,
    profile: ScreenEmulationProfile,
    layout: str,
) -> Image.Image:
    strength = max(0.0, min(0.35, float(profile.cfa_strength)))
    if not profile.cfa_enabled or strength == 0.0:
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
            _cfa_mask_bytes(
                source.width, source.height, layout, color_index,
                profile.native_portrait[0], profile.native_portrait[1],
                profile.mirror_cfa_horizontal,
            ),
        )
        channels.append(Image.composite(channel.point(high_lut), channel.point(low_lut), mask))
    return Image.merge("RGB", tuple(channels))


def _coordinate_hash(x: int, y: int) -> int:
    value = ((int(x) * 0x1F123BB5) ^ (int(y) * 0x5F356495) ^ 0xA3C59AC3) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value & 0xFF


@lru_cache(maxsize=2)
def _portrait_grain_bytes(width: int, height: int) -> bytes:
    return bytes(_coordinate_hash(x, y) for y in range(height) for x in range(width))


@lru_cache(maxsize=2)
def _grain_bytes(width: int, height: int, layout: str) -> bytes:
    if layout == PORTRAIT_LAYOUT:
        return _portrait_grain_bytes(width, height)
    if layout == LANDSCAPE_LAYOUT:
        portrait = Image.frombytes("L", (height, width), _portrait_grain_bytes(height, width))
        return portrait.rotate(-90, expand=True).tobytes()
    raise ValueError(f"Unsupported output layout for grain: {layout}")


def apply_micro_grain(
    image: Image.Image,
    profile: ScreenEmulationProfile,
    layout: str,
) -> Image.Image:
    strength = max(0.0, min(4.0, float(profile.grain_strength)))
    if not profile.micro_grain_enabled or strength == 0.0:
        return image
    source = image.convert("RGB")
    field = Image.frombytes("L", source.size, _grain_bytes(source.width, source.height, layout))
    lut = [max(0, min(255, 128 + round((value - 127.5) * strength / 127.5)))
           for value in range(256)]
    delta = field.point(lut)
    return ImageChops.add(
        source, Image.merge("RGB", (delta, delta, delta)), scale=1.0, offset=-128)


def emulate_screen(
    image: Image.Image,
    profile: ScreenEmulationProfile,
    layout: str,
    check_cancel: Optional[Callable[[], None]] = None,
) -> Image.Image:
    """Return only the simulated Kobo framebuffer, never the decorative bezel."""
    target = native_screen_size(profile, layout)
    out = contain_on_canvas(image, target, check_cancel)
    out = reduce_chroma_resolution(out, profile.chroma_resolution_percent, check_cancel)
    _check(check_cancel)
    out = apply_tone(out, profile)
    out = apply_channel_gains(out, profile)
    out = ImageEnhance.Color(out).enhance(profile.saturation)
    out = apply_hue_corrections(out, profile, check_cancel)
    _check(check_cancel)
    out = apply_cfa_modulation(out, profile, layout)
    _check(check_cancel)
    out = apply_micro_grain(out, profile, layout)
    _check(check_cancel)
    if profile.softness_radius > 0:
        out = out.filter(ImageFilter.GaussianBlur(radius=profile.softness_radius))
    return out


def render_emulated_detail(
    image: Image.Image,
    profile_id: str,
    layout: str,
    check_cancel: Optional[Callable[[], None]] = None,
) -> EmulatedDetail:
    """Preview-only one-page device simulation. Final-output code must not call this."""
    profile = profile_for(profile_id)
    if profile is None:
        raise ValueError("No-emulation is not a device render request.")
    _check(check_cancel)
    screen = emulate_screen(image, profile, layout, check_cancel)
    _check(check_cancel)
    _check(check_cancel)
    return EmulatedDetail(
        image=screen,
        screen_size=screen.size,
        profile_id=profile.profile_id,
        display_name=profile.display_name,
        layout=layout,
    )
