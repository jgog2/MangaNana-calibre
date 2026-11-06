"""Official-release selection and bounded transport; no Qt or downloaded code execution."""
import ast
import hashlib
import io
import json
import re
import time
import urllib.request
from urllib.parse import urlparse
from pathlib import PurePosixPath
from zipfile import ZipFile

REPOSITORY = 'jgog2/MangaNana-calibre'
API_URL = 'https://api.github.com/repos/' + REPOSITORY + '/releases?per_page=50'
MAX_DOWNLOAD = 64 * 1024 * 1024
STABLE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')


def stable_version(value):
    match = STABLE.fullmatch(str(value))
    return tuple(map(int, match.groups())) if match else None


def current_version(value):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:[-+]([\w.-]+))?', value)
    if not match:
        raise ValueError('Unrecognized installed version')
    return tuple(map(int, match.groups()[:3])), bool(match[4] and '-' in value)


def official_asset_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.netloc == 'github.com'
        and parsed.path.startswith('/' + REPOSITORY + '/releases/download/')
        and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment)


def select_release(releases, installed):
    current, prerelease = current_version(installed)
    candidates = []
    if not isinstance(releases, list):
        raise ValueError('GitHub returned an invalid release list')
    for row in releases:
        version = stable_version(row.get('tag_name'))
        if (not version or row.get('draft') or row.get('prerelease') or
                version < current or (version == current and not prerelease)):
            continue
        assets = [a for a in row.get('assets', []) if
            re.match(r'^Manga(?:Nana|Anka|Ankā)[-_].*\.zip$', a.get('name', ''), re.I)
            and not re.search(r'(?:test|beta|alpha|\bdev\b|source)', a.get('name', ''), re.I)
            and official_asset_url(a.get('browser_download_url', ''))
            and 0 < int(a.get('size') or 0) <= MAX_DOWNLOAD]
        candidates.append((version, row, assets))
    if not candidates:
        return None
    version, row, assets = max(candidates, key=lambda v: v[0])
    if len(assets) != 1:
        raise ValueError('The newest official release has no unique installable plugin ZIP. Check its GitHub release page.')
    asset = assets[0]
    return dict(version='.'.join(map(str, version)), url=asset['browser_download_url'],
        size=int(asset['size']), digest=asset.get('digest') or '', tag=row['tag_name'],
        notes_url='https://github.com/' + REPOSITORY + '/releases/tag/' + row['tag_name'])


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != 'https' or parsed.netloc not in ('github.com', 'api.github.com',
                'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
            raise ValueError('Unexpected release download redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit, cancelled=lambda: False):
    if url != API_URL and not official_asset_url(url):
        raise ValueError('Not an official release URL')
    request = urllib.request.Request(url, headers={'User-Agent': 'MangaAnka-release-check',
        'Accept': 'application/vnd.github+json' if url == API_URL else 'application/octet-stream',
        'X-GitHub-Api-Version': '2022-11-28'})
    opener = urllib.request.build_opener(OfficialRedirects())
    started = time.monotonic()
    with opener.open(request, timeout=20) as response:
        length = int(response.headers.get('Content-Length') or 0)
        if length > limit:
            raise ValueError('Release response exceeds size limit')
        chunks, size = [], 0
        while True:
            if cancelled():
                raise InterruptedError('Update cancelled')
            if time.monotonic() - started > 120:
                raise TimeoutError('Release download timed out')
            chunk = response.read(min(65536, limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise ValueError('Release response exceeds size limit')
            chunks.append(chunk)
    return b''.join(chunks)


def check_release(installed, cancelled=lambda: False):
    raw = fetch(API_URL, 2 * 1024 * 1024, cancelled)
    return select_release(json.loads(raw), installed)


def assignments(raw):
    tree = ast.parse(raw.decode('utf-8-sig'))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    return tree, values


def validate_package(raw, release):
    if len(raw) != release['size'] or len(raw) > MAX_DOWNLOAD:
        raise ValueError('Downloaded release size does not match GitHub metadata')
    digest = release.get('digest', '')
    if digest:
        if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest) or hashlib.sha256(raw).hexdigest() != digest[7:].lower():
            raise ValueError('Release checksum does not match GitHub metadata')
    with ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 2048:
            raise ValueError('Invalid plugin archive entries')
        if sum(i.file_size for i in archive.infolist()) > 128 * 1024 * 1024:
            raise ValueError('Plugin archive expands beyond the size limit')
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe plugin archive path')
        for name in ('__init__.py', 'version_info.py', 'ui.py', 'plugin-import-name-manganana.txt'):
            if name not in names:
                raise ValueError('Release is not a MangaAnka plugin archive')
        if any(archive.getinfo(n).file_size > 256 * 1024 for n in ('__init__.py', 'version_info.py')):
            raise ValueError('Oversized plugin identity metadata')
        _, version = assignments(archive.read('version_info.py'))
        expected = stable_version(release['version'])
        if not expected or version.get('SEMANTIC_VERSION') != release['version'] or version.get('CALIBRE_VERSION') != expected:
            raise ValueError('Plugin version does not match the official release')
        tree, _ = assignments(archive.read('__init__.py'))
        identities = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                values = {}
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and isinstance(item.value, ast.Constant):
                                values[target.id] = item.value.value
                identities.append(values)
        if not any(v.get('name') == 'MangaNana' and v.get('actual_plugin') ==
                'calibre_plugins.manganana.ui:MangaNanaAction' for v in identities):
            raise ValueError('Plugin identity does not match MangaAnka')
        if archive.testzip() is not None:
            raise ValueError('Plugin archive is damaged')
    return raw


def download_release(release, cancelled=lambda: False):
    return validate_package(fetch(release['url'], MAX_DOWNLOAD, cancelled), release)
