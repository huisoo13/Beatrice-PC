"""Verify a candidate off-thread, then persist only on the owner's poll call."""
import queue
import threading

from .lostark import LostArkClient
from .lostark.errors import LostArkAuthError, LostArkRateLimitError, LostArkNetworkError


class LostArkRegistration:
    def __init__(self, store, client_factory=LostArkClient):
        self.store, self.client_factory = store, client_factory
        self.pending = None
        self.closed = False
        self.message = ''

    def view(self):
        return dict(self.store.view(), busy=self.pending is not None,
                    message=self.message)

    def begin(self, key):
        if self.closed or self.pending is not None:
            return False
        if not isinstance(key, str) or not key.strip():
            self.message = 'API 키를 입력해주세요.'
            return False
        key = key.strip()
        if len(key) > 16384 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            self.message = 'API 키 형식을 확인해주세요.'
            return False
        result = queue.Queue()

        def verify():
            try:
                response = self.client_factory(key=key).news.events()
                if not isinstance(response, list):
                    result.put((False, '뉴스 API 응답을 확인하지 못했습니다. 다시 시도해주세요.'))
                else:
                    result.put((True, ''))
            except LostArkAuthError:
                result.put((False, 'API 키가 유효하지 않습니다. 입력한 키를 확인해주세요.'))
            except LostArkRateLimitError:
                result.put((False, 'API 호출 제한에 도달했습니다. 잠시 후 다시 시도해주세요.'))
            except LostArkNetworkError:
                result.put((False, 'API에 연결하지 못했습니다. 인터넷 연결을 확인해주세요.'))
            except Exception:
                # Never expose an exception containing the candidate or HTTP payload.
                result.put((False, '뉴스 API 검증에 실패했습니다. 잠시 후 다시 시도해주세요.'))

        thread = threading.Thread(target=verify, name='lostark-key-verification', daemon=True)
        self.pending = (key, result, thread)
        self.message = 'API 키를 검증하는 중…'
        thread.start()
        return True

    def poll(self):
        if self.pending is None:
            return None
        key, result, thread = self.pending
        try:
            success, message = result.get_nowait()
        except queue.Empty:
            return None
        self.pending = None
        if self.closed:
            return None
        if success:
            success = self.store.save(key)
            message = 'API키가 정상적으로 등록되었습니다.' if success else self.store.message
        self.message = message
        return dict(success=success, **self.view())

    def stop(self):
        self.closed = True

    @property
    def settled(self):
        return self.pending is None or not self.pending[2].is_alive()
