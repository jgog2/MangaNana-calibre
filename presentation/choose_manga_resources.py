"""Bundled presentation assets, available from source and Calibre's ZIP loader."""
from calibre_plugins.manganana.common.plugin_paths import plugin_root
import hashlib
import os
from pathlib import Path
import tempfile

PROVIDER_FILES = tuple(f'assets/ui/provider_shaders/{name}_Shader.{ext}'
    for name in ('MangaDex', 'MangaPill', 'WeebCentral', 'MangaK', 'Atsu')
    for ext in ('frag', 'png'))
UI_FILES = (*PROVIDER_FILES,
    'assets/audio/mangaanka_complete.mp3',
    'assets/ui/icons/chevron-down.svg','assets/ui/icons/sort-ascending.svg','assets/ui/icons/sort-descending.svg',
    'assets/ui/selected_work_hero.frag', 'assets/ui/selected_work_hero.png',
    'assets/ui/LICENSE.selected-work-hero.txt',
    *(f'assets/ui/fonts/Geist-{weight}.ttf' for weight in ('Regular', 'SemiBold', 'Bold')),
    'assets/ui/fonts/OFL.txt', 'assets/ui/fonts/README.md',
    'assets/hero_shaders/NoSelection_Shader.frag',
    'assets/hero_shaders/NoSelection_Shader.png',
    'assets/hero_shaders/LICENSE.NoSelection.txt')
_root = None


def asset_root():
    """Extract one immutable content-addressed set; never use the installed ZIP."""
    global _root
    if _root is not None:
        return _root
    loader = globals().get('get_resources')
    if loader is None:
        return plugin_root()
    payload = {name: loader(name) for name in UI_FILES}
    missing = [name for name, data in payload.items() if not data]
    if missing:
        raise FileNotFoundError('Bundled UI resources missing: ' + ', '.join(missing))
    digest = hashlib.sha256()
    for name, data in payload.items():
        digest.update(name.encode('utf-8')); digest.update(data)
    from calibre.constants import config_dir
    root = Path(config_dir) / 'plugins/manganana-ui' / digest.hexdigest()
    for name, data in payload.items():
        target = root / name
        if target.is_file() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.asset-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    _root = root
    return root
