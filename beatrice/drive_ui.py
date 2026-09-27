"""Drive upload/restore and automatic completion uploads; network I/O stays off Qt."""
from datetime import datetime
from pathlib import Path
import queue
import threading
import time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox

from .google_auth import AuthError, DRIVE_SCOPE, drive_access_token
from .google_drive import DriveClient, DriveError
from .drive_data import export_snapshot, restore_records
from .auto_upload import AutoUploadSchedule


class DrivePanel(QWidget):
    def __init__(self, root, data, login, store, can_restore, changed, parent=None):
        super().__init__(parent)
        self.root, self.data, self.login, self.store = root, Path(data), login, store
        self.can_restore, self.changed = can_restore, changed
        self.pending = None
        self.busy = False
        self.closed = False
        self.auto = AutoUploadSchedule()
        self.next_scan = 0
        self.upload_revision = None
        self.automatic = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.connect_button = QPushButton('Drive 권한 연결')
        self.upload_button = QPushButton('Drive에 저장')
        self.download_button = QPushButton('Drive에서 불러오기')
        self.download_button.setToolTip('분석을 정지한 후 사용할 수 있습니다. 로컬 백업 후 기록을 교체합니다.')
        for button in (self.connect_button, self.upload_button, self.download_button):
            row.addWidget(button)
        layout.addLayout(row)
        layout.addWidget(QLabel('새 완료 기록은 Google 로그인·Drive 권한 연결 후 자동 저장됩니다.'))
        self.label = QLabel('Drive · 로그인 후 사용할 수 있습니다.')
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.connect_button.clicked.connect(self.connect_drive)
        self.upload_button.clicked.connect(lambda: self.begin('upload'))
        self.download_button.clicked.connect(lambda: self.begin('download'))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.update_buttons()

    def update_buttons(self):
        session = self.login.session
        available = bool(session) and not self.login.pending and not self.busy and not self.closed
        authorized = bool(session) and DRIVE_SCOPE in session.get('scopes', [])
        self.connect_button.setVisible(not authorized)
        self.connect_button.setEnabled(available)
        self.upload_button.setEnabled(available and authorized)
        self.download_button.setEnabled(available and authorized and self.can_restore())

    def connect_drive(self):
        if self.busy or self.closed or not self.login.session or self.login.pending:
            return
        self.label.setText('브라우저에서 앱 전용 Drive 데이터 접근에 동의해주세요.')
        self.login.begin(True, self.login.session)
        self.update_buttons()

    def begin(self, action, automatic=False):
        if self.closed or self.busy or not self.login.session or self.login.pending:
            return
        if action == 'download' and not self.can_restore():
            return
        try:
            records, omitted, revision = export_snapshot(self.store) if action == 'upload' else (None, 0, None)
        except Exception:
            # Validation/SQLite failure must leave the durable obligation pending.
            delay = self.auto.failed(time.monotonic())
            self.label.setText(f'저장할 기록을 확인하지 못했습니다. {delay}초 후 자동 저장을 재시도합니다.')
            return
        if action == 'upload' and not records:
            self.auto.failed(time.monotonic())
            self.label.setText('저장할 확정 기록이 없습니다. 빈 기록은 Drive에 올리지 않습니다.')
            return
        self.upload_revision = revision
        self.automatic = automatic
        cancel, results = threading.Event(), queue.Queue()
        session, root = self.login.session, self.root

        def run():
            try:
                token = drive_access_token(root, session, cancel)
                client = DriveClient(token, cancel)
                result = client.upload(records) if action == 'upload' else client.download()
                results.put((result, None))
            except (AuthError, DriveError, ValueError) as exc:
                results.put((None, str(exc)))
            except Exception:
                results.put((None, 'Drive 작업을 완료하지 못했습니다. 다시 시도해주세요.'))

        self.pending = (cancel, results, action, len(records or []), omitted, session['account']['sub'])
        self.busy = True
        self.login.setEnabled(False)
        self.label.setText(('새 완료 기록을 Drive에 자동 저장하는 중…' if automatic else 'Drive에 저장하고 확인하는 중…')
                           if action == 'upload' else 'Drive 기록을 읽는 중…')
        self.update_buttons()
        self.changed()
        threading.Thread(target=run, daemon=True, name='GoogleDrive').start()

    def tick(self):
        self.update_buttons()
        if not self.pending:
            self.check_auto_upload()
            return
        cancel, results, action, count, omitted, account = self.pending
        try:
            result, error = results.get_nowait()
        except queue.Empty:
            return
        # Keep busy through the modal dialog: the event loop continues inside it.
        self.pending = None
        try:
            if self.closed or cancel.is_set():
                return
            if not self.login.session or self.login.session['account']['sub'] != account:
                self.label.setText('Google 계정이 변경되어 결과를 적용하지 않았습니다.')
                return
            if error:
                if action == 'upload':
                    delay = self.auto.failed(time.monotonic())
                    error += f' · 미전송 완료 기록은 {delay}초 후 재시도합니다.'
                self.label.setText(error)
                return
            if action == 'upload':
                if self.upload_revision is not None:
                    self.store.acknowledge_drive(account, *self.upload_revision)
                self.auto.reset()
                prefix = 'Drive 자동 저장·읽기 검증 완료' if self.automatic else 'Drive 저장·읽기 검증 완료'
                self.label.setText(f'{prefix} · {count}건 · 제외 {omitted}건')
                return
            if not self.can_restore():
                self.label.setText('분석을 정지한 후 다시 불러와주세요.')
                return
            rows = result['records']
            created = result['metadata'].get('createdTime', '')
            try:
                created = datetime.fromisoformat(created.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                created = '시각 확인 불가'
            message = (f"계정: {self.login.session['account']['email']}\n저장 시각: {created}\n"
                       f"Drive 기록: {len(rows)}건 / 현재 PC 기록: {len(self.store.state_records())}건\n\n"
                       '현재 PC 기록을 로컬 백업한 후 Drive 기록으로 교체합니다. 계속할까요?')
            answer = QMessageBox.question(self, 'Drive 기록 불러오기', message,
                                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                           QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes or self.closed or not self.can_restore():
                self.label.setText('불러오기를 취소했습니다. PC 기록은 유지됩니다.')
                return
            backup = restore_records(self.store, rows, self.data / 'drive-backups')
            self.label.setText(f'Drive 기록 {len(rows)}건 복원 완료 · 이전 기록 백업: {backup}')
        except Exception:
            if action == 'upload':
                delay = self.auto.failed(time.monotonic())
                self.label.setText(f'업로드 확인 상태를 저장하지 못했습니다. {delay}초 후 재시도합니다.')
            else:
                self.label.setText('로컬 기록을 복원하지 못했습니다. 기존 기록을 유지합니다.')
        finally:
            self.busy = False
            self.login.setEnabled(True)
            self.update_buttons()
            if not self.closed:
                self.changed()

    def check_auto_upload(self):
        now = time.monotonic()
        if self.closed or self.busy or now < self.next_scan:
            return
        self.next_scan = now + 1
        session = self.login.session
        if not session or self.login.pending or DRIVE_SCOPE not in session.get('scopes', []):
            return
        account = session['account']['sub']
        try:
            revision = self.store.drive_pending(account)
        except Exception:
            self.next_scan = now + 5
            return
        target = (account, *revision) if revision else None
        if self.auto.due(target, now):
            self.begin('upload', automatic=True)

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        if self.pending:
            self.pending[0].set()
            self.pending = None
