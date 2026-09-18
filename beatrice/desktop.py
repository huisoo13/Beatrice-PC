"""Qt UI는 메인 스레드, 모델과 캡처/저장은 단일 작업자 스레드에서 실행합니다."""
import os
import time
import threading
import traceback
from datetime import datetime,timezone
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QTimer,QLockFile
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,
    QPushButton,QLabel,QComboBox,QDoubleSpinBox,QTableWidget,QTableWidgetItem,QHeaderView)
from .storage import Store
from .windows_capture import windows

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('BEATRICE_DATA_DIR',str(Path.home()/'BeatricePC')))

class Worker(QThread):
    status=Signal(str); observation=Signal(dict)
    def __init__(self,hwnd,scale):
        super().__init__();self.hwnd=hwnd;self.scale=scale;self.stop_event=threading.Event()
    def run(self):
        store=None;capture=None
        try:
            self.status.emit('모델을 불러오는 중… 첫 실행은 시간이 걸릴 수 있습니다.')
            from .character_vision import CharacterVision
            from .dungeon import DungeonOCR,DungeonTracker
            from .live import LiveCoordinator
            from .layout import normalize
            from .windows_capture import WindowCapture
            from ultralytics import YOLO
            character=CharacterVision();dungeon= DungeonOCR();tracker=DungeonTracker(max_gap=5)
            model=YOLO(str(ROOT/'models/gates-yolo26n-first.pt'))
            store=Store(DATA/'records.sqlite3');coordinator=LiveCoordinator(store)
            capture=WindowCapture(self.hwnd)
            while not self.stop_event.is_set():
                started=time.monotonic();frame,reason=capture.grab()
                at=datetime.now(timezone.utc)
                if frame is None:
                    self.status.emit(reason);self.stop_event.wait(.5);continue
                centered=normalize(frame,self.scale,True);left=normalize(frame,self.scale)
                identity=character.analyze(centered)
                result=model.predict(left[112:224,32:352],imgsz=320,conf=.25,iou=.5,device='cpu',verbose=False)[0]
                boxes=[]
                for box in result.boxes:
                    x1,y1,x2,y2=box.xyxy[0].tolist()
                    boxes.append(dict(state=model.names[int(box.cls[0])],confidence=float(box.conf[0]),xyxy=[x1+32,y1+112,x2+32,y2+112]))
                context=tracker.update(at.timestamp(),dungeon.analyze(left))
                state=coordinator.update(at,identity,boxes,context)
                state['milliseconds']=round((time.monotonic()-started)*1000)
                state['size']=f'{frame.shape[1]} × {frame.shape[0]}'
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
        self.scale=QDoubleSpinBox();self.scale.setRange(.5,2);self.scale.setSingleStep(.05);self.scale.setValue(1)
        row.addWidget(QLabel('대상'));row.addWidget(self.targets,1);row.addWidget(refresh)
        row.addWidget(QLabel('UI 배율 보정'));row.addWidget(self.scale);layout.addLayout(row)
        controls=QHBoxLayout();self.start_button=QPushButton('시작');self.stop_button=QPushButton('정지');self.delete_button=QPushButton('기록 전체 삭제')
        for button in (self.start_button,self.stop_button,self.delete_button):button.setMinimumHeight(42);controls.addWidget(button)
        layout.addLayout(controls);self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start);self.stop_button.clicked.connect(self.stop);self.delete_button.clicked.connect(self.delete)
        self.character=QLabel('현재 캐릭터: 확인 대기 — 게임에서 ESC 메뉴를 잠시 유지해주세요.')
        self.status_label=QLabel('준비 · 게임 창을 선택하고 시작해주세요.');self.status_label.setWordWrap(True)
        layout.addWidget(self.character);layout.addWidget(self.status_label)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['관측 시각 (PC 현지 시간)','캐릭터','던전','난이도','관문','상태'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);layout.addWidget(self.table,1)
        note=QLabel('테스트 정책: 동일 캐릭터·던전·난이도·관문은 전체 삭제 전까지 한 번 저장합니다.\n'
            '이미 완료된 화면으로 시작하면 신규 완료로 기록하지 않습니다. 미확정 기록은 이름 확인 전까지 보존됩니다.\n'
            '해상도는 높이 기준으로 보정합니다. UI 배율/배치가 다르면 인식 확인이 필요합니다.');note.setWordWrap(True);layout.addWidget(note)
        layout.addWidget(QLabel('저장 위치: '+str(DATA)))
        self.refresh();self.reload();self.timer=QTimer(self);self.timer.timeout.connect(self.reload);self.timer.start(1000)
    def refresh(self):
        if self.worker is not None:return
        self.targets.clear()
        for hwnd,title in windows():self.targets.addItem(title,hwnd)
    def start(self):
        if self.worker is not None:return
        if self.targets.currentData() is None:self.status_label.setText('게임을 실행한 뒤 게임 창 새로고침을 눌러주세요.');return
        self.worker=Worker(self.targets.currentData(),self.scale.value())
        self.worker.status.connect(self.status_label.setText);self.worker.observation.connect(self.update_observation);self.worker.finished.connect(self.stopped)
        self.start_button.setEnabled(False);self.delete_button.setEnabled(False);self.stop_button.setEnabled(True);self.targets.setEnabled(False);self.scale.setEnabled(False)
        self.worker.start()
    def stop(self):
        if self.worker is not None:self.worker.stop_event.set();self.status_label.setText('현재 분석을 마치고 정지하는 중…');self.stop_button.setEnabled(False)
    def stopped(self):
        self.worker.deleteLater();self.worker=None
        self.start_button.setEnabled(True);self.delete_button.setEnabled(True);self.stop_button.setEnabled(False);self.targets.setEnabled(True);self.scale.setEnabled(True)
        if self.status_label.text().startswith('현재 분석'):self.status_label.setText('정지됨 · 기록은 PC에 보존됩니다.')
        if self.closing:self.close()
    def update_observation(self,value):
        identity=value['identity'];name=identity['currentName'] if identity['recordingAllowed'] else '캐릭터 확인 대기'
        self.character.setText('현재 캐릭터: '+(name or '확인 대기'))
        dungeon=value['dungeon'];summary=f"{dungeon.get('dungeonName') or '던전 확인 대기'} / {dungeon.get('difficulty') or '난이도 확인 대기'}"
        self.status_label.setText(f"분석 중 · {summary} · {value['size']} · 프레임 분석 {value['milliseconds']} ms")
    def reload(self):
        records=self.store.records()+[e for e in self.store.pending_records() if e['resolvedEventID'] is None]
        records.sort(key=lambda e:e['observedAt'],reverse=True);self.table.setRowCount(len(records))
        for row,event in enumerate(records):
            when=datetime.fromisoformat(event['observedAt']).astimezone().strftime('%Y-%m-%d %H:%M:%S')
            values=[when,event.get('characterName') or '캐릭터 확인 대기',event.get('dungeonName') or '확인 대기',event.get('difficulty') or '확인 대기',str(event['gate'])+'관문','저장 완료' if event.get('characterName') else '임시 저장']
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
