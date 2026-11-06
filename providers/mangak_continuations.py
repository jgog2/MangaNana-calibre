"""Opt-in reconstruction of specifically reviewed MangaK continuation pairs.

This contains no chapter identities or publication memberships. Unknown readers
are untouched; a changed reviewed manifest or fragment fails closed. No sizing
heuristic, crop, resize, or content removal is used.
"""
from calibre_plugins.manganana.common.plugin_paths import plugin_root
from functools import lru_cache
import hashlib
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import urlparse

RESOURCE = 'assets/acquisition_layouts/mangak_continuations.json'
SCHEME = 'mangak-continuation'


@lru_cache(maxsize=1)
def reviewed_layouts():
    loader = globals().get('get_resources')  # Calibre plugin ZIP loader.
    raw = loader(RESOURCE) if loader is not None else (plugin_root() / RESOURCE).read_bytes()
    data = json.loads(raw)
    if data.get('version') != 1:
        raise ValueError('Unsupported MangaK continuation evidence')
    return tuple(data['reviewed_readers'])


def _key(recipe):
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def manifest_pages(chapter, reader_url):
    """Return paired page handles only for the unchanged reviewed reader."""
    for recipe in reviewed_layouts():
        if chapter.get('id') != recipe['provider_record_id'] and reader_url != recipe['reader_url']:
            continue
        expected = [{k: p[k] for k in ('url', 'width', 'height')} for p in recipe['fragments']]
        if (chapter.get('id') != recipe['provider_record_id'] or reader_url != recipe['reader_url']
                or chapter.get('pages') != expected or chapter.get('images') != [p['url'] for p in expected]):
            raise ValueError('Reviewed MangaK continuation manifest changed; reconstruction refused')
        if not expected or len(expected) % 2:
            raise ValueError('Incomplete reviewed MangaK continuation pairs')
        return [f'{SCHEME}://{_key(recipe)}/{n}.png' for n in range(len(expected) // 2)]
    return None


def fetch_page(url, fetch, check_cancel):
    """Verify and concatenate one reviewed top/footer pair without resampling."""
    from PIL import Image
    parsed = urlparse(url)
    recipe = next((r for r in reviewed_layouts() if _key(r) == parsed.netloc), None)
    try:
        number = int(parsed.path.removeprefix('/').removesuffix('.png'))
    except ValueError:
        number = -1
    if (parsed.scheme != SCHEME or parsed.query or parsed.fragment or recipe is None
            or parsed.path != f'/{number}.png' or number < 0 or number >= len(recipe['fragments']) // 2):
        raise ValueError('Unknown reviewed MangaK continuation page')
    images = []
    try:
        for fragment in recipe['fragments'][number * 2:number * 2 + 2]:
            check_cancel()
            blob = fetch(fragment['url'])
            if hashlib.sha256(blob).hexdigest() != fragment['sha256']:
                raise ValueError('Reviewed MangaK fragment bytes changed; reconstruction refused')
            with Image.open(BytesIO(blob)) as image:
                if (image.size != (fragment['width'], fragment['height'])
                        or image.getexif().get(274, 1) != 1 or image.mode not in ('RGB', 'L')):
                    raise ValueError('Reviewed MangaK fragment geometry changed')
                images.append(image.convert('RGB'))
        top, footer = images
        if top.width != footer.width or top.height <= footer.height:
            raise ValueError('Invalid reviewed MangaK top/footer pair')
        check_cancel()
        with Image.new('RGB', (top.width, top.height + footer.height)) as page:
            page.paste(top, (0, 0)); page.paste(footer, (0, top.height))
            stream = BytesIO(); page.save(stream, 'PNG')
        check_cancel()
        return stream.getvalue()
    finally:
        for image in images:
            image.close()
