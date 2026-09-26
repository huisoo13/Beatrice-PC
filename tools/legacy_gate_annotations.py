"""Retired crop-model helpers, retained only to reproduce offline training labels."""
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def load_config():
    return json.loads((ROOT/'tools/legacy-gate-regions.json').read_text(encoding='utf-8'))


def relative_box(panel,region,shape):
    x1,y1,x2,y2=panel
    l,t,r,b=region
    if not (0<=l<r<=1 and 0<=t<b<=1):raise ValueError('상대 영역은 0~1 범위여야 합니다.')
    h,w=shape[:2]
    return [max(0,math.floor(x1+(x2-x1)*l)),max(0,math.floor(y1+(y2-y1)*t)),
            min(w,math.ceil(x1+(x2-x1)*r)),min(h,math.ceil(y1+(y2-y1)*b))]




def gate_crop_box(region,shape):
    """관문 아이콘이 세로로 늘어나지 않도록 기존 모델의 입력 비율만큼 영역을 확장합니다."""
    l,t,r,b=region
    w,h=r-l,b-t;cx,cy=(l+r)/2,(t+b)/2
    w=max(w,h*320/112);h=max(h,w*112/320)
    w=min(shape[1],math.ceil(w));h=min(shape[0],math.ceil(h))
    l=max(0,min(math.floor(cx-w/2),shape[1]-w))
    t=max(0,min(math.floor(cy-h/2),shape[0]-h))
    return [l,t,l+w,t+h]


def predict_panel_gates(model,frame,region,expected_count=None):
    """패널 내부 관문을 기존 모델로 읽고 저장용 좌표를 기존 기준에 정규화합니다."""
    import cv2
    l,t,r,b=gate_crop_box(region,frame.shape)
    def read(left,right):
        crop=cv2.resize(frame[t:b,left:right],(320,112))
        result=model.predict(crop,imgsz=320,conf=.65,iou=.5,agnostic_nms=True,device='cpu',verbose=False)[0]
        boxes=[]
        for box in result.boxes:
            x1,y1,x2,y2=box.xyxy[0].tolist()
            # 보조 crop의 좌표도 기준 crop의 가상 좌표로 환산합니다.
            x1=((x1/320*(right-left)+left)-l)/(r-l)*320
            x2=((x2/320*(right-left)+left)-l)/(r-l)*320
            if not 0<=x1<x2<=320:continue
            boxes.append(dict(state=model.names[int(box.cls[0])],confidence=float(box.conf[0]),xyxy=[x1+32,y1+112,x2+32,y2+112]))
        return sorted(boxes,key=lambda b:b['xyxy'][0])
    boxes=read(l,r)
    if expected_count and len(boxes)<expected_count and l>=2 and r+2<=frame.shape[1]:
        candidates=[read(l+offset,r+offset) for offset in (-2,2)]
        if all(len(c)==expected_count for c in candidates):
            agree=all(a['state']==b['state'] and max(abs(x-y) for x,y in zip(a['xyxy'],b['xyxy']))<=10 for a,b in zip(*candidates))
            if agree:boxes=max(candidates,key=lambda c:min(b['confidence'] for b in c))
    return boxes
