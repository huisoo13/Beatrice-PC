"""이름 읽기에 필요한 한국어 OCR 가중치를 프로젝트 내부에 준비합니다."""
from pathlib import Path
import easyocr
root = Path(__file__).resolve().parents[1]
easyocr.Reader(['ko','en'], gpu=False, detector=False,
    model_storage_directory=str(root/'models/easyocr'),
    user_network_directory=str(root/'models/easyocr/user'), verbose=True)
print('한국어 OCR 가중치 준비 완료')
