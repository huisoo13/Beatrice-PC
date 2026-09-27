"""Login UI with cancellable background I/O; persistence happens on the UI thread."""
import queue
import threading
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from .google_auth import AuthError, TokenStore, authenticate


class GoogleLogin(QWidget):
    def __init__(self, root, data, parent=None):
        super().__init__(parent)
        self.root = root
        self.store = TokenStore(data)
        self.session = None
        self.pending = None
        self.closed = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel('Google · 로그인하지 않음')
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.login = QPushButton('Google 로그인')
        self.logout = QPushButton('로그아웃')
        self.logout.setToolTip('이 PC의 로그인 정보를 삭제합니다. Google 계정의 앱 권한은 유지됩니다.')
        self.logout.hide()
        row.addWidget(self.label, 1)
        row.addWidget(self.login)
        row.addWidget(self.logout)
        self.login.clicked.connect(self.login_clicked)
        self.logout.clicked.connect(self.sign_out)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        QTimer.singleShot(0, self.restore)

    def restore(self):
        if self.closed or self.pending:
            return
        try:
            saved = self.store.load()
            if saved:
                self.begin(False, saved)
        except AuthError as exc:
            self.label.setText(str(exc))
            self.logout.show()

    def begin(self, interactive, saved=None):
        if self.closed or self.pending:
            return
        cancel = threading.Event()
        results = queue.Queue()
        root = self.root

        def run():
            try:
                results.put((authenticate(root, saved, cancel, interactive), None))
            except AuthError as exc:
                results.put((None, str(exc)))
            except Exception:
                results.put((None, '로그인을 완료하지 못했습니다. 다시 시도해주세요.'))

        self.pending = (cancel, results)
        self.login.setText('로그인 취소')
        self.login.show()
        self.logout.hide()
        self.label.setText('브라우저에서 Google 로그인을 완료해주세요.' if interactive else 'Google 로그인 확인 중…')
        threading.Thread(target=run, daemon=True, name='GoogleLogin').start()

    def login_clicked(self):
        if self.pending:
            self.pending[0].set()
            self.pending = None
            self.login.setText('Google 로그인')
            self.label.setText('로그인을 취소했습니다.')
            self.logout.setVisible(self.store.path.exists())
            if self.session is not None:
                self.login.hide()
        elif self.session is not None:
            return
        else:
            self.begin(True)

    def poll(self):
        if not self.pending:
            return
        try:
            session, error = self.pending[1].get_nowait()
        except queue.Empty:
            return
        self.pending = None
        self.login.setText('Google 로그인')
        if not error and session:
            try:
                self.store.save(session)
                self.session = session
                self.label.setText('Google · ' + session['account']['email'])
                self.login.hide()
            except (AuthError, OSError):
                error = '로그인 정보를 안전하게 저장하지 못했습니다. 다시 시도해주세요.'
        if error:
            self.label.setText(error)
            if self.session is not None:
                self.login.hide()
        self.logout.setVisible(self.store.path.exists())

    def sign_out(self):
        try:
            self.store.clear()
        except OSError:
            self.label.setText('로그인 정보를 삭제하지 못했습니다. 다시 시도해주세요.')
            return
        self.session = None
        self.label.setText('Google · 로그인하지 않음')
        self.login.setText('Google 로그인')
        self.login.show()
        self.logout.hide()

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        if self.pending:
            self.pending[0].set()
            self.pending = None
