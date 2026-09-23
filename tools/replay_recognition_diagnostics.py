"""저장된 실제 프레임과 탐지 결과로 OCR 및 시간 순서 처리를 재검증합니다."""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--weights',type=Path,help='지정하면 저장된 탐지 대신 원본 프레임에 YOLO부터 다시 실행')
    p.add_argument('--config',type=Path,help='실행할 모델 구성. 지정하면 원본 프레임에 YOLO부터 다시 실행')
    p.add_argument('--restore-recorded-identity',action='store_true',help='잘린 진단 구간 시작 시 기록된 확정 캐릭터를 초기 상태로 복원. 이름 OCR 검증이 아닙니다.')
    p.add_argument('--gate-weights',type=Path,help='검증할 관문 상태 모델')
    args=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2
    from ultralytics import YOLO
    from beatrice.character_vision import CharacterVision
    from beatrice.dungeon import DungeonOCR,DungeonTracker
    from beatrice.ui_regions import UIRegionDetector,load_config
    from beatrice.dungeon_observer import DungeonObserver
    from beatrice.live import LiveCoordinator
    from beatrice.storage import Store
    from beatrice.character import valid_name
    ocr=DungeonOCR();vision=CharacterVision(reader=ocr.reader,legacy=False)
    model=YOLO(str(args.gate_weights or ROOT/'models/gates-yolo26n-first.pt'))
    config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else load_config()
    if args.weights:config.update(architecture='integrated',weights=str(args.weights.resolve()))
    detector=UIRegionDetector(config) if args.weights or args.config else None
    reports=sorted((json.loads(p.read_text(encoding='utf-8')) for p in args.directory.glob('frame-*.json')),key=lambda r:r['observedAt'])
    sessions={};results=[]
    for r in reports:
        if r['sessionId'] not in sessions:
            store=Store(':memory:');live=LiveCoordinator(store)
            initial=r.get('state',{}).get('identity',{})
            if args.restore_recorded_identity and initial.get('recordingAllowed'):
                name=valid_name(dict(text=initial.get('currentName') or '',confidence=1))
                if name:live.identity.current=name;live.identity.blocked=False
            sessions[r['sessionId']]=(live,DungeonTracker(max_gap=5),DungeonObserver(ocr,model),store)
        live,dt,observer,store=sessions[r['sessionId']];ct=live.identity
        frame=cv2.imread(str(args.directory/r['frameFile']))
        regions=detector.locate(frame) if detector else r['character']['detections']
        seconds=datetime.fromisoformat(r['observedAt']).timestamp()
        identity=vision.analyze_detected(frame,regions,seconds=seconds,confirmed_name=ct.current if not ct.blocked else None)
        blocked=any(regions.get(k,{}).get('status')!='missing' for k in ('game_menu','switch_dialog')) or identity.get('switchLoading',False)
        dungeon,gates=observer.analyze(frame,regions,seconds,blocked=blocked)
        context=dt.update(seconds,dungeon)
        state=live.update(datetime.fromisoformat(r['observedAt']),identity,gates,context)
        if any(a['type']=='suspend' for a in state['identity']['actions']):
            dt.reset();observer.reset();context=dt.update(seconds,{})
        row=dict(sequence=r['sequence'],sessionId=r['sessionId'],character=identity,
                 identity=state['identity'],dungeon=dungeon,context=context,gates=gates,
                 result=state['result'],recordingStatus=state['recordingStatus'])
        results.append(row)
        if row['identity']['actions'] or row['context']['contextStatus']=='ocr_verified':
            print(json.dumps(dict(n=r['sequence'],identity=row['identity'],context=row['context']),ensure_ascii=True),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=dict(identityInitialization='recorded_confirmed_identity' if args.restore_recorded_identity else 'fresh',
                 sessions={sid:dict(states=values[3].state_records(),events=[r for r in values[3].state_records() if r['state']=='완료' and r.get('characterName')],pendingEvents=[r for r in values[3].state_records() if not r.get('characterName')]) for sid,values in sessions.items()})
    args.output.with_suffix('.summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    for values in sessions.values():values[3].close()
    print('DONE',len(results),flush=True)

if __name__=='__main__':main()
