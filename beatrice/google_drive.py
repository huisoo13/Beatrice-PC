"""One PC-owned JSON file, with a local recovery copy before replacement."""
import json
import secrets
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .drive_data import MAX_BYTES, decode_records, encode_records

API = 'https://www.googleapis.com/drive/v3/files'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
PROPERTY = 'beatriceRecords'
VERSION = 'v1'


class DriveError(Exception):
    pass


class DriveClient:
    def __init__(self, access_token, cancel, opener=None, namespace=VERSION, backup_directory=None):
        self.access_token = access_token
        self.cancel = cancel
        self.opener = opener or urlopen
        if namespace not in (VERSION, 'integration-test'):
            raise ValueError('지원하지 않는 Drive 저장 영역입니다.')
        self.namespace = namespace
        self.backup_directory = Path(backup_directory) if backup_directory is not None else None

    def request(self, url, method='GET', body=None, content_type=None):
        if self.cancel.is_set():
            raise DriveError('Drive 작업을 취소했습니다.')
        headers = {'Authorization': 'Bearer ' + self.access_token}
        if content_type:
            headers['Content-Type'] = content_type
        try:
            with self.opener(Request(url, data=body, headers=headers, method=method), timeout=20) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise DriveError('Drive 파일이 허용 크기(4 MiB)를 초과합니다.')
                return data
        except HTTPError as exc:
            messages = {
                401: 'Google 인증이 만료되었습니다. 로그아웃 후 다시 로그인해주세요.',
                403: 'Drive 접근이 거부되었습니다. Drive 권한 동의와 Google Cloud의 Drive API 사용 설정을 확인해주세요.',
                404: 'Drive 파일을 찾을 수 없습니다. 다시 불러와주세요.',
                429: 'Drive 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.',
            }
            raise DriveError(messages.get(exc.code, 'Drive 요청에 실패했습니다. 잠시 후 다시 시도해주세요.')) from None
        except (URLError, OSError):
            raise DriveError('Drive 연결이 끊겼습니다. 저장 결과를 불러오기로 확인한 뒤 다시 시도해주세요.') from None

    def json_request(self, *args, **kwargs):
        try:
            result = json.loads(self.request(*args, **kwargs))
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeError):
            raise DriveError('Drive 서버 응답이 올바르지 않습니다.') from None

    def latest(self):
        parameters = dict(spaces='appDataFolder',
            q=f"trashed = false and appProperties has {{ key='{PROPERTY}' and value='{self.namespace}' }}",
            orderBy='createdTime desc', pageSize=1,
            fields='nextPageToken,files(id,name,createdTime,modifiedTime,size,mimeType,appProperties)')
        if self.namespace == VERSION:
            parameters['q'] += " and name = 'PC.json'"
        seen = set()
        while True:
            response = self.json_request(API + '?' + urlencode(parameters))
            files = response.get('files', [])
            if not isinstance(files, list):
                raise DriveError('Drive 파일 목록이 올바르지 않습니다.')
            if files:
                return files[0]
            token = response.get('nextPageToken')
            if not token:
                return None
            if not isinstance(token, str) or token in seen or len(seen) >= 100:
                raise DriveError('Drive 파일 목록을 완료하지 못했습니다. 다시 시도해주세요.')
            seen.add(token)
            parameters['pageToken'] = token

    def read(self, metadata):
        if not isinstance(metadata, dict) or not isinstance(metadata.get('id'), str):
            raise DriveError('Drive 파일 정보가 올바르지 않습니다.')
        if metadata.get('mimeType') != 'application/json':
            raise DriveError('지원하지 않는 Drive 파일 형식입니다.')
        if metadata.get('appProperties', {}).get('schemaVersion', '1') not in ('1', '2', '3'):
            raise DriveError('더 새로운 앱에서 만든 파일입니다. 앱을 업데이트해주세요.')
        body = self.request(API + '/' + quote(metadata['id'], safe='') + '?alt=media')
        return decode_records(body)

    def download(self):
        metadata = self.latest()
        if metadata is None:
            raise DriveError('이 Google 계정에 저장된 Beatrice 기록이 없습니다.')
        return dict(metadata=metadata, records=self.read(metadata))

    def upload(self, records):
        body = encode_records(records)
        boundary = 'beatrice_' + secrets.token_hex(24)
        previous = self.latest() if self.namespace == VERSION else None
        if previous:
            if self.backup_directory is None:
                raise DriveError('기존 PC 파일을 보존할 로컬 백업 경로가 필요합니다.')
            old_body = encode_records(self.read(previous))
            self.backup_directory.mkdir(parents=True, exist_ok=True)
            backup = self.backup_directory / ('PC-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(8) + '.json')
            with backup.open('xb') as recovery:
                recovery.write(old_body)
            if backup.read_bytes() != old_body:
                raise DriveError('기존 PC 기록의 백업을 검증하지 못했습니다.')
        metadata = dict(name='PC.json' if self.namespace == VERSION else 'beatrice-records-' + self.namespace + '-' + secrets.token_hex(16) + '.json',
                        mimeType='application/json', parents=['appDataFolder'],
                        appProperties={PROPERTY: self.namespace, 'schemaVersion': '3'})
        if previous:
            metadata.pop('parents')
        multipart = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
                     + json.dumps(metadata).encode() +
                     f'\r\n--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
                     + body + f'\r\n--{boundary}--\r\n'.encode())
        target = UPLOAD + ('/' + quote(previous['id'], safe='') if previous else '')
        uploaded = self.json_request(target + '?uploadType=multipart&fields=id,name,createdTime,modifiedTime,mimeType,appProperties',
                                     method='PATCH' if previous else 'POST', body=multipart,
                                     content_type='multipart/related; boundary=' + boundary)
        # Re-read the exact PC file; iOS must only read this file.
        if self.read(uploaded) != decode_records(body):
            raise DriveError('Drive에 저장한 내용의 검증에 실패했습니다. 다시 불러와 확인해주세요.')
        return uploaded
