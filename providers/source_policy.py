"""Persisted, provider-neutral policy for ordinary search participation."""


SOURCE_ENABLED_PREF = 'source_enabled'


def source_enabled_states(preferences):
    """Return a sanitized copy of the stored ``source_id -> bool`` mapping."""
    try:
        raw = preferences.get(SOURCE_ENABLED_PREF, {})
    except AttributeError:
        try:
            raw = preferences[SOURCE_ENABLED_PREF]
        except (KeyError, TypeError):
            raw = {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(source_id).strip(): enabled
        for source_id, enabled in raw.items()
        if str(source_id or '').strip() and isinstance(enabled, bool)
    }


def is_source_enabled(preferences, source):
    """Return whether a registered source participates in general searches."""
    source_id = str(getattr(source, 'source_id', source) or '').strip()
    default = bool(getattr(source, 'enabled_by_default', True))
    return source_enabled_states(preferences).get(source_id, default)


def enabled_sources(registry, preferences):
    """Return enabled adapters without removing anything from the registry."""
    return tuple(
        source for source in registry.all()
        if is_source_enabled(preferences, source)
    )


def save_source_enabled_states(preferences, updates, commit=True):
    """Merge stable source-id updates while preserving unknown future entries."""
    states = source_enabled_states(preferences)
    for source_id, enabled in dict(updates or {}).items():
        source_id = str(source_id or '').strip()
        if source_id:
            states[source_id] = bool(enabled)
    preferences[SOURCE_ENABLED_PREF] = states
    if commit:
        try:
            preferences.commit()
        except Exception:
            pass
    return dict(states)


def media_class(record):
    """Explicit acquisition medium wins over broad type; titles are never evidence."""
    row=record or {}
    value=str(row.get('medium') or row.get('type') or '').casefold()
    value=''.join(c for c in value if c.isalnum())
    if value in ('novel','lightnovel','webnovel'): return 'novel'
    if value in ('comic','manga','manhwa','manwha','manhua'): return 'comic'
    return 'unknown'


def supported_media(record):
    return media_class(record) != 'novel'


def compatible_media(first, second):
    a,b=media_class(first),media_class(second)
    return a == b or 'unknown' in (a,b)
