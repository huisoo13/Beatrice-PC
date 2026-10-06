"""Replay a preserved login session without changing the live database."""
import argparse,json,os,sys
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))

def main():
    import cv2,numpy as np,torch
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.character_vision import CharacterVision
    from beatrice.character import CharacterTracker
    torch.set_num_threads(4)
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('--weights',required=True)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--config',default='config/character-regions.json')
    p.add_argument('--detection-only',action='store_true');a=p.parse_args()
    config=json.loads((ROOT/a.config).read_text(encoding='utf-8'));config['weights']=a.weights
    detector=UIRegionDetector(config);vision=None if a.detection_only else CharacterVision()
    tracker=CharacterTracker(max_gap=5);rows=[];sources=[]
    for file in a.folder.glob('frame-*.json'):
        r=json.loads(file.read_text(encoding='utf-8'));sources.append((r['observedAt'],file,r))
    for at,file,r in sorted(sources):
        frame=cv2.imdecode(np.fromfile(file.with_suffix('.jpg'),dtype=np.uint8),1)
        regions=detector.locate(frame);row=dict(frame=file.name,at=at,regions=regions)
        if vision:
            seconds=datetime.fromisoformat(at).timestamp()
            obs=vision.analyze_detected(frame,regions,seconds=seconds)
            row.update(observation=obs,state=tracker.update(seconds,obs))
        rows.append(row)
    result=dict(weights=a.weights,rows=rows,final=rows[-1].get('state'))
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(frames=len(rows),final=result['final']),ensure_ascii=True))

if __name__=='__main__':main()
