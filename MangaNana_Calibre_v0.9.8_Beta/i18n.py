# MangaNana UI localization foundation.
# English is currently bundled. Future translations can be added here without
# changing downloader or Calibre integration logic.

UI_LANGUAGES = [
    ('System Default', 'system'),
    ('English', 'en'),
]

_ENGLISH = {}

def tr(text, language=None):
    # Reserved translation hook. Fall back to the source English string.
    return _ENGLISH.get(text, text)
