"""Public emblem JSON and Drive image cache, independent of the raid catalog."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
from .drive import DriveError
from .emblem_cache import EmblemCache
from .public_content import ContentError, FOLDER_MIME, MAX_BYTES, parse_json

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_IMAGES = 500
IMAGE_TYPES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp',
               'image/gif': '.gif', 'image/svg+xml': '.svg', 'image/bmp': '.bmp'}


def validate_emblems(value):
    if (not isinstance(value, dict) or not 1 <= len(value) <= 500
            or any(not isinstance(k, str) or not k.strip() or len(k) > 200
                   or not isinstance(v, str) or not v.strip() or len(v) > 2048
                   or any(ord(c) < 32 for c in k + v) for k, v in value.items())):
        raise ContentError('문양 JSON에는 직업명과 이미지 경로 문자열이 필요합니다.')
    return value


class PublicAssetCache:
    """Immutable file versions; publish the index only after a successful refresh."""
    def __init__(self, directory, settings):
        self.directory = Path(directory) / 'public-content'
        self.path = self.directory / 'assets-cache.json'
        self.settings = settings
        self.emblem_cache = EmblemCache(self.directory, settings['emblemBaseUrl']) if settings.get('emblemBaseUrl') else None

    def _source(self):
        return dict(rootFolderID=self.settings['rootFolderID'],
                    emblemFileName=self.settings.get('emblemFileName', 'EmblemJSON.json'),
                    imagesFolderName=self.settings.get('imagesFolderName', 'Images'))

    def file_path(self, item):
        # Local filenames depend only on validated Drive ID/checksum, never remote names.
        metadata = item['metadata']
        identity, checksum = metadata.get('id'), metadata.get('md5Checksum')
        if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identity)
                or not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{32}', checksum)):
            raise ContentError('공용 파일의 ID 또는 무결성 정보를 확인하지 못했습니다.')
        suffix = '.json' if item['kind'] == 'json' else IMAGE_TYPES.get(metadata.get('mimeType'))
        if suffix is None:
            raise ContentError('지원하지 않는 공용 이미지 형식입니다.')
        folder = 'JSON' if item['kind'] == 'json' else 'Images'
        target = self.directory / 'assets' / folder / (identity + '-' + checksum + suffix)
        if not target.resolve().is_relative_to(self.directory.resolve()):
            raise ContentError('공용 파일 보관 경로를 확인해주세요.')
        return target

    def _body(self, item):
        try:
            path = self.file_path(item)
            limit = MAX_BYTES if item['kind'] == 'json' else MAX_IMAGE_BYTES
            with path.open('rb') as stream:
                body = stream.read(limit + 1)
            if len(body) > limit or hashlib.md5(body).hexdigest() != item['metadata']['md5Checksum']:
                return None
            return body
        except OSError:
            return None

    def load(self):
        if not self.path.exists():
            return None
        try:
            with self.path.open('rb') as stream:
                value = parse_json(stream.read(MAX_BYTES + 1))
            if not isinstance(value, dict) or value.get('schemaVersion') != 1 or value.get('source') != self._source():
                raise ValueError()
            validate_emblems(value['emblem']['content'])
            if not isinstance(value['images'], list) or len(value['images']) > MAX_IMAGES:
                raise ValueError()
            total = 0
            for item in [value['emblem']] + value['images']:
                body = self._body(item)
                if body is None:
                    raise ValueError()
                if item.get('path') != self.file_path(item).relative_to(self.directory).as_posix():
                    raise ValueError()
                total += len(body)
            if value.get('emblems') is not None and self.emblem_cache:
                total += self.emblem_cache.validate(value['emblem']['content'], value['emblems'], value.get('emblemErrors'))
            if total > MAX_TOTAL_BYTES or parse_json(self._body(value['emblem'])) != value['emblem']['content']:
                raise ValueError()
            return value
        except (OSError, ValueError, KeyError, TypeError, ContentError):
            raise ContentError('보관된 문양·이미지 데이터를 확인하지 못했습니다. 다시 갱신해주세요.') from None

    @staticmethod
    def _unique(items, name, folder=False):
        matches = [item for item in items if item['name'] == name
                   and (not folder or item.get('mimeType') == FOLDER_MIME)]
        if len(matches) != 1:
            raise ContentError('공용 폴더에 ' + name + ' 항목이 없거나 중복됩니다.')
        return matches[0]

    def _images(self, client, folder_id):
        images, folders, seen, names = [], [(folder_id, '', 0)], set(), set()
        while folders:
            identity, prefix, depth = folders.pop()
            if identity in seen or depth > 8 or len(seen) >= 100:
                raise ContentError('공용 이미지 폴더가 너무 깊거나 반복됩니다.')
            seen.add(identity)
            for metadata in client.children(identity):
                name = metadata['name']
                if not name or name in ('.', '..') or any(c in name for c in '/\\') or any(ord(c) < 32 for c in name):
                    raise ContentError('공용 이미지 이름을 확인해주세요.')
                logical_name = prefix + name
                if logical_name.casefold() in names:
                    raise ContentError('공용 이미지 이름이 중복됩니다.')
                names.add(logical_name.casefold())
                mime = metadata.get('mimeType')
                if mime == FOLDER_MIME:
                    folders.append((metadata['id'], logical_name + '/', depth + 1))
                elif mime in IMAGE_TYPES:
                    images.append(dict(kind='image', name=logical_name, metadata=metadata))
                    if len(images) > MAX_IMAGES:
                        raise ContentError('공용 이미지 파일이 너무 많습니다.')
        return sorted(images, key=lambda item: item['name'])

    @staticmethod
    def _write(path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
        try:
            temporary.write_bytes(body)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def prepare(self, client):
        """Download/verify versions in a worker; cancellation never publishes an index."""
        source = self._source()
        root = client.children(source['rootFolderID'])
        json_folder = self._unique(root, self.settings['jsonFolderName'], True)
        image_folder = self._unique(root, source['imagesFolderName'], True)
        emblem_metadata = self._unique(client.children(json_folder['id']), source['emblemFileName'])
        if emblem_metadata.get('mimeType') not in ('application/json', 'text/plain', 'application/octet-stream'):
            raise ContentError('문양 데이터는 JSON 파일이어야 합니다.')
        emblem = dict(kind='json', name=source['emblemFileName'], metadata=emblem_metadata)
        images = self._images(client, image_folder['id'])
        total, downloaded = 0, 0
        for item in [emblem] + images:
            client.api.check_cancelled()
            path = self.file_path(item)
            limit = MAX_BYTES if item['kind'] == 'json' else MAX_IMAGE_BYTES
            try:
                advertised = int(item['metadata']['size'])
                if advertised < 0 or advertised > limit:
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise ContentError('공용 파일의 크기 정보를 확인해주세요.') from None
            if total + advertised > MAX_TOTAL_BYTES:
                raise ContentError('공용 문양·이미지 전체 크기 제한을 초과합니다.')
            body = self._body(item)
            if body is None:
                try:
                    body = client.api.files.download(item['metadata']['id'], max_bytes=limit)
                except DriveError as error:
                    raise client._content_error(error) from None
                if len(body) != advertised or hashlib.md5(body).hexdigest() != item['metadata']['md5Checksum']:
                    raise ContentError('조회 중 공용 문양·이미지 파일이 변경되었습니다.')
                if item['kind'] == 'json':
                    validate_emblems(parse_json(body))
                client.api.check_cancelled()
                self._write(path, body)
                downloaded += 1
            if len(body) != advertised:
                raise ContentError('공용 파일의 크기 정보가 내용과 다릅니다.')
            if item['kind'] == 'json':
                item['content'] = validate_emblems(parse_json(body))
            total += len(body)
            item['path'] = path.relative_to(self.directory).as_posix()
        client.api.check_cancelled()
        result = dict(schemaVersion=1, source=source, checkedAt=datetime.now(timezone.utc).isoformat(),
                      emblem=emblem, images=images, downloadedFiles=downloaded)
        if self.emblem_cache:
            # Salvage validators for valid files even if another cached SVG is missing.
            previous = None
            try:
                with self.path.open('rb') as stream:
                    saved = parse_json(stream.read(MAX_BYTES + 1))
                if isinstance(saved, dict) and saved.get('source') == source:
                    previous = saved
            except (OSError, ContentError):
                pass
            entries, count, errors = self.emblem_cache.prepare(emblem['content'],
                (previous or {}).get('emblems'), cancel=client.cancel, max_bytes=MAX_TOTAL_BYTES - total)
            result.update(emblems=entries, downloadedEmblems=count, emblemErrors=errors)
        return result

    def save(self, result):
        if result.get('source') != self._source():
            raise ContentError('공용 문양·이미지 보관 대상이 다릅니다.')
        validate_emblems(result['emblem']['content'])
        for item in [result['emblem']] + result['images']:
            if self._body(item) is None:
                raise ContentError('공용 문양·이미지 보관 파일을 검증하지 못했습니다.')
        if self.emblem_cache and result.get('emblems') is not None:
            self.emblem_cache.validate(result['emblem']['content'], result['emblems'], result.get('emblemErrors'))
        body = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(body) > MAX_BYTES:
            raise ContentError('공용 문양·이미지 목록이 너무 큽니다.')
        self._write(self.path, body)

    def emblem_path(self, job, bundle=None):
        """Resolve a profession to a verified local SVG without a network request."""
        bundle = self.load() if bundle is None else bundle
        return self.emblem_cache.for_job(job, (bundle or {}).get('emblems')) if self.emblem_cache else None

    def image_path(self, name, bundle=None):
        """Resolve an exact logical image name to a verified local version; never fetch."""
        try:
            bundle = self.load() if bundle is None else bundle
            if not bundle or bundle.get('source') != self._source():
                return None
            matches = [item for item in bundle.get('images', []) if item.get('name') == name]
            if len(matches) != 1 or self._body(matches[0]) is None:
                return None
            return str(self.file_path(matches[0]).resolve())
        except (OSError, ValueError, KeyError, TypeError, ContentError):
            return None
