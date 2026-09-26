"""전체 화면 이미지에서 YOLO와 PaddleOCR로 던전 정보를 읽습니다."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2,numpy as np,torch
    torch.set_num_threads(4)
    from ultralytics import YOLO
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.dungeon import DungeonOCR
    from beatrice.dungeon_observer import DungeonObserver
    if args.source.suffix.lower() not in ('.jpg','.jpeg','.png'):p.error('전체 화면 이미지만 지원합니다. 잘라낸 패널 JSON은 지원하지 않습니다.')
    frame=cv2.imdecode(np.fromfile(args.source,dtype=np.uint8),cv2.IMREAD_COLOR)
    if frame is None:raise ValueError('이미지 읽기 실패')
    regions=UIRegionDetector().locate(frame)
    observer=DungeonObserver(DungeonOCR())
    observation,gates=observer.analyze(frame,regions,0)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(source=str(args.source.resolve()),observation=observation,gates=gates,regions=regions,eventConfirmed=False),ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
