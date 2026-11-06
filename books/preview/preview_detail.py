"""Pure detail-preview bounds and zoom geometry; no acquisition or image cache."""
DETAIL_MAX_BYTES = 64 * 1024 * 1024
ZOOM_FACTORS = (None, .25, .5, .75, 1.0, 1.25, 1.5, 2.0)


def detail_rgba(image):
    """Return one selected processed page, never a thumbnail or all-page cache."""
    if image.width * image.height * 4 > DETAIL_MAX_BYTES:
        raise ValueError('Detail page exceeds the 64 MiB limit. Overview remains available.')
    return image.convert('RGBA').tobytes()


def zoom_dimensions(image_size, viewport_size, factor=None):
    """Qt logical pixels. 100% is exact 1:1; Fit contains and never upscales."""
    width, height = image_size
    if factor is None:
        factor = min(1.0, max(1, viewport_size[0]) / width, max(1, viewport_size[1]) / height)
    elif factor not in ZOOM_FACTORS:
        raise ValueError('Unsupported detail zoom.')
    return max(1, round(width * factor)), max(1, round(height * factor))
