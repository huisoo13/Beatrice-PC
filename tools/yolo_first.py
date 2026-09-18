"""YOLO26n 첫 학습 및 정지 이미지 추론. 기능 확인용 데이터이며 독립 평가 아님."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('YOLO_CONFIG_DIR', str(ROOT/'outputs/ultralytics-config'))
os.environ.setdefault('MPLCONFIGDIR', str(ROOT/'outputs/matplotlib'))
Path(os.environ['YOLO_CONFIG_DIR']).mkdir(parents=True, exist_ok=True)
Path(os.environ['MPLCONFIGDIR']).mkdir(parents=True, exist_ok=True)
ROI = (32, 112, 352, 224)
CLASSES = ['진행중', '완료', '진행 전']
DATA = ROOT/'data/yolo-first'


def prepare():
    from PIL import Image
    import yaml
    items=[]; seen=set()
    for name in ['review-v1','review-v2']:
        doc=json.loads((ROOT/f'data/annotations/{name}.json').read_text())
        if doc['reviewStatus']!='approved' or doc['classes']!=CLASSES:
            raise ValueError('승인 상태 또는 클래스 순서 불일치')
        for item in doc['images']:
            src=ROOT/item['path']; raw=src.read_bytes()
            digest=hashlib.sha256(raw).hexdigest()
            if digest!=item['sha256']: raise ValueError('원본 해시 불일치')
            if digest in seen: continue
            seen.add(digest)
            im=Image.open(src).convert('RGB')
            if im.size!=(3440,1440):raise ValueError('첫 버전은 3440x1440만 지원')
            key=name+'_'+item['id']; labels=[]
            for b in item['boxes']:
                x1,y1,x2,y2=b['xyxy']; l,t,r,bot=ROI
                if not(l<=x1<x2<=r and t<=y1<y2<=bot):raise ValueError('ROI가 박스를 자릅니다')
                values=[((x1+x2)/2-l)/(r-l),((y1+y2)/2-t)/(bot-t),(x2-x1)/(r-l),(y2-y1)/(bot-t)]
                labels.append(str(CLASSES.index(b['state']))+' '+' '.join(f'{v:.9f}' for v in values))
            for folder in ['images','labels']:(DATA/folder).mkdir(parents=True,exist_ok=True)
            im.crop(ROI).save(DATA/'images'/f'{key}.png')
            (DATA/'labels'/f'{key}.txt').write_text('\n'.join(labels)+'\n')
            items.append(dict(key=key,source=item['path'],sessionId=item['sessionId'],boxes=item['boxes']))
    manifest=dict(purpose='training_set_reconstruction_only_not_independent_evaluation',roi=ROI,images=items)
    (DATA/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    # Ultralytics가 요구하는 val 경로. 같은 데이터를 다시 읽는 기능 확인일 뿐 독립 평가가 아닙니다.
    (DATA/'dataset.yaml').write_text(yaml.safe_dump(dict(path=str(DATA),train='images',val='images',names=CLASSES),allow_unicode=True))
    print(f'{len(items)}장 준비. train=val은 기능 확인 전용, 정확도 보고 금지.')


def train(epochs,device):
    import torch
    torch.set_num_threads(4)
    from ultralytics import YOLO
    model=YOLO(str(ROOT/'models/yolo26n.pt'))
    model.train(data=str(DATA/'dataset.yaml'),epochs=epochs,imgsz=320,batch=5,device=device,workers=0,
                project=str(ROOT/'outputs/training'),name='yolo26n-first',exist_ok=False,
                seed=42,optimizer='AdamW',lr0=.001,patience=0,freeze=10,
                mosaic=0,mixup=0,fliplr=0,flipud=0,degrees=0,shear=0,perspective=0,
                translate=.05,scale=.15,hsv_h=0,hsv_s=.1,hsv_v=.15,
                plots=False,val=False,amp=False)


def predict(source,weights,destination,font_path):
    from PIL import Image,ImageDraw,ImageFont
    import numpy as np
    from ultralytics import YOLO
    im=Image.open(source).convert('RGB')
    if im.size!=(3440,1440):raise ValueError('현재 ROI 설정은 3440x1440 전용입니다.')
    if not weights.is_file():raise ValueError('학습된 모델 파일을 지정해주세요.')
    model=YOLO(str(weights))
    if [model.names[i] for i in range(len(model.names))]!=CLASSES:raise ValueError('학습 모델의 클래스가 다릅니다.')
    frame=np.array(im.crop(ROI))[:,:,::-1].copy()
    start=time.perf_counter()
    result=model.predict(frame,imgsz=320,conf=.25,iou=.5,device='cpu',verbose=False)[0]
    elapsed=(time.perf_counter()-start)*1000
    detections=[];counts={n:0 for n in CLASSES}
    for b in result.boxes:
        x1,y1,x2,y2=b.xyxy[0].tolist(); state=model.names[int(b.cls[0])]
        detections.append(dict(state=state,confidence=float(b.conf[0]),box=[x1+ROI[0],y1+ROI[1],x2+ROI[0],y2+ROI[1]]));counts[state]+=1
    detections.sort(key=lambda d:d['box'][0])
    # 누락 시 번호가 바뀔 수 있으므로 탐지 순서를 확정 관문 번호로 저장하지 않습니다.
    report=dict(schemaVersion=1,kind='frame_observation',source=str(source.resolve()),roi=ROI,
                model=str(weights.resolve()),counts=counts,detections=detections,
                predictionCallMs=elapsed,gateIdentityStatus='not_validated',eventConfirmed=False)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'observation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    font=ImageFont.truetype(str(font_path),22)
    preview=im.crop((32,100,352,240)).resize((960,420));draw=ImageDraw.Draw(preview)
    for i,d in enumerate(detections):
        x1,y1,x2,y2=d['box'];rect=((x1-32)*3,(y1-100)*3,(x2-32)*3,(y2-100)*3)
        draw.rectangle(rect,outline='#00ff99',width=3)
        draw.text((rect[0],rect[3]+5),f"{d['state']} {d['confidence']:.2f}",fill='white',font=font,stroke_width=2,stroke_fill='black')
    preview.save(destination/'prediction.png')
    print(json.dumps(counts,ensure_ascii=False));print(destination)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('prepare');t=sub.add_parser('train');t.add_argument('--epochs',type=int,default=80);t.add_argument('--device',default='cpu')
    pred=sub.add_parser('predict');pred.add_argument('image',type=Path);pred.add_argument('--weights',type=Path,required=True);pred.add_argument('--output',type=Path,default=ROOT/'outputs/prediction');pred.add_argument('--font',type=Path,default=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc'))
    a=p.parse_args()
    if a.command=='prepare':prepare()
    elif a.command=='train':train(a.epochs,a.device)
    else:predict(a.image,a.weights,a.output,a.font)
