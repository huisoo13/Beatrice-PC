"""Read-only completion detail; remote strings are always rendered as plain text."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
from .content_match import record_detail


class RecordDetailDialog(QDialog):
    def __init__(self, record, cached=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('완료 기록 상세')
        self.resize(480, 280)
        layout = QVBoxLayout(self)
        def label(text):
            widget = QLabel(text)
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setWordWrap(True)
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(widget)
            return widget
        gate = record.get('gateName') or ('레이드 전체' if record.get('completionScope') == 'raid'
                                          else f"{record['gate']}관문")
        label(f"{record.get('characterName') or '캐릭터 확인 대기'}\n"
              f"{record['dungeonName']} / {record['difficulty']} / {gate}")
        detail = record_detail(record, cached)
        if detail['status'] == 'matched':
            values = detail['values']
            self.info = label(f"골드: {values['gold']:,}\n비용 (fee): {values['fee']:,}\n"
                              f"귀속 비율: {values['bound_percentage'] * 100:g}%\n\n{detail['source']}")
        else:
            reason = '일치 후보가 여러 개입니다.' if detail['status'] == 'ambiguous' else '일치하는 항목을 찾지 못했습니다.'
            self.info = label(f'상세 정보가 연결되지 않았습니다. {reason}\n기록은 인식된 값 그대로 유지합니다.')
        original = record.get('ocrOriginal')
        if original:
            label(f"OCR 원문: {original['dungeonName']} / {original['difficulty']} / {original['gate']}관문")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
