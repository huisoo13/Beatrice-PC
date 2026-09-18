"""3440x1440 이미지 → YOLO 영역 → OCR 이름. 입력 출처와 시간 처리는 분리됩니다."""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ROIS={'portrait': (900,850,1140,960), 'dialog': (1440,560,2000,880)}


class CharacterVision:
    def __init__(self, weights=None):
        for key,folder in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib')]:
            os.environ.setdefault(key,str(ROOT/'outputs'/folder))
            Path(os.environ[key]).mkdir(parents=True,exist_ok=True)
        import torch
        torch.set_num_threads(4)
        from ultralytics import YOLO
        import easyocr
        self.model=YOLO(str(weights or ROOT/'models/character-yolo26n-first.pt'))
        if list(self.model.names.values()) != ['current_name','target_name','switch_dialog']:
            raise ValueError('캐릭터 모델 클래스가 다릅니다.')
        import cv2
        self.menu_template=cv2.imread(str(ROOT/'models/menu-layout/normal-menu.png'),cv2.IMREAD_GRAYSCALE)
        if self.menu_template is None:
            raise ValueError('일반 메뉴 참조 이미지가 없습니다.')
        self.reader=easyocr.Reader(['ko','en'],gpu=False,detector=False,
            model_storage_directory=str(ROOT/'models/easyocr'),
            user_network_directory=str(ROOT/'models/easyocr/user'),download_enabled=False,verbose=False)

    def read_name(self,frame,box):
        import cv2
        x1,y1,x2,y2=[round(v) for v in box]
        crop=frame[max(0,y1-2):min(frame.shape[0],y2+2),max(0,x1-2):min(frame.shape[1],x2+2)]
        if crop.size==0:
            return None
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        enlarged=cv2.resize(gray,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
        readings=[]
        for variant in [gray,enlarged]:
            values=self.reader.recognize(variant)
            if len(values)==1:
                readings.append(dict(text=values[0][1],confidence=float(values[0][2])))
        # 전처리 간 결과가 다르면 알고 있는 이름으로 임의 보정하지 않습니다.
        accepted=None
        if len(readings)==2 and readings[0]['text']==readings[1]['text']:
            accepted=dict(text=readings[0]['text'],confidence=min(v['confidence'] for v in readings))
        return dict(accepted=accepted,raw=readings)

    def analyze(self,frame):
        if frame.shape[:2]!=(1440,3440):
            raise ValueError('현재 캐릭터 ROI는 3440x1440 전용입니다.')
        detections=[]
        for region,(l,t,r,b) in ROIS.items():
            prediction=self.model.predict(frame[t:b,l:r],imgsz=640,conf=.5,device='cpu',verbose=False)[0]
            for box in prediction.boxes:
                kind=self.model.names[int(box.cls[0])]
                if (kind=='current_name') != (region=='portrait'):
                    continue
                x1,y1,x2,y2=box.xyxy[0].tolist()
                detections.append(dict(kind=kind,confidence=float(box.conf[0]),xyxy=[x1+l,y1+t,x2+l,y2+t]))
        groups={kind:[d for d in detections if d['kind']==kind] for kind in self.model.names.values()}
        import cv2
        menu_region=cv2.cvtColor(frame[415:840,1160:2040],cv2.COLOR_BGR2GRAY)
        menu_score=float(cv2.matchTemplate(menu_region,self.menu_template,cv2.TM_CCOEFF_NORMED)[0,0])
        out=dict(normalMenu=menu_score>=.90 and not bool(groups['switch_dialog']),normalMenuScore=menu_score,currentName=None,targetName=None,currentRegionVisible=bool(groups['current_name']),
                 switchDialog=bool(groups['switch_dialog']),detections=detections,ocr={})
        for kind,field in [('current_name','currentName'),('target_name','targetName')]:
            if len(groups[kind])==1 and (kind!='target_name' or out['switchDialog']):
                read=self.read_name(frame,groups[kind][0]['xyxy'])
                out['ocr'][field]=read
                if read:
                    out[field]=read['accepted']
        return out
