"""Headless analysis host for the WinUI desktop (UTF-8 JSON lines over pipes).

Qt is used only for the existing worker's signals; no QWidget is created.
All Store access and commands run on the QCoreApplication thread.
"""
import json
import faulthandler
import os
import queue
import sys
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QTimer, QLockFile
from . import engine_worker as engine
from .storage import Store
from .weekly import open_week, week_start
from .lostark_api import LostArkApiKey
from .account_service import GoogleAccount
from .drive_service import PersonalDrive
from .content_match import ContentMatcher, record_detail
from .public_content import ContentCache, ContentError, PublicContentClient, load_settings, load_api_key


def record_view(row, cached=None):
    """Retain the stored matching decision and expose completed records only."""
    when = datetime.fromisoformat(row['observedAt']).astimezone().strftime('%Y.%m.%d %H:%M')
    detail = record_detail(row, cached)
    if row.get('ocrOriginal'): detail['ocrOriginal'] = row['ocrOriginal']
    return dict(character=row.get('characterName') or '캐릭터 확인 대기',
                dungeon=row.get('dungeonName') or '확인 대기', mode=row.get('difficulty') or '확인 대기',
                gate=row.get('gateName') or ('레이드 전체' if row.get('completionScope') == 'raid' else f"{row['gate']}관문"),
                date=when, observedAt=row['observedAt'], detail=detail)


def empty_profile():
    return dict(character='캐릭터 확인 대기', message='캐릭터 미설정', active=False, characterState='unset')


def character_view(identity):
    status = identity.get('status')
    allowed = bool(identity.get('recordingAllowed') and identity.get('currentName'))
    name = identity.get('currentName') if allowed else identity.get('pendingName') or identity.get('previewName') or identity.get('currentName')
    if status in ('switching', 'initial_login_loading', 'initial_login_selection'):
        name = identity.get('pendingName') or name
        message = '캐릭터 변경 중' if status == 'switching' else '캐릭터 선택 중'
        state = 'selecting'
    elif allowed: message, state = '플레이 중', 'playing'
    elif status == 'awaiting_current_confirmation' and name: message, state = '캐릭터 확인 중', 'selecting'
    else: message, state = '캐릭터 미설정', 'unset'
    return dict(character=name or '캐릭터 확인 대기', message=message, active=state == 'playing', characterState=state)


def progress_unit(value):
    dungeon = value.get('dungeon', {})
    if dungeon.get('raidKind') == 'gateless': return '레이드 전체'
    result = value.get('result', {})
    states = result.get('observedStates', result.get('stableStates')) or []
    gate = next((i for i, state in enumerate(states, 1) if state == '진행중'), None)
    return f'{gate}관문' if gate else ''


def observation_view(value, matcher=None):
    profile = character_view(value.get('identity', {}))
    dungeon = value.get('dungeon', {})
    name, difficulty = dungeon.get('dungeonName'), dungeon.get('difficulty')
    if matcher: name, difficulty = matcher.display_context(name, difficulty)
    visible = bool(name and dungeon.get('contextStatus') in ('ocr_verified', 'ocr_held', 'ocr_partial'))
    profile.update(dungeon=name if visible else None,
        dungeonSubtitle=' · '.join(filter(None, [difficulty, progress_unit(value)])) if visible else '',
        dungeonState='진행 중', diagnostics=value.get('recordingStatus', ''))
    return profile


class DungeonFooter:
    """Display-only retention; never supplies context to completion recording."""
    def __init__(self):
        self.context = None
        self.unit = ''
        self.last_panel_seen = None

    def update(self, value, now):
        dungeon = value.get('dungeon', {})
        panel = dungeon.get('raidPanelVisible', dungeon.get('currentRaidPanel', False))
        if panel: self.last_panel_seen = now
        if dungeon.get('dungeonName') and dungeon.get('contextStatus') in ('ocr_verified', 'ocr_held', 'ocr_partial'):
            pair = dungeon.get('dungeonName'), dungeon.get('difficulty')
            previous = (self.context.get('dungeonName'), self.context.get('difficulty')) if self.context else None
            if pair != previous: self.unit = ''
            current_unit = progress_unit(value)
            if dungeon.get('contextStatus') != 'ocr_held' or (panel and current_unit): self.unit = current_unit
            self.context = dict(dungeonName=pair[0], difficulty=pair[1])
            # A held context received as the first observation starts one bounded grace period.
            if self.last_panel_seen is None: self.last_panel_seen = now

    def view(self, matcher, now):
        if not self.context or self.last_panel_seen is None or now-self.last_panel_seen >= 30:
            return dict(dungeon=None, dungeonSubtitle='', dungeonState='진행 중')
        name, difficulty = matcher.display_context(self.context['dungeonName'], self.context['difficulty'])
        return dict(dungeon=name, dungeonSubtitle=' · '.join(filter(None, [difficulty, self.unit])), dungeonState='진행 중')


class Host(QObject):

    def __init__(self, app, emit, worker_factory=engine.Worker):
        super().__init__()
        self.app, self.emit, self.worker_factory = app, emit, worker_factory
        self.store = open_week(engine.DATA)
        self.week_start = self.store.repeat_start()
        self.worker = None
        self.clients = []
        self.client = None
        self.pids = None
        self.generation = 0
        self.closing = self.restarting = self.maintenance = False
        self.initialized = False
        self.closed = False
        self.worker_done = False
        self.maintenance_action = None
        self.maintenance_settled = False
        self.preview_sent = None
        self.lostark_api = LostArkApiKey(engine.DATA)
        self.account = GoogleAccount(engine.ROOT, engine.DATA)
        self.drive = PersonalDrive(engine.ROOT, engine.DATA, self.account, self.store)
        self.startup_step = 0
        self.startup_catalog_finished = False
        self.error = ''
        self.status = '모델을 준비하는 중…'
        self.profile = empty_profile()
        self.footer = DungeonFooter()
        self.cached = self.cache = self.settings = None
        self.catalog_message = '공용 데이터 · 확인 대기'
        self.catalog_pending = None
        self.catalog_jobs = []
        self.catalog_refresh_available_at = 0.0
        self.catalog_cooldown_path = Path(engine.DATA) / 'public-content' / 'manual-refresh.json'
        try:
            saved = json.loads(self.catalog_cooldown_path.read_text(encoding='utf-8'))
            self.catalog_refresh_available_at = max(0.0, float(saved.get('availableAt', 0)))
        except (OSError, ValueError, TypeError, AttributeError): pass
        self.next_check = 0
        self.last_snapshot = None
        self.commands = queue.Queue()
        try:
            self.settings = load_settings(engine.ROOT)
            self.cache = ContentCache(engine.DATA, self.settings)
            self.cached = self.cache.load()
            if self.cached: self.catalog_message = '공용 데이터 · 로컬 보관본'
        except ContentError as error:
            self.catalog_message = str(error)
        self.matcher = ContentMatcher(self.cached)
        self.command_timer = QTimer(self)
        self.command_timer.timeout.connect(self.drain_commands)
        self.command_timer.start(50)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def start(self):
        self.worker_done = False
        self.worker = self.worker_factory()
        self.worker.progress.connect(self.progress)
        self.worker.ready.connect(self.ready)
        self.worker.observation.connect(self.observation)
        self.worker.process_changed.connect(self.process_changed)
        self.worker.status.connect(self.worker_status)
        self.worker.failed.connect(self.failed)
        self.worker.settled.connect(self.settled)
        self.worker.finished.connect(self.finished)
        self.worker.start()
        self.snapshot()

    def progress(self, message):
        with (engine.DATA/'startup-progress.log').open('a',encoding='utf-8') as log:
            log.write(datetime.now().isoformat(timespec='seconds')+' · '+message+'\n')
        self.status = message
        if message.startswith('2 / 3'): self.startup_step = 1
        self.snapshot()

    def ready(self, clients):
        if self.closing or self.restarting: return
        self.initialized = True
        self.startup_step = 2
        if not self.settings: self.startup_catalog_finished = True
        self.error = ''
        self.generation, self.client = self.worker.requested()
        self.clients = clients
        self.status = '분석 중' if self.client else '게임 실행 대기'
        self.account.restore()
        self.snapshot()

    def refresh_clients(self):
        clients = engine.find_clients(self.pids) if self.pids else []
        chosen = next((c for c in clients if self.client and c.identity == self.client.identity), None)
        chosen = chosen or next((c for c in clients if engine.client_active(c)), clients[0] if clients else None)
        self.clients = clients
        if chosen != self.client and not self.maintenance and not self.error and not self.drive.busy:
            self.select(chosen)

    def select(self, client):
        self.client = client
        self.generation += 1
        self.worker.select(self.generation, client)
        self.profile = empty_profile()
        self.footer = DungeonFooter()
        self.status = '게임 창 연결 중' if client else '게임 실행 대기'

    def process_changed(self, snapshot):
        if self.closing or self.restarting: return
        self.pids, error = snapshot
        if error: self.status = error
        if self.initialized: self.refresh_clients()
        self.snapshot()

    def observation(self, value):
        if value.get('generation') != self.generation or self.maintenance or self.closing or self.restarting: return
        now = time.monotonic()
        self.footer.update(value, now)
        self.profile = character_view(value.get('identity', {}))
        self.profile.update(self.footer.view(self.matcher, now))
        self.status = value.get('recordingStatus', '분석 중')
        self.snapshot()

    def worker_status(self, generation, message):
        if generation != self.generation or self.maintenance or self.closing or self.restarting: return
        self.status = message
        self.snapshot()

    def failed(self, message):
        self.error = self.status = message
        if self.maintenance_action == 'restore':
            if self.drive.pending: self.drive.pending['job'].cancel.set()
            self.drive.preview = None
            self.preview_sent = None
            self.drive.message = '분석 작업자 오류로 복원을 중단했습니다.'
        self.maintenance = False
        self.maintenance_action = None
        self.snapshot()

    def snapshot(self):
        if self.closed: return
        records = [record_view(row, self.cached) for row in self.store.history_records() if row['state'] == '완료']
        records.sort(key=lambda row: datetime.fromisoformat(row['observedAt']).timestamp(), reverse=True)
        value = dict(type='snapshot', status=self.status, error=self.error, profile=self.profile,
                     records=records, clients=[asdict(client) for client in self.clients],
                     selected=self.client.hwnd if self.client else 0,
                     catalogStatus=self.catalog_message,
                     catalogLastUpdated=(self.cached or {}).get('checkedAt', ''),
                     catalogRefreshAvailableAt=self.catalog_refresh_available_at,
                     busy=self.maintenance or self.restarting or self.drive.busy or self.account.busy or (not self.initialized and not self.error),
                     google=self.account.view(),
                     lostArkApi=self.lostark_api.view(),
                     drive=dict(self.drive.view(), available=self.drive.available and self.can_change_records()),
                     restarting=self.restarting,
                     catalogBusy=self.catalog_pending is not None,
                     startupStep=0 if self.restarting else 3 if self.initialized and self.startup_catalog_finished else self.startup_step,
                     startupReady=self.initialized and self.startup_catalog_finished and not self.restarting)
        serialized = json.dumps(value, ensure_ascii=False)
        if serialized != self.last_snapshot:
            self.last_snapshot = serialized
            self.emit(value)

    def command(self, value):
        if self.closing: return
        kind = value.get('type')
        if kind == 'shutdown':
            self.closing = True
            self.account.shutdown()
            self.drive.shutdown()
            self.stop_catalog()
            self.worker.stop_event.set()
            if not self.worker.isRunning(): self.finished()
        elif kind == 'restart' and not self.maintenance and not self.restarting and not self.drive.busy and not self.account.busy:
            self.restarting = True
            self.error = ''
            self.stop_catalog()
            self.status = '현재 작업을 종료하고 초기화하는 중…'
            self.profile = empty_profile()
            self.footer = DungeonFooter()
            self.worker.stop_event.set()
            self.snapshot()
            if not self.worker.isRunning(): self.finished()
        elif kind == 'select' and self.initialized and not (self.maintenance or self.restarting or self.error or self.drive.busy or self.account.busy):
            chosen = next((c for c in self.clients if c.hwnd == value.get('hwnd')), None)
            if chosen: self.select(chosen)
            self.snapshot()
        elif kind == 'delete' and self.can_change_records():
            self.pause_for('delete')
        elif kind == 'lostark_api_save':
            success = self.lostark_api.save(value.get('key'))
            self.emit(dict(type='lostark_api_saved', success=success, **self.lostark_api.view()))
            self.snapshot()
        elif kind == 'lostark_api_clear':
            success = self.lostark_api.clear()
            self.emit(dict(type='lostark_api_cleared', success=success, **self.lostark_api.view()))
            self.snapshot()
        elif kind == 'google_cancel':
            self.account.cancel()
            self.snapshot()
        elif kind in ('google_login', 'google_connect', 'google_logout'):
            if self.initialized and not (self.maintenance or self.restarting or self.drive.busy or self.account.busy):
                if kind == 'google_logout':
                    self.account.sign_out()
                    self.drive.auto.reset()
                    if self.account.session is None: self.drive.message = 'Drive · 로그인 후 사용할 수 있습니다.'
                elif kind == 'google_connect' and self.account.session:
                    self.account.begin(True, self.account.session)
                elif kind == 'google_login' and not self.account.session:
                    self.account.begin(True)
            self.snapshot()
        elif kind == 'drive_upload':
            if self.can_change_records(): self.drive.begin('upload')
            self.snapshot()
        elif kind == 'drive_download':
            if self.can_change_records() and self.drive.available: self.pause_for('restore')
            self.snapshot()
        elif kind == 'drive_restore':
            if (self.maintenance_action == 'restore' and self.maintenance_settled
                    and self.drive.resolve(value.get('previewId'), value.get('apply') is True)):
                self.resume_analysis()
        elif kind == 'catalog_refresh':
            if (self.initialized and self.settings and not self.catalog_pending and not self.restarting
                    and not self.maintenance and time.time() >= self.catalog_refresh_available_at):
                self.catalog_refresh_available_at = time.time() + 300
                try:
                    self.catalog_cooldown_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.catalog_cooldown_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(dict(availableAt=self.catalog_refresh_available_at)), encoding='utf-8')
                    temporary.replace(self.catalog_cooldown_path)
                except OSError: pass
                self.refresh_catalog()
            self.snapshot()
        elif kind == 'catalog':
            rows = []
            for dungeon, modes in (self.cached or {}).get('content', {}).items():
                for mode, gates in modes.items():
                    for gate, values in gates.items():
                        rows.append(dict(dungeon=dungeon, mode=mode, gate=gate, **values))
            self.emit(dict(type='catalog', rows=rows))

    def can_change_records(self):
        return self.initialized and not (self.maintenance or self.restarting or self.error or self.drive.busy or self.account.busy)

    def pause_for(self, action):
        self.maintenance = True
        self.maintenance_action = action
        self.maintenance_settled = False
        self.generation += 1
        self.worker.select(self.generation, None)
        self.status = '주간 반복 상태 초기화 중…' if action == 'weekly' else '기록 삭제 준비 중…' if action == 'delete' else 'Drive 복원을 위해 분석을 보류하는 중…'
        self.snapshot()

    def resume_analysis(self):
        self.maintenance = False
        self.maintenance_action = None
        self.maintenance_settled = False
        self.preview_sent = None
        # Re-detect games that started/exited while the restore dialog was open.
        if self.pids is not None:
            self.clients = engine.find_clients(self.pids) if self.pids else []
            chosen = next((c for c in self.clients if self.client and c.identity == self.client.identity), None)
            self.client = chosen or next((c for c in self.clients if engine.client_active(c)), self.clients[0] if self.clients else None)
        self.select(self.client)
        self.snapshot()

    def drain_commands(self):
        if self.closed: return
        # Honor pending user cancel/shutdown before committing ready network results.
        for _ in range(50):
            try: value = self.commands.get_nowait()
            except queue.Empty: break
            self.command(value)
            if self.closing: break
        if self.closed: return
        changed = self.account.poll()
        changed = self.drive.poll() or changed
        if self.closing:
            self.finish_shutdown()
            return
        if self.maintenance_action == 'restore' and self.maintenance_settled:
            preview = self.drive.preview_view()
            if preview and preview['previewId'] != self.preview_sent:
                self.preview_sent = preview['previewId']
                self.emit(preview)
            elif not self.drive.busy:
                self.resume_analysis()
        if changed: self.snapshot()

    def settled(self, generation):
        if not self.maintenance or generation != self.generation or self.closing or self.maintenance_settled: return
        self.maintenance_settled = True
        if self.maintenance_action == 'restore':
            if not self.drive.begin('download'): self.resume_analysis()
            else: self.snapshot()
            return
        try:
            if self.maintenance_action == 'weekly':
                self.store.roll_week()
                self.week_start = self.store.repeat_start()
            else:
                self.store.clear_all()
            self.drive.auto.reset()
        except Exception:
            self.emit(dict(type='error', message='기록 초기화를 완료하지 못했습니다.'))
        finally:
            self.resume_analysis()

    def finish_shutdown(self):
        if (self.closed or not self.worker_done or not self.account.settled or not self.drive.settled
                or any(job.is_alive() for job in self.catalog_jobs)): return
        self.closed = True
        self.timer.stop()
        self.command_timer.stop()
        self.store.close()
        self.emit(dict(type='stopped'))
        self.app.quit()

    def stop_catalog(self):
        if self.catalog_pending:
            self.catalog_pending[0].set()
            self.catalog_pending = None

    def refresh_catalog(self):
        # Finish model startup before scheduling the independent catalog check.
        if not self.initialized or self.catalog_pending or not self.settings or self.closing or self.restarting: return
        self.next_check = time.monotonic() + self.settings['refreshSeconds']
        try: api_key = load_api_key(engine.ROOT)
        except ContentError as error:
            self.catalog_message = str(error) + (' · 마지막 정상 데이터 사용 중' if self.cached else '')
            self.startup_catalog_finished = True
            self.snapshot()
            return
        cancel, results = threading.Event(), queue.Queue()
        settings, cached = self.settings, self.cached
        def run():
            try: results.put((PublicContentClient(api_key, settings, cancel).refresh(cached), None))
            except Exception as error: results.put((None, str(error)))
        self.catalog_pending = cancel, results
        self.catalog_message = '공용 데이터 변경 확인 중…'
        job = threading.Thread(target=run, daemon=True, name='PublicContent')
        self.catalog_jobs = [old for old in self.catalog_jobs if old.is_alive()]
        self.catalog_jobs.append(job)
        job.start()
        self.snapshot()

    def tick(self):
        if self.closing or self.restarting: return
        if self.catalog_pending:
            try: result, error = self.catalog_pending[1].get_nowait()
            except queue.Empty: pass
            else:
                self.catalog_pending = None
                self.startup_catalog_finished = True
                if error: self.catalog_message = error + (' · 마지막 정상 데이터 사용 중' if self.cached else '')
                else:
                    try:
                        self.cache.save(result)
                        self.cached = result
                        self.matcher = ContentMatcher(result)
                        self.catalog_message = '공용 데이터 · 최신 확인 ' + datetime.now().strftime('%H:%M')
                    except (OSError, ContentError): self.catalog_message = '공용 데이터를 보관하지 못했습니다.'
        elif self.initialized and time.monotonic() >= self.next_check: self.refresh_catalog()
        if self.initialized and self.pids and not self.maintenance and (self.client is None or not engine.client_alive(self.client)):
            self.refresh_clients()
        if self.initialized and not self.maintenance:
            if self.week_start < week_start() and (not self.drive.busy or self.drive.pending and self.drive.pending['action'] == 'upload'):
                self.pause_for('weekly')
            elif self.week_start >= week_start():
                self.drive.check_auto_upload()
        self.profile.update(self.footer.view(self.matcher, time.monotonic()))
        self.snapshot()

    def finished(self):
        self.worker_done = True
        if self.closing:
            self.finish_shutdown()
        elif self.restarting:
            if self.account.session is None: self.account.restored = False
            self.worker.deleteLater()
            self.restarting = False
            self.pids = None
            self.clients = []
            self.client = None
            self.generation = 0
            self.initialized = False
            self.startup_step = 0
            self.startup_catalog_finished = False
            self.next_check = 0
            self.error = ''
            self.last_snapshot = None
            self.start()


def main(worker_factory=None):
    engine.DATA.mkdir(parents=True, exist_ok=True)
    # Isolate C/C++ library stdout as well as Python prints from the wire protocol.
    wire = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    log = (engine.DATA / 'runtime.log').open('a', encoding='utf-8', buffering=1)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    if sys.platform == 'win32':
        import ctypes
        import msvcrt
        set_handle = ctypes.windll.kernel32.SetStdHandle
        set_handle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        set_handle.restype = ctypes.c_int
        for kind in (-11, -12): set_handle(kind & 0xffffffff, msvcrt.get_osfhandle(log.fileno()))
    sys.stdout = sys.stderr = log
    startup_trace = (engine.DATA / 'startup-stacks.log').open('w', encoding='utf-8')
    faulthandler.dump_traceback_later(20, repeat=True, file=startup_trace)
    host = None
    wire_lock = threading.Lock()
    def emit(value):
        try:
            with wire_lock: wire.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
        except (BrokenPipeError, OSError):
            if host is not None: host.commands.put(dict(type='shutdown'))
    app = QCoreApplication([])
    lock = QLockFile(str(engine.DATA / 'app.lock'))
    if not lock.tryLock(0):
        emit(dict(type='error', message='Beatrice가 이미 실행 중입니다.'))
        return 2
    try: host = Host(app, emit, worker_factory or engine.Worker)
    except Exception as error:
        emit(dict(type='error', message=str(error)))
        return 1
    if worker_factory is None:
        # Import native numerical runtimes before the Qt event loop and threads.
        # Cold first imports inside the worker can block indefinitely on Windows.
        try:
            host.progress('1 / 3 · 분석 라이브러리를 준비하는 중…')
            import numpy
            import cv2
            import ultralytics
            host.progress('1 / 3 · OCR 라이브러리를 준비하는 중…')
            import paddleocr
        except Exception as error:
            host.failed(str(error))
            host.store.close()
            return 1
    startup_check = '--engine-startup-check' in sys.argv
    if startup_check:
        # Developer check uses an isolated data directory and never binds a game.
        engine.find_clients = lambda *_: []
    def read():
        try:
            for line in sys.stdin:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict): host.commands.put(value)
                except (ValueError, TypeError): emit(dict(type='error', message='잘못된 앱 명령입니다.'))
        finally: host.commands.put(dict(type='shutdown'))
    threading.Thread(target=read, daemon=True, name='WinUICommands').start()
    host.start()
    host.worker.ready.connect(lambda _: faulthandler.cancel_dump_traceback_later())
    host.worker.failed.connect(lambda _: faulthandler.cancel_dump_traceback_later())
    try:
        return app.exec()
    finally:
        faulthandler.cancel_dump_traceback_later()
        startup_trace.close()
