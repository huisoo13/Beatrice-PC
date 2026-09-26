"""전체 화면 → YOLO 영역 → PaddleOCR 이름. 입력 출처와 시간 처리는 분리됩니다."""
import re
import unicodedata
from .character import valid_name

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
    def __init__(self, reader=None):
        if reader is None:
            from .paddle_reader import PaddleKoreanReader
            reader=PaddleKoreanReader()
        self.reader=reader

    def read_name(self,frame,box,includes_level=False):
        import cv2
        x1,y1,x2,y2=[round(v) for v in box]
        # Preserve edge glyphs when the detector clips part of the first/last character.
        # Margins follow this detected line's height, independent of screen position.
        horizontal=max(1,round((y2-y1)*.5));vertical=max(1,round((y2-y1)*.15))
        crop=frame[max(0,y1-vertical):min(frame.shape[0],y2+vertical),max(0,x1-horizontal):min(frame.shape[1],x2+horizontal)]
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


    def read_loading_crop(self,crop):
        """YOLO 영역 안에서 청록 아이콘과 흰 글자 줄을 찾아 전체 문구를 검증합니다."""
        import cv2
        import numpy as np
        if crop.size==0:return dict(visible=False,iconVisible=False,raw=[])
        height,width=crop.shape[:2]
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        cyan=cv2.inRange(hsv,(75,70,100),(110,255,255))
        _,_,stats,_=cv2.connectedComponentsWithStats(cyan)
        icons=[(x,y,w,h,area) for x,y,w,h,area in stats[1:]
               if area>=max(30,width*height*.002) and h>=height*.1 and w>=width*.04]
        if not icons:return dict(visible=False,iconVisible=False,raw=[])
        x,y,w,h,area=max(icons,key=lambda item:item[4])
        # 아이콘 왼쪽을 모두 보존해 YOLO 박스 폭의 변화로 첫 글자가 잘리지 않게 합니다.
        right=max(0,x-round(width*.01));text_area=crop[:,:right]
        readings=[]
        if text_area.size:
            text_hsv=hsv[:,:right]
            mask=(text_hsv[:,:,1]<110)&(text_hsv[:,:,2]>=150)
            rows=np.flatnonzero(mask.sum(axis=1)>=max(3,right*.015))
            bands=[]
            for row in rows:
                if not bands or row-bands[-1][-1]>3:bands.append([int(row)])
                else:bands[-1].append(int(row))
            bands=[band for band in bands if max(4,height*.035)<=band[-1]-band[0]+1<=height*.3]
            for band in sorted(bands,key=lambda b:int(mask[b[0]:b[-1]+1].sum()),reverse=True)[:3]:
                line=trim_name_line(text_area[max(0,band[0]-2):min(height,band[-1]+3)],max_gap=max(12,round(width*.06)))
                if line is None:continue
                gray=cv2.cvtColor(line,cv2.COLOR_BGR2GRAY)
                for image in (gray,cv2.resize(gray,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)):
                    for _,text,confidence in self.reader.recognize(image):
                        readings.append(dict(text=text,confidence=float(confidence)))
                    if any(r['confidence']>=.85 and re.sub(r'[\s.!。]','',r['text'])=='잠시만기다려주세요' for r in readings):
                        return dict(visible=True,iconVisible=True,raw=readings)
        return dict(visible=False,iconVisible=True,raw=readings)

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
        # 복수 팝업 후보가 있으면 일반 메뉴 복귀/취소로 단정하지 않습니다.
        popup_clear=regions.get('switch_dialog',{}).get('status')=='missing'
        out=dict(normalMenu=bool(menu and popup_clear and not loading['visible']),
                 switchDialog=bool(dialog),switchLoading=loading['visible'],currentName=None,targetName=None,
                 currentRegionVisible=bool(current and menu and contained(current,menu)),
                 detections=regions,ocr=dict(loading=loading))
        can_read=bool(current and menu and contained(current,menu) and popup_clear and not loading['visible'])
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
