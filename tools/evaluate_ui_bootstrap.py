"""현재 해상도 학습 이미지의 탐지/OCR 재현 검사. 독립 정확도 보고가 아닙니다."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def iou(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return inter/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('weights',type=Path,nargs='?',help='명시하면 단일 통합 모델 검사');p.add_argument('--imgsz',type=int,default=1280)
    p.add_argument('--config',type=Path)
    p.add_argument('--confidence',type=float,default=.7);p.add_argument('--output',type=Path,default=ROOT/'outputs/ui-bootstrap-check')
    args=p.parse_args()
    for key,folder in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib')]:
        os.environ.setdefault(key,str(ROOT/'outputs'/folder));Path(os.environ[key]).mkdir(parents=True,exist_ok=True)
    import torch
    torch.set_num_threads(4)
    import cv2
    from ultralytics import YOLO
    from beatrice.ui_regions import UIRegionDetector,load_config,dungeon_location
    from beatrice.character_vision import CharacterVision
    from beatrice.character import CharacterTracker
    from beatrice.dungeon import DungeonOCR
    from beatrice.dungeon_observer import DungeonObserver
    config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else load_config()
    config.update(imageSize=args.imgsz,confidence=args.confidence)
    if args.weights:config.update(architecture='integrated',weights=str(args.weights.resolve()))
    detector=UIRegionDetector(config);ocr=DungeonOCR();vision=CharacterVision(reader=ocr.reader)
    observer=DungeonObserver(ocr)
    manifest=json.loads((ROOT/'data/annotations/ui-bootstrap.json').read_text(encoding='utf-8'))
    direct={}
    for role in ('character','dungeon'):
        for row in json.loads((ROOT/f'data/annotations/{role}-direct-0926.json').read_text('utf8'))['images']:
            direct.setdefault(row['path'],[]).extend(row['boxes'])
    args.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for item in manifest['images']:
        source=(ROOT/'data/annotations'/item['path']).resolve();frame=cv2.imread(str(source))
        regions=detector.locate(frame)
        character=vision.analyze_detected(frame,regions)
        dungeon,gates=observer.analyze(frame,regions,len(rows))
        expected={b['class']:b['xyxy'] for b in direct.get(item['path'],item['boxes'])}
        # 기존 7클래스 자료에서 음성이었던 화면에도 실제 완료 배너가 있습니다.
        # 배너 클래스를 활성화한 구성에 한해 수동 확인한 추가 라벨을 검사합니다.
        if 'quest_complete_banner' in regions and source.name=='negative-260910_213142.png':
            expected['quest_complete_banner']=[1300,35,2150,290]
        expected={name:coords for name,coords in expected.items() if name in regions}
        matches={name:regions[name]['status']=='detected' and iou(coords,regions[name]['xyxy'])>=.5 for name,coords in expected.items()}
        extra=[name for name,region in regions.items() if region['status']!='missing' and name not in expected]
        row=dict(image=source.name,synthetic=item['synthetic'],matches=matches,extra=extra,
            character=character,dungeon=dungeon,gates=gates)
        rows.append(row)
        print(json.dumps(dict(image=source.name,matches=matches,extra=extra,
            current=character['currentName'],target=character['targetName'],loading=character['switchLoading'],
            dungeon=dungeon['dungeonName'],difficulty=dungeon['difficulty']),ensure_ascii=True),flush=True)
        preview=frame.copy()
        for name,region in regions.items():
            for box in region['candidates']:
                l,t,r,b=box['xyxy'];cv2.rectangle(preview,(l,t),(r,b),(0,255,0),2)
                cv2.putText(preview,name,(l,max(20,t)),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,0),2)
        cv2.imwrite(str(args.output/(source.stem+'.jpg')),preview)
    report=dict(purpose='training_reconstruction_only_not_independent',config=config,
        matches=sum(sum(r['matches'].values()) for r in rows),expected=sum(len(r['matches']) for r in rows),
        extras=sum(len(r['extra']) for r in rows),rows=rows)
    by_name={row['image']:row for row in rows}
    tracker=CharacterTracker(max_gap=5)
    current=by_name['260916_172657.png']['character']
    for t in (0,1,2):initial=tracker.update(t,current)
    popup=tracker.update(3,by_name['260916_172713.png']['character'])
    loading=tracker.update(4,by_name['260921_134230.png']['character'])
    for t in (5,6,7):switched=tracker.update(t,by_name['reconstructed-C1.png']['character'])
    tracker=CharacterTracker(max_gap=5)
    for t in (0,1,2):tracker.update(t,current)
    tracker.update(3,by_name['260916_172713.png']['character'])
    for t in (4,5,6):cancelled=tracker.update(t,current)
    map_load=tracker.update(7,by_name['260921_134230.png']['character'])
    report['scenarios']=dict(initial=initial['recordingAllowed'],popupKeepsCurrent=popup['recordingAllowed'],
        loadingSuspends=not loading['recordingAllowed'],newCharacterConfirmed=switched['recordingAllowed'] and switched['currentName']=='후이수',
        cancelKeepsCurrent=cancelled['recordingAllowed'],unrelatedLoadingKeepsCurrent=map_load['recordingAllowed'])
    # 학습에 넣지 않은 같은 해상도의 일반 UI 화면. 양성 독립 검증을 대신하지 않습니다.
    heldout=[]
    screenshot_root=Path('C:/Program Files (x86)/Smilegate/Games/LOSTARK/EFGame/Screenshots')
    for name in ('Screenshot_260818_193250.jpg','Screenshot_260723_213823.jpg',
                 'Screenshot_260604_213433.jpg','Screenshot_260207_152751.jpg'):
        import numpy as np
        image=cv2.imdecode(np.fromfile(screenshot_root/name,dtype=np.uint8),cv2.IMREAD_COLOR)
        found=detector.locate(image)
        heldout.append(dict(image=name,detected=[kind for kind,value in found.items() if value['status']!='missing']))
    report['heldoutNegativeChecks']=heldout
    functional={}
    for name,expected in [('260916_172657.png','테베체'),('reconstructed-C1.png','후이수'),
                          ('reconstructed-C3.png','테베체'),('reconstructed-C5.png','테베체')]:
        reading=by_name[name]['character']['currentName']
        functional[name]=bool(reading and reading['text']==expected)
    for name,expected in [('260916_172713.png','후이수'),('reconstructed-C2.png','테베체'),
                          ('reconstructed-C4.png','힐레우스'),('reconstructed-C6.png','후이수')]:
        reading=by_name[name]['character']['targetName']
        functional[name]=bool(reading and reading['text']==expected)
    for name in ('260921_134229.png','260921_134230.png'):
        functional[name]=by_name[name]['character']['switchLoading']
    dungeon=by_name['dungeon-single.png']['dungeon']
    functional['dungeon-single.png']=bool(dungeon['dungeonName'] and
        dungeon['dungeonName']['text'].replace(' ','')=='2막:부유하는악몽의진혼곡' and
        dungeon['difficulty'] and dungeon['difficulty']['text']=='싱글 모드' and by_name['dungeon-single.png']['gates'])
    report['functionalChecks']=functional
    report['readyForLocalActivation']=(all(functional.values()) and all(report['scenarios'].values()) and
        report['extras']==0 and not any(row['detected'] for row in heldout))
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SUMMARY',report['matches'],report['expected'],'extras',report['extras'])
    print('SCENARIOS',report['scenarios'])
    print('HELDOUT_NEGATIVES',heldout)
    print('FUNCTIONAL',functional,'READY',report['readyForLocalActivation'])


if __name__=='__main__':main()
