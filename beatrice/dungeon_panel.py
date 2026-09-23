"""전체 화면에서 던전 패널을 찾고 원본 픽셀의 상대 영역을 반환합니다."""
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def load_config():
    return json.loads((ROOT/'config/dungeon-panel.json').read_text(encoding='utf-8'))


def relative_box(panel,region,shape):
    x1,y1,x2,y2=panel
    l,t,r,b=region
    if not (0<=l<r<=1 and 0<=t<b<=1):raise ValueError('상대 영역은 0~1 범위여야 합니다.')
    h,w=shape[:2]
    return [max(0,math.floor(x1+(x2-x1)*l)),max(0,math.floor(y1+(y2-y1)*t)),
            min(w,math.ceil(x1+(x2-x1)*r)),min(h,math.ceil(y1+(y2-y1)*b))]


class DungeonPanelDetector:
    def __init__(self,config=None,model=None):
        self.config=config or load_config()
        if model is None:
            path=ROOT/self.config['weights']
            if not path.is_file():
                raise ValueError('던전 패널 모델이 없습니다. 학습·검증 후 yolo 모드를 활성화해주세요.')
            from ultralytics import YOLO
            model=YOLO(str(path))
        if list(model.names.values())!=[self.config['className']]:
            raise ValueError('던전 패널 모델 클래스가 다릅니다.')
        self.model=model

    def locate(self,frame):
        result=self.model.predict(frame,imgsz=self.config['imageSize'],
            conf=self.config['confidence'],iou=.5,device='cpu',verbose=False)[0]
        candidates=[]
        h,w=frame.shape[:2]
        for box in result.boxes:
            coords=box.xyxy[0].tolist();score=float(box.conf[0])
            if len(coords)!=4 or not all(math.isfinite(v) for v in coords):continue
            x1,y1,x2,y2=coords
            if (int(box.cls[0])!=0 or not math.isfinite(score) or score<self.config['confidence']
                or not (0<=x1<x2<=w and 0<=y1<y2<=h)):continue
            candidates.append(dict(xyxy=coords,confidence=score))
        # 위치가 모호하면 최고 점수 하나로 임의 선택하지 않습니다.
        if len(candidates)!=1:
            return dict(status='missing' if not candidates else 'ambiguous',regions={},candidates=candidates)
        panel=candidates[0]
        regions={name:relative_box(panel['xyxy'],value,frame.shape)
                 for name,value in self.config['regions'].items()}
        if any(r-l<2 or b-t<2 for l,t,r,b in regions.values()):
            return dict(status='too_small',regions={},candidates=candidates)
        return dict(status='detected',regions=regions,**panel)


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
