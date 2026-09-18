"""로컬 한국어 PaddleOCR 인식기. 기존 문자 인식 호출 형태로 결과를 반환합니다."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL='korean_PP-OCRv5_mobile_rec'


class PaddleKoreanReader:
    def __init__(self):
        os.environ.setdefault('PADDLE_PDX_CACHE_HOME',str(ROOT/'outputs/paddlex-cache'))
        os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
        os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'outputs/matplotlib'))
        Path(os.environ['MPLCONFIGDIR']).mkdir(parents=True,exist_ok=True)
        directory=ROOT/'models/paddleocr/korean_PP-OCRv5_mobile_rec_infer'
        if not (directory/'inference.json').is_file():
            raise ValueError('먼저 tools/prepare_dungeon_ocr.py로 한국어 모델을 준비해주세요.')
        from paddleocr import TextRecognition
        self.model=TextRecognition(model_name=MODEL,model_dir=str(directory),device='cpu',enable_mkldnn=False,cpu_threads=4)

    def recognize(self,image):
        import cv2
        if image.ndim==2:image=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
        results=list(self.model.predict(image,batch_size=1))
        return [(None,value['rec_text'],float(value['rec_score'])) for value in results]
