"""Analysis worker: Qt Core signals/threads, no Qt widgets or screens."""
import os
import json
import time
import threading
import traceback
from datetime import datetime,timezone
from pathlib import Path
from PySide6.QtCore import QThread,Signal
from .storage import Store
from .game_window import find_clients,client_alive,client_active
from .process_watch import ProcessWatch
from .content_match import FileContentMatcher

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('BEATRICE_DATA_DIR',str(Path.home()/'BeatricePC')))

class Worker(QThread):
    status=Signal(int,str); observation=Signal(dict)
    progress=Signal(str);ready=Signal(list);failed=Signal(str)
    settled=Signal(int)
    process_changed=Signal(object)
    def __init__(self):
        super().__init__();self.stop_event=threading.Event()
        self.command_lock=threading.Lock();self.command=(0,None)
        self.process_snapshot=None
        self.capture_pause=None
        self.settled_generation=0
    def process_state(self,pids,error):
        self.process_snapshot=(pids,error);self.process_changed.emit(self.process_snapshot)
    def select(self,generation,client):
        with self.command_lock:self.command=(generation,client)
    def requested(self):
        with self.command_lock:return self.command
    def capture_wait(self,capture,reason,generation,character,tracker,dungeon_observer,coordinator):
        if capture.wait_kind=='transient':
            self.stop_event.wait(.01)
            return
        if self.capture_pause is None:
            character.reset_name_cache();dungeon_observer.reset()
            tracker.last=None;tracker.counts={f:0 for f in tracker.counts}
            tracker.replacement=None;tracker.replacement_since=None
            coordinator.capture_interrupted()
        if self.capture_pause!=reason:self.status.emit(generation,reason)
        self.capture_pause=reason
        self.stop_event.wait(.1)
    def run(self):
        store=None;capture=None;watch=None
        try:
            DATA.mkdir(parents=True,exist_ok=True)
            self.progress.emit('1 / 3 · 모델을 불러오는 중… 첫 실행은 시간이 걸릴 수 있습니다.')
            from .character_vision import CharacterVision
            from .dungeon import DungeonOCR,DungeonTracker
            from .live import LiveCoordinator
            from .obs_capture import ObsCapture
            from .ui_regions import load_config as load_ui_config,UIRegionDetector
            from .recognition_diagnostic import RecognitionDiagnostic
            from .dungeon_observer import DungeonObserver
            from .completion_overlay import CompletionOverlayDetector
            from .completion_diagnostic import CompletionDiagnostic
            ui_config=load_ui_config()
            if ui_config['mode']!='yolo':raise ValueError('YOLO 탐지만 지원합니다.')
            ui_detector=UIRegionDetector(ui_config,progress=lambda message:self.progress.emit('1 / 3 · '+message))
            self.progress.emit('1 / 3 · 한국어 OCR 모델을 불러오는 중…')
            dungeon=DungeonOCR();character=CharacterVision(reader=dungeon.reader);tracker=DungeonTracker(max_gap=5)
            dungeon_observer=DungeonObserver(dungeon)
            self.progress.emit('1 / 3 · 완료 표시 모델을 불러오는 중…')
            completion=CompletionOverlayDetector(dungeon.reader,json.loads((ROOT/'config/completion-overlay.json').read_text(encoding='utf-8')))
            completion_diagnostic=CompletionDiagnostic(DATA/'completion-diagnostics')
            from .weekly import open_week
            store=open_week(DATA,catalog=FileContentMatcher(ROOT,DATA));coordinator=LiveCoordinator(store)
            diagnostic=RecognitionDiagnostic(DATA/'recognition-diagnostics')
            last_diagnostic=0
            self.progress.emit('2 / 3 · 내장 OBS 엔진을 준비하는 중…')
            capture=ObsCapture(None,DATA)
            if not capture.prepare(self.stop_event):return
            self.progress.emit('3 / 3 · LOSTARK 클라이언트를 연결하는 중…')
            watch=ProcessWatch(self.process_state);watch.start()
            while not watch.ready.wait(.1):
                if self.stop_event.is_set():return
            if self.stop_event.is_set():return
            clients=find_clients(watch.pids) if watch.pids else []
            initial=next((c for c in clients if client_active(c)),clients[0] if clients else None)
            if initial is not None:
                self.select(1,initial);capture.bind(initial)
                deadline=time.monotonic()+3
                while not capture.binding_ready.wait(.05):
                    if self.stop_event.is_set():return
                    if not client_alive(initial) or time.monotonic()>=deadline:break
            self.ready.emit(clients)
            generation=-1
            while not self.stop_event.is_set():
                requested,client=self.requested()
                if requested!=generation:
                    generation=requested;self.capture_pause=None
                    character.reset_name_cache();tracker.reset();dungeon_observer.reset()
                    coordinator=LiveCoordinator(store)
                    capture.bind(client)
                    self.settled_generation=generation
                    self.settled.emit(generation)
                if client is None:
                    self.stop_event.wait(.1);continue
                if not client_alive(client):
                    self.status.emit(generation,'클라이언트 실행 대기')
                    self.stop_event.wait(.2);continue
                started=time.monotonic()
                try:frame,reason=capture.grab()
                except RuntimeError:
                    if not client_alive(client):continue
                    raise
                at=capture.observed_at if frame is not None else datetime.now(timezone.utc)
                if frame is None:
                    self.capture_wait(capture,reason,generation,character,tracker,dungeon_observer,coordinator)
                    continue
                self.capture_pause=None
                regions=ui_detector.locate(frame)
                detected_at=time.monotonic()
                identity=character.analyze_detected(frame,regions,seconds=started,
                    confirmed_name=coordinator.identity.current if not coordinator.identity.blocked else None)
                character_at=time.monotonic()
                write_diagnostic=started-last_diagnostic>=2
                if write_diagnostic:
                    (DATA/'character-diagnostic.json').write_text(json.dumps(dict(
                        observedAt=at.isoformat(),frameSize=list(frame.shape[:2]),
                        observation=identity),ensure_ascii=False,indent=2),encoding='utf-8')
                    last_diagnostic=started
                blocked=any(regions.get(k,{}).get('status')!='missing' for k in ('game_menu','switch_dialog')) or identity.get('switchLoading',False)
                blocked=blocked or any(identity.get(k) for k in ('serverSelection','characterSelection','loginLoading','selectionUncertain'))
                dungeon_observation,boxes=dungeon_observer.analyze(frame,regions,started,blocked=blocked)
                if self.requested()!=(generation,client) or not client_alive(client):continue
                if not blocked and coordinator.completion_context is not None:
                    dungeon_observation['completionOverlay']=completion.analyze(frame)
                if self.requested()!=(generation,client) or not client_alive(client):continue
                context=tracker.update(at.timestamp(),dungeon_observation)
                dungeon_at=time.monotonic()
                if write_diagnostic:
                    (DATA/'dungeon-diagnostic.json').write_text(json.dumps(dict(
                        mode='ui_yolo',observedAt=at.isoformat(),observation=dungeon_observation),
                        ensure_ascii=False,indent=2),encoding='utf-8')
                try:
                    state=coordinator.update(at,identity,boxes,context)
                except Exception as error:
                    # Preserve the triggering frame even if the DB transaction fails.
                    try:
                        completion_diagnostic.record(frame,dict(observedAt=at.isoformat(),
                            modelConfig=ui_config,completionModelConfig=completion.config,
                            character=identity,dungeon=dungeon_observation,gates=boxes,
                            error=str(error),state=dict(result=dict(completionDecision=dict(
                                reason='coordinator_error',observation=context.get('completionOverlay',{}))))))
                    except OSError:
                        pass  # The original failure is logged by the outer handler.
                    raise
                if any(action['type']=='suspend' for action in state['identity']['actions']):
                    tracker.reset()
                    dungeon_observer.reset()
                    state['dungeon']=tracker.update(at.timestamp(),{})
                state['recognitionMode']='캐릭터·던전 분리 탐지' if ui_config.get('architecture')=='split' else 'UI 자동 탐지'
                state['recognitionMode']='내장 OBS · '+state['recognitionMode']
                state['milliseconds']=round((time.monotonic()-started)*1000)
                state['timingsMs']=dict(detection=round((detected_at-started)*1000),character=round((character_at-detected_at)*1000),dungeon=round((dungeon_at-character_at)*1000))
                state['size']=f'{frame.shape[1]} × {frame.shape[0]}'
                state['generation']=generation
                try:
                    report=dict(observedAt=at.isoformat(),
                        capture=capture.frame_info,
                        modelConfig=ui_config,completionModelConfig=completion.config,character=identity,dungeon=dungeon_observation,
                        gates=boxes,state=state)
                    completion_diagnostic.record(frame,report)
                    diagnostic.record(frame,report,now=started)
                except OSError as exc:
                    # 진단 저장 실패가 인식 및 기록 루프를 중단하지 않게 합니다.
                    self.status.emit(generation,f'진단 저장 실패: {exc}')
                self.observation.emit(state)
                interval=.1 if state['result'].get('gateRecheckPending') else .5
                self.stop_event.wait(max(0,interval-(time.monotonic()-started)))
        except Exception as exc:
            with (DATA/'errors.log').open('a',encoding='utf-8') as f:f.write(traceback.format_exc()+'\n')
            self.failed.emit(f'오류: {exc} — errors.log를 확인해주세요.')
        finally:
            try:
                if capture is not None:capture.close()
                if store is not None:store.close()
            finally:
                if watch is not None:
                    watch.stop_event.set();watch.join()
