"""화면 상단 텍스트 OCR과 시간 안정화. 알 수 없는 이름을 비슷한 이름으로 치환하지 않습니다."""
from pathlib import Path
import json
import math
import re
import unicodedata

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config/dungeon-ocr.json').read_text())
FIELDS=('dungeonName','difficulty')


def key(text):
    # 글자는 그대로 두고 공백과 UI 구두점만 정규화합니다.
    return re.sub(r'[\s,:\[\]]','',unicodedata.normalize('NFC',text))


def validate_readings(readings, allowed, threshold=.65):
    canonical={key(value):value for value in allowed}
    votes={}
    for reading in readings:
        text=reading['text'];confidence=reading['confidence']
        if math.isfinite(confidence) and 0.5<=confidence<=1 and key(text) in canonical:
            value=canonical[key(text)]
            votes.setdefault(value,[]).append(confidence)
    accepted=[(value,scores) for value,scores in votes.items() if len(scores)>=2 and max(scores)>=threshold]
    if len(accepted)!=1 or len(votes)!=1:
        return None
    value,scores=accepted[0]
    return dict(text=value,confidence=max(scores),agreementMinimumConfidence=min(scores))


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

    def analyze(self,frame):
        if frame.shape[:2]!=(1440,3440):
            raise ValueError('현재 던전 OCR은 3440x1440 전용입니다.')
        return self.analyze_panel(frame[:240,:400])

    def analyze_panel(self,panel):
        """원본 좌상단 400×240 보존 패널. 리사이즈한 미리보기는 입력하지 않습니다."""
        import cv2
        if panel.shape[:2]!=(240,400):
            raise ValueError('원본 좌상단 400x240 패널이 필요합니다.')
        result=dict(kind='dungeon_observation',engine=self.engine,ocr={})
        for field in FIELDS:
            l,t,r,b=CONFIG['regions'][field]
            gray=cv2.cvtColor(panel[t:b,l:r],cv2.COLOR_BGR2GRAY)
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
            allowed=CONFIG['supportedDungeonNames' if field=='dungeonName' else 'supportedDifficulties']
            result[field]=validate_readings(readings,allowed,CONFIG['minimumConfidence'])
            result['ocr'][field]=dict(region=CONFIG['regions'][field],raw=readings,
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
        result=dict(sourceSeconds=seconds,engine=observation.get('engine'),ocr=observation.get('ocr',{}))
        for field in FIELDS:
            value=observation.get(field)
            allowed=CONFIG['supportedDungeonNames' if field=='dungeonName' else 'supportedDifficulties']
            name=value.get('text') if value and math.isfinite(value.get('confidence',0)) and value.get('confidence',0)>=CONFIG['minimumConfidence'] else None
            if name not in allowed:name=None
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
    for field,allowed in [('dungeonName',CONFIG['supportedDungeonNames']),('difficulty',CONFIG['supportedDifficulties'])]:
        if values[field] not in allowed:values[field]=None
    count=sum(value is not None for value in values.values())
    return dict(**values,contextStatus='ocr_verified' if count==2 else ('ocr_partial' if count else 'ocr_pending'),
                dungeonObservation=context)
