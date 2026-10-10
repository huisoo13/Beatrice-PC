"""Drive file operations; no application filenames or record schemas."""
import json
import re
import secrets
from urllib.parse import quote
from .errors import DriveResponseError

class FilesApi:
    def __init__(self, client): self._client = client

    @staticmethod
    def _path(file_id):
        if not isinstance(file_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', file_id):
            raise ValueError('Drive 파일 ID가 필요합니다.')
        return '/' + quote(file_id, safe='')

    def list(self, **parameters):
        result = self._client.json_request(params=parameters)
        result.setdefault('files', [])
        if not isinstance(result.get('files'), list) or any(not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] for item in result['files']):
            raise DriveResponseError('Drive 파일 목록이 올바르지 않습니다.')
        return result

    def iter_files(self, **parameters):
        parameters, seen = dict(parameters), set()
        for _ in range(100):
            result = self.list(**parameters)
            yield from result['files']
            token = result.get('nextPageToken')
            if not token: return
            if not isinstance(token, str) or token in seen: break
            seen.add(token)
            parameters['pageToken'] = token
        raise DriveResponseError('Drive 파일 목록을 완료하지 못했습니다. 다시 시도해주세요.')

    def get(self, file_id, *, fields=None):
        return self._client.json_request(self._path(file_id), params={'fields': fields} if fields else None)

    def download(self, file_id, *, max_bytes=None):
        return self._client.request(self._path(file_id), params={'alt': 'media'}, max_bytes=max_bytes)

    def _upload(self, metadata, content, mime_type, file_id, fields):
        boundary = 'beatrice_' + secrets.token_hex(24)
        if not isinstance(mime_type, str) or not mime_type or any(ord(c) < 32 or ord(c) > 126 for c in mime_type):
            raise ValueError('파일 MIME 형식을 확인해주세요.')
        if not isinstance(metadata, dict) or not isinstance(content, bytes):
            raise ValueError('메타데이터 객체와 파일 bytes가 필요합니다.')
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode()
                + json.dumps(metadata, allow_nan=False).encode()
                + f'\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n'.encode()
                + content + f'\r\n--{boundary}--\r\n'.encode())
        return self._client.json_request(self._path(file_id) if file_id is not None else '',
            method='PATCH' if file_id is not None else 'POST', upload=True,
            params={'uploadType': 'multipart', 'fields': fields}, body=body,
            content_type='multipart/related; boundary=' + boundary)

    def create(self, metadata, content, *, mime_type='application/octet-stream', fields='id,name,mimeType'):
        return self._upload(metadata, content, mime_type, None, fields)

    def update(self, file_id, metadata, content, *, mime_type='application/octet-stream', fields='id,name,mimeType'):
        return self._upload(metadata, content, mime_type, file_id, fields)
