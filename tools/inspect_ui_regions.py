"""통합 UI 모델을 한 이미지에 실행해 원본 위 탐지 박스와 OCR JSON을 보존합니다."""
import argparse
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path);parser.add_argument('--weights',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    for key,folder in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib')]:
        os.environ.setdefault(key,str(ROOT/'outputs'/folder))
        Path(os.environ[key]).mkdir(parents=True,exist_ok=True)
    import cv2
    import numpy as np
    from ultralytics import YOLO
    from beatrice.ui_regions import UIRegionDetector,load_config,dungeon_location
    from beatrice.dungeon_observer import DungeonObserver
    from beatrice.character_vision import CharacterVision
    from beatrice.dungeon import DungeonOCR
    frame=cv2.imdecode(np.fromfile(args.image,dtype=np.uint8),cv2.IMREAD_COLOR)
    if frame is None:raise ValueError('원본 이미지 읽기 실패')
    config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else load_config()
    if args.weights:config.update(architecture='integrated',weights=str(args.weights.resolve()))
    regions=UIRegionDetector(config).locate(frame)
    dungeon=DungeonOCR();vision=CharacterVision(reader=dungeon.reader)
    observation,gates=DungeonObserver(dungeon).analyze(frame,regions,0)
    report=dict(source=str(args.image.resolve()),regions=regions,character=vision.analyze_detected(frame,regions),
                dungeon=observation,gates=gates,note='Single-frame observation, not a state transition test.')
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'observation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    preview=frame.copy()
    for kind,item in regions.items():
        for candidate in item.get('candidates',[]):
            l,t,r,b=candidate['xyxy']
            cv2.rectangle(preview,(l,t),(r,b),(0,255,0),2)
            cv2.putText(preview,kind,(l,max(20,t)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,0),2)
    cv2.imencode('.png',preview)[1].tofile(args.output/'regions.png')
    print(args.output)


if __name__=='__main__':main()
