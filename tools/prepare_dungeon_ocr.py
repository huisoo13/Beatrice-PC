"""PaddleOCR 공식 한국어 모델을 프로젝트 안에 준비합니다. 게임 이미지는 전송하지 않습니다."""
import hashlib
import json
from pathlib import Path
import tarfile
from urllib.request import urlretrieve
ROOT=Path(__file__).resolve().parents[1]
URL='https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/korean_PP-OCRv5_mobile_rec_infer.tar'

def main():
    folder=ROOT/'models/paddleocr';folder.mkdir(parents=True,exist_ok=True)
    archive=folder/'korean_PP-OCRv5_mobile_rec_infer.tar'
    if not archive.exists():urlretrieve(URL,archive)
    with tarfile.open(archive) as bundle:bundle.extractall(folder,filter='data')
    files={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file() and p.name!='manifest.json'}
    (folder/'manifest.json').write_text(json.dumps(dict(source=URL,sha256=files),indent=2)+'\n')
    print(folder)

if __name__=='__main__':main()
