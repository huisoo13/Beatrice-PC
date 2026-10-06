"""로컬 한국어 PaddleOCR 인식기. 기존 문자 인식 호출 형태로 결과를 반환합니다."""
import os
import warnings
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL='korean_PP-OCRv5_mobile_rec'


def recognize_images(reader,images):
    """Keep one result list per input, including for single-image reader adapters."""
    batch_method=getattr(type(reader),'recognize_many',None)
    if callable(batch_method):return reader.recognize_many(images)
    return [reader.recognize(image) for image in images]


class PaddleKoreanReader:
    def __init__(self,*,cpu_threads=None,enable_mkldnn=None):
        from .cpu_inference import load_config
        config=load_config()
        self.cpu_threads=config['ocrThreads'] if cpu_threads is None else cpu_threads
        self.enable_mkldnn=config['ocrMkldnn'] if enable_mkldnn is None else enable_mkldnn
        if type(self.cpu_threads) is not int or not 1<=self.cpu_threads<=32:
            raise ValueError('OCR CPU 스레드는 1~32 정수여야 합니다.')
        if type(self.enable_mkldnn) is not bool:raise ValueError('OCR CPU 가속 설정 오류')
        os.environ.setdefault('PADDLE_PDX_CACHE_HOME',str(ROOT/'outputs/paddlex-cache'))
        os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
        os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'outputs/matplotlib'))
        Path(os.environ['MPLCONFIGDIR']).mkdir(parents=True,exist_ok=True)
        self.directory=ROOT/'models/paddleocr/korean_PP-OCRv5_mobile_rec_infer'
        if not (self.directory/'inference.json').is_file():
            raise ValueError('먼저 tools/prepare_dungeon_ocr.py로 한국어 모델을 준비해주세요.')
        try:self.model=self._create_model()
        except Exception as error:
            if not self.enable_mkldnn:raise
            self._disable_acceleration(error)

    def _create_model(self):
        from paddleocr import TextRecognition
        return TextRecognition(model_name=MODEL,model_dir=str(self.directory),device='cpu',
                               enable_mkldnn=self.enable_mkldnn,cpu_threads=self.cpu_threads)

    def _disable_acceleration(self,error):
        warnings.warn(f'OCR CPU 가속 실패; 기본 CPU 방식으로 재시도합니다: {error}',RuntimeWarning)
        self.enable_mkldnn=False
        self.model=self._create_model()

    def _predict(self,images):
        try:return list(self.model.predict(images,batch_size=1))
        except Exception as error:
            if not getattr(self,'enable_mkldnn',False):raise
            self._disable_acceleration(error)
            return list(self.model.predict(images,batch_size=1))

    def recognize(self,image):
        import cv2
        if image.ndim==2:image=cv2.cvtColor(image,cv2.COLOR_GRAY2BGR)
        results=self._predict(image)
        return [(None,value['rec_text'],float(value['rec_score'])) for value in results]

    def recognize_many(self,images):
        import cv2
        if not images:return []
        converted=[cv2.cvtColor(image,cv2.COLOR_GRAY2BGR) if image.ndim==2 else image for image in images]
        # Keep the per-image inference/preprocessing validated in the batch
        # submission stage; CPU acceleration does not change the batch shape.
        results=self._predict(converted)
        if len(results)!=len(converted):
            raise RuntimeError('OCR 일괄 처리 결과 수가 입력과 다릅니다.')
        return [[(None,value['rec_text'],float(value['rec_score']))] for value in results]
