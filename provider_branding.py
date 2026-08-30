"""Local presentation metadata for MangaNana provider badges."""

from dataclasses import dataclass


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


def provider_brand(source_id):
    """Return a neutral, readable brand when a provider has no curated entry."""
    return PROVIDER_BRANDS.get(str(source_id or '').casefold(), DEFAULT_PROVIDER_BRAND)


def provider_badge_spec(source_id, display_name):
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
    }


def source_badge_specs(source_names, source_ids=()):
    """Return deterministic presentation specs for confirmed provider sources."""
    ids = tuple(source_ids or ())
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
        specs.append(provider_badge_spec(source_id, name))
    return tuple(specs)
