"""Reading-page framing geometry, independent of image-processing presets."""

from PIL import Image


def framing_value(value):
    return max(-100, min(100, int(value)))


def framing_rectangle(size, baseline, value):
    """Centered fitting box: reclaim safe area, then at most 5% zoom.

    Baseline is the current fitting rectangle's size. Artwork is always aspect-fit
    inside this box by the caller, so changing the box never stretches pixels.
    """
    value = -framing_value(value)  # Positive UI values move inward.
    width, height = size
    base_w, base_h = baseline
    if value >= 0:
        factor = 1 - .15 * value / 100
        fit_w, fit_h = base_w * factor, base_h * factor
    elif baseline == size:
        factor = 1 + .05 * -value / 100
        fit_w, fit_h = width * factor, height * factor
    elif value >= -70:
        fraction = -value / 70
        fit_w = base_w + (width - base_w) * fraction
        fit_h = base_h + (height - base_h) * fraction
    else:
        factor = 1 + .05 * (-value - 70) / 30
        fit_w, fit_h = width * factor, height * factor
    fit_w, fit_h = max(1, round(fit_w)), max(1, round(fit_h))
    return (width - fit_w) // 2, (height - fit_h) // 2, fit_w, fit_h


def portrait_framing(image, value, check_cancel=None):
    value = framing_value(value)
    if not value:
        return image
    if check_cancel: check_cancel()
    x, y, width, height = framing_rectangle(image.size, image.size, value)
    size = (width, height)
    artwork = image.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new('RGB', image.size, 'white')
    canvas.paste(artwork, (x, y))
    if check_cancel: check_cancel()
    return canvas


def framing_label(value, landscape=False, size=None, baseline=None, gutter_px=0):
    """Added canvas margins, not whitespace already present in source artwork."""
    value = framing_value(value)
    zoom = max(0, 5 * (value - 70) / 30) if landscape else max(0, 5 * value / 100)
    if size is None:
        margin = 'Outer Margin: awaiting page dimensions' if value < 0 else 'Outer Margin: 0 px'
    else:
        x, y, _w, _h = framing_rectangle(size, baseline or size, value)
        x, y = max(0, x), max(0, y)
        margin = f'Outer Margin: {x} px H × {y} px V' if x or y else 'Outer Margin: 0 px'
    if zoom: margin += f' · Zoom: +{zoom:.1f}%'
    if landscape: margin += f' · Gutter: {gutter_px} px'
    return margin


def framing_snapshot(value, gutter_px=0):
    """Versioned, descriptive configuration for both layout interpretations."""
    value = framing_value(value)
    return {'version': 1, 'outer': (
        {'mode': 'baseline_reduction', 'fraction': -.15 * value / 100} if value < 0 else
        {'mode': 'inward', 'safe_area_reclaimed': min(value / 70, 1),
         'landscape_zoom': max(0, .05 * (value - 70) / 30), 'portrait_zoom': .05 * value / 100}),
        'gutter_px': max(0, min(80, int(gutter_px)))}


def framing_from_snapshot(payload):
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise ValueError('Unsupported framing preset.')
    outer = payload['outer']
    if outer['mode'] == 'baseline_reduction':
        value = round(-100 * outer['fraction'] / .15)
    elif outer['mode'] == 'inward':
        value = round(100 * outer['portrait_zoom'] / .05)
    else: raise ValueError('Unknown framing mode.')
    gutter = payload['gutter_px']
    if payload != framing_snapshot(value, gutter):
        raise ValueError('Malformed framing geometry.')
    return value, int(gutter)


def save_framing_preset(presets, name, payload, current_name=None):
    name = ' '.join(str(name).split())
    if not name or name.casefold() in ('default', 'no margin', 'custom'):
        raise ValueError('Choose a nonempty name other than a built-in preset name.')
    if current_name is not None and current_name not in presets:
        raise ValueError('Only saved user presets can be changed.')
    if any(n.casefold() == name.casefold() and n != current_name for n in presets):
        raise ValueError('A preset with this name already exists. Use Manage to update it.')
    value, gutter = framing_from_snapshot(payload)
    result = dict(presets)
    if current_name is not None: del result[current_name]
    result[name] = framing_snapshot(value, gutter)
    return result


def delete_framing_preset(presets, name):
    if name in ('Default', 'No Margin') or name not in presets:
        raise ValueError('Only saved user presets can be deleted.')
    return {n: p for n, p in presets.items() if n != name}


def load_framing_presets(payload):
    result = {}
    if isinstance(payload, dict):
        for name, settings in payload.items():
            try: result = save_framing_preset(result, name, settings)
            except (ValueError, TypeError, KeyError, OverflowError): pass
    return result
