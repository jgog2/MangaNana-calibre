"""Dither Lab diffusion semantics, shared by every reading-page output.

One kernel runs in Python or optional Numba (no bundled dependencies or JIT
disk cache). Three float32 scanlines bound error-buffer memory. Integer palette
values are rounded consistently, including hard quantization; the lab's float
quantization/error math and clipped-old-pixel semantics are retained.
"""
from array import array
import math
from threading import Lock

from PIL import Image
try:
    from . import native_dithering
except ImportError:
    import native_dithering

KERNELS = {
    'floyd-steinberg': ((1, 0, 7/16), (-1, 1, 3/16), (0, 1, 5/16), (1, 1, 1/16)),
    'atkinson': ((1, 0, 1/8), (2, 0, 1/8), (-1, 1, 1/8), (0, 1, 1/8), (1, 1, 1/8), (0, 2, 1/8)),
    'sierra-lite': ((1, 0, 2/4), (-1, 1, 1/4), (0, 1, 1/4)),
}
_lock = Lock()
_accelerator = None
_attempted = False


def palette(levels):
    return tuple(round(i * 255.0 / (levels-1)) for i in range(levels))


def _diffuse_rows(source, output, buf, width, height, channels, start, stop, levels, strength, kernel):
    """Canonical implementation; only scalar operations supported by both paths."""
    stride = width * channels
    step = 255.0 / (levels-1)
    for y in range(start, stop):
        # Load each future scanline once, before receiving any distributed error.
        if y+2 < height:
            for i in range(stride):
                buf[((y+2) % 3)*stride+i] = source[(y+2)*stride+i]
        direction = 1 if y % 2 == 0 else -1
        for scan in range(width):
            x = scan if direction == 1 else width-1-scan
            for ch in range(channels):
                index = (y % 3)*stride + x*channels+ch
                # Float64 arithmetic / float32 stores match the lab's Numba
                # implementation, independent of NumPy scalar-promotion versions.
                old = min(255.0, max(0.0, buf[index] * 1.0))
                new = math.floor(old/step + 0.5)*step
                # Unlike the lab's final uint8 cast, use the hard-quantization palette.
                output[y*stride+x*channels+ch] = round(new)
                error = (old-new)*strength
                for dx, dy, weight in kernel:
                    nx, ny = x+dx*direction, y+dy
                    if 0 <= nx < width and ny < height:
                        target = (ny % 3)*stride + nx*channels+ch
                        buf[target] = buf[target] + error*weight


def _get_accelerator():
    """Lazy worker-side import; any unavailable/broken optional install is safe."""
    global _attempted, _accelerator
    with _lock:
        if not _attempted:
            _attempted = True
            try:
                import numpy as np
                from numba import njit
                _accelerator = (np, njit(nogil=True, cache=False)(_diffuse_rows))
            except Exception:
                _accelerator = None
    return _accelerator


def quantize(image, levels, algorithm='off', strength=1.0, *, backend='auto', check_cancel=None):
    """Original is identity. No Pillow FS shortcut: it lacks these semantics.

    Auto prefers validated native C and otherwise uses portable Python.
    Explicit 'python'/'numba' remain available; 'native' is strict for tests.
    """
    if levels == 0:
        return image
    if levels not in (2, 4, 8, 16) or algorithm not in ('off', *KERNELS):
        raise ValueError('Unsupported depth or dithering algorithm.')
    if not math.isfinite(strength) or not 0 <= strength <= 2:
        raise ValueError('Dither strength must be between 0 and 200%.')
    if image.mode not in ('L', 'RGB'):
        raise ValueError('Quantization requires L or RGB pixels; alpha is handled by the shared transform.')
    if algorithm == 'off' or strength == 0:
        values = palette(levels)
        lut = [values[math.floor(v*(levels-1)/255.0 + .5)] for v in range(256)]
        return image.point(lut * len(image.getbands()))
    if backend in ('auto', 'native'):
        native = native_dithering.get_backend()
        if native is not None:
            if check_cancel is not None: check_cancel()
            try:
                pixels = native.transform(image.tobytes(), image.width, image.height,
                                          len(image.getbands()), levels, strength, algorithm)
            except Exception as exc:
                native_dithering.disable_backend(str(exc))
                if backend == 'native': raise
            else:
                if check_cancel is not None: check_cancel()
                return Image.frombytes(image.mode, image.size, pixels)
        elif backend == 'native':
            raise RuntimeError('Validated native backend unavailable')
    accelerated = _get_accelerator() if backend == 'numba' else None
    if backend == 'numba' and accelerated is None:
        raise RuntimeError('Optional Numba accelerator unavailable.')
    source = image.tobytes()
    channels = len(image.getbands())
    stride = image.width * channels
    cancellation_error = False

    def run(accel):
        nonlocal cancellation_error
        output = bytearray(len(source))
        buf = array('f', [0.0]) * (3*stride)
        for i in range(min(2*stride, len(source))): buf[i] = source[i]
        src, dst, work = source, output, buf
        kernel_fn = _diffuse_rows
        if accel is not None:
            np, kernel_fn = accel
            src = np.frombuffer(source, dtype=np.uint8)
            dst = np.frombuffer(output, dtype=np.uint8)
            work = np.frombuffer(buf, dtype=np.float32)
        for row in range(0, image.height, 16):
            if check_cancel is not None:
                try: check_cancel()
                except Exception:
                    cancellation_error = True
                    raise
            kernel_fn(src, dst, work, image.width, image.height, channels, row,
                      min(row+16, image.height), levels, strength, KERNELS[algorithm])
        return Image.frombytes(image.mode, image.size, bytes(output))

    try:
        return run(accelerated)
    except InterruptedError:
        raise
    except Exception:
        if cancellation_error or accelerated is None or backend == 'numba': raise
        # Do not repeatedly select a failed runtime for subsequent pages.
        global _accelerator
        with _lock: _accelerator = None
        return run(None)
