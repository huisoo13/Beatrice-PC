"""정지 이미지 또는 녹화 영상에서 캐릭터 이름 관측과 상태 변화를 JSON으로 저장합니다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.character import CharacterTracker
from beatrice.character_vision import CharacterVision


def main():
    import cv2
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hz',type=float,default=2)
    p.add_argument('--config',type=Path)
    args=p.parse_args()
    if not 1.5 <= args.hz <= 10:
        p.error('현재 연속 관측 설정에 맞게 1.5~10Hz를 사용해주세요.')
    from beatrice.ui_regions import UIRegionDetector,load_config
    config=json.loads(args.config.read_text(encoding='utf-8')) if args.config else load_config()
    detector=UIRegionDetector(config);vision=CharacterVision()
    tracker=CharacterTracker()
    rows=[]
    def analyze(frame,seconds):
        start=time.perf_counter()
        observed=vision.analyze_detected(frame,detector.locate(frame),seconds=seconds)
        state=tracker.update(seconds,observed)
        row=dict(videoSeconds=seconds,observation=observed,state=state,analysisMs=(time.perf_counter()-start)*1000)
        rows.append(row)
        if state['actions']:
            print(json.dumps(dict(seconds=seconds,actions=state['actions']),ensure_ascii=False),flush=True)
    if args.source.suffix.lower() in ('.jpg','.jpeg','.png'):
        frame=cv2.imread(str(args.source))
        if frame is None:raise ValueError('이미지를 읽을 수 없습니다.')
        analyze(frame,0)
    else:
        cap=cv2.VideoCapture(str(args.source))
        if not cap.isOpened():raise ValueError('영상을 열 수 없습니다.')
        fps=cap.get(cv2.CAP_PROP_FPS)
        if fps<=0:raise ValueError('영상 FPS를 읽을 수 없습니다.')
        index=0;next_sample=0
        try:
            while cap.grab():
                seconds=index/fps
                if seconds>=next_sample:
                    ok,frame=cap.retrieve()
                    if not ok:raise ValueError(f'{seconds}초 프레임 디코딩 실패')
                    analyze(frame,seconds)
                    next_sample+=1/args.hz
                index+=1
        finally:
            cap.release()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # 영상 시각은 흐름 검증용입니다. 실제 완료 이벤트의 시각으로 저장하지 않습니다.
    with args.source.open('rb') as f:
        digest=hashlib.file_digest(f,'sha256').hexdigest()
    result=dict(schemaVersion=1,source=str(args.source.resolve()),sha256=digest,
        purpose='development_replay_not_independent_evaluation',eventStoragePerformed=False,
        modelConfig=config,observations=rows)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(f'{len(rows)}개 관측 저장: {args.output}')

if __name__=='__main__':main()
