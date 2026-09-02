"""Local presentation metadata for MangaNana provider badges."""

from dataclasses import dataclass
import re
import urllib.parse


@dataclass(frozen=True)
class ProviderBrand:
    """Stable display metadata with an optional bundled icon resource."""

    source_id: str
    display_name: str
    accent_color: str
    text_color: str = '#FFFFFF'
    icon_path: str = ''


DEFAULT_PROVIDER_BRAND = ProviderBrand('', 'Provider', '#555B61')

PROVIDER_BRANDS = {
    'mangadex': ProviderBrand(
        source_id='mangadex', display_name='MangaDex', accent_color='#FF6740',
        icon_path='images/favicon_mangadex_org_32x32.png',
    ),
    'mangapill': ProviderBrand(
        source_id='mangapill', display_name='MangaPill', accent_color='#0070F3',
        icon_path='images/favicon_mangapill_com_32x32.png',
    ),
    'weebcentral': ProviderBrand(
        source_id='weebcentral', display_name='WeebCentral', accent_color='#454EA7',
        icon_path='images/favicon_weebcentral_com_32x32.png',
    ),
}

_PROVIDER_TITLE_PATHS = {
    'mangadex': re.compile(
        r'^/title/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:/[^/?#]+)?/?$',
        re.I,
    ),
    'mangapill': re.compile(r'^/manga/\d+(?:/[^/?#]+)?/?$', re.I),
    'weebcentral': re.compile(r'^/series/[0-9a-z]{26}(?:/[^/?#]+)?/?$', re.I),
}


def provider_brand(source_id):
    """Return a neutral, readable brand when a provider has no curated entry."""
    return PROVIDER_BRANDS.get(str(source_id or '').casefold(), DEFAULT_PROVIDER_BRAND)


def safe_provider_public_url(source_id, value):
    """Return an exact supported provider title URL, never a guessed URL."""
    source_id = str(source_id or '').casefold()
    text = str(value or '').strip()
    pattern = _PROVIDER_TITLE_PATHS.get(source_id)
    brand = provider_brand(source_id)
    if not text or pattern is None or not brand.source_id:
        return ''
    try:
        parsed = urllib.parse.urlparse(text)
    except Exception:
        return ''
    if parsed.scheme.casefold() not in ('http', 'https'):
        return ''
    host = (parsed.hostname or '').casefold()
    expected = {
        'mangadex': {'mangadex.org', 'www.mangadex.org'},
        'mangapill': {'mangapill.com', 'www.mangapill.com'},
        'weebcentral': {'weebcentral.com', 'www.weebcentral.com'},
    }.get(source_id, set())
    if host not in expected or not pattern.match(parsed.path or ''):
        return ''
    return text


def format_rating_label(value):
    """Render a known rating as explicit secondary metadata."""
    text = str(value or '').strip()
    if not text:
        return ''
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if not match:
        return ''
    try:
        number = float(match.group(1))
    except Exception:
        return ''
    rendered = f'{number:.1f}'.rstrip('0').rstrip('.')
    return f'★ {rendered}'


def provider_badge_spec(source_id, display_name, public_url=''):
    """Return local-only UI metadata without provider-specific UI branches."""
    brand = provider_brand(source_id)
    label = str(display_name or brand.display_name or source_id or 'Provider')
    return {
        'source_id': str(source_id or ''),
        'text': label,
        'kind': 'source',
        'accent_color': brand.accent_color,
        'text_color': brand.text_color,
        'icon_path': brand.icon_path,
        'public_url': safe_provider_public_url(source_id, public_url),
    }


def edition_badge_spec(label):
    """Use the same pill component language for edition/type labels."""
    return {
        'source_id': '',
        'text': str(label or '').strip().upper(),
        'kind': 'edition',
        'accent_color': '#FF6740',
        'text_color': '#FFD7CC',
        'icon_path': '',
        'public_url': '',
    }


def source_badge_specs(source_names, source_ids=(), public_urls=()):
    """Return deterministic presentation specs for confirmed provider sources."""
    ids = tuple(source_ids or ())
    urls = tuple(public_urls or ())
    specs = []
    seen = set()
    for index, name in enumerate(source_names or ()):
        if not name:
            continue
        source_id = ids[index] if index < len(ids) else ''
        identity = (source_id, name)
        if identity in seen:
            continue
        seen.add(identity)
        public_url = urls[index] if index < len(urls) else ''
        specs.append(provider_badge_spec(source_id, name, public_url))
    return tuple(specs)
