"""Synchronous Drive transport independent of UI, storage and application schemas."""
import json
import math
import re
import threading
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .errors import (DriveAuthError, DrivePermissionError, DriveNotFoundError,
    DriveRateLimitError, DriveNetworkError, DriveResponseError, DriveCancelledError)

API = 'https://www.googleapis.com/drive/v3/files'
UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files'
DEFAULT_MAX_BYTES = 4 * 1024 * 1024

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class GoogleDriveClient:
    def __init__(self, *, access_token=None, api_key=None, cancel=None, timeout=20,
                 max_bytes=DEFAULT_MAX_BYTES, opener=None):
        if (access_token is None) == (api_key is None):
            raise ValueError('access_token 또는 api_key 중 하나를 지정해주세요.')
        credential = access_token if access_token is not None else api_key
        if not isinstance(credential, str) or not credential or any(ord(c) < 33 or ord(c) > 126 for c in credential):
            raise ValueError('Drive 인증 정보 형식을 확인해주세요.')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout은 유한한 양수여야 합니다.')
        self._check_limit(max_bytes)
        self._access_token, self._api_key = access_token, api_key
        self.cancel = cancel if cancel is not None else threading.Event()
        self.timeout, self.max_bytes = timeout, max_bytes
        self.opener = opener if opener is not None else build_opener(_NoRedirect()).open
        from .files import FilesApi
        from .folders import FoldersApi
        self.files, self.folders = FilesApi(self), FoldersApi(self)

    @staticmethod
    def _check_limit(value):
        if type(value) is not int or value <= 0:
            raise ValueError('max_bytes는 양의 정수여야 합니다.')

    def check_cancelled(self):
        if self.cancel.is_set():
            raise DriveCancelledError('Drive 작업을 취소했습니다.')

    def request(self, path='', *, method='GET', params=None, body=None,
                content_type=None, upload=False, max_bytes=None):
        # Fixed host and file IDs prevent forwarding credentials elsewhere.
        if not isinstance(path, str) or (path and not re.fullmatch(r'/[A-Za-z0-9_-]+', path)):
            raise ValueError('Drive API 상대 경로를 확인해주세요.')
        if method not in ('GET', 'POST', 'PATCH', 'DELETE') or (method == 'GET' and body is not None):
            raise ValueError('지원하지 않는 Drive 요청입니다.')
        if self._api_key is not None and method != 'GET':
            raise DrivePermissionError('공용 Drive 클라이언트는 읽기만 지원합니다.')
        limit = self.max_bytes if max_bytes is None else max_bytes
        self._check_limit(limit)
        self.check_cancelled()
        parameters = dict(params or {})
        headers = {'Accept': 'application/json'}
        if self._access_token is not None:
            headers['Authorization'] = 'Bearer ' + self._access_token
        else:
            parameters['key'] = self._api_key
        if content_type:
            headers['Content-Type'] = content_type
        url = (UPLOAD if upload else API) + path
        if parameters:
            url += '?' + urlencode(parameters)
        try:
            with self.opener(Request(url, data=body, headers=headers, method=method), timeout=self.timeout) as response:
                data = response.read(limit + 1)
            self.check_cancelled()
            if len(data) > limit:
                raise DriveResponseError('Drive 파일이 허용 크기를 초과합니다.')
            return data
        except HTTPError as exc:
            status, reason, retry = exc.code, None, None
            try:
                payload = json.loads(exc.read(65537))
                candidate = payload['error']['errors'][0]['reason']
                if candidate in ('rateLimitExceeded', 'userRateLimitExceeded', 'dailyLimitExceeded',
                                 'insufficientPermissions', 'forbidden', 'notFound', 'authError', 'keyInvalid'):
                    reason = candidate
            except (ValueError, KeyError, IndexError, TypeError, OSError, HTTPException, RecursionError):
                pass
            try:
                retry = int(exc.headers.get('Retry-After'))
                if retry < 0:
                    retry = None
            except (ValueError, TypeError, AttributeError):
                pass
            finally:
                exc.close()
            error = DriveResponseError
            message = 'Drive 요청에 실패했습니다. 잠시 후 다시 시도해주세요.'
            if status == 401:
                error, message = DriveAuthError, 'Google 인증이 만료되었습니다. 로그아웃 후 다시 로그인해주세요.'
            elif status == 429 or (status == 403 and reason in ('rateLimitExceeded', 'userRateLimitExceeded', 'dailyLimitExceeded')):
                error, message = DriveRateLimitError, 'Drive 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'
            elif status == 403:
                error, message = DrivePermissionError, 'Drive 접근이 거부되었습니다. Drive 권한 동의와 Google Cloud의 Drive API 사용 설정을 확인해주세요.'
            elif status == 404:
                error, message = DriveNotFoundError, 'Drive 파일을 찾을 수 없습니다. 다시 불러와주세요.'
            raise error(message, status=status, reason=reason, retry_after=retry) from None
        except (URLError, OSError, HTTPException):
            raise DriveNetworkError('Drive 연결이 끊겼습니다. 저장 결과를 불러오기로 확인한 뒤 다시 시도해주세요.') from None

    def json_request(self, path='', **kwargs):
        return self._decode_json(self.request(path, **kwargs))

    @staticmethod
    def _decode_json(body):
        def unique_pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result

        def reject_constant(value):
            raise ValueError()

        try:
            value = json.loads(body, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError, RecursionError):
            raise DriveResponseError('Drive 서버 응답이 올바르지 않습니다.') from None

    def request_url(self, url, **kwargs):
        """Compatibility adapter for existing tools; only official files endpoints."""
        from urllib.parse import parse_qsl
        parts = urlsplit(url)
        prefix = '/upload/drive/v3/files' if parts.path.startswith('/upload/') else '/drive/v3/files'
        if parts.scheme != 'https' or parts.netloc != 'www.googleapis.com' or parts.fragment or not (parts.path == prefix or parts.path.startswith(prefix + '/')):
            raise ValueError('Drive API 주소를 확인해주세요.')
        return self.request(parts.path[len(prefix):], params=dict(parse_qsl(parts.query)),
                            upload=prefix.startswith('/upload/'), **kwargs)

    def json_request_url(self, url, **kwargs):
        return self._decode_json(self.request_url(url, **kwargs))
