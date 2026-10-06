"""실제 저장 프레임의 배너·레이드 유형 검사. 같은 세션 재생이며 독립 정확도 평가가 아닙니다."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('weights',type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--config',type=Path,default=ROOT/'config/dungeon-regions.json')
    args=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import torch
    torch.set_num_threads(2)
    import cv2
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.dungeon_observer import DungeonObserver
    from beatrice.dungeon import DungeonOCR
    from ultralytics import YOLO
    config=json.loads(args.config.read_text('utf8'));config['weights']=str(args.weights.resolve())
    detector=UIRegionDetector(config);observer=DungeonObserver(DungeonOCR())
    cases=[]
    for slot in (11,40,75,100,108,109,110,111,112,113,114,120,140,0):
        cases.append((f'outputs/state-failure-0923/frame-{slot:03d}.jpg','gateless',110<=slot<=113))
    for slot in (34,35,36,37,38,39,45,50):
        cases.append((f'outputs/gate-completion-review-0923/frame-{slot:03d}.jpg','gated',36<=slot<=39))
    for slot in range(24,32):
        cases.append((f'outputs/normal-quest-review-0924/frame-{slot:03d}.jpg',None,27<=slot<=30))
    for slot in (133,175,1,31,80,121,127):
        cases.append((f'outputs/exception-completion-0924/frame-{slot:03d}.jpg',None,False))
    rows=[]
    for i,(path,kind,banner) in enumerate(cases):
        frame=cv2.imread(str(ROOT/path));regions=detector.locate(frame)
        observer.reset();obs,gates=observer.analyze(frame,regions,i)
        detected=[k for k,v in regions.items() if v['status']=='detected']
        actual='gateless' if 'gateless_raid_panel' in detected else 'gated' if 'dungeon_panel' in detected else None
        good=actual==kind
        if kind is not None:good=good and bool(obs.get('dungeonVisible') and obs.get('dungeonName'))
        row=dict(path=path,expectedKind=kind,expectedBanner=banner,passed=bool(good),regions=regions,observation=obs,gates=gates)
        rows.append(row)
        print(path,good,detected,obs.get('dungeonName'),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS',sum(r['passed'] for r in rows),'/',len(rows),flush=True)
    # 학습에 넣지 않은 인접 프레임의 하단을 변경해 헤더 탐지/OCR을 재검사합니다.
    # 실제 다른 콘텐츠 UI의 독립 검증을 대신하지는 않습니다.
    variable=[]
    for variant in range(3):
        frame=cv2.imread(str(ROOT/'outputs/state-failure-0923/frame-111.jpg'))
        if variant==0:frame[145:355,5:400]=frame[400:610,5:400]
        elif variant==1:frame[145:355,5:400]=230
        else:
            frame[145:355,5:400]=25
            for y in (155,205,315):cv2.putText(frame,'Alternate objective',(15,y+20),cv2.FONT_HERSHEY_SIMPLEX,.65,(200,200,200),2)
        observer.reset();regions=detector.locate(frame);obs,gates=observer.analyze(frame,regions,0)
        good=obs.get('raidKind')=='gateless' and obs.get('dungeonVisible')
        variable.append(dict(variant=variant,passed=bool(good),observation=obs,regions=regions))
    args.output.with_suffix('.variable.json').write_text(json.dumps(variable,ensure_ascii=False,indent=2),encoding='utf-8')
    print('VARIABLE',sum(r['passed'] for r in variable),'/',len(variable),flush=True)

if __name__=='__main__':main()
