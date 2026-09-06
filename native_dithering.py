"""Optional ABI-1 native pixel kernel. No GUI/provider/settings dependencies.

Calibre injects get_resources into ZIP-loaded modules. Extraction is lazy on
the processing worker, content-addressed, atomic, and verified before CDLL.
Missing/invalid resources never prevent module or plugin startup.
"""
import ctypes
import hashlib
import logging
import os
from pathlib import Path
import platform
import sys
import tempfile
from threading import Lock

RESOURCE = 'native/windows-x86_64/manganana_dither_abi1.dll'
ABI_VERSION = 1
ALG_IDS = {'floyd-steinberg': 1, 'atkinson': 2, 'sierra-lite': 3}
_PROBE_HASHES = (
    '64b61c098bc1795e1583b98fa92bcaeec3aaf1cf0ef3fa6b2f80eff5a5df0983',
    'fb3dcafdc69509cf417f9d59ab99b442c27595f57cbe4b3d7e06dab686b4f6f1',
    '0e8e9b826eb5990bae003e74a11052312bb9a8c2b6b4df6dfd58401698b92e51',
)
_lock = Lock()
_attempted = False
_backend = None
_status = 'not attempted'
_logged = set()
_logger = logging.getLogger('manganana.native_dithering')


def _notice(message):
    # Calibre debug/session log, not a GUI callback from the worker thread.
    if message in _logged: return
    _logged.add(message)
    if not _logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        _logger.addHandler(handler)
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
    _logger.info(message)


def supported():
    return sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p) == 8 and platform.machine().lower() in ('amd64', 'x86_64')


def _resource_bytes():
    loader = globals().get('get_resources')
    if loader is not None:
        data = loader(RESOURCE)
        if not data: raise FileNotFoundError('packaged native resource missing')
        return data
    # Source checkout / deterministic tests only. Never search PATH or cwd.
    return (Path(__file__).resolve().parent/RESOURCE).read_bytes()


def _cache_root():
    try:
        from calibre.constants import config_dir
    except ImportError:
        return Path(__file__).resolve().parent/'build/native-cache'
    return Path(config_dir)/'plugins/manganana-native'


def extract_library(data, root):
    digest = hashlib.sha256(data).hexdigest()
    target_dir = Path(root)/f'abi-{ABI_VERSION}'/'windows-x86_64'/digest
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir/'manganana_dither_abi1.dll'
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('extracted DLL hash mismatch')
        return target.resolve()
    fd, temporary = tempfile.mkstemp(prefix='.extract-', suffix='.tmp', dir=target_dir)
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(data)
        try: os.replace(temporary, target)
        except OSError:
            # Another Calibre process may have extracted and loaded this hash.
            if not target.exists() or target.read_bytes() != data: raise
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('extracted DLL hash mismatch')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target.resolve()


class NativeBackend:
    def __init__(self, library):
        self.library = library  # Hold the CDLL for the complete session.
        version = library.manganana_dither_abi_version
        version.argtypes = []; version.restype = ctypes.c_int
        fn = library.manganana_dither_u8
        fn.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_double, ctypes.c_int]
        fn.restype = ctypes.c_int
        if version() != ABI_VERSION: raise ValueError('native ABI mismatch; expected 1')
        self.function = fn
        source = bytes((i*37+i//7*13) % 256 for i in range(105))
        for algorithm, expected in zip(ALG_IDS, _PROBE_HASHES):
            output = self.transform(source, 7, 5, 3, 8, 1.5, algorithm)
            if hashlib.sha256(output).hexdigest() != expected:
                raise ValueError('native deterministic validation failed')

    def transform(self, source, width, height, channels, levels, strength, algorithm):
        if (width <= 0 or height <= 0 or width > 2147483645 or height > 2147483645
                or channels not in (1, 3) or len(source) != width*height*channels):
            raise ValueError('Invalid native pixel buffer dimensions')
        if levels not in (2, 4, 8, 16) or algorithm not in ALG_IDS or not 0 <= strength <= 2:
            raise ValueError('Invalid native quantization parameters')
        src = (ctypes.c_uint8*len(source)).from_buffer_copy(source)
        out = (ctypes.c_uint8*len(source))()
        result = self.function(src, out, width, height, channels, levels, float(strength), ALG_IDS[algorithm])
        if result: raise RuntimeError(f'native dither returned error {result}')
        return bytes(out)


def get_backend():
    global _attempted, _backend, _status
    with _lock:
        if not _attempted:
            _attempted = True
            try:
                if not supported(): raise RuntimeError('unsupported platform/architecture')
                path = extract_library(_resource_bytes(), _cache_root())
                # Absolute path + Windows restricted dependency search. CDLL releases GIL.
                _backend = NativeBackend(ctypes.CDLL(str(path), winmode=0x1100))
                _status = 'native'
                _notice('Image processing: Native dithering acceleration enabled.')
            except Exception as exc:
                _backend = None
                _status = f'portable ({type(exc).__name__}: {exc})'
                _notice(f'Native dithering acceleration unavailable; using portable processing. Reason: {exc}')
        return _backend


def disable_backend(reason):
    global _backend, _attempted, _status
    with _lock:
        _backend = None; _attempted = True
        _status = f'portable ({reason})'
        _notice(f'Native dithering acceleration disabled; using portable processing. Reason: {reason}')


def backend_status():
    return _status
