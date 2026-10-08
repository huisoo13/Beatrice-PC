"""Google account lifecycle without a UI framework. Poll only on the host thread."""
import queue
import threading
from .google_auth import AuthError, TokenStore, authenticate, DRIVE_SCOPE


class Job:
    def __init__(self, action, name):
        self.cancel = threading.Event()
        self.results = queue.Queue()
        def run():
            try:
                self.results.put((action(self.cancel), None))
            except Exception as error:
                # Auth/Drive errors contain user-safe messages, never request/token data.
                from .google_drive import DriveError
                message = str(error) if isinstance(error, (AuthError, DriveError, ValueError)) else 'Google 작업을 완료하지 못했습니다. 다시 시도해주세요.'
                self.results.put((None, message))
        self.thread = threading.Thread(target=run, daemon=True, name=name)
        self.thread.start()

    def result(self):
        if self.thread.is_alive():
            return None
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None


class GoogleAccount:
    def __init__(self, root, data):
        self.root = root
        self.tokens = TokenStore(data)
        self.session = None
        self.pending = None
        self.retired = []
        self.closed = False
        self.restored = False
        self.message = 'Google · 로그인하지 않음'

    @property
    def busy(self):
        return self.pending is not None

    @property
    def authorized(self):
        return bool(self.session and DRIVE_SCOPE in self.session.get('scopes', []))

    @property
    def settled(self):
        return self.pending is None and not any(job.thread.is_alive() for job in self.retired)

    def view(self):
        return dict(signedIn=bool(self.session), email=(self.session or {}).get('account', {}).get('email', ''),
                    busy=self.busy, authorized=self.authorized, message=self.message,
                    canLogout=bool(self.session) or self.tokens.path.exists())

    def restore(self):
        if self.closed or self.restored:
            return
        self.restored = True
        try:
            saved = self.tokens.load()
            if saved:
                self.begin(False, saved)
        except AuthError as error:
            self.message = str(error)

    def begin(self, interactive=True, saved=None):
        if self.closed or self.busy:
            return
        self.message = '브라우저에서 Google 로그인을 완료해주세요.' if interactive else 'Google 로그인 확인 중…'
        self.pending = Job(lambda cancel: authenticate(self.root, saved, cancel, interactive), 'GoogleLogin')

    def cancel(self):
        if self.pending:
            self.pending.cancel.set()
            self.retired.append(self.pending)
            self.pending = None
            self.message = '로그인을 취소했습니다.'

    def poll(self):
        self.retired = [job for job in self.retired if job.thread.is_alive()]
        if not self.pending:
            return False
        result = self.pending.result()
        if result is None:
            return False
        self.pending = None
        session, error = result
        if not error and session:
            try:
                self.tokens.save(session)
                self.session = session
                self.message = 'Google · ' + session['account']['email']
            except (AuthError, OSError):
                error = '로그인 정보를 안전하게 저장하지 못했습니다. 다시 시도해주세요.'
        if error:
            self.message = error
        return True

    def sign_out(self):
        if self.closed or self.busy:
            return
        try:
            self.tokens.clear()
        except OSError:
            self.message = '로그인 정보를 삭제하지 못했습니다. 다시 시도해주세요.'
            return
        self.session = None
        self.message = 'Google · 로그인하지 않음'

    def shutdown(self):
        self.closed = True
        self.cancel()
