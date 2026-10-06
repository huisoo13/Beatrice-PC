"""Qt UI는 메인 스레드, 모델과 캡처/저장은 단일 작업자 스레드에서 실행합니다."""
import os
import json
import time
import threading
import traceback
from datetime import datetime,timezone
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QTimer,QLockFile,Qt
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QPushButton,QLabel,QComboBox,QTableWidget,QTableWidgetItem,QHeaderView)
from .storage import Store
from .windows_capture import find_clients,client_alive,client_active
from .process_watch import ProcessWatch
from .google_login_ui import GoogleLogin
from .drive_ui import DrivePanel
from .public_content_ui import PublicContentPanel
from .content_match import FileContentMatcher
from .record_detail_ui import RecordDetailDialog

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
    def process_state(self,pids,error):
        self.process_snapshot=(pids,error);self.process_changed.emit(self.process_snapshot)
    def select(self,generation,client):
        with self.command_lock:self.command=(generation,client)
    def requested(self):
        with self.command_lock:return self.command
    def run(self):
        store=None;capture=None;watch=None
        try:
            self.progress.emit('1 / 2 · 모델을 불러오는 중… 첫 실행은 시간이 걸릴 수 있습니다.')
            from .character_vision import CharacterVision
            from .dungeon import DungeonOCR,DungeonTracker
            from .live import LiveCoordinator
            from .windows_capture import WindowCapture
            from .ui_regions import load_config as load_ui_config,UIRegionDetector
            from .recognition_diagnostic import RecognitionDiagnostic
            from .dungeon_observer import DungeonObserver
            from .completion_overlay import CompletionOverlayDetector
            from .completion_diagnostic import CompletionDiagnostic
            ui_config=load_ui_config()
            if ui_config['mode']!='yolo':raise ValueError('YOLO 탐지만 지원합니다.')
            ui_detector=UIRegionDetector(ui_config)
            dungeon=DungeonOCR();character=CharacterVision(reader=dungeon.reader);tracker=DungeonTracker(max_gap=5)
            dungeon_observer=DungeonObserver(dungeon)
            completion=CompletionOverlayDetector(dungeon.reader,json.loads((ROOT/'config/completion-overlay.json').read_text(encoding='utf-8')))
            completion_diagnostic=CompletionDiagnostic(DATA/'completion-diagnostics')
            store=Store(DATA/'records.sqlite3',catalog=FileContentMatcher(ROOT,DATA));coordinator=LiveCoordinator(store)
            diagnostic=RecognitionDiagnostic(DATA/'recognition-diagnostics')
            last_diagnostic=0
            self.progress.emit('2 / 2 · LOSTARK 클라이언트를 탐색하는 중…')
            watch=ProcessWatch(self.process_state);watch.start()
            while not watch.ready.wait(.1):
                if self.stop_event.is_set():return
            if self.stop_event.is_set():return
            self.ready.emit(find_clients(watch.pids) if watch.pids else [])
            generation=-1
            while not self.stop_event.is_set():
                requested,client=self.requested()
                if requested!=generation:
                    if capture is not None:capture.close()
                    capture=None;generation=requested
                    character.reset_name_cache();tracker.reset();dungeon_observer.reset()
                    coordinator=LiveCoordinator(store)
                    if client is not None:capture=WindowCapture(client.hwnd)
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
                at=datetime.now(timezone.utc)
                if frame is None:
                    character.reset_name_cache()
                    dungeon_observer.reset()
                    context=tracker.update(at.timestamp(),{})
                    state=coordinator.update(at,{},[],context)
                    state.update(milliseconds=0,size='캡처 대기',generation=generation)
                    self.observation.emit(state)
                    self.status.emit(generation,reason);self.stop_event.wait(.5);continue
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
                state['milliseconds']=round((time.monotonic()-started)*1000)
                state['timingsMs']=dict(detection=round((detected_at-started)*1000),character=round((character_at-detected_at)*1000),dungeon=round((dungeon_at-character_at)*1000))
                state['size']=f'{frame.shape[1]} × {frame.shape[0]}'
                state['generation']=generation
                try:
                    report=dict(observedAt=at.isoformat(),
                        modelConfig=ui_config,completionModelConfig=completion.config,character=identity,dungeon=dungeon_observation,
                        gates=boxes,state=state)
                    completion_diagnostic.record(frame,report)
                    diagnostic.record(frame,report,now=started)
                except OSError as exc:
                    # 진단 저장 실패가 인식 및 기록 루프를 중단하지 않게 합니다.
                    self.status.emit(generation,f'진단 저장 실패: {exc}')
                self.observation.emit(state)
                self.stop_event.wait(max(0,.5-(time.monotonic()-started)))
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

class Window(QMainWindow):
    restart_requested=Signal()
    def __init__(self,worker,clients,error=''):
        super().__init__();DATA.mkdir(parents=True,exist_ok=True)
        self.worker=worker;self.closing=False;self.store=Store(DATA/'records.sqlite3')
        self.clients=[];self.client=None;self.generation=0;self.settled_generation=0;self.analyzing=False;self.error=error
        self.process_pids,self.watch_error=worker.process_snapshot or (frozenset(c.pid for c in clients),'')
        self.setWindowTitle('Beatrice PC · 실시간 관문 기록 테스트');self.resize(1000,620)
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        self.google_login=GoogleLogin(ROOT,DATA,self);layout.addWidget(self.google_login)
        row=QHBoxLayout();self.targets=QComboBox();self.targets.setMinimumWidth(330)
        refresh=QPushButton('새로고침');refresh.setToolTip('앱을 초기화하고 스플래시부터 다시 시작합니다. 저장된 기록은 유지됩니다.')
        refresh.clicked.connect(self.restart_requested.emit)
        self.refresh_button=refresh
        row.addWidget(QLabel('대상'));row.addWidget(self.targets,1);row.addWidget(refresh)
        self.targets.currentIndexChanged.connect(self.target_changed)
        layout.addLayout(row)
        controls=QHBoxLayout();self.start_button=QPushButton('시작');self.stop_button=QPushButton('정지');self.delete_button=QPushButton('기록 전체 삭제')
        for button in (self.start_button,self.stop_button,self.delete_button):button.setMinimumHeight(42);controls.addWidget(button)
        layout.addLayout(controls);self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start);self.stop_button.clicked.connect(self.stop);self.delete_button.clicked.connect(self.delete)
        self.character=QLabel('현재 캐릭터: 확인 대기 — 게임에서 ESC 메뉴를 잠시 유지해주세요.')
        self.status_dot=QLabel('●');self.status_label=QLabel();self.status_label.setWordWrap(True)
        status_row=QHBoxLayout();status_row.addWidget(self.status_dot);status_row.addWidget(self.status_label,1)
        layout.addWidget(self.character);layout.addLayout(status_row)
        self.detail=QLabel();self.detail.setWordWrap(True);layout.addWidget(self.detail)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['변경 확인 시각 (PC 현지 시간)','캐릭터','던전','난이도','관문','상태','확인 근거'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table,1)
        self.record_dialog=None
        self.table.cellClicked.connect(self.show_record_detail)
        note=QLabel('완료된 관문만 저장·표시하며 동일 캐릭터·던전·관문은 전체 삭제 전까지 한 번만 기록합니다.\n'
            '진행 전·진행 중 상태는 분석 중에만 유지합니다. 후속 관문 완료는 앞선 관문 완료를 보완합니다.\n'
            '화면에서 패널을 자동으로 찾습니다. 다른 해상도·UI 배율·배치에서는 추가 검증이 필요합니다.');note.setWordWrap(True);layout.addWidget(note)
        layout.addWidget(QLabel('저장 위치: '+str(DATA)))
        self.drive=DrivePanel(ROOT,DATA,self.google_login,self.store,
            lambda: not self.analyzing and self.settled_generation==self.generation,
            self.drive_changed,self)
        layout.insertWidget(1,self.drive)
        self.public_content=PublicContentPanel(ROOT,DATA,self)
        layout.insertWidget(2,self.public_content)
        self.worker.status.connect(self.worker_status);self.worker.observation.connect(self.update_observation)
        self.worker.failed.connect(self.worker_failed);self.worker.finished.connect(self.stopped)
        self.worker.settled.connect(self.command_settled)
        self.worker.process_changed.connect(self.process_changed)
        self.apply_clients([c for c in clients if c.pid in self.process_pids]);self.reload()
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(1000)
    def set_status(self,text,color):
        self.status_label.setText(text);self.status_dot.setStyleSheet(f'color: {color}; font-size: 22px;')
    def update_status(self):
        busy=self.drive.busy
        self.refresh_button.setEnabled(not busy)
        self.start_button.setEnabled(bool(self.client) and not self.analyzing and not self.error and not busy)
        self.stop_button.setEnabled(self.analyzing)
        self.delete_button.setEnabled(not self.analyzing and self.settled_generation==self.generation and not busy)
        self.targets.setEnabled(not self.analyzing and not busy)
        if self.error:self.set_status(self.error,'#dc2626')
        elif self.client is None:
            if self.process_pids:self.set_status('클라이언트 시작 중 · 게임 창 생성 대기','#ca8a04')
            else:self.set_status('클라이언트 실행 대기','#dc2626')
        elif not client_active(self.client):self.set_status('게임 화면 활성화 대기','#ca8a04')
        elif self.analyzing and self.detail.text().startswith('분석 중'):
            self.set_status('분석 중','#2563eb')
        else:self.set_status('클라이언트 감지됨','#16a34a')
        if self.watch_error:
            self.status_label.setText(self.status_label.text()+' · '+self.watch_error)
    def apply_clients(self,clients):
        previous=self.client.identity if self.client else None
        self.clients=clients
        chosen=next((c for c in clients if c.identity==previous),None)
        if chosen is None:
            chosen=next((c for c in clients if client_active(c)),clients[0] if clients else None)
        self.targets.blockSignals(True);self.targets.clear()
        for c in clients:self.targets.addItem(f'{c.title} · PID {c.pid}',c)
        if chosen is not None:self.targets.setCurrentIndex(clients.index(chosen))
        self.targets.blockSignals(False);self.client=chosen
        if previous!=(chosen.identity if chosen else None):
            self.generation+=1
            self.worker.select(self.generation,chosen if self.analyzing else None)
            self.detail.clear();self.character.setText('현재 캐릭터: 확인 대기')
        self.update_status()
    def target_changed(self,index):
        if 0<=index<len(self.clients):
            self.client=self.clients[index];self.detail.clear();self.update_status()
    def refresh(self):
        self.apply_clients(find_clients(self.process_pids) if self.process_pids else [])
    def process_changed(self,snapshot):
        self.process_pids,self.watch_error=snapshot
        if not self.closing:self.refresh()
    def tick(self):
        self.reload()
        # The background watcher polls processes; only scan windows for known PIDs.
        if self.process_pids and (self.client is None or not client_alive(self.client)):self.refresh()
        else:self.update_status()
    def start(self):
        if self.analyzing or self.error or self.drive.busy:return
        self.refresh()
        if self.client is None:return
        self.analyzing=True;self.generation+=1;self.detail.setText('첫 캡처 프레임 대기 중')
        self.worker.select(self.generation,self.client);self.update_status()
    def stop(self):
        self.analyzing=False;self.generation+=1;self.worker.select(self.generation,None)
        self.detail.setText('정지됨 · 기록은 PC에 보존됩니다.');self.update_status()
    def stopped(self):
        if self.closing:self.close()
    def command_settled(self,generation):
        self.settled_generation=generation;self.update_status()
    def worker_failed(self,message):
        self.error=message;self.analyzing=False;self.update_status()
    def worker_status(self,generation,message):
        if generation!=self.generation or not self.analyzing:return
        self.detail.setText(message);self.update_status()
    def update_observation(self,value):
        if value.get('generation')!=self.generation or not self.analyzing:return
        identity=value['identity'];name=identity['currentName'] if identity['recordingAllowed'] else '캐릭터 확인 대기'
        if not identity['recordingAllowed'] and identity.get('previewName'):
            name=identity['previewName']+' (확인 중)'
        if identity.get('status')=='switching' and identity.get('pendingName'):
            name=identity['pendingName']+' · 변경 중'
        if identity.get('status')=='initial_login_loading':
            name=(identity.get('pendingName') or '캐릭터')+' · 접속 중'
        elif identity.get('status')=='initial_login_selection':
            name=(identity.get('pendingName') or identity.get('previewName') or '캐릭터')+' · 선택 중'
        self.character.setText('현재 캐릭터: '+(name or '확인 대기'))
        dungeon=value['dungeon']
        def display(field,waiting):
            return dungeon.get(field) or ((dungeon['preview'][field]+' (확인 중)') if dungeon.get('preview',{}).get(field) else waiting)
        summary=f"{display('dungeonName','던전 확인 대기')} / {display('difficulty','난이도 확인 대기')}"
        self.detail.setText(f"분석 중 · {value.get('recognitionMode','캡처 대기')} · {summary} · {value.get('recordingStatus','')} · {value['size']} · 프레임 분석 {value['milliseconds']} ms" if value['size']!='캡처 대기' else '캡처 프레임 대기 중')
        self.update_status()
    def reload(self):
        records=self.store.state_records()
        records.sort(key=lambda e:(e.get('characterName') or '',e.get('dungeonName') or '',e['gate']));self.table.setRowCount(len(records))
        for row,event in enumerate(records):
            when=datetime.fromisoformat(event['observedAt']).astimezone().strftime('%Y-%m-%d %H:%M:%S')
            if event.get('evidenceType')=='drive_import':when+=' (불러옴)'
            evidence={'later_gate_completion':'후속 관문으로 보완','legacy_completion':'기존 완료 기록','direct':'직접 관측','completion_banner':'완료 배너','gate_breakthrough':'관문 돌파 표시','dungeon_clear':'던전 클리어 표시','drive_import':'Google Drive'}
            unit=event.get('gateName') or ('레이드 전체' if event.get('completionScope')=='raid' else str(event['gate'])+'관문')
            values=[when,event.get('characterName') or '캐릭터 확인 대기',event.get('dungeonName') or '확인 대기',event.get('difficulty') or '확인 대기',unit,{'진행중':'진행 중'}.get(event['state'],event['state']),evidence.get(event.get('evidenceType'),'직접 관측')]
            for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(value))
            self.table.item(row,0).setData(Qt.ItemDataRole.UserRole,event)
    def show_record_detail(self,row,column):
        item=self.table.item(row,0)
        if item is None:return
        record=item.data(Qt.ItemDataRole.UserRole)
        if not record:return
        if self.record_dialog is not None:
            self.record_dialog.close();self.record_dialog.deleteLater()
        self.record_dialog=RecordDetailDialog(record,self.public_content.cached,self)
        self.record_dialog.show()
    def delete(self):
        if self.analyzing or self.settled_generation!=self.generation or self.drive.busy:return
        self.store.clear_all();self.reload();self.character.setText('현재 캐릭터: 확인 대기');self.detail.setText('완료·임시 기록과 중복 방지 이력을 모두 삭제했습니다.')
    def drive_changed(self):
        self.reload();self.update_status()
    def closeEvent(self,event):
        if self.drive.busy:
            self.drive.label.setText('Drive 작업을 마친 후 앱을 종료해주세요.');event.ignore();return
        self.drive.shutdown()
        self.public_content.shutdown()
        self.google_login.shutdown()
        if self.worker.isRunning():
            self.closing=True;self.timer.stop();self.worker.stop_event.set();event.ignore()
        else:self.timer.stop();self.store.close();event.accept()


class Startup(QWidget):
    def __init__(self):
        super().__init__();self.setWindowTitle('Beatrice PC · 시작');self.setFixedSize(480,180)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('Beatrice PC'))
        self.label=QLabel('1 / 2 · 모델을 준비하는 중…');self.label.setWordWrap(True);layout.addWidget(self.label)
        self.window=None;self.closing=False;self.restarting=False
        self.create_worker()
        QTimer.singleShot(0,self.begin)
    def create_worker(self):
        self.worker=Worker()
        self.worker.progress.connect(self.label.setText);self.worker.ready.connect(self.open_main)
        self.worker.failed.connect(self.startup_failed);self.worker.finished.connect(self.finished)
    def begin(self):
        if not self.closing:self.worker.start()
    def open_main(self,clients,error=''):
        if self.closing:return
        self.window=Window(self.worker,clients,error)
        self.window.restart_requested.connect(self.restart)
        self.window.show();self.hide()
    def restart(self):
        if self.restarting or self.closing:return
        if self.window is not None and self.window.drive.busy:return
        self.restarting=True
        self.label.setText('현재 작업을 종료하고 앱을 초기화하는 중…');self.show()
        if self.window is not None:
            self.window.drive.shutdown()
            self.window.public_content.shutdown()
            self.window.google_login.shutdown()
            self.window.timer.stop();self.window.stop();self.window.hide()
        self.worker.stop_event.set()
        if not self.worker.isRunning():self.finish_restart()
    def dispose_main(self):
        if self.window is not None:
            self.window.close();self.window.deleteLater();self.window=None
    def finish_restart(self):
        self.dispose_main();self.worker.deleteLater()
        self.restarting=False
        self.label.setText('1 / 2 · 모델을 준비하는 중…')
        self.create_worker();self.begin()
    def startup_failed(self,message):
        if self.window is None:self.open_main([],message)
    def finished(self):
        if self.closing:
            self.dispose_main();self.close()
        elif self.restarting:self.finish_restart()
    def closeEvent(self,event):
        self.closing=True
        if self.worker.isRunning():
            self.closing=True;self.worker.stop_event.set();self.label.setText('초기화를 마무리하고 종료하는 중…');event.ignore()
        else:
            if self.restarting:self.dispose_main()
            event.accept()

def main():
    app=QApplication([]);DATA.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(DATA/'app.lock'))
    if not lock.tryLock(0):return 0
    startup=Startup();startup.show();return app.exec()
