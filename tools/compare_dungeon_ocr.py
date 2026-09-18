"""한국어 PaddleOCR 모델을 원본 샘플 제목·난이도에서 비교합니다."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'outputs/matplotlib'))
os.environ.setdefault('PADDLE_PDX_CACHE_HOME',str(ROOT/'outputs/paddlex-cache'))
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
import cv2
from paddleocr import TextRecognition


def main():
    model=TextRecognition(model_name='korean_PP-OCRv5_mobile_rec',
        model_dir=str(ROOT/'models/paddleocr/korean_PP-OCRv5_mobile_rec_infer'),device='cpu',enable_mkldnn=False,cpu_threads=4)
    for path in sorted((ROOT/'data/raw').glob('SAMPLE*.jpg')):
        im=cv2.imread(str(path))
        inputs=[im[63:87,25:355],im[98:120,140:240]]
        outputs=list(model.predict(inputs,batch_size=1))
        print(path.name,[(v['rec_text'],float(v['rec_score'])) for v in outputs],flush=True)

if __name__=='__main__':main()
