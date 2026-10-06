"""Read-only replay of saved frames through character YOLO/OCR and identity tracker."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))

def main():
    import cv2,numpy as np,torch
    from datetime import datetime
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.character_vision import CharacterVision
    from beatrice.character import CharacterTracker
    torch.set_num_threads(4)
    p=argparse.ArgumentParser();p.add_argument('weights');p.add_argument('--output',required=True);p.add_argument('--config',default='config/character-regions.json');args=p.parse_args()
    config=json.loads((ROOT/args.config).read_text(encoding='utf-8'))
    manifest=json.loads((ROOT/'data/annotations/character-initial-login-0930.json').read_text(encoding='utf-8'))
    config.update(weights=args.weights,classes=manifest['classes'])
    detector=UIRegionDetector(config);vision=CharacterVision();tracker=CharacterTracker(max_gap=5)
    folder=Path(os.environ['LOCALAPPDATA'])/'BeatricePC/recognition-diagnostics'
    rows=[]
    for i in range(115,161):
        file=folder/f'frame-{i:03}.json'
        report=json.loads(file.read_text(encoding='utf-8'));at=datetime.fromisoformat(report['observedAt'])
        # The ring must still contain the intended recording; never mix sessions.
        if not '2026-09-30T04:5' in report['observedAt']:raise ValueError('Source frames were overwritten')
        frame=cv2.imdecode(np.fromfile(file.with_suffix('.jpg'),dtype=np.uint8),cv2.IMREAD_COLOR)
        regions=detector.locate(frame)
        obs=vision.analyze_detected(frame,regions,seconds=at.timestamp())
        state=tracker.update(at.timestamp(),obs)
        rows.append(dict(frame=file.name,at=report['observedAt'],observation=obs,state=state))
    result=dict(rows=rows,final=rows[-1]['state'])
    # 저장 구간에는 입장 후 두 프레임만 있습니다. 실제 관측과 이어지는 가정 검사를 분리합니다.
    result['continuedFrameSimulation']=tracker.update(at.timestamp()+1,obs)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=True))
if __name__=='__main__':main()
