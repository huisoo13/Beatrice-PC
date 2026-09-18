"""학습 이미지 재관측 검사. 독립 정확도 평가가 아닙니다."""
import json
from pathlib import Path
import numpy as np
from PIL import Image
from yolo_first import ROOT, ROI, CLASSES
from ultralytics import YOLO


def iou(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


m=json.loads((ROOT/'data/yolo-first/manifest.json').read_text())
model=YOLO(str(ROOT/'models/gates-yolo26n-first.pt'))
rows=[]
for item in m['images']:
    im=Image.open(ROOT/item['source']).convert('RGB').crop(ROI)
    result=model.predict(np.array(im)[:,:,::-1].copy(),imgsz=320,conf=.25,iou=.5,device='cpu',verbose=False)[0]
    pred=[]
    for box in result.boxes:
        x1,y1,x2,y2=box.xyxy[0].tolist()
        pred.append(dict(state=model.names[int(box.cls[0])],box=[x1+ROI[0],y1+ROI[1],x2+ROI[0],y2+ROI[1]]))
    matches=[];used=set()
    for gt in item['boxes']:
        choices=[(iou(gt['xyxy'],p['box']),i) for i,p in enumerate(pred) if i not in used]
        overlap,index=max(choices,default=(0,-1))
        if overlap>=.5:
            used.add(index);matches.append(dict(iou=overlap,stateCorrect=pred[index]['state']==gt['state']))
    rows.append(dict(source=item['source'],expected=len(item['boxes']),predicted=len(pred),
                     missed=len(item['boxes'])-len(matches),extra=len(pred)-len(matches),
                     stateErrors=sum(not match['stateCorrect'] for match in matches)))
report=dict(purpose='training_image_reconstruction_not_independent_evaluation',images=rows)
(ROOT/'outputs/training-reconstruction.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False,indent=2))
