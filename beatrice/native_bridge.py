"""Headless analysis host for the WinUI desktop (UTF-8 JSON lines over pipes).

Worker events are queued onto the owner thread; Store and commands stay there.
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

from .thread_events import EventLoop
from .instance_lock import InstanceLock
from . import engine_worker as engine
from .weekly import open_week, week_start
from .lostark_api import LostArkApiKey
from .account_service import GoogleAccount
from .drive_service import PersonalDrive
from .native_presentation import record_view, empty_profile, character_view, progress_unit, observation_view, DungeonFooter
from .catalog_service import CatalogService
from .character_catalog import CharacterCatalog


class Host:

    def __init__(self, app, emit, worker_factory=engine.Worker):
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
        self.character_catalog = CharacterCatalog(engine.DATA, key_available=lambda: self.lostark_api.view()["configured"])
        self.account = GoogleAccount(engine.ROOT, engine.DATA)
        self.drive = PersonalDrive(engine.ROOT, engine.DATA, self.account, self.store)
        self.startup_step = 0
        self.error = ''
        self.status = '모델을 준비하는 중…'
        self.profile = empty_profile()
        self.footer = DungeonFooter()
        self.catalog = CatalogService(engine.ROOT, engine.DATA)
        self.store.refresh_catalog_matches(self.catalog.matcher)
        self.last_snapshot = None
        self.commands = queue.Queue()
        self.command_timer = app.call_later(.05,self.drain_commands,repeat=True)
        self.timer = app.call_later(1,self.tick,repeat=True)

    def start(self):
        self.worker_done = False
        self.worker = self.worker_factory()
        worker=self.worker
        for name in ('progress','ready','observation','process_changed','status','failed','settled','finished'):
            handler=self.worker_status if name=='status' else getattr(self,name)
            def receive(*args,handler=handler,worker=worker):
                self.app.dispatch(self.worker_event,worker,handler,args)
            getattr(worker,name).connect(receive)
        self.worker.start()
        self.snapshot()

    def worker_event(self,worker,handler,args):
        # A restarted worker's queued callbacks cannot affect the new session.
        if worker is self.worker and not self.closed:handler(*args)

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
        if not self.catalog.settings: self.catalog.startup_finished = True
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
        self.profile.update(self.footer.view(self.catalog.matcher, now))
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
        records = [record_view(row, self.catalog.cached, matcher=self.catalog.matcher) for row in self.store.history_records() if not row['isTest']]
        self.character_catalog.ensure([self.profile['character']] + [row['character'] for row in records])
        self.character_catalog.decorate(records, self.catalog.emblem_path)
        records.sort(key=lambda row: datetime.fromisoformat(row['observedAt']).timestamp() if row.get('observedAt') else float('-inf'), reverse=True)
        profile = dict(self.profile, **{key: value for key, value in
                       self.character_catalog.character_view(self.profile['character'], self.catalog.emblem_path).items()
                       if key != 'character'})
        value = dict(type='snapshot', status=self.status, error=self.error, profile=profile,
                     records=records, clients=[asdict(client) for client in self.clients],
                     selected=self.client.hwnd if self.client else 0,
                     catalogStatus=self.catalog.message,
                     catalogLastUpdated=(self.catalog.cached or {}).get('checkedAt', ''),
                     catalogRefreshAvailableAt=self.catalog.refresh_available_at,
                     busy=self.maintenance or self.restarting or self.drive.busy or self.account.busy or (not self.initialized and not self.error),
                     google=self.account.view(),
                     lostArkApi=self.lostark_api.view(),
                     drive=dict(self.drive.view(), available=self.drive.available and self.can_change_records()),
                     restarting=self.restarting,
                     catalogBusy=self.catalog.pending is not None,
                     startupStep=0 if self.restarting else 3 if self.initialized and self.catalog.startup_finished else self.startup_step,
                     startupReady=self.initialized and self.catalog.startup_finished and not self.restarting)
        serialized = json.dumps(value, ensure_ascii=False)
        if serialized != self.last_snapshot:
            self.last_snapshot = serialized
            self.emit(value)

    def command(self, value):
        if self.closing: return
        kind = value.get('type')
        if kind == 'shutdown':
            self.closing = True
            self.character_catalog.stop()
            self.account.shutdown()
            self.drive.shutdown()
            self.stop_catalog()
            self.worker.stop_event.set()
            if not self.worker.is_alive(): self.finished()
        elif kind == 'restart' and not self.maintenance and not self.restarting and not self.drive.busy and not self.account.busy:
            self.restarting = True
            self.error = ''
            self.stop_catalog()
            self.status = '현재 작업을 종료하고 초기화하는 중…'
            self.profile = empty_profile()
            self.footer = DungeonFooter()
            self.worker.stop_event.set()
            self.snapshot()
            if not self.worker.is_alive(): self.finished()
        elif kind == 'select' and self.initialized and not (self.maintenance or self.restarting or self.error or self.drive.busy or self.account.busy):
            chosen = next((c for c in self.clients if c.hwnd == value.get('hwnd')), None)
            if chosen: self.select(chosen)
            self.snapshot()
        elif kind == 'delete' and self.can_change_records():
            self.pause_for('delete')
        elif kind == 'lostark_api_save':
            success = self.lostark_api.save(value.get('key'))
            if success: self.character_catalog.credentials_changed()
            self.emit(dict(type='lostark_api_saved', success=success, **self.lostark_api.view()))
            self.snapshot()
        elif kind == 'lostark_api_clear':
            success = self.lostark_api.clear()
            if success: self.character_catalog.credentials_changed()
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
            if (self.initialized and self.catalog.settings and not self.catalog.pending and not self.restarting
                    and not self.maintenance and time.time() >= self.catalog.refresh_available_at):
                self.catalog.reserve_manual_refresh()
                self.refresh_catalog()
            self.snapshot()
        elif kind == 'catalog':
            self.emit(dict(type='catalog', rows=self.catalog.rows()))

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
        changed = self.character_catalog.poll()
        changed = self.account.poll() or changed
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
                or not self.catalog.settled or not self.character_catalog.settled): return
        self.closed = True
        self.timer.stop()
        self.command_timer.stop()
        self.store.close()
        self.emit(dict(type='stopped'))
        self.app.quit()

    def stop_catalog(self):
        self.catalog.stop()

    def refresh_catalog(self):
        if not self.initialized or self.closing or self.restarting:
            return
        self.catalog.refresh()
        self.snapshot()

    def tick(self):
        if self.closing or self.restarting: return
        if self.catalog.pending:
            if self.catalog.poll() and not self.maintenance:
                self.store.refresh_catalog_matches(self.catalog.matcher)
        elif self.initialized and time.monotonic() >= self.catalog.next_check:
            self.refresh_catalog()
        if self.initialized and self.pids and not self.maintenance and (self.client is None or not engine.client_alive(self.client)):
            self.refresh_clients()
        if self.initialized and not self.maintenance:
            if self.week_start < week_start() and (not self.drive.busy or self.drive.pending and self.drive.pending['action'] == 'upload'):
                self.pause_for('weekly')
            elif self.week_start >= week_start():
                self.drive.check_auto_upload()
        self.profile.update(self.footer.view(self.catalog.matcher, time.monotonic()))
        self.snapshot()

    def finished(self):
        self.worker.join()
        self.worker_done = True
        if self.closing:
            self.finish_shutdown()
        elif self.restarting:
            if self.account.session is None: self.account.restored = False
            self.worker.join()
            self.restarting = False
            self.pids = None
            self.clients = []
            self.client = None
            self.generation = 0
            self.initialized = False
            self.startup_step = 0
            self.catalog.startup_finished = False
            self.catalog.next_check = 0
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
    app = EventLoop()
    lock = InstanceLock(engine.DATA / 'app.lock')
    if not lock.acquire():
        emit(dict(type='error', message='Beatrice가 이미 실행 중입니다.'))
        faulthandler.cancel_dump_traceback_later()
        startup_trace.close()
        return 2
    try:
        try: host = Host(app, emit, worker_factory or engine.Worker)
        except Exception as error:
            emit(dict(type='error', message=str(error)))
            return 1
        if worker_factory is None:
            # Import native numerical runtimes before the event loop and threads.
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
            from .recognition import service as recognition_service
            recognition_service.find_clients = lambda *_: []
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
        return app.run()
    finally:
        faulthandler.cancel_dump_traceback_later()
        startup_trace.close()
        lock.release()
