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
