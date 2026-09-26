"""기존 모델로 영상을 주기 관측합니다. 이벤트 확정/추가 학습은 하지 않습니다."""
import argparse
import sys
import hashlib
import json
import time
from pathlib import Path
from yolo_first import ROOT, CLASSES
sys.path.insert(0,str(ROOT))
from beatrice.dungeon import DungeonOCR, DungeonTracker, CONFIG
import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path);p.add_argument('--output',type=Path,default=ROOT/'outputs/video002')
    p.add_argument('--hz',type=float,default=5)
    p.add_argument('--without-dungeon-ocr',action='store_true')
    a=p.parse_args()
    dungeon_ocr=None if a.without_dungeon_ocr else DungeonOCR()
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.dungeon_observer import DungeonObserver
    from beatrice.ui_regions import detected_gates
    detector=UIRegionDetector()
    dungeon_tracker=DungeonTracker(max_gap=5)
    if a.hz<=0:raise ValueError('hz는 양수여야 합니다')
    out=a.output;out.mkdir(parents=True,exist_ok=True)
    (out/'frames').mkdir(exist_ok=True)
    model_hashes={name:hashlib.sha256((ROOT/f'models/{name}.pt').read_bytes()).hexdigest()
                  for name in ('character-regions','dungeon-regions','dungeon-elements')}
    torch.set_num_threads(4)
    observer=DungeonObserver(dungeon_ocr) if dungeon_ocr else None
    cap=cv2.VideoCapture(str(a.video))
    if not cap.isOpened():raise ValueError('영상 열기 실패')
    fps=cap.get(cv2.CAP_PROP_FPS);n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));w=int(cap.get(3));h=int(cap.get(4))
    meta=dict(width=w,height=h,fps=fps,metadataFrameCount=n,durationSeconds=n/fps,requestedHz=a.hz,modelSha256=model_hashes)
    print(json.dumps(meta),flush=True)
    rows=[];changes=[];previous=None;next_t=0;idx=0;begin=time.perf_counter()
    try:
        while cap.grab():
            t=cap.get(cv2.CAP_PROP_POS_MSEC)/1000
            if t+1e-6>=next_t:
                ok,frame=cap.retrieve()
                if not ok:raise RuntimeError(f'프레임 복원 실패 {idx}')
                start=time.perf_counter();regions=detector.locate(frame)
                if observer is not None:
                    observation,boxes=observer.analyze(frame,regions,t)
                else:
                    boxes=detected_gates(regions)
                ms=(time.perf_counter()-start)*1000
                boxes.sort(key=lambda v:v['xyxy'][0]);signature=[v['state'] for v in boxes]
                row=dict(frameIndex=idx,videoSeconds=t,predictionMs=ms,boxes=boxes,counts={s:signature.count(s) for s in CLASSES})
                if dungeon_ocr is not None:
                    row['dungeonObservation']=observation
                    row['dungeonContext']=dungeon_tracker.update(t,row['dungeonObservation'])
                rows.append(row)
                cv2.imwrite(str(out/'frames'/f'{idx:06d}.png'),frame)
                if signature!=previous:changes.append(dict(sampleIndex=len(rows)-1,videoSeconds=t,statesLeftToRight=signature));previous=signature
                next_t=(int(t*a.hz)+1)/a.hz
                if len(rows)%50==0:print(f'{t:.2f}초까지 {len(rows)}회 관측',flush=True)
            idx+=1
    finally:cap.release()
    with a.video.open('rb') as source_file:
        meta['sourceSha256']=hashlib.file_digest(source_file,'sha256').hexdigest()
    meta['dungeonOCREnabled']=dungeon_ocr is not None
    meta['dungeonOCR']=CONFIG if dungeon_ocr is not None else None
    meta.update(decodedFrameCount=idx,sampleCount=len(rows),wallSeconds=time.perf_counter()-begin,signatureChanges=changes,eventConfirmed=False,metadataFrameCountDifference=n-idx,lastSampleSeconds=rows[-1]["videoSeconds"] if rows else None)
    (out/'observations.json').write_text(json.dumps(dict(meta=meta,observations=rows),ensure_ascii=False,indent=2))
    # 약 2초마다 원본과 예측을 함께 보존한 검토 카드 생성.
    font_path=next((p for p in (Path('C:/Windows/Fonts/malgun.ttf'),Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')) if p.exists()),None)
    font=ImageFont.truetype(str(font_path),18) if font_path else ImageFont.load_default()
    picks=sorted(set(list(range(0,len(rows),10))+[c['sampleIndex'] for c in changes]+[len(rows)-1]))
    cards=[]
    for j in picks:
        row=rows[j];im=Image.open(out/'frames'/f'{row["frameIndex"]:06d}.png').convert('RGB')
        original_width,original_height=im.size
        scale=min(800/original_width,480/original_height)
        preview=im.resize((round(original_width*scale),round(original_height*scale)))
        card=Image.new('RGB',(800,530),'#101820');card.paste(preview,(0,40));d=ImageDraw.Draw(card)
        d.text((8,7),f"{row['videoSeconds']:.3f}s / {len(row['boxes'])}개 예측",font=font,fill='white')
        for box in row['boxes']:
            x1,y1,x2,y2=[v*scale for v in box['xyxy']];d.rectangle((x1,y1+40,x2,y2+40),outline='#00ff99',width=2)
            d.text((x1,y2+43),f"{box['state']} {box['confidence']:.2f}",font=font,fill='white',stroke_width=1,stroke_fill='black')
        card.save(out/f'review_{j:03d}.png');cards.append(card)
    for page in range(0,len(cards),6):
        sheet=Image.new('RGB',(1600,530*((min(6,len(cards)-page)+1)//2)),'#101820')
        for k,card in enumerate(cards[page:page+6]):sheet.paste(card,((k%2)*800,(k//2)*530))
        sheet.save(out/f'sheet_{page//6:02d}.jpg')
    print(json.dumps(meta,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
