"""Synchronous, UI-independent Lost Ark transport using the standard library."""
import json
import math
from http.client import HTTPException
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..google_auth import AuthError
from ..lostark_api import LostArkApiKey
from .errors import (LostArkAuthError, LostArkNetworkError, LostArkNotFoundError,
                     LostArkRateLimitError, LostArkResponseError)

BASE_URL = 'https://developer-lostark.game.onstove.com'


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an authenticated request to a redirected destination.
        return None


@dataclass(frozen=True)
class RateLimit:
    limit: int | None = None
    remaining: int | None = None
    reset_at: int | None = None


def _integer(headers, name):
    try:
        value = int(headers.get(name))
        return value if value >= 0 else None
    except (TypeError, ValueError):
        return None


class LostArkClient:
    """Reuse one client across feature groups. No requests during construction."""
    def __init__(self, key=None, *, key_provider=None, timeout=15):
        if (key is None) == (key_provider is None):
            raise ValueError('key 또는 key_provider 중 하나를 지정해주세요.')
        if key_provider is not None and not callable(key_provider):
            raise ValueError('key_provider는 호출 가능한 함수여야 합니다.')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout은 유한한 양수여야 합니다.')
        self._key_provider = key_provider if key_provider is not None else lambda: key
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect())
        self._lock = threading.Lock()
        self.rate_limit = RateLimit()
        self._blocked_until = 0
        from .characters import CharactersApi
        from .armory import ArmoryApi
        self.characters = CharactersApi(self)
        self.armory = ArmoryApi(self)

    @classmethod
    def from_saved_key(cls, directory=None, *, timeout=15):
        """Load the current app key on every request, respecting app data overrides."""
        if directory is None:
            directory = os.environ.get('BEATRICE_DATA_DIR') or (
                Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'BeatricePC')
        directory = Path(directory)

        def load_key():
            return LostArkApiKey(directory).load()

        return cls(key_provider=load_key, timeout=timeout)

    def _authorization(self):
        try:
            key = self._key_provider()
        except (OSError, ValueError, AuthError):
            raise LostArkAuthError('저장된 로스트아크 API 키를 읽지 못했습니다.') from None
        if not isinstance(key, str):
            raise LostArkAuthError('로스트아크 API 키를 먼저 저장해주세요.')
        key = key.strip()
        if key.lower() == 'bearer' or key.lower().startswith('bearer '):
            key = key[7:].strip()
        if not key or len(key) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise LostArkAuthError('로스트아크 API 키 형식을 확인해주세요.')
        return 'bearer ' + key

    def _read_limits(self, headers, *, limited=False):
        self.rate_limit = RateLimit(*(_integer(headers, name) for name in (
            'X-RateLimit-Limit', 'X-RateLimit-Remaining', 'X-RateLimit-Reset')))
        now = time.time()
        if limited or self.rate_limit.remaining == 0:
            retry = _integer(headers, 'Retry-After')
            reset = self.rate_limit.reset_at
            # No blocking sleep: callers decide when to schedule another attempt.
            self._blocked_until = max(now + (retry if retry is not None else 0),
                                      reset if reset is not None else 0)
            if self._blocked_until <= now:
                self._blocked_until = now + 60

    def request(self, method, path, *, params=None, body=None):
        """GET/POST to the fixed official host. Return unchanged decoded JSON."""
        if method not in ('GET', 'POST'):
            raise ValueError('GET 또는 POST만 지원합니다.')
        if not isinstance(path, str) or not path.startswith('/') or any(
                item in path for item in ('//', '\\', '?', '#')) or any(
                part in ('.', '..') for part in path.split('/')) or any(
                ord(c) < 33 or ord(c) > 126 for c in path):
            raise ValueError('인코딩된 API 상대 경로를 사용해주세요.')
        if method == 'GET' and body is not None:
            raise ValueError('GET 요청에는 body를 사용할 수 없습니다.')
        query = '?' + urlencode(params, doseq=True) if params else ''
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8') if body is not None else None
        with self._lock:
            wait = self._blocked_until - time.time()
            if wait > 0:
                raise LostArkRateLimitError(retry_after=math.ceil(wait))
            headers = {'Authorization': self._authorization(), 'Accept': 'application/json'}
            if data is not None:
                headers['Content-Type'] = 'application/json'
            request = Request(BASE_URL + path + query, data=data, headers=headers, method=method)
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    self._read_limits(response.headers)
                    if response.status == 204:
                        return None
                    try:
                        return json.load(response)
                    except (ValueError, UnicodeError):
                        raise LostArkResponseError('로스트아크 API 응답을 읽지 못했습니다.', status=response.status) from None
            except HTTPError as error:
                status = error.code
                self._read_limits(error.headers or {}, limited=status == 429)
                error.close()
                if status in (401, 403):
                    raise LostArkAuthError('로스트아크 API 인증이 거부되었습니다. 저장된 키를 확인해주세요.', status=status) from None
                if status == 429:
                    raise LostArkRateLimitError(retry_after=max(0, math.ceil(self._blocked_until - time.time()))) from None
                if status == 404:
                    raise LostArkNotFoundError('요청한 로스트아크 API 정보를 찾지 못했습니다.', status=status) from None
                raise LostArkResponseError('로스트아크 API 요청을 처리하지 못했습니다.', status=status) from None
            except (URLError, OSError, HTTPException):
                raise LostArkNetworkError('로스트아크 API 연결에 실패했습니다. 인터넷 연결을 확인해주세요.') from None
