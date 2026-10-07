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
from . import desktop
from .storage import Store
from .content_match import record_detail
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


def observation_view(value):
    identity = value.get('identity', {})
    allowed = identity.get('recordingAllowed', False)
    name = identity.get('currentName') if allowed else identity.get('previewName')
    message = '플레이 중' if allowed else '캐릭터 확인 중'
    if identity.get('status') in ('switching', 'initial_login_loading', 'initial_login_selection'):
        name = identity.get('pendingName') or name
        message = {'switching': '캐릭터 변경 중', 'initial_login_loading': '접속 중',
                   'initial_login_selection': '캐릭터 선택 중'}[identity['status']]
    dungeon = value.get('dungeon', {})
    # Only currently verified context belongs in the detected footer.
    visible = dungeon.get('contextStatus') == 'ocr_verified' and dungeon.get('currentRaidPanel')
    result = value.get('result', {})
    # Stored completions are monotonic; the current run's HUD can be in progress
    # even when every gate already has a saved completion from an earlier run.
    states = result.get('observedStates', result.get('stableStates')) or []
    gate = next((i for i, state in enumerate(states, 1) if state == '진행중'), None)
    unit = '레이드 전체' if dungeon.get('raidKind') == 'gateless' else f'{gate}관문' if gate else ''
    return dict(character=name or '캐릭터 확인 대기', message=message, active=allowed,
                dungeon=dungeon.get('dungeonName') if visible else None,
                dungeonSubtitle=' · '.join(filter(None, [dungeon.get('difficulty'), unit])) if visible else '',
                dungeonState='진행 중',
                diagnostics=value.get('recordingStatus', ''))


def character_status(message):
    """Keep capture engine diagnostics out of the character status line."""
    if 'OBS' not in message.upper(): return message
    if '최소화' in message: return '게임 최소화'
    if '연결' in message: return '게임 화면 연결 중'
    if '화면 변화 없음' in message: return '화면 변화 대기'
    return '게임 화면 대기'


class Host(QObject):

    def __init__(self, app, emit, worker_factory=desktop.Worker):
        super().__init__()
        self.app, self.emit, self.worker_factory = app, emit, worker_factory
        self.store = Store(desktop.DATA / 'records.sqlite3')
        self.worker = None
        self.clients = []
        self.client = None
        self.pids = None
        self.generation = 0
        self.closing = self.restarting = self.maintenance = False
        self.initialized = False
        self.error = ''
        self.status = '모델을 준비하는 중…'
        self.profile = dict(character='캐릭터 확인 대기', message='초기화 중', active=False)
        self.cached = self.cache = self.settings = None
        self.catalog_message = '공용 데이터 · 확인 대기'
        self.catalog_pending = None
        self.next_check = 0
        self.last_snapshot = None
        self.commands = queue.Queue()
        try:
            self.settings = load_settings(desktop.ROOT)
            self.cache = ContentCache(desktop.DATA, self.settings)
            self.cached = self.cache.load()
            if self.cached: self.catalog_message = '공용 데이터 · 로컬 보관본'
        except ContentError as error:
            self.catalog_message = str(error)
        self.command_timer = QTimer(self)
        self.command_timer.timeout.connect(self.drain_commands)
        self.command_timer.start(50)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def start(self):
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
        with (desktop.DATA/'startup-progress.log').open('a',encoding='utf-8') as log:
            log.write(datetime.now().isoformat(timespec='seconds')+' · '+message+'\n')
        self.status = message
        self.profile['message'] = '초기화 중'
        self.snapshot()

    def ready(self, clients):
        if self.closing or self.restarting: return
        self.initialized = True
        self.error = ''
        self.generation, self.client = self.worker.requested()
        self.clients = clients
        self.status = '분석 중' if self.client else '게임 실행 대기'
        self.profile['message'] = '탐지 대기' if self.client else '게임 실행 대기'
        self.snapshot()

    def refresh_clients(self):
        clients = desktop.find_clients(self.pids) if self.pids else []
        chosen = next((c for c in clients if self.client and c.identity == self.client.identity), None)
        chosen = chosen or next((c for c in clients if desktop.client_active(c)), clients[0] if clients else None)
        self.clients = clients
        if chosen != self.client and not self.maintenance and not self.error:
            self.select(chosen)

    def select(self, client):
        self.client = client
        self.generation += 1
        self.worker.select(self.generation, client)
        self.profile = dict(character='캐릭터 확인 대기', message='게임 창 연결 중' if client else '게임 실행 대기', active=False)
        self.status = self.profile['message']

    def process_changed(self, snapshot):
        if self.closing or self.restarting: return
        self.pids, error = snapshot
        if error: self.status = error
        if self.initialized: self.refresh_clients()
        self.snapshot()

    def observation(self, value):
        if value.get('generation') != self.generation or self.maintenance or self.closing or self.restarting: return
        self.profile = observation_view(value)
        self.status = value.get('recordingStatus', '분석 중')
        self.snapshot()

    def worker_status(self, generation, message):
        if generation != self.generation or self.maintenance or self.closing or self.restarting: return
        self.status = message
        self.profile = dict(character=self.profile['character'], message=character_status(message), active=False)
        self.snapshot()

    def failed(self, message):
        self.error = self.status = message
        self.profile = dict(character='캐릭터 확인 대기', message='분석 오류', active=False)
        self.maintenance = False
        self.snapshot()

    def snapshot(self):
        records = [record_view(row, self.cached) for row in self.store.state_records() if row['state'] == '완료']
        records.sort(key=lambda row: datetime.fromisoformat(row['observedAt']).timestamp(), reverse=True)
        value = dict(type='snapshot', status=self.status, error=self.error, profile=self.profile,
                     records=records, clients=[asdict(client) for client in self.clients],
                     selected=self.client.hwnd if self.client else 0,
                     catalogStatus=self.catalog_message,
                     busy=self.maintenance or self.restarting or (not self.initialized and not self.error),
                     catalogBusy=self.catalog_pending is not None)
        serialized = json.dumps(value, ensure_ascii=False)
        if serialized != self.last_snapshot:
            self.last_snapshot = serialized
            self.emit(value)

    def command(self, value):
        if self.closing: return
        kind = value.get('type')
        if kind == 'shutdown':
            self.closing = True
            self.stop_catalog()
            self.worker.stop_event.set()
            if not self.worker.isRunning(): self.finished()
        elif kind == 'restart' and not self.maintenance and not self.restarting:
            self.restarting = True
            self.stop_catalog()
            self.status = '현재 작업을 종료하고 초기화하는 중…'
            self.profile = dict(character='캐릭터 확인 대기', message='재실행 중', active=False)
            self.worker.stop_event.set()
            self.snapshot()
            if not self.worker.isRunning(): self.finished()
        elif kind == 'select' and self.initialized and not (self.maintenance or self.restarting or self.error):
            chosen = next((c for c in self.clients if c.hwnd == value.get('hwnd')), None)
            if chosen: self.select(chosen)
            self.snapshot()
        elif kind == 'delete' and self.initialized and not (self.maintenance or self.restarting or self.error):
            # Mutate only after the worker acknowledges the paused generation.
            self.maintenance = True
            self.generation += 1
            self.worker.select(self.generation, None)
            self.status = '기록 삭제 준비 중…'
            self.snapshot()
        elif kind == 'catalog_refresh': self.refresh_catalog()
        elif kind == 'catalog':
            rows = []
            for dungeon, modes in (self.cached or {}).get('content', {}).items():
                for mode, gates in modes.items():
                    for gate, values in gates.items():
                        rows.append(dict(dungeon=dungeon, mode=mode, gate=gate, **values))
            self.emit(dict(type='catalog', rows=rows))

    def drain_commands(self):
        for _ in range(50):
            try: value = self.commands.get_nowait()
            except queue.Empty: return
            self.command(value)

    def settled(self, generation):
        if not self.maintenance or generation != self.generation or self.closing: return
        try:
            self.store.clear_all()
        except Exception:
            self.emit(dict(type='error', message='기록을 삭제하지 못했습니다.'))
        finally:
            self.maintenance = False
            self.select(self.client)
            self.snapshot()

    def stop_catalog(self):
        if self.catalog_pending:
            self.catalog_pending[0].set()
            self.catalog_pending = None

    def refresh_catalog(self):
        # Finish model startup before scheduling the independent catalog check.
        if not self.initialized or self.catalog_pending or not self.settings or self.closing or self.restarting: return
        self.next_check = time.monotonic() + self.settings['refreshSeconds']
        try: api_key = load_api_key(desktop.ROOT)
        except ContentError as error:
            self.catalog_message = str(error)
            self.snapshot()
            return
        cancel, results = threading.Event(), queue.Queue()
        settings, cached = self.settings, self.cached
        def run():
            try: results.put((PublicContentClient(api_key, settings, cancel).refresh(cached), None))
            except Exception as error: results.put((None, str(error)))
        self.catalog_pending = cancel, results
        self.catalog_message = '공용 데이터 변경 확인 중…'
        threading.Thread(target=run, daemon=True, name='PublicContent').start()
        self.snapshot()

    def tick(self):
        if self.closing or self.restarting: return
        if self.catalog_pending:
            try: result, error = self.catalog_pending[1].get_nowait()
            except queue.Empty: pass
            else:
                self.catalog_pending = None
                if error: self.catalog_message = error + (' · 마지막 정상 데이터 사용 중' if self.cached else '')
                else:
                    try:
                        self.cache.save(result)
                        self.cached = result
                        self.catalog_message = '공용 데이터 · 최신 확인 ' + datetime.now().strftime('%H:%M')
                    except (OSError, ContentError): self.catalog_message = '공용 데이터를 보관하지 못했습니다.'
        elif self.initialized and time.monotonic() >= self.next_check: self.refresh_catalog()
        if self.initialized and self.pids and not self.maintenance and (self.client is None or not desktop.client_alive(self.client)):
            self.refresh_clients()
        self.snapshot()

    def finished(self):
        if self.closing:
            self.timer.stop()
            self.command_timer.stop()
            self.store.close()
            self.emit(dict(type='stopped'))
            self.app.quit()
        elif self.restarting:
            self.worker.deleteLater()
            self.restarting = False
            self.pids = None
            self.clients = []
            self.client = None
            self.generation = 0
            self.initialized = False
            self.error = ''
            self.last_snapshot = None
            self.start()


def main(worker_factory=None):
    desktop.DATA.mkdir(parents=True, exist_ok=True)
    # Isolate C/C++ library stdout as well as Python prints from the wire protocol.
    wire = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8', buffering=1)
    log = (desktop.DATA / 'runtime.log').open('a', encoding='utf-8', buffering=1)
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
    startup_trace = (desktop.DATA / 'startup-stacks.log').open('w', encoding='utf-8')
    faulthandler.dump_traceback_later(20, repeat=True, file=startup_trace)
    host = None
    wire_lock = threading.Lock()
    def emit(value):
        try:
            with wire_lock: wire.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
        except (BrokenPipeError, OSError):
            if host is not None: host.commands.put(dict(type='shutdown'))
    app = QCoreApplication([])
    lock = QLockFile(str(desktop.DATA / 'app.lock'))
    if not lock.tryLock(0):
        emit(dict(type='error', message='Beatrice가 이미 실행 중입니다.'))
        return 2
    try: host = Host(app, emit, worker_factory or desktop.Worker)
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
        desktop.find_clients = lambda *_: []
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
    if startup_check:
        host.worker.ready.connect(lambda _: host.command(dict(type='shutdown')))
    host.worker.ready.connect(lambda _: faulthandler.cancel_dump_traceback_later())
    host.worker.failed.connect(lambda _: faulthandler.cancel_dump_traceback_later())
    try:
        return app.exec()
    finally:
        faulthandler.cancel_dump_traceback_later()
        startup_trace.close()
