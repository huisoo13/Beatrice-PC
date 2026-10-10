"""Local Lost Ark API credential storage; never expose the credential in UI state."""
from pathlib import Path
from .google_auth import dpapi, AuthError


class LostArkApiKey:
    def __init__(self, directory):
        self.path = Path(directory) / 'lostark-api-key.bin'
        self.configured = False
        self.message = '저장된 API Key가 없습니다.'
        try:
            self.configured = bool(self.load())
            if self.configured: self.message = 'API Key가 저장되어 있습니다.'
        except (OSError, ValueError, AuthError):
            self.message = '저장된 API Key를 읽지 못했습니다. 다시 입력해주세요.'

    def load(self):
        if not self.path.exists(): return None
        return dpapi(self.path.read_bytes(), decrypt=True).decode('utf-8')

    def view(self):
        return dict(configured=self.configured, message=self.message)

    def save(self, key):
        if not isinstance(key, str) or not key.strip():
            self.message = 'API Key를 입력해주세요.'
            return False
        key = key.strip()
        if len(key) > 16384 or any(ord(c) < 32 or ord(c) == 127 for c in key):
            self.message = 'API Key 형식을 확인해주세요. 줄바꿈은 사용할 수 없습니다.'
            return False
        temporary = self.path.with_suffix('.tmp')
        try:
            encrypted = dpapi(key.encode('utf-8'))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(encrypted)
            temporary.replace(self.path)
        except (OSError, ValueError, AuthError):
            self.message = 'API Key를 저장하지 못했습니다. 다시 시도해주세요.'
            return False
        finally:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
        self.configured = True
        self.message = 'API Key를 저장했습니다.'
        return True

    def clear(self):
        try:
            self.path.with_suffix('.tmp').unlink(missing_ok=True)
            self.path.unlink(missing_ok=True)
        except OSError:
            self.message = '초기화하지 못했습니다. 다시 시도해주세요.'
            return False
        self.configured = False
        self.message = '초기화했습니다.'
        return True
