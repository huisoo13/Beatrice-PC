"""Personal Drive snapshots and retries, independent of WinUI and Qt widgets."""
import secrets
import time
from pathlib import Path
from .account_service import Job
from .auto_upload import AutoUploadSchedule
from .google_auth import drive_access_token
from .google_drive import DriveClient
from .drive_data import export_snapshot, restore_records


class PersonalDrive:
    def __init__(self, root, data, account, store):
        self.root, self.data, self.account, self.store = root, Path(data), account, store
        self.pending = None
        self.preview = None
        self.auto = AutoUploadSchedule()
        self.closed = False
        self.message = 'Drive · 로그인 후 사용할 수 있습니다.'

    @property
    def busy(self):
        return self.pending is not None or self.preview is not None

    @property
    def available(self):
        return not self.closed and not self.busy and not self.account.busy and self.account.authorized

    @property
    def settled(self):
        return self.pending is None

    def view(self):
        return dict(busy=self.busy, message=self.message, available=self.available)

    def begin(self, action, automatic=False):
        if action not in ('upload', 'download') or not self.available:
            return False
        revision, count, omitted = None, 0, 0
        try:
            records, omitted, revision = export_snapshot(self.store) if action == 'upload' else (None, 0, None)
            if action == 'upload' and not records:
                self.auto.failed(time.monotonic())
                self.message = '저장할 확정 기록이 없습니다. 빈 기록은 Drive에 올리지 않습니다.'
                return False
            count = len(records or [])
        except Exception:
            self.auto.failed(time.monotonic())
            self.message = '저장할 기록을 확인하지 못했습니다. 자동 저장을 재시도합니다.'
            return False
        session = self.account.session
        def run(cancel):
            client = DriveClient(drive_access_token(self.root, session, cancel), cancel, backup_directory=self.data / 'drive-backups')
            return client.upload(records) if action == 'upload' else client.download()
        self.pending = dict(job=Job(run, 'GoogleDrive'), action=action, account=session['account']['sub'],
                            revision=revision, count=count, omitted=omitted, automatic=automatic)
        self.message = ('새 완료 기록을 Drive에 자동 저장하는 중…' if automatic else 'Drive에 저장하고 확인하는 중…') if action == 'upload' else 'Drive 기록을 읽는 중…'
        return True

    def poll(self):
        if not self.pending:
            return False
        task = self.pending
        result = task['job'].result()
        if result is None:
            return False
        self.pending = None
        value, error = result
        if task['job'].cancel.is_set():
            self.message = 'Drive 작업을 취소했습니다.'
            return True
        if not self.account.session or self.account.session['account']['sub'] != task['account']:
            self.message = 'Google 계정이 변경되어 결과를 적용하지 않았습니다.'
            return True
        if error:
            if task['action'] == 'upload':
                delay = self.auto.failed(time.monotonic())
                error += f' · 미전송 완료 기록은 {delay}초 후 재시도합니다.'
            self.message = error
        elif task['action'] == 'upload':
            try:
                self.store.acknowledge_drive(task['account'], *task['revision'])
                self.auto.reset()
                prefix = 'Drive 자동 저장·읽기 검증 완료' if task['automatic'] else 'Drive 저장·읽기 검증 완료'
                self.message = f"{prefix} · {task['count']}건 · 제외 {task['omitted']}건"
            except Exception:
                delay = self.auto.failed(time.monotonic())
                self.message = f'업로드 확인 상태를 저장하지 못했습니다. {delay}초 후 재시도합니다.'
        elif not self.closed:
            self.preview = dict(id=secrets.token_hex(16), account=task['account'], result=value)
            self.message = 'Drive 기록을 확인하고 복원 여부를 선택해주세요.'
        return True

    def preview_view(self):
        if self.preview is None:
            return None
        result = self.preview['result']
        rows = result['records']
        completed = len(rows)
        return dict(type='drive_preview', previewId=self.preview['id'],
                    email=self.account.session['account']['email'],
                    createdTime=result['metadata'].get('modifiedTime') or result['metadata'].get('createdTime', ''),
                    completedCount=completed, omittedCount=len(rows)-completed,
                    localCount=len(self.store.history_records()))

    def resolve(self, preview_id, apply):
        if self.closed or not self.preview or self.preview['id'] != preview_id:
            return False
        preview, self.preview = self.preview, None
        if not self.account.session or self.account.session['account']['sub'] != preview['account']:
            self.message = 'Google 계정이 변경되어 결과를 적용하지 않았습니다.'
        elif not apply:
            self.message = '불러오기를 취소했습니다. PC 기록은 유지됩니다.'
        else:
            try:
                rows = preview['result']['records']
                backup = restore_records(self.store, rows, self.data / 'drive-backups')
                self.auto.reset()
                self.message = f"Drive 완료 기록 {len(rows)}건 복원 완료 · 이전 기록 백업: {backup}"
            except Exception:
                self.message = '로컬 기록을 복원하지 못했습니다. 기존 기록을 유지합니다.'
        return True

    def check_auto_upload(self):
        if not self.available:
            return
        try:
            revision = self.store.drive_pending(self.account.session['account']['sub'])
        except Exception:
            return
        target = (self.account.session['account']['sub'], *revision) if revision else None
        if self.auto.due(target, time.monotonic()):
            self.begin('upload', automatic=True)

    def shutdown(self):
        self.closed = True
        self.preview = None
        # Complete and verify an in-flight upload before the host closes SQLite.
        if self.pending and self.pending['action'] == 'download':
            self.pending['job'].cancel.set()
