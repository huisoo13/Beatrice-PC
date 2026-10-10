"""Read-only public Drive content. No OAuth, account tokens or game records."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import quote
from .drive import GoogleDriveClient, DriveError, DriveRateLimitError
from .drive.client import API
from .drive.folders import FOLDER_MIME

MAX_BYTES = 4 * 1024 * 1024


class ContentError(Exception):
    pass


def parse_json(body):
    if len(body) > MAX_BYTES:
        raise ContentError('공용 JSON이 허용 크기(4 MiB)를 초과합니다.')
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError()
            result[name] = value
        return result
    try:
        return json.loads(body.decode('utf-8-sig'), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError):
        raise ContentError('공용 데이터가 올바른 UTF-8 JSON이 아닙니다.') from None


def validate_content(content):
    def label(value):
        return isinstance(value, str) and 0 < len(value.strip()) <= 200 and not any(ord(c) < 32 for c in value)
    if not isinstance(content, dict) or not 1 <= len(content) <= 500:
        raise ContentError('공용 데이터에는 던전별 JSON 객체가 필요합니다.')
    count = 0
    for dungeon, modes in content.items():
        if not label(dungeon) or not isinstance(modes, dict) or not 1 <= len(modes) <= 30:
            raise ContentError('던전 또는 난이도 형식이 올바르지 않습니다.')
        for mode, gates in modes.items():
            if not label(mode) or not isinstance(gates, dict) or not 1 <= len(gates) <= 8:
                raise ContentError('난이도 또는 관문 형식이 올바르지 않습니다.')
            if set(gates) != {f'{i}관문' for i in range(1, len(gates) + 1)}:
                raise ContentError('공용 데이터의 관문은 1관문부터 순서대로 필요합니다.')
            for values in gates.values():
                if not isinstance(values, dict) or set(values) != {'gold', 'fee', 'bound_percentage'}:
                    raise ContentError('각 관문에는 gold, fee, bound_percentage가 필요합니다.')
                if any(type(values[k]) is not int or not 0 <= values[k] <= 10**12 for k in ('gold', 'fee')):
                    raise ContentError('gold와 fee는 0 이상의 정수여야 합니다.')
                ratio = values['bound_percentage']
                if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
                    raise ContentError('bound_percentage는 0~1 사이 숫자여야 합니다.')
                count += 1
    if count > 10000:
        raise ContentError('공용 관문 데이터가 너무 많습니다.')
    return content


def load_settings(root):
    try:
        value = json.loads((Path(root) / 'config/public-content.json').read_text(encoding='utf-8'))
        if not re.fullmatch(r'[A-Za-z0-9_-]+', value['rootFolderID']):
            raise ValueError()
        if not all(isinstance(value[k], str) and value[k] for k in ('jsonFolderName', 'fileName')):
            raise ValueError()
        value.setdefault('emblemFileName', 'EmblemJSON.json')
        value.setdefault('imagesFolderName', 'Images')
        value.setdefault('emblemBaseUrl', 'https://cdn-lostark.game.onstove.com')
        if not isinstance(value['emblemBaseUrl'], str) or value['emblemBaseUrl'].rstrip('/') != 'https://cdn-lostark.game.onstove.com':
            raise ValueError()
        if not all(isinstance(value[k], str) and value[k] for k in ('emblemFileName', 'imagesFolderName')):
            raise ValueError()
        if type(value['refreshSeconds']) is not int or value['refreshSeconds'] < 60:
            raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise ContentError('공용 데이터 설정 파일을 확인해주세요.') from None


def load_api_key(root):
    path = Path(os.environ.get('BEATRICE_DRIVE_API_KEY_FILE', str(Path(root) / 'google_drive_api_key.txt')))
    try:
        value = path.read_text(encoding='utf-8-sig').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,200}', value):
            raise ValueError()
        return value
    except (OSError, ValueError):
        raise ContentError('공용 데이터용 google_drive_api_key.txt 파일을 확인해주세요.') from None


class PublicContentClient:
    def __init__(self, api_key, settings, cancel, opener=None):
        self.api_key, self.settings, self.cancel = api_key, settings, cancel
        self.api = GoogleDriveClient(api_key=api_key, cancel=cancel, timeout=15, max_bytes=MAX_BYTES, opener=opener)

    @property
    def opener(self):
        return self.api.opener

    @opener.setter
    def opener(self, value):
        self.api.opener = value

    @staticmethod
    def _content_error(error):
        messages = {
            400: '공용 데이터 API 키 또는 요청 설정을 확인해주세요.',
            403: '공용 데이터 접근이 거부되었습니다. 공유 권한과 API 키 제한을 확인해주세요.',
            404: '공용 데이터 파일을 찾을 수 없습니다.',
            429: '공용 데이터 요청 한도에 도달했습니다. 나중에 다시 시도해주세요.',
        }
        if isinstance(error, DriveRateLimitError):
            return ContentError(messages[429])
        return ContentError(messages.get(error.status, str(error)))

    def get(self, suffix='', **parameters):
        try:
            return self.api.request(suffix, params=parameters)
        except DriveError as error:
            raise self._content_error(error) from None

    def children(self, folder):
        try:
            files = self.api.folders.children(folder)
        except DriveError as error:
            raise self._content_error(error) from None
        for item in files:
            if (not isinstance(item.get('name'), str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]+', item['id'])):
                raise ContentError('공용 파일 정보가 올바르지 않습니다.')
        return files

    def refresh(self, cached=None):
        folders = [f for f in self.children(self.settings['rootFolderID'])
                   if f['name'] == self.settings['jsonFolderName'] and f.get('mimeType') == FOLDER_MIME]
        if len(folders) != 1:
            raise ContentError('공개 폴더에 JSON 폴더가 없거나 같은 이름의 폴더가 여러 개입니다.')
        files = [f for f in self.children(folders[0]['id']) if f['name'] == self.settings['fileName']]
        if len(files) != 1:
            raise ContentError('JSON 폴더에 지정 파일이 없거나 같은 이름의 파일이 여러 개입니다.')
        metadata = files[0]
        if metadata.get('mimeType') not in ('application/json', 'text/plain', 'application/octet-stream'):
            raise ContentError('공용 데이터 파일은 JSON 파일이어야 합니다.')
        checksum = metadata.get('md5Checksum')
        if not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{32}', checksum):
            raise ContentError('공용 JSON 파일의 무결성 정보를 확인하지 못했습니다.')
        unchanged = (cached and cached.get('rootFolderID') == self.settings['rootFolderID']
                     and cached.get('fileName') == self.settings['fileName']
                     and cached.get('metadata', {}).get('id') == metadata['id']
                     and cached.get('metadata', {}).get('md5Checksum') == checksum)
        if unchanged:
            content = validate_content(cached['content'])
        else:
            body = self.get('/' + quote(metadata['id'], safe=''), alt='media')
            if hashlib.md5(body).hexdigest() != checksum:
                raise ContentError('조회 중 공용 파일이 변경되었습니다. 다시 시도해주세요.')
            content = validate_content(parse_json(body))
        return dict(rootFolderID=self.settings['rootFolderID'], fileName=self.settings['fileName'],
                    checkedAt=datetime.now(timezone.utc).isoformat(), metadata=metadata, content=content)


class ContentCache:
    def __init__(self, directory, settings):
        self.path = Path(directory) / 'public-content' / 'content-cache.json'
        self.settings = settings

    def load(self):
        if not self.path.exists():
            return None
        try:
            with self.path.open('rb') as stream:
                value = parse_json(stream.read(MAX_BYTES + 1))
            if (not isinstance(value, dict) or value.get('rootFolderID') != self.settings['rootFolderID']
                    or value.get('fileName') != self.settings['fileName'] or not isinstance(value.get('metadata'), dict)):
                raise ValueError()
            validate_content(value['content'])
            return value
        except (OSError, ValueError, KeyError, TypeError):
            raise ContentError('저장된 공용 데이터를 읽지 못했습니다. 다시 갱신해주세요.') from None

    def save(self, result):
        validate_content(result['content'])
        body = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(body) > MAX_BYTES:
            raise ContentError('공용 데이터 캐시가 허용 크기를 초과합니다.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        try:
            temporary.write_bytes(body)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
