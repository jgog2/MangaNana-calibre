"""Platform-neutral opening-size policy, expressed in Qt logical pixels."""
# Slightly wider preview-first opening; saved user geometry still wins.
DEFAULT_WINDOW_FRAME = (1680, 950)
NORMAL_DESKTOP_FRACTION = 0.94
MINIMUM_WINDOW_CLIENT = (1200, 760)


def choose_window_size(saved, available, frame_extra=(0, 0)):
    """Return client size. Saved client sizes win when they fit the desktop.

    Fresh sizes target the approved outer frame. Actual Qt decoration extents
    are supplied by the dialog after show; no OS-specific title-bar constants.
    A constrained desktop takes priority over the normal minimum usable size.
    """
    extra_w, extra_h = (max(0, int(v)) for v in frame_extra)
    available_w, available_h = (max(1, int(v)) for v in available)
    try:
        saved_w, saved_h = (int(v) for v in saved)
        if saved_w <= 0 or saved_h <= 0:
            raise ValueError()
        frame_w, frame_h = saved_w + extra_w, saved_h + extra_h
    except (TypeError, ValueError, OverflowError):
        frame_w, frame_h = DEFAULT_WINDOW_FRAME
    scale = min(1, NORMAL_DESKTOP_FRACTION * available_w / frame_w,
                NORMAL_DESKTOP_FRACTION * available_h / frame_h)
    return (max(1, int(frame_w * scale) - extra_w),
            max(1, int(frame_h * scale) - extra_h))


def clamp_window_position(saved, size, available):
    """Frame top-left on the current logical desktop, including negative origins."""
    left, top, width, height = available
    frame_w, frame_h = size
    try:
        x, y = (int(v) for v in saved)
    except (TypeError, ValueError, OverflowError):
        x, y = left + (width-frame_w)//2, top + (height-frame_h)//2
    return (max(left, min(x, left+max(0, width-frame_w))),
            max(top, min(y, top+max(0, height-frame_h))))
