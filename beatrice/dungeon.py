"""화면 상단 텍스트 OCR과 시간 안정화. 알 수 없는 이름을 비슷한 이름으로 치환하지 않습니다."""
from pathlib import Path
import json
import math
import re
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config/dungeon-ocr.json').read_text(encoding='utf-8'))
FIELDS=('dungeonName','difficulty')


def has_dungeon_hud(boxes):
    """상단 관문 아이콘의 위치/상태/신뢰도가 일치할 때만 던전 OCR을 실행합니다."""
    boxes=[box for box in boxes if math.isfinite(box.get('confidence',0)) and box.get('confidence',0)>=.65]
    if not 1<=len(boxes)<=8:return False
    for box in boxes:
        coords=box.get('xyxy',[])
        score=box.get('confidence',0)
        if (box.get('state') not in ('진행중','완료','진행 전') or
            not math.isfinite(score) or score<.65 or len(coords)!=4):return False
        x1,y1,x2,y2=coords
        if not (32<=x1<x2<=352 and 112<=y1<y2<=224):return False
    return True


def key(text):
    # 글자는 그대로 두고 공백과 UI 구두점만 정규화합니다.
    return re.sub(r'[\s,:\[\]]','',unicodedata.normalize('NFC',text))


def clean_text(text):
    text=' '.join(unicodedata.normalize('NFC',text).split()).strip('[] ')
    return text if 1<=len(text)<=80 and any(c.isalnum() for c in text) else None


def validate_readings(readings, allowed=None, threshold=.65):
    canonical={key(value):value for value in allowed} if allowed is not None else None
    votes={}
    originals={}
    for reading in readings:
        text=clean_text(reading['text']);confidence=reading['confidence']
        if text and math.isfinite(confidence) and 0.5<=confidence<=1 and (canonical is None or key(text) in canonical):
            value=canonical[key(text)] if canonical is not None else key(text)
            votes.setdefault(value,[]).append(confidence)
            originals.setdefault(value,[]).append((confidence,text))
    accepted=[(value,scores) for value,scores in votes.items() if len(scores)>=2 and max(scores)>=threshold]
    if len(accepted)!=1 or len(votes)!=1:
        return None
    value,scores=accepted[0]
    text=value if canonical is not None else max(originals[value],key=lambda item:item[0])[1]
    return dict(text=text,confidence=max(scores),agreementMinimumConfidence=min(scores))


class DungeonOCR:
    def __init__(self, reader=None, engine=None):
        self.engine=engine or CONFIG.get('engine','paddle')
        if self.engine not in ('paddle','easyocr'):
            raise ValueError('지원하지 않는 OCR 엔진')
        if reader is None:
            if self.engine=='paddle':
                from .paddle_reader import PaddleKoreanReader
                reader=PaddleKoreanReader()
            else:
                import torch
                torch.set_num_threads(4)
                import easyocr
                reader=easyocr.Reader(['ko','en'],gpu=False,detector=False,
                    model_storage_directory=str(ROOT/'models/easyocr'),
                    user_network_directory=str(ROOT/'models/easyocr/user'),download_enabled=False,verbose=False)
        self.reader=reader

    def analyze(self,frame,gate_boxes=None):
        if frame.shape[:2]!=(1440,3440):
            raise ValueError('현재 던전 OCR은 3440x1440 전용입니다.')
        if not has_dungeon_hud(gate_boxes or []):
            return dict(kind='dungeon_observation',engine=self.engine,ocr={},dungeonName=None,
                        difficulty=None,dungeonVisible=False)
        result=self.analyze_panel(frame[:240,:800])
        # 진행 아이콘과 닮은 일반 HUD도 있으므로 난이도 표기까지 함께 확인합니다.
        difficulty=result.get('difficulty')
        difficulties={key(value):value for value in CONFIG['supportedDifficulties']}
        visible=bool(difficulty and key(difficulty['text']) in difficulties)
        if visible:difficulty['text']=difficulties[key(difficulty['text'])]
        result['dungeonVisible']=visible
        if not visible:
            result['dungeonName']=None
            result['difficulty']=None
        return result

    def analyze_panel(self,panel):
        """원본 좌상단 400×240 보존 패널. 리사이즈한 미리보기는 입력하지 않습니다."""
        import cv2
        if panel.shape[0]!=240 or panel.shape[1]<400:
            raise ValueError('원본 좌상단 높이 240, 너비 400 이상 패널이 필요합니다.')
        result=dict(kind='dungeon_observation',engine=self.engine,ocr={})
        for field in FIELDS:
            l,t,r,b=CONFIG['regions'][field]
            if field=='dungeonName':r=min(panel.shape[1],800)
            region=panel[t:b,l:r]
            if field=='dungeonName':
                from .character_vision import trim_name_line
                region=trim_name_line(region,max_gap=24)
                if region is None:
                    result[field]=None
                    result['ocr'][field]=dict(region=[l,t,r,b],raw=[],status='no_text_pixels')
                    continue
            gray=cv2.cvtColor(region,cv2.COLOR_BGR2GRAY)
            mask=cv2.threshold(gray,130 if field=='dungeonName' else 110,255,cv2.THRESH_BINARY)[1]
            points=cv2.findNonZero(mask)
            readings=[]
            if points is not None:
                x,y,w,h=cv2.boundingRect(points)
                crop=gray[max(0,y-2):min(gray.shape[0],y+h+2),max(0,x-2):min(gray.shape[1],x+w+2)]
                enlarged=cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
                for variant,image in [('gray',crop),('enlarged',enlarged),('inverted',255-enlarged)]:
                    values=self.reader.recognize(image)
                    if len(values)==1:
                        readings.append(dict(variant=variant,text=values[0][1],confidence=float(values[0][2])))
            result[field]=validate_readings(readings,threshold=CONFIG['minimumConfidence'])
            result['ocr'][field]=dict(region=[l,t,r,b],raw=readings,
                status='accepted' if result[field] else 'unrecognized_or_unverified')
        return result


class DungeonTracker:
    def __init__(self, confirmations=3, max_gap=.8):
        self.required=confirmations;self.max_gap=max_gap;self.last=None
        self.candidates={f:None for f in FIELDS};self.counts={f:0 for f in FIELDS}

    def update(self,seconds,observation):
        if not math.isfinite(seconds) or (self.last is not None and seconds<=self.last):
            raise ValueError('관측 시각은 유한하고 증가해야 합니다.')
        if self.last is not None and seconds-self.last>self.max_gap:
            self.counts={f:0 for f in FIELDS}
        self.last=seconds
        result=dict(sourceSeconds=seconds,engine=observation.get('engine'),ocr=observation.get('ocr',{}),preview={})
        for field in FIELDS:
            value=observation.get(field)
            name=value.get('text') if value and math.isfinite(value.get('confidence',0)) and value.get('confidence',0)>=CONFIG['minimumConfidence'] else None
            name=clean_text(name) if name else None
            result['preview'][field]=name
            self.counts[field]=self.counts[field]+1 if name is not None and name==self.candidates[field] else (1 if name is not None else 0)
            self.candidates[field]=name
            result[field]=name if self.counts[field]>=self.required else None
        known=sum(result[f] is not None for f in FIELDS)
        result['contextStatus']='ocr_verified' if known==2 else ('ocr_partial' if known else 'ocr_pending')
        return result


def event_context(context):
    """호출자가 같은 프레임에 대응하는 안정화된 관측을 전달합니다."""
    if context is None:
        return dict(dungeonName=None,difficulty=None,contextStatus='ocr_pending')
    values={field:context.get(field) for field in FIELDS}
    for field in FIELDS:
        values[field]=clean_text(values[field]) if values[field] else None
    count=sum(value is not None for value in values.values())
    return dict(**values,contextStatus='ocr_verified' if count==2 else ('ocr_partial' if count else 'ocr_pending'),
                dungeonObservation=context)
