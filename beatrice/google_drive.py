"""One PC-owned JSON file, with a local recovery copy before replacement."""
import secrets
from pathlib import Path
from datetime import datetime, timezone

from .drive_data import MAX_BYTES, decode_records, encode_records

from .drive import GoogleDriveClient, DriveError
from .drive.client import API, UPLOAD
PROPERTY = 'beatriceRecords'
VERSION = 'v1'


class DriveClient:
    def __init__(self, access_token, cancel, opener=None, namespace=VERSION, backup_directory=None):
        self.access_token = access_token
        self.cancel = cancel
        self.api = GoogleDriveClient(access_token=access_token, cancel=cancel, opener=opener, max_bytes=MAX_BYTES)
        if namespace not in (VERSION, 'integration-test'):
            raise ValueError('지원하지 않는 Drive 저장 영역입니다.')
        self.namespace = namespace
        self.backup_directory = Path(backup_directory) if backup_directory is not None else None

    @property
    def opener(self):
        return self.api.opener

    @opener.setter
    def opener(self, value):
        self.api.opener = value

    def request(self, url, method='GET', body=None, content_type=None):
        return self.api.request_url(url, method=method, body=body, content_type=content_type)

    def json_request(self, *args, **kwargs):
        return self.api.json_request_url(*args, **kwargs)

    def latest(self):
        parameters = dict(spaces='appDataFolder',
            q=f"trashed = false and appProperties has {{ key='{PROPERTY}' and value='{self.namespace}' }}",
            orderBy='createdTime desc', pageSize=1,
            fields='nextPageToken,files(id,name,createdTime,modifiedTime,size,mimeType,appProperties)')
        if self.namespace == VERSION:
            parameters['q'] += " and name = 'PC.json'"
        return next(self.api.files.iter_files(**parameters), None)

    def read(self, metadata):
        if not isinstance(metadata, dict) or not isinstance(metadata.get('id'), str):
            raise DriveError('Drive 파일 정보가 올바르지 않습니다.')
        if metadata.get('mimeType') != 'application/json':
            raise DriveError('지원하지 않는 Drive 파일 형식입니다.')
        if metadata.get('appProperties', {}).get('schemaVersion', '1') not in ('1', '2', '3'):
            raise DriveError('더 새로운 앱에서 만든 파일입니다. 앱을 업데이트해주세요.')
        body = self.api.files.download(metadata['id'])
        return decode_records(body)

    def download(self):
        metadata = self.latest()
        if metadata is None:
            raise DriveError('이 Google 계정에 저장된 Beatrice 기록이 없습니다.')
        return dict(metadata=metadata, records=self.read(metadata))

    def upload(self, records):
        body = encode_records(records)
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
        options = dict(mime_type='application/json; charset=UTF-8',
                       fields='id,name,createdTime,modifiedTime,mimeType,appProperties')
        uploaded = (self.api.files.update(previous['id'], metadata, body, **options) if previous
                    else self.api.files.create(metadata, body, **options))
        # Re-read the exact PC file; iOS must only read this file.
        if self.read(uploaded) != decode_records(body):
            raise DriveError('Drive에 저장한 내용의 검증에 실패했습니다. 다시 불러와 확인해주세요.')
        return uploaded
