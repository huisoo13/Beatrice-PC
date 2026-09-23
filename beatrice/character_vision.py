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
    def __init__(self, weights=None, reader=None, legacy=True):
        for key,folder in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib')]:
            os.environ.setdefault(key,str(ROOT/'outputs'/folder))
            Path(os.environ[key]).mkdir(parents=True,exist_ok=True)
        import torch
        torch.set_num_threads(4)
        if legacy:
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
        # 레벨과 이름 사이 공백도 같은 줄로 묶어야 이름만 남고 Lv가 사라지지 않습니다.
        crop=trim_name_line(crop,max_gap=max(12,crop.shape[0]) if includes_level else None)
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
        return self.read_loading_crop(crop)

    def read_menu_name(self,frame,menu):
        """탐지된 메뉴의 초상화에서 노란 레벨 줄을 찾고 Lv 접두사를 검증합니다."""
        import cv2
        import numpy as np
        l,t,r,b=menu;w=r-l;h=b-t
        x1=max(0,round(l-.08*w));x2=min(frame.shape[1],round(l+.22*w))
        y1=max(0,round(t+.68*h));y2=min(frame.shape[0],round(t+.90*h))
        crop=frame[y1:y2,x1:x2]
        if not crop.size:return dict(accepted=None,raw=[],status='empty_menu_portrait')
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(15,80,120),(40,255,255))
        # 초상화 장식의 금색 픽셀을 행 전체로 합산하면 레벨 줄과 합쳐집니다.
        # 글자 높이의 가로 군집만 줄 후보로 사용합니다.
        joined=cv2.dilate(mask,np.ones((1,max(3,round(h*.015))),np.uint8))
        _,_,stats,_=cv2.connectedComponentsWithStats(joined)
        bands=[]
        for x,y,width,height,area in stats[1:]:
            if h*.012<=height<=h*.05 and width>=height*1.5:
                band=(max(y1,y1+int(y)-5),min(y2,y1+int(y+height)+5))
                if not any(abs(band[0]-old[0])<4 and abs(band[1]-old[1])<4 for old in bands):bands.append(band)
        reads=[]
        # 가장 가능성이 높은 레벨 줄부터 검사해 장식/아이템 레벨 OCR을 줄입니다.
        for top,bottom in sorted(bands,key=lambda band:abs((band[0]+band[1])/2-(t+.81*h))):
            box=[x1,top,x2,bottom]
            reading=self.read_name(frame,box,includes_level=True)
            if reading:
                reads.append(dict(region=box,**reading))
                if reading['accepted']:
                    self._last_name_box=box
                    return dict(accepted=reading['accepted'],raw=reads,status='accepted')
        return dict(accepted=None,raw=reads,status='menu_level_line_unverified')

    def read_loading_crop(self,crop):
        import cv2
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

    def reset_name_cache(self):
        self._name_cache=None

    def analyze_detected(self,frame,regions,seconds=None,confirmed_name=None):
        """통합 YOLO 위치에서만 읽습니다. 탐지 실패 시 과거 좌표를 사용하지 않습니다."""
        from .ui_regions import get_box,contained
        menu=get_box(regions,'game_menu');dialog=get_box(regions,'switch_dialog')
        current=get_box(regions,'current_name_line');target=get_box(regions,'target_name_line')
        loading_box=get_box(regions,'loading_indicator')
        loading=dict(visible=False,iconVisible=False,raw=[])
        if loading_box:
            l,t,r,b=loading_box
            loading=self.read_loading_crop(frame[t:b,l:r])
        if menu and not loading['visible']:
            # 영역 모델이 놓친 로딩도 기존 문구+아이콘 검증으로 확인합니다.
            # 좌표 보조 경로 사용 여부를 진단에 명시합니다.
            fallback=self.read_loading(frame)
            if fallback['visible']:
                loading=dict(fallback,source='window_corner_verified')
        # 복수 팝업 후보가 있으면 일반 메뉴 복귀/취소로 단정하지 않습니다.
        popup_clear=regions.get('switch_dialog',{}).get('status')=='missing'
        out=dict(normalMenu=bool(menu and popup_clear and not loading['visible']),
                 switchDialog=bool(dialog),switchLoading=loading['visible'],currentName=None,targetName=None,
                 currentRegionVisible=bool(current and menu and contained(current,menu)),
                 detections=regions,ocr=dict(loading=loading))
        can_read=bool(menu and popup_clear and not loading['visible'])
        if not can_read:self._name_cache=None
        cache=getattr(self,'_name_cache',None)
        skip=False
        if can_read and cache and confirmed_name==cache['name'] and seconds is not None and 0<=seconds-cache['at']<2:
            # 확정 후 OCR은 최대 2초 간격. 메뉴/팝업/로딩 감시는 매 프레임 유지합니다.
            # 캐시를 새 OCR 관측으로 공급하지 않아 확정 횟수를 부풀리지 않습니다.
            skip=frame.shape==cache['frameShape']
        if skip:
            out['ocr']['menuName']=dict(status='confirmed_ocr_interval_skip',accepted=None,raw=[])
            out['currentRegionVisible']=True
        if can_read and not skip:
            read=self.read_menu_name(frame,menu)
            out['ocr']['menuName']=read
            if read['accepted']:
                out['currentName']=read['accepted']
                out['currentRegionVisible']=True
            elif current and contained(current,menu):
                read=self.read_name(frame,current,includes_level=True)
                out['ocr']['currentName']=read
                if read and read['accepted']:
                    out['currentName']=read['accepted'];self._last_name_box=current
            if out['currentName'] and seconds is not None:
                box=getattr(self,'_last_name_box',current)
                if box:
                    l,t,r,b=box
                    self._name_cache=dict(name=out['currentName']['text'],at=seconds,box=box,frameShape=frame.shape)
        if target and dialog and contained(target,dialog):
            read=self.read_name(frame,target)
            out['ocr']['targetName']=read
            if read:out['targetName']=read['accepted']
        out['diagnosticStatus']=out['ocr'].get('menuName',out['ocr'].get('currentName',{})).get('status','name_region_not_found')
        return out

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
