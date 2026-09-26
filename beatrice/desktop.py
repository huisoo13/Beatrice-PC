"""Qt UI는 메인 스레드, 모델과 캡처/저장은 단일 작업자 스레드에서 실행합니다."""
import os
import json
import time
import threading
import traceback
from datetime import datetime,timezone
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QTimer,QLockFile
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QPushButton,QLabel,QComboBox,QTableWidget,QTableWidgetItem,QHeaderView)
from .storage import Store
from .windows_capture import windows

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('BEATRICE_DATA_DIR',str(Path.home()/'BeatricePC')))

class Worker(QThread):
    status=Signal(str); observation=Signal(dict)
    def __init__(self,hwnd):
        super().__init__();self.hwnd=hwnd;self.stop_event=threading.Event()
    def run(self):
        store=None;capture=None
        try:
            self.status.emit('모델을 불러오는 중… 첫 실행은 시간이 걸릴 수 있습니다.')
            from .character_vision import CharacterVision
            from .dungeon import DungeonOCR,DungeonTracker
            from .live import LiveCoordinator
            from .windows_capture import WindowCapture
            from .ui_regions import load_config as load_ui_config,UIRegionDetector
            from .recognition_diagnostic import RecognitionDiagnostic
            from .dungeon_observer import DungeonObserver
            ui_config=load_ui_config()
            if ui_config['mode']!='yolo':raise ValueError('YOLO 탐지만 지원합니다.')
            ui_detector=UIRegionDetector(ui_config)
            dungeon=DungeonOCR();character=CharacterVision(reader=dungeon.reader);tracker=DungeonTracker(max_gap=5)
            dungeon_observer=DungeonObserver(dungeon)
            store=Store(DATA/'records.sqlite3');coordinator=LiveCoordinator(store)
            capture=WindowCapture(self.hwnd)
            diagnostic=RecognitionDiagnostic(DATA/'recognition-diagnostics')
            last_diagnostic=0
            while not self.stop_event.is_set():
                started=time.monotonic();frame,reason=capture.grab()
                at=datetime.now(timezone.utc)
                if frame is None:
                    character.reset_name_cache()
                    dungeon_observer.reset()
                    context=tracker.update(at.timestamp(),{})
                    state=coordinator.update(at,{},[],context)
                    state.update(milliseconds=0,size='캡처 대기')
                    self.observation.emit(state)
                    self.status.emit(reason);self.stop_event.wait(.5);continue
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
                dungeon_observation,boxes=dungeon_observer.analyze(frame,regions,started,blocked=blocked)
                context=tracker.update(at.timestamp(),dungeon_observation)
                dungeon_at=time.monotonic()
                if write_diagnostic:
                    (DATA/'dungeon-diagnostic.json').write_text(json.dumps(dict(
                        mode='ui_yolo',observedAt=at.isoformat(),observation=dungeon_observation),
                        ensure_ascii=False,indent=2),encoding='utf-8')
                state=coordinator.update(at,identity,boxes,context)
                if any(action['type']=='suspend' for action in state['identity']['actions']):
                    tracker.reset()
                    dungeon_observer.reset()
                    state['dungeon']=tracker.update(at.timestamp(),{})
                state['recognitionMode']='캐릭터·던전 분리 탐지' if ui_config.get('architecture')=='split' else 'UI 자동 탐지'
                state['milliseconds']=round((time.monotonic()-started)*1000)
                state['timingsMs']=dict(detection=round((detected_at-started)*1000),character=round((character_at-detected_at)*1000),dungeon=round((dungeon_at-character_at)*1000))
                state['size']=f'{frame.shape[1]} × {frame.shape[0]}'
                try:
                    diagnostic.record(frame,dict(observedAt=at.isoformat(),
                        modelConfig=ui_config,character=identity,dungeon=dungeon_observation,
                        gates=boxes,state=state),now=started)
                except OSError as exc:
                    # 진단 저장 실패가 인식 및 기록 루프를 중단하지 않게 합니다.
                    self.status.emit(f'진단 저장 실패: {exc}')
                self.observation.emit(state)
                self.stop_event.wait(max(0,.5-(time.monotonic()-started)))
        except Exception as exc:
            with (DATA/'errors.log').open('a',encoding='utf-8') as f:f.write(traceback.format_exc()+'\n')
            self.status.emit(f'오류: {exc} — errors.log를 확인해주세요.')
        finally:
            if capture is not None:capture.close()
            if store is not None:store.close()

class Window(QMainWindow):
    def __init__(self):
        super().__init__();DATA.mkdir(parents=True,exist_ok=True)
        self.worker=None;self.closing=False;self.store=Store(DATA/'records.sqlite3')
        self.setWindowTitle('Beatrice PC · 실시간 관문 기록 테스트');self.resize(1000,620)
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        row=QHBoxLayout();self.targets=QComboBox();self.targets.setMinimumWidth(330)
        refresh=QPushButton('게임 창 새로고침');refresh.clicked.connect(self.refresh)
        row.addWidget(QLabel('대상'));row.addWidget(self.targets,1);row.addWidget(refresh)
        layout.addLayout(row)
        controls=QHBoxLayout();self.start_button=QPushButton('시작');self.stop_button=QPushButton('정지');self.delete_button=QPushButton('기록 전체 삭제')
        for button in (self.start_button,self.stop_button,self.delete_button):button.setMinimumHeight(42);controls.addWidget(button)
        layout.addLayout(controls);self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start);self.stop_button.clicked.connect(self.stop);self.delete_button.clicked.connect(self.delete)
        self.character=QLabel('현재 캐릭터: 확인 대기 — 게임에서 ESC 메뉴를 잠시 유지해주세요.')
        self.status_label=QLabel('준비 · 게임 창을 선택하고 시작해주세요.');self.status_label.setWordWrap(True)
        layout.addWidget(self.character);layout.addWidget(self.status_label)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['변경 확인 시각 (PC 현지 시간)','캐릭터','던전','난이도','관문','상태','확인 근거'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table,1)
        note=QLabel('동일 캐릭터·던전·관문은 전체 삭제 전까지 하나의 상태 기록을 유지합니다. 완료는 변경하지 않습니다.\n'
            '전체 관문 검증 후 최초 저장·상태 변경 시 갱신합니다. 후속 관문 완료는 앞선 관문 완료를 보완합니다.\n'
            '화면에서 패널을 자동으로 찾습니다. 다른 해상도·UI 배율·배치에서는 추가 검증이 필요합니다.');note.setWordWrap(True);layout.addWidget(note)
        layout.addWidget(QLabel('저장 위치: '+str(DATA)))
        self.refresh();self.reload();self.timer=QTimer(self);self.timer.timeout.connect(self.reload);self.timer.start(1000)
    def refresh(self):
        if self.worker is not None:return
        self.targets.clear()
        for hwnd,title in windows():self.targets.addItem(title,hwnd)
    def start(self):
        if self.worker is not None:return
        if self.targets.currentData() is None:self.status_label.setText('게임을 실행한 뒤 게임 창 새로고침을 눌러주세요.');return
        self.worker=Worker(self.targets.currentData())
        self.worker.status.connect(self.status_label.setText);self.worker.observation.connect(self.update_observation);self.worker.finished.connect(self.stopped)
        self.start_button.setEnabled(False);self.delete_button.setEnabled(False);self.stop_button.setEnabled(True);self.targets.setEnabled(False)
        self.worker.start()
    def stop(self):
        if self.worker is not None:self.worker.stop_event.set();self.status_label.setText('현재 분석을 마치고 정지하는 중…');self.stop_button.setEnabled(False)
    def stopped(self):
        self.worker.deleteLater();self.worker=None
        self.start_button.setEnabled(True);self.delete_button.setEnabled(True);self.stop_button.setEnabled(False);self.targets.setEnabled(True)
        if self.status_label.text().startswith('현재 분석'):self.status_label.setText('정지됨 · 기록은 PC에 보존됩니다.')
        if self.closing:self.close()
    def update_observation(self,value):
        identity=value['identity'];name=identity['currentName'] if identity['recordingAllowed'] else '캐릭터 확인 대기'
        if not identity['recordingAllowed'] and identity.get('previewName'):
            name=identity['previewName']+' (확인 중)'
        self.character.setText('현재 캐릭터: '+(name or '확인 대기'))
        dungeon=value['dungeon']
        def display(field,waiting):
            return dungeon.get(field) or ((dungeon['preview'][field]+' (확인 중)') if dungeon.get('preview',{}).get(field) else waiting)
        summary=f"{display('dungeonName','던전 확인 대기')} / {display('difficulty','난이도 확인 대기')}"
        self.status_label.setText(f"분석 중 · {value.get('recognitionMode','캡처 대기')} · {summary} · {value.get('recordingStatus','')} · {value['size']} · 프레임 분석 {value['milliseconds']} ms")
    def reload(self):
        records=self.store.state_records()
        records.sort(key=lambda e:(e.get('characterName') or '',e.get('dungeonName') or '',e['gate']));self.table.setRowCount(len(records))
        for row,event in enumerate(records):
            when=datetime.fromisoformat(event['observedAt']).astimezone().strftime('%Y-%m-%d %H:%M:%S')
            evidence={'later_gate_completion':'후속 관문으로 보완','legacy_completion':'기존 완료 기록','direct':'직접 관측','completion_banner':'완료 배너'}
            unit='레이드 전체' if event.get('completionScope')=='raid' else str(event['gate'])+'관문'
            values=[when,event.get('characterName') or '캐릭터 확인 대기',event.get('dungeonName') or '확인 대기',event.get('difficulty') or '확인 대기',unit,{'진행중':'진행 중'}.get(event['state'],event['state']),evidence.get(event.get('evidenceType'),'직접 관측')]
            for col,value in enumerate(values):self.table.setItem(row,col,QTableWidgetItem(value))
    def delete(self):
        if self.worker is not None:return
        self.store.clear_all();self.reload();self.character.setText('현재 캐릭터: 확인 대기');self.status_label.setText('완료·임시 기록과 중복 방지 이력을 모두 삭제했습니다.')
    def closeEvent(self,event):
        if self.worker is not None:self.closing=True;self.stop();event.ignore()
        else:self.timer.stop();self.store.close();event.accept()

def main():
    app=QApplication([]);DATA.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(DATA/'app.lock'))
    if not lock.tryLock(0):return 0
    window=Window();window.show();return app.exec()
