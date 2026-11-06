"""Validated, source-owned artwork delivery. Never fetches manga reading pages.

The MangaDex denial signature was captured with MangaK and Atsu Referers on
2026-09-11 (both 59,480 bytes, 600 x 642). A neutral request returned the cover.
Hash decoded RGB pixels so lossless re-encoding/metadata changes cannot bypass
the check. Dimensions only select the hash check; they never reject a cover.
No copyrighted cover or denial-image bytes are bundled.
"""
from collections import OrderedDict
from dataclasses import dataclass, replace
import json
from hashlib import sha256
from io import BytesIO
from threading import RLock
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageOps

from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
from calibre_plugins.manganana.version_info import USER_AGENT
from calibre_plugins.manganana.books.imaging.artwork_cache import ResourceFailure


MANGADEX_DENIAL_RGB = '6da9639ad2ee2270238250bc3d5d1bcdb979a1ed635248607b2f279870b7fa55'
MAX_BYTES = 24 * 1024 * 1024


def validate_artwork(raw):
    if not raw or len(raw) > MAX_BYTES:
        return 'invalid image'
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                return 'invalid image'
            image.load()
            if image.size == (600, 642) and sha256(image.convert('RGB').tobytes()).hexdigest() == MANGADEX_DENIAL_RGB:
                return 'known placeholder'
    except Exception:
        return 'invalid image'
    return ''


def prepare_artwork(raw):
    """Validate and derive a display rendition in one Pillow decode, in a worker."""
    if not raw or len(raw)>MAX_BYTES:return 'invalid image',None
    try:
        with Image.open(BytesIO(raw))as image:
            if image.width*image.height>40_000_000:return 'invalid image',None
            image.load()
            if image.size==(600,642)and sha256(image.convert('RGB').tobytes()).hexdigest()==MANGADEX_DENIAL_RGB:return 'known placeholder',None
            preview=ImageOps.exif_transpose(image)
            preview=preview.convert('RGBA'if 'A'in preview.getbands()else'RGB')
            preview.thumbnail((220,300),getattr(Image,'Resampling',Image).LANCZOS)
            buffer=BytesIO();preview.save(buffer,'PNG',compress_level=1)
            return '',buffer.getvalue()
    except Exception:return 'invalid image',None


@dataclass(frozen=True)
class ArtworkCandidate:
    source: str
    url: str
    volume: str = ''
    source_identity: str = ''
    confidence: str = 'exact'
    validation_context: str = ''
    preview_url: str = ''
    publication_key: str = ''

    @property
    def key(self):
        return (self.source, self.url, self.volume, self.source_identity,
                self.confidence, self.validation_context)


def candidate_for_url(url, provider):
    """Legacy series/edition covers still need host-owned transport."""
    try:host = (urllib.parse.urlparse(url).hostname or '').lower()
    except ValueError:host=''
    if host == 'uploads.mangadex.org':
        source = 'mangadex_artwork'
    elif host == 'bookwalker.jp' or host.endswith('.bookwalker.jp'):
        source = 'bookwalker'
    elif host in ('books.google.com', 'books.google.co.jp') or host.endswith('.googleusercontent.com'):
        source = 'google_books'
    else:
        source = getattr(provider, 'source_id', 'provider')
    return ArtworkCandidate(source, url)


def neutral_fetch(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT, 'Accept': 'image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8'})
    with urllib.request.urlopen(request, timeout=14) as response:
        return response.read(MAX_BYTES + 1)


class ArtworkResolver:
    """One session owner, immutable candidate snapshots, bounded byte/negative LRUs.

    Metadata preference stays in the manifest. Only `resolve` promotes bytes and
    winning provenance. Call from a worker; no decoding/network on the GUI thread.
    """
    def __init__(self, mangadex=None, reference_fetch=None, clock=None, resources=None):
        self.mangadex = mangadex or MangaDexSource()
        self.reference_fetch = reference_fetch or neutral_fetch
        self.clock = clock or time.monotonic
        self.chains = {}
        self.valid = OrderedDict()
        self.valid_at = {}
        self.negative = OrderedDict()
        self.winners = OrderedDict()
        self.lock = RLock()
        self.resources=resources

    def register_manifest(self, manifest):
        context=sha256(json.dumps((manifest.schema_version,
            manifest.work.canonical_identity,manifest.work.language,manifest.edition.identity,
            manifest.edition.language,manifest.runtime_publication.get('as_of'),
            manifest.runtime_publication.get('source_fingerprints'),
            manifest.runtime_publication.get('release_boundary'),
            [(s.source,s.status,s.contract,s.parser_version,s.cache_state=='last_known_good',s.last_validated)
                for s in manifest.source_states]),sort_keys=True,default=str).encode('utf-8')).hexdigest()
        with self.lock:
            chains={}
            for volume in manifest.volumes:
                artwork = volume.artwork_candidates or ((volume.cover,) if volume.cover else ())
                chain = tuple(ArtworkCandidate(item.source, item.url, volume.key, item.identity, item.confidence,
                              context+'|'+str((item.preview_url,item.source_url,item.source_field,item.retrieval)),
                              item.preview_url, self._publication_key(manifest,item))for item in artwork)
                for item in chain:
                    chains[item.url] = chain
            edition_art = manifest.display.edition_artwork
            if edition_art and edition_art.url not in chains:
                chains[edition_art.url] = (ArtworkCandidate(
                    edition_art.source, edition_art.url, source_identity=edition_art.identity,
                    confidence=edition_art.confidence,validation_context=context),)
            changed={url for url in self.chains.keys()|chains.keys() if self.chains.get(url)!=chains.get(url)}
            self.chains=chains
            if self.resources:
                from calibre_plugins.manganana.books.imaging.artwork_cache import resource_identity
                for chain in chains.values():
                    for candidate in chain:
                        for variant in self._display_candidates(candidate):
                            value=self.resources.peek(resource_identity(variant)[0])
                            if value:self.resources.associate(variant,value)
            return changed

    @staticmethod
    def _publication_key(manifest,item):
        # Source publication/edition/cover IDs, never acquisition IDs or titles.
        if item.confidence!='exact' or not item.publication_id or not item.edition_id or not item.volume_id:return ''
        return sha256(json.dumps((item.source,item.publication_id,item.edition_id,item.volume_id,item.volume,
            manifest.edition.identity,manifest.edition.language,manifest.edition.market,item.url),sort_keys=True).encode()).hexdigest()

    def _fetch(self,candidate,provider):
        if candidate.source in ('mangadex_artwork','mangadex'):
            return self.mangadex.fetch_binary(candidate.url,timeout=14,retries=1)
        if candidate.source in ('bookwalker','google_books'):return self.reference_fetch(candidate.url)
        if candidate.source in ('provider',getattr(provider,'source_id','provider')):
            return provider.fetch_binary(candidate.url,timeout=14,retries=1)
        raise ValueError('unavailable artwork source')

    @staticmethod
    def _display_candidates(candidate):
        return ((replace(candidate,url=candidate.preview_url),candidate)
                if candidate.preview_url and candidate.preview_url!=candidate.url else (candidate,))

    def _display_result(self,candidate,value,failures=(),decode=False):
        image=self.resources.image(value)if decode else self.resources.peek_image(value)
        stamp=sha256(((candidate.publication_key or candidate.source_identity or candidate.url)+'|'+value.key).encode()).hexdigest()
        with self.lock:
            self.winners[candidate.volume or candidate.url]=candidate
            while len(self.winners)>256:self.winners.popitem(last=False)
        return dict(raw=value.preview,image=image,candidate=candidate,failures=tuple(failures),artwork_key=stamp,resource_key=value.key)

    def peek_display(self,url,provider):
        """Current chain qualification + memory-only resource lookup. Never I/O."""
        if self.resources is None:return None
        from calibre_plugins.manganana.books.imaging.artwork_cache import resource_identity
        for candidate in self.candidates(url,provider):
            variants=self._display_candidates(candidate)
            for variant in variants:
                value=self.resources.peek(resource_identity(variant)[0])
                if value:return self._display_result(candidate,value)
            if not all(self.resources.rejected(resource_identity(v)[0])for v in variants):return None
        return None

    def resolve_display_url(self,url,provider,cancelled=None):
        """Display renditions are separate resources; output still resolves full art."""
        if self.resources is None:return self.resolve_url(url,provider,cancelled)
        from calibre_plugins.manganana.books.imaging.artwork_cache import ResourceFailure
        check=cancelled or(lambda:False);failures=[]
        hit=self.peek_display(url,provider)
        if hit:
            if check():raise InterruptedError()
            value=self.resources.peek(hit['resource_key'])
            if value:
                try:return self._display_result(hit['candidate'],value,decode=True)
                except ResourceFailure as exc:self.resources.reject(value.key,str(exc))
        for candidate in self.candidates(url,provider):
            for variant in self._display_candidates(candidate):
                if check():raise InterruptedError()
                value=None
                try:
                    value=self.resources.acquire(variant,lambda:self._fetch(variant,provider),prepare_artwork,check)
                    return self._display_result(candidate,value,failures,decode=True)
                except ResourceFailure as exc:
                    if value is not None:self.resources.reject(value.key,str(exc))
                    failures.append((candidate.source,str(exc)))
        return dict(raw=None,candidate=None,failures=tuple(failures))

    def has_validated_url(self, url, provider):
        chain=self.candidates(url,provider)
        with self.lock:
            for candidate in chain:
                if candidate.key in self.valid and self.clock()-self.valid_at.get(candidate.key,float('-inf')) < 3600:
                    self.winners[candidate.volume or candidate.url]=candidate
                    while len(self.winners)>256:self.winners.popitem(last=False)
                    return True
                rejected=self.negative.get(candidate.key)
                if not rejected or self.clock()-rejected[0]>=60:
                    return False
            return False

    def clear_manifest(self):
        """Drop active evidence on selection, retaining bounded identity-keyed bytes."""
        with self.lock:
            self.chains.clear()

    def candidates(self, url, provider):
        with self.lock:
            return self.chains.get(url) or ((candidate_for_url(url, provider),) if url else ())

    def retry_failed_url(self, url, provider):
        """Explicit user retry: retain valid bytes and accepted candidate chains."""
        chain = self.candidates(url, provider)
        with self.lock:
            for candidate in chain:
                self.negative.pop(candidate.key, None)
                if self.resources:
                    from calibre_plugins.manganana.books.imaging.artwork_cache import resource_identity
                    for variant in self._display_candidates(candidate):self.resources.retry(resource_identity(variant)[0])

    def resolve_url(self, url, provider, cancelled=None, log=None):
        return self.resolve(self.candidates(url, provider), provider, cancelled, log)

    def winner_for_url(self, url, provider):
        chain = self.candidates(url, provider)
        with self.lock:
            winner = self.winners.get(chain[0].volume or chain[0].url) if chain else None
            return winner if winner in chain else None

    def resolve(self, candidates, provider, cancelled=None, log=None):
        check = cancelled or (lambda: False)
        failures = []
        for candidate in candidates:
            if check():
                raise InterruptedError()
            with self.lock:
                raw = self.valid.get(candidate.key)
                if raw and self.clock()-self.valid_at.get(candidate.key,float('-inf')) >= 3600:
                    self.valid.pop(candidate.key,None);self.valid_at.pop(candidate.key,None);raw=None
                rejected = self.negative.get(candidate.key)
            reason = rejected[1] if rejected and self.clock() - rejected[0] < 60 else ''
            if not raw and not reason:
                try:
                    if self.resources is not None:
                        value=self.resources.acquire(candidate,lambda:self._fetch(candidate,provider),prepare_artwork,check)
                        raw=value.raw
                    elif candidate.source in ('mangadex_artwork', 'mangadex'):
                        # Same transport as normal MangaDex artwork: UA + Accept,
                        # no acquisition Referer/Origin/cookie state, one attempt.
                        raw = self.mangadex.fetch_binary(candidate.url, timeout=14, retries=1)
                    elif candidate.source in ('bookwalker', 'google_books'):
                        raw = self.reference_fetch(candidate.url)
                    elif candidate.source in ('provider', getattr(provider, 'source_id', 'provider')):
                        raw = provider.fetch_binary(candidate.url, timeout=14, retries=1)
                    else:
                        reason = 'unavailable artwork source'
                    if check():
                        raise InterruptedError()
                    reason = reason or (validate_artwork(raw)if self.resources is None else '')
                except InterruptedError:
                    raise
                except Exception as exc:
                    reason = str(exc)if isinstance(exc,ResourceFailure)else'fetch failed'
            if check():
                raise InterruptedError()
            if reason:
                failures.append((candidate.source, reason))
                with self.lock:
                    if not rejected or self.clock() - rejected[0] >= 60:
                        self.negative[candidate.key] = (self.clock(), reason)
                    self.negative.move_to_end(candidate.key)
                    while len(self.negative) > 256:
                        self.negative.popitem(last=False)
                continue
            with self.lock:
                self.negative.pop(candidate.key, None)
                self.valid[candidate.key] = raw
                self.valid_at[candidate.key] = self.clock()
                self.valid.move_to_end(candidate.key)
                while self.valid and sum(map(len, self.valid.values())) > 32 * 1024 * 1024:
                    key,_=self.valid.popitem(last=False);self.valid_at.pop(key,None)
                self.winners[candidate.volume or candidate.url] = candidate
                while len(self.winners)>256:self.winners.popitem(last=False)
            if failures and log:
                rejected_sources = ', '.join(f'{source}: {reason}' for source, reason in failures)
                log(f'Artwork Vol.{candidate.volume or "?"}: {rejected_sources}; {candidate.source} fallback accepted.')
            return dict(raw=raw, candidate=candidate, failures=tuple(failures))
        if failures and log:
            log('Volume artwork unavailable: all candidates failed validation or delivery.')
        return dict(raw=None, candidate=None, failures=tuple(failures))
