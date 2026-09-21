"""보존된 이미지의 실제 OCR 비교. 전체 화면/독립 정확도 검사가 아닙니다."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from beatrice.character_vision import CharacterVision
from beatrice.character import valid_name


def main():
    vision=CharacterVision()
    rows=[]
    passed=0
    for i in range(1,7):
        frame=np.zeros((1440,3440,3),dtype=np.uint8)
        frame[550:976,800:2048]=cv2.imread(str(ROOT/f'data/character-first/images/C{i}.png'))
        result=vision.analyze(frame)
        original=vision.read_name(frame,[974,897,1044,925])
        rows.append(dict(sample=f'C{i}',current=result['currentName'],ocr=result['ocr'],
                         detections=result['detections'],originalNameOnly=original))
        field='currentName' if i in (1,3,5) else 'targetName'
        expected={1:'후이수',2:'테베체',3:'테베체',4:'힐레우스',5:'테베체',6:'후이수'}[i]
        rows[-1]['passed']=valid_name(result[field])==expected
        passed+=rows[-1]['passed']
    out=ROOT/'outputs/character-diagnosis.json'
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Image regression: {passed}/6; report: {out}')
    if passed!=6:raise SystemExit(1)


if __name__=='__main__':main()
