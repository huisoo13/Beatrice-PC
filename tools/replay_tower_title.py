"""Read preserved Tower frames with real parent/child YOLO and Korean OCR."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--weights',required=True);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--title-confidence',type=float);args=p.parse_args()
    import cv2,numpy as np,torch
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.dungeon import DungeonOCR,key
    from beatrice.dungeon_observer import DungeonObserver
    torch.set_num_threads(2)
    element=json.loads((ROOT/'config/dungeon-elements.json').read_text(encoding='utf-8'));element['weights']=args.weights
    if args.title_confidence is not None:element.setdefault('classConfidence',{})['dungeon_name']=args.title_confidence
    temporary=args.output.with_suffix('.config.json');temporary.write_text(json.dumps(element),encoding='utf-8')
    parent=json.loads((ROOT/'config/dungeon-regions.json').read_text(encoding='utf-8'));parent['elementConfig']=str(temporary.resolve())
    detector=UIRegionDetector(parent);observer=DungeonObserver(DungeonOCR());rows=[]
    images=[ROOT/'outputs/tower-review-1006/tower.jpg',*sorted((ROOT/'outputs/tower-review-1006/holdout').glob('*.jpg'))]
    for i,path in enumerate(images):
        frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR);regions=detector.locate(frame)
        observation,gates=observer.analyze(frame,regions,i)
        passed=(key((observation.get('dungeonName') or {}).get('text',''))==key('구원의 종탑') and (observation.get('difficulty') or {}).get('text')=='3단계')
        capture_missing=not np.any(frame)
        if capture_missing:passed=not observation.get('dungeonVisible') and not gates
        rows.append(dict(path=str(path),captureMissing=capture_missing,passed=passed,regions=regions,observation=observation,gates=gates))
    args.output.write_text(json.dumps(dict(purpose='training_frame_and_same_session_temporal_replay_not_independent',passed=sum(r['passed'] for r in rows),total=len(rows),rows=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    print(dict(passed=sum(r['passed'] for r in rows),total=len(rows)))
    if not all(r['passed'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
