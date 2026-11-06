"""Portable state utility included ONLY in the popup laboratory build."""
import json
import os
from pathlib import Path
import time

MARKER = 'mangaanka-popup-test-profile.json'
RESET_VALUES = {
    'ask_virtual_library': True,
    'popup_test_google_invited': False,
    'update_last_attempt': 0,
    'update_last_success': 0,
    'update_ignored_version': '',
    'update_later_until': 0,
}


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def normal_locations():
    home = Path.home()
    paths = [home / '.config/calibre', home / 'Library/Preferences/calibre']
    if os.environ.get('APPDATA'):
        paths.append(Path(os.environ['APPDATA']) / 'calibre')
    return {p.resolve() for p in paths}


def ensure_profile(directory, existing=False):
    directory = Path(directory).resolve()
    if directory in normal_locations():
        raise ValueError('The normal Calibre profile cannot be a popup laboratory.')
    marker = directory / MARKER
    if marker.exists():
        record = json.loads(marker.read_text(encoding='utf-8'))
        if record.get('kind') != 'MangaAnka-popup-laboratory-v1' or Path(record['profile']).resolve() != directory:
            raise ValueError('Invalid laboratory profile marker.')
        return directory
    if directory.exists() and any(directory.iterdir()) and not existing:
        raise ValueError('Choose a new empty directory; existing profiles are never adopted by this utility.')
    directory.mkdir(parents=True, exist_ok=True)
    atomic_json(marker, dict(kind='MangaAnka-popup-laboratory-v1', profile=str(directory)))
    return directory


def lock_profile(directory):
    """Held for the lifetime of Calibre; the reset utility needs this same lock."""
    stream = (Path(directory) / 'popup-test-session.lock').open('a+b')
    if stream.tell() == 0:
        stream.write(b'0'); stream.flush()
    stream.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise ValueError('Close the laboratory Calibre process before changing its prompt state.') from None
    return stream


def reset_prompts(directory):
    directory = Path(directory).resolve()
    if not (directory / MARKER).is_file():
        raise ValueError('Only a marked popup laboratory profile can be reset.')
    ensure_profile(directory)
    with lock_profile(directory):
        path = directory / 'plugins/manganana.json'
        raw = path.read_bytes() if path.exists() else b'{}'
        values = json.loads(raw.decode('utf-8'))
        if not isinstance(values, dict):
            raise ValueError('Preferences are not a JSON object; nothing changed.')
        backup = directory / ('popup-reset-before-' + str(time.time_ns()) + '.json')
        backup.write_bytes(raw)
        values.update(RESET_VALUES)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, values)
        return backup
