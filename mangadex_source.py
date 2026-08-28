"""Calibre-independent MangaDex source implementation."""

import re
import urllib.parse

try:
    from .core_helpers import choose_preferred_title, collect_titles
    from .source_adapter import SourceAdapter
except ImportError:
    from core_helpers import choose_preferred_title, collect_titles
    from source_adapter import SourceAdapter


UUID_RE = re.compile(r'/title/([0-9a-fA-F-]{36})')


class MangaDexSource(SourceAdapter):
    key = 'mangadex'
    display_name = 'MangaDex'

    def __init__(self, api_json):
        self._api_json = api_json

    def parse_manga_ref(self, value):
        match = UUID_RE.search(value or '')
        return match.group(1) if match else None

    def get_manga(self, value, preferred='en'):
        manga_id = self.parse_manga_ref(value)
        if not manga_id:
            raise ValueError(
                'Paste a MangaDex title-page URL, for example https://mangadex.org/title/...'
            )
        query = urllib.parse.urlencode(
            [('includes[]', 'author'), ('includes[]', 'artist'), ('includes[]', 'cover_art')]
        )
        data = self._api_json(
            f'https://api.mangadex.org/manga/{manga_id}?{query}'
        )['data']
        attrs = data.get('attributes', {})
        title_rows = collect_titles(attrs)
        title = choose_preferred_title(title_rows, preferred)
        author = ''
        cover_filename = ''
        for relationship in data.get('relationships', []):
            if (
                relationship.get('type') == 'author'
                and relationship.get('attributes')
                and not author
            ):
                author = relationship['attributes'].get('name', '')
            elif (
                relationship.get('type') == 'cover_art'
                and relationship.get('attributes')
                and not cover_filename
            ):
                cover_filename = relationship['attributes'].get('fileName', '') or ''
        available = [
            str(language)
            for language in (attrs.get('availableTranslatedLanguages') or [])
            if language
        ]
        main_cover_url = (
            f'https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}'
            if cover_filename
            else ''
        )
        return {
            'uuid': manga_id,
            'title': title,
            'author': author,
            'titles': title_rows,
            'available_languages': available,
            'original_language': attrs.get('originalLanguage') or '',
            'main_cover_url': main_cover_url,
        }
