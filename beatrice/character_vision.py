"""3440x1440 이미지 → YOLO 영역 → OCR 이름. 입력 출처와 시간 처리는 분리됩니다."""
import os
import re
import unicodedata
from pathlib import Path
from .character import valid_name

ROOT=Path(__file__).resolve().parents[1]
ROIS={'portrait': (900,850,1140,960), 'dialog': (1440,560,2000,880)}
# 현재 캐릭터는 레벨을 포함한 전체 줄을 읽습니다. 이름 시작점은 고정하지 않습니다.
NAME_LINES={'current_name': (760,897,1310,925), 'target_name': (1552,655,1888,688)}


def name_from_line(text, includes_level=False):
    text=unicodedata.normalize('NFC',text).strip()
    if includes_level:
        # 줄 맨 앞의 레벨만 제거합니다. 이름 안의 Lv/숫자는 보존합니다.
        # 두 자리 레벨 뒤에 붙은 숫자 닉네임을 레벨로 삼키지 않습니다.
        match=re.match(r'^Lv\s*[.．]?\s*[0-9]{1,2}\s*',text,re.IGNORECASE)
        if match is None:
            return None
        text=text[match.end():].strip()
    return valid_name(dict(text=text,confidence=1))


def name_line_box(kind, detected=None):
    left,top,right,bottom=NAME_LINES[kind]
    if detected is not None:
        # 탐지된 세로 위치와 넓은 이름의 끝은 보존합니다.
        x1,top,x2,bottom=detected
        left=min(left,x1);right=max(right,x2)
    return [left,top,right,bottom]


def trim_name_line(crop, max_gap=None):
    """넓은 탐색 줄에서 흰색/노란색 글자 군집을 찾아 배경 여백을 제거합니다."""
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    h,s,v=cv2.split(hsv)
    mask=(((s<100)|((h>=15)&(h<=40)))&(v>=120)).astype(np.uint8)*255
    joined=cv2.dilate(mask,np.ones((1,max_gap or max(3,crop.shape[0]//3)),np.uint8))
    count,labels,stats,_=cv2.connectedComponentsWithStats(joined)
    candidates=[]
    for index in range(1,count):
        x,y,w,height,area=stats[index]
        if height>=crop.shape[0]*.35 and w>=height:
            candidates.append((int(np.count_nonzero(mask[labels==index])),index))
    if not candidates:
        return None
    index=max(candidates)[1]
    points=cv2.findNonZero(np.where(labels==index,mask,0).astype(np.uint8))
    x,y,w,height=cv2.boundingRect(points)
    return crop[max(0,y-3):min(crop.shape[0],y+height+3),max(0,x-3):min(crop.shape[1],x+w+3)]


class CharacterVision:
    def __init__(self, weights=None, reader=None):
        for key,folder in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib')]:
            os.environ.setdefault(key,str(ROOT/'outputs'/folder))
            Path(os.environ[key]).mkdir(parents=True,exist_ok=True)
        import torch
        torch.set_num_threads(4)
        from ultralytics import YOLO
        self.model=YOLO(str(weights or ROOT/'models/character-yolo26n-first.pt'))
        if list(self.model.names.values()) != ['current_name','target_name','switch_dialog']:
            raise ValueError('캐릭터 모델 클래스가 다릅니다.')
        import cv2
        self.menu_template=cv2.imread(str(ROOT/'models/menu-layout/normal-menu.png'),cv2.IMREAD_GRAYSCALE)
        if self.menu_template is None:
            raise ValueError('일반 메뉴 참조 이미지가 없습니다.')
        if reader is None:
            from .paddle_reader import PaddleKoreanReader
            reader=PaddleKoreanReader()
        self.reader=reader

    def read_name(self,frame,box,includes_level=False):
        import cv2
        x1,y1,x2,y2=[round(v) for v in box]
        crop=frame[max(0,y1-2):min(frame.shape[0],y2+2),max(0,x1-2):min(frame.shape[1],x2+2)]
        if crop.size==0:
            return None
        crop=trim_name_line(crop)
        if crop is None:
            return dict(accepted=None,raw=[],status='no_text_pixels')
        gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        enlarged=cv2.resize(gray,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
        readings=[]
        for variant in [gray,enlarged]:
            values=self.reader.recognize(variant)
            if len(values)==1:
                readings.append(dict(text=values[0][1],confidence=float(values[0][2]),
                    name=name_from_line(values[0][1],includes_level)))
        # 전처리 간 결과가 다르면 알고 있는 이름으로 임의 보정하지 않습니다.
        accepted=None
        if len(readings)==2 and readings[0]['name'] and readings[0]['name']==readings[1]['name']:
            accepted=dict(text=readings[0]['name'],confidence=min(v['confidence'] for v in readings))
        status='accepted' if valid_name(accepted) else ('low_confidence' if accepted else 'ocr_disagreement_or_invalid_name')
        if status!='accepted':accepted=None
        return dict(accepted=accepted,raw=readings,status=status)

    def read_loading(self,frame,ui_scale=1.0):
        """실제 게임 창 오른쪽 아래에 고정된 청록색 아이콘과 대기 문구를 함께 확인합니다."""
        import cv2
        h,w=frame.shape[:2]
        scale=h/1440*ui_scale
        crop=frame[max(0,h-round(170*scale)):h,max(0,w-round(450*scale)):w]
        crop=cv2.resize(crop,(450,170))
        hsv=cv2.cvtColor(crop[20:130,295:425],cv2.COLOR_BGR2HSV)
        cyan=cv2.inRange(hsv,(75,70,100),(110,255,255))
        icon=bool(cv2.countNonZero(cyan)>=150)
        readings=[]
        if icon:
            text_crop=crop[60:96,65:292]
            for _,text,confidence in self.reader.recognize(text_crop):
                readings.append(dict(text=text,confidence=float(confidence)))
        matched=any(r['confidence']>=.85 and re.sub(r'[\s.!。]','',r['text'])=='잠시만기다려주세요' for r in readings)
        return dict(visible=icon and matched,iconVisible=icon,raw=readings)

    def analyze(self,frame,loading_frame=None,ui_scale=1.0):
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
        switch_dialog=bool(groups['switch_dialog'])
        # 이름 학습과 무관한 팝업 제목으로 탐지 누락을 보완합니다.
        if not switch_dialog:
            title=trim_name_line(frame[588:642,1460:1980])
            if title is not None:
                for _,text,confidence in self.reader.recognize(title):
                    if confidence>=.85 and '다른캐릭터바로접속' in re.sub(r'\s','',text):
                        switch_dialog=True
        out=dict(normalMenu=menu_score>=.90 and not switch_dialog,normalMenuScore=menu_score,currentName=None,targetName=None,currentRegionVisible=bool(groups['current_name']),
                 switchDialog=switch_dialog,detections=detections,ocr={})
        loading=self.read_loading(frame if loading_frame is None else loading_frame,ui_scale)
        out['switchLoading']=loading['visible']
        out['ocr']['loading']=loading
        for kind,field in [('current_name','currentName'),('target_name','targetName')]:
            # 일반 메뉴에서는 이름의 길이/학습 여부와 무관하게 전체 이름 줄을 읽습니다.
            # 메뉴가 닫힌 플레이 화면에는 고정 영역 OCR을 적용하지 않습니다.
            box=None
            if kind=='current_name' and out['normalMenu']:
                box=name_line_box(kind)
                out['currentRegionVisible']=True
            elif len(groups[kind])==1 and (kind!='target_name' or out['switchDialog']):
                box=name_line_box(kind,groups[kind][0]['xyxy'])
            if box is not None:
                read=self.read_name(frame,box,includes_level=kind=='current_name')
                out['ocr'][field]=read
                if read:
                    out[field]=read['accepted']
        out['diagnosticStatus']=out['ocr'].get('currentName',{}).get('status','name_region_not_found')
        return out
