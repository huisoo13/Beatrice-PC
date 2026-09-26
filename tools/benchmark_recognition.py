"""저장 화면의 동일 순서로 모델/OCR 처리 시간을 측정합니다(캡처·파일 저장 제외)."""
import argparse,json,os,sys,time,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--optimized',action='store_true')
    args=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2,torch
    torch.set_num_threads(4)
    from ultralytics import YOLO
    from beatrice.ui_regions import UIRegionDetector,dungeon_location
    from beatrice.character_vision import CharacterVision
    from beatrice.character import CharacterTracker
    from beatrice.dungeon import DungeonOCR
    from beatrice.dungeon_observer import DungeonObserver
    config=json.loads(args.config.read_text(encoding='utf-8'))
    detector=UIRegionDetector(config);ocr=DungeonOCR();vision=CharacterVision(reader=ocr.reader)
    observer=DungeonObserver(ocr)
    samples=[('live-name-failure',n) for n in (4,5,6,7,8,69,70,71,72,73)]+[('live-failure',n) for n in (35,37,56,60,62)]+[('live-dungeon-failure',n) for n in (67,68,69,70,71,72,73)]
    tracker=CharacterTracker(max_gap=5);rows=[];clock=0
    detector.locate(cv2.imread(str(ROOT/'outputs/live-name-failure/frame-004.jpg')))
    for directory,n in samples:
        frame=cv2.imread(str(ROOT/f'outputs/{directory}/frame-{n:03d}.jpg'))
        start=time.perf_counter();regions=detector.locate(frame);t1=time.perf_counter()
        if args.optimized:
            character=vision.analyze_detected(frame,regions,seconds=clock,confirmed_name=tracker.current if not tracker.blocked else None)
        else:character=vision.analyze_detected(frame,regions)
        t2=time.perf_counter()
        dungeon,boxes=observer.analyze(frame,regions,clock);end=time.perf_counter()
        state=tracker.update(clock,character)
        rows.append(dict(source=f'{directory}/{n}',yoloMs=(t1-start)*1000,characterMs=(t2-t1)*1000,dungeonMs=(end-t2)*1000,totalMs=(end-start)*1000,character=character.get('currentName'),identity=state,dungeon=dungeon.get('dungeonName')))
        clock+=max(.5,end-start)
    report=dict(config=config,optimized=args.optimized,rows=rows,means={k:statistics.mean(r[k] for r in rows) for k in ('yoloMs','characterMs','dungeonMs','totalMs')},menuMeanMs=statistics.mean(r['totalMs'] for r in rows[:10]))
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('config','rows')}))

if __name__=='__main__':main()
