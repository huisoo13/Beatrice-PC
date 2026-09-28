"""Background public catalog retrieval and a read-only content viewer."""
from datetime import datetime
import queue
import threading
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton, QDialog,
                              QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView)
from .public_content import ContentCache, ContentError, PublicContentClient, load_api_key, load_settings


class PublicContentPanel(QWidget):
    def __init__(self, root, data, parent=None):
        super().__init__(parent)
        self.root = root
        self.cached = None
        self.pending = None
        self.closed = False
        self.next_check = 0
        self.settings = self.cache = None
        self.dialog = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel('공용 데이터 · 확인 대기')
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.view_button = QPushButton('공용 데이터 보기')
        self.refresh_button = QPushButton('공용 데이터 갱신')
        self.view_button.setEnabled(False)
        row.addWidget(self.label, 1)
        row.addWidget(self.view_button)
        row.addWidget(self.refresh_button)
        self.view_button.clicked.connect(self.show_content)
        self.refresh_button.clicked.connect(self.refresh)
        try:
            self.settings = load_settings(root)
            self.cache = ContentCache(data, self.settings)
            self.cached = self.cache.load()
            if self.cached:
                self.display('로컬 보관본')
        except ContentError as exc:
            self.label.setText(str(exc))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(200)
        QTimer.singleShot(0, self.refresh)

    def display(self, source):
        data = self.cached['content']
        gates = sum(len(g) for modes in data.values() for g in modes.values())
        self.label.setText(f'공용 데이터 · 던전 {len(data)}개 / 관문 항목 {gates}개 · {source}')
        self.view_button.setEnabled(True)

    def refresh(self):
        if self.closed or self.pending or not self.settings:
            return
        self.next_check = time.monotonic() + self.settings['refreshSeconds']
        try:
            api_key = load_api_key(self.root)
        except ContentError as exc:
            self.failure(str(exc))
            return
        cancel, results = threading.Event(), queue.Queue()
        settings, cached = self.settings, self.cached
        def run():
            try:
                result = PublicContentClient(api_key, settings, cancel).refresh(cached)
                results.put((result, None))
            except ContentError as exc:
                results.put((None, str(exc)))
            except Exception:
                results.put((None, '공용 데이터 조회를 완료하지 못했습니다.'))
        self.pending = cancel, results
        self.refresh_button.setEnabled(False)
        self.label.setText('공용 데이터 변경 확인 중…')
        threading.Thread(target=run, daemon=True, name='PublicContent').start()

    def failure(self, message):
        suffix = ' · 마지막 정상 데이터 사용 중' if self.cached else ' · 사용 가능한 공용 데이터 없음'
        self.label.setText(message + suffix)

    def tick(self):
        if self.closed:
            return
        if not self.pending:
            if time.monotonic() >= self.next_check:
                self.refresh()
            return
        try:
            result, error = self.pending[1].get_nowait()
        except queue.Empty:
            return
        self.pending = None
        self.refresh_button.setEnabled(True)
        if error:
            self.failure(error)
            return
        try:
            self.cache.save(result)
            self.cached = result
            self.display('최신 확인 ' + datetime.now().strftime('%H:%M'))
        except (OSError, ContentError):
            self.failure('공용 데이터를 로컬에 보관하지 못했습니다.')

    def show_content(self):
        if not self.cached:
            return
        if self.dialog:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.dialog = QDialog(self)
        self.dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.dialog.setWindowTitle('Beatrice 공용 데이터 · ContentJSON.json')
        self.dialog.resize(820, 560)
        layout = QVBoxLayout(self.dialog)
        layout.addWidget(QLabel('공용 던전·난이도·관문별 보상 정보'))
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(['던전', '난이도', '관문', '골드', '비용 (fee)', '귀속 비율'])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for dungeon, modes in self.cached['content'].items():
            for mode, gates in modes.items():
                for gate, values in gates.items():
                    index = table.rowCount()
                    table.insertRow(index)
                    cells = [dungeon, mode, gate, f"{values['gold']:,}", f"{values['fee']:,}", f"{values['bound_percentage'] * 100:g}%"]
                    for col, value in enumerate(cells):
                        table.setItem(index, col, QTableWidgetItem(value))
        layout.addWidget(table)
        self.dialog.destroyed.connect(self.dialog_closed)
        self.dialog.show()

    def dialog_closed(self):
        self.dialog = None

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        if self.pending:
            self.pending[0].set()
            self.pending = None
        if self.dialog:
            self.dialog.close()
