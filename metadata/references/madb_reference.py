"""Bounded, edition-sensitive Japanese publication bibliography. No acquisition."""
from concurrent.futures import CancelledError
from dataclasses import asdict, dataclass
import json
import re
import threading
import time
import urllib.parse
import urllib.request

from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text, creator_comparison_identity
from calibre_plugins.manganana.publication.publication_manifest import normalize_publication_number

ENDPOINT = 'https://mediaarts-db.artmuseums.go.jp/sparql'
CACHE_CONTRACT = 'madb-publication-v1'
MATCHER_CONTRACT = 'canonical-titles-neutral-script-v2'
LABEL = 'http://www.w3.org/2000/01/rdf-schema#label'
SCHEMA = 'https://schema.org/'
PREFIX = '''PREFIX schema: <https://schema.org/>
PREFIX class: <https://mediaarts-db.artmuseums.go.jp/data/class#>
PREFIX ma: <https://mediaarts-db.artmuseums.go.jp/data/property#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
'''
FIELDS = '''schema:identifier schema:name rdfs:label schema:creator schema:publisher
schema:brand schema:version schema:alternateName schema:inLanguage schema:volumeNumber
schema:isbn schema:datePublished schema:numberOfPages ma:originalWorkCreator'''
_ALTERNATE = re.compile(
    r'文庫|ムック|愛蔵|完全収録|完全版|総集編|劇場版|アニメ|クイズ|真説|新装|改訂|カラー|'
    r'\b(?:sjr|deluxe|omnibus|collector|color|colour|logbook|animation|for beginners)\b', re.I)
_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


def _literal(value):
    value = str(value)
    if len(value) > 300: raise ValueError('MADB title exceeds the bounded query limit.')
    return json.dumps(value, ensure_ascii=False)


def candidate_query(titles):
    terms = tuple(dict.fromkeys(str(t).strip() for t in titles if str(t).strip()))[:8]
    if not terms: raise ValueError('No trusted title evidence.')
    return PREFIX + '''SELECT ?series ?property ?value WHERE {
 { SELECT DISTINCT ?series WHERE {
 VALUES ?term { %s }
 VALUES ?titleField { schema:name schema:alternateName rdfs:label }
 ?series a class:MangaBookSeries; ?titleField ?name .
 FILTER(LCASE(STR(?name))=LCASE(?term))
 } LIMIT 21 }
 VALUES ?property { %s }
 ?series ?property ?value
} LIMIT 1001''' % (' '.join(_literal(t) for t in terms), FIELDS)


def inventory_query(series_id):
    if not re.fullmatch(r'C[0-9]+', series_id): raise ValueError('Invalid MADB series ID.')
    return PREFIX + '''SELECT ?book ?property ?value WHERE {
 { SELECT DISTINCT ?book WHERE {
 ?book a class:MangaBook; schema:isPartOf <https://mediaarts-db.artmuseums.go.jp/id/%s> .
 } LIMIT 251 }
 VALUES ?property { %s }
 ?book ?property ?value
} LIMIT 6001''' % (series_id, FIELDS)


def _records(payload, variable, limit):
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), dict):
        raise ValueError('Malformed MADB SPARQL result.')
    rows = payload['results'].get('bindings')
    if not isinstance(rows, list): raise ValueError('Malformed MADB bindings.')
    if len(rows) >= limit: raise ValueError('MADB query reached its bounded result limit.')
    grouped = {}
    for row in rows:
        try:
            uri = row[variable]['value']; prop = row['property']['value']; value = row['value']['value']
            if row[variable]['type'] != 'uri' or row['property']['type'] != 'uri': raise ValueError()
            prefix = 'C' if variable == 'series' else 'M'
            if not re.fullmatch(r'https://mediaarts-db\.artmuseums\.go\.jp/id/' + prefix + r'\d+', uri): raise ValueError()
            if not isinstance(value, str): raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('Malformed MADB record.') from None
        values = grouped.setdefault(uri.rsplit('/',1)[-1], {}).setdefault(prop, [])
        if value not in values: values.append(value)
    if len(grouped) >= (21 if variable == 'series' else 251):
        raise ValueError('MADB record limit reached.')
    return grouped


def _values(record, *names):
    return tuple(dict.fromkeys(v for name in names for v in record.get(SCHEMA + name, ())))


def _creators(record):
    values = list(_values(record, 'creator')) + record.get(
        'https://mediaarts-db.artmuseums.go.jp/data/property#originalWorkCreator', [])
    return tuple(re.sub(r'^(?:\[[^]]+\]\s*)+', '', v).strip() for v in values
                 if not re.match(r'^\[+(?:編|編集)', v))


def _edition_ok(record):
    text = ' '.join((*_values(record, 'name','alternateName','brand','version'), *record.get(LABEL, ())))
    return not _ALTERNATE.search(text)


def _creator_contradiction(trusted, actual):
    def script(value):
        return 'ja' if re.search(r'[\u3040-\u30ff\u3400-\u9fff]', value) else 'other'
    identities = {creator_comparison_identity(c) for c in actual}
    return any(any(script(c) == script(a) for a in actual) and
               creator_comparison_identity(c) not in identities for c in trusted)


def trusted_titles(evidence):
    # Explicitly separated canonical aliases win, including an intentionally empty pool.
    aliases = evidence.get('canonical_aliases', evidence.get('aliases', ())) or ()
    return tuple(dict.fromkeys(str(t).strip() for t in (
        evidence.get('canonical_title') or evidence.get('title') or '', *aliases
    ) if str(t).strip()))[:8]


def creator_relationship(trusted, actual):
    if _creator_contradiction(trusted, actual): return 'CONTRADICTION'
    if {creator_comparison_identity(c) for c in trusted}.intersection(
            creator_comparison_identity(c) for c in actual): return 'MATCH'
    return 'INCOMPARABLE_SCRIPT' if trusted and actual else 'MISSING'


def title_evidence(fields, trusted):
    return tuple({'field':field, 'value':value} for field in (SCHEMA+'name', SCHEMA+'alternateName', LABEL)
                 for value in fields.get(field, ()) if normalize_identity_text(value) in trusted)


@dataclass(frozen=True)
class MadbVolumeRecord:
    madb_id: str
    uri: str
    number: str
    raw_number: str
    titles: tuple
    isbn: tuple
    publishers: tuple
    brands: tuple
    dates: tuple
    page_counts: tuple
    versions: tuple
    source: str = 'madb'


def _book(ident, fields):
    raw = _values(fields, 'volumeNumber')
    # Conflicting explicit labels remain unresolved; never use schema:position.
    label = raw[0] if len(raw) == 1 else ''
    match = re.fullmatch(r'\s*(?:第|巻|vol(?:ume)?\.?|v\.?)?\s*(\d+(?:\.\d+)?)\s*(?:巻|卷)?\s*', label, re.I)
    number = normalize_publication_number(match.group(1)) if match else ''
    return MadbVolumeRecord(ident, 'https://mediaarts-db.artmuseums.go.jp/id/'+ident,
                            number or '', ' | '.join(raw), _values(fields,'name','alternateName'),
                            _values(fields,'isbn'), _values(fields,'publisher'), _values(fields,'brand'),
                            _values(fields,'datePublished'), _values(fields,'numberOfPages'), _values(fields,'version'))


class MadbPublicationAdapter:
    def __init__(self, request_json=None):
        self._injected = request_json
        self._cancel = lambda: False
        self.request_count = 0

    def set_cancel_check(self, callback): self._cancel = callback

    def _check(self):
        if self._cancel(): raise CancelledError()

    def _request(self, query):
        global _LAST_REQUEST
        self._check()
        if self._injected:
            self.request_count += 1
            result = self._injected(query)
            self._check()
            return result
        with _LOCK:
            while time.monotonic() - _LAST_REQUEST < 1.5:
                self._check(); time.sleep(.05)
            self._check(); self.request_count += 1; _LAST_REQUEST = time.monotonic()
            request = urllib.request.Request(ENDPOINT,
                data=urllib.parse.urlencode({'query':query}).encode(),
                headers={'Accept':'application/sparql-results+json',
                         'Content-Type':'application/x-www-form-urlencoded',
                         'User-Agent':'MangaNana/0.14 MADB publication reference'})
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read(2_000_001)
            self._check()
            if len(data) > 2_000_000: raise ValueError('MADB response size limit reached.')
            return json.loads(data.decode('utf-8'))

    def resolve(self, evidence):
        self.request_count = 0; self._check()
        base = {'source':'madb','cache_contract':CACHE_CONTRACT,'market':'JP','language':'ja',
                'books':[], 'network':{'requests':0}}
        def result(status, reason, **extra):
            return dict(base, status=status, reason=reason, network={'requests':self.request_count}, **extra)
        if evidence.get('identity_confidence') != 'high' or not evidence.get('reference_key'):
            return result('insufficient_evidence','Trusted canonical context is required.')
        edition = evidence.get('edition_profile') or evidence.get('edition')
        if edition not in ('standard','original'):
            return result('incompatible_edition','Only standard Japanese publication bibliography is supported.')
        creators = tuple(evidence.get('creators') or ())
        if not creators: return result('insufficient_evidence','Trusted creator evidence is required.')
        titles = trusted_titles(evidence)
        candidates = _records(self._request(candidate_query(titles)), 'series', 1001)
        trusted = {normalize_identity_text(t) for t in titles if t}
        accepted = []; reasons = []
        for ident, fields in candidates.items():
            self._check()
            if not title_evidence(fields, trusted): continue
            if not _edition_ok(fields): reasons.append('alternate edition or supplementary publication'); continue
            if _values(fields,'inLanguage') != ('日本語',): reasons.append('unconfirmed Japanese publication'); continue
            actual = _creators(fields)
            if creator_relationship(creators, actual) == 'CONTRADICTION':
                reasons.append('material creator contradiction'); continue
            if not actual:
                reasons.append('publication creator evidence missing'); continue
            # An explicit regular comic label supplies publication evidence beyond a title/author pair.
            if not any(re.search(r'コミック|\bcomics?\b|\bcomix\b|^MFC$', b, re.I) for b in _values(fields,'brand')):
                reasons.append('regular publication label unconfirmed'); continue
            accepted.append((ident, fields))
        if len(accepted) > 1: return result('ambiguous','Multiple compatible publication series remain.')
        if not accepted: return result('no_match' if not candidates else 'insufficient_evidence', '; '.join(sorted(set(reasons))) or 'No exact trusted title/alias found.')
        ident, fields = accepted[0]
        inventory = _records(self._request(inventory_query(ident)), 'book', 6001)
        if not inventory: return result('no_match','Selected series has no usable book records.')
        if any(not _edition_ok(book) for book in inventory.values()):
            return result('ambiguous','Book-level edition evidence conflicts with the selected standard collection.')
        if any(_creator_contradiction(creators, _creators(book)) or
               (_values(book,'inLanguage') and _values(book,'inLanguage') != ('日本語',))
               for book in inventory.values()):
            return result('ambiguous','Book-level creator or publication-language contradiction.')
        books = [asdict(_book(i, f)) for i, f in sorted(inventory.items())]
        if not any(book['number'] for book in books): return result('insufficient_evidence','No explicit numbered books.')
        match = {'source':'madb','series_id':ident,'series_uri':'https://mediaarts-db.artmuseums.go.jp/id/'+ident,
                 'title':next(iter(_values(fields,'name')), title_evidence(fields, trusted)[0]['value']), 'aliases':_values(fields,'name','alternateName'),
                 'creators':_creators(fields),'brands':_values(fields,'brand'),'publishers':_values(fields,'publisher'),
                 'confidence':'confident','edition_profile':'standard','market':'JP',
                 'title_evidence':title_evidence(fields, trusted),
                 'creator_relationship':creator_relationship(creators, _creators(fields)),
                 'creator_evidence_source':evidence.get('creator_provenance') or 'canonical',
                 'reason':'Unique exact trusted title/alias, no creator contradiction, regular Japanese comic label, explicit related books.'}
        return result('valid',match['reason'],match=match,books=books)
