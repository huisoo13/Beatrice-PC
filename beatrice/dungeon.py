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
    """탐지된 관문 아이콘의 상태·신뢰도·유효한 박스를 검사합니다."""
    boxes=[box for box in boxes if math.isfinite(box.get('confidence',0)) and box.get('confidence',0)>=.65]
    if not 1<=len(boxes)<=8:return False
    for box in boxes:
        coords=box.get('xyxy',[])
        score=box.get('confidence',0)
        if (box.get('state') not in ('진행중','완료','진행 전') or
            not math.isfinite(score) or score<.65 or len(coords)!=4):return False
        x1,y1,x2,y2=coords
        if not all(math.isfinite(v) for v in coords) or not (0<=x1<x2 and 0<=y1<y2):return False
    return True


def key(text):
    # 글자는 그대로 두고 공백과 UI 구두점만 정규화합니다.
    return re.sub(r'[\s,:\[\]]','',unicodedata.normalize('NFC',text))


def clean_text(text):
    text=' '.join(unicodedata.normalize('NFC',text).split()).strip('[] ')
    return text if 1<=len(text)<=80 and any(c.isalnum() for c in text) else None


def trim_difficulty_line(region):
    """넓힌 모드 영역에서 제목 끝 획·구분선을 제외하고 글자 높이의 줄을 선택합니다."""
    import cv2
    import numpy as np
    gray=cv2.cvtColor(region,cv2.COLOR_BGR2GRAY)
    if 0<int(gray.max())<110 and int(gray.max())>int(gray.min()):
        gray=cv2.normalize(gray,None,0,255,cv2.NORM_MINMAX)
    mask=gray>=110
    rows=np.flatnonzero(mask.sum(axis=1)>=max(2,region.shape[1]*.01))
    bands=[]
    for y in rows:
        if not bands or y-bands[-1][-1]>3:bands.append([int(y)])
        else:bands[-1].append(int(y))
    bands=[band for band in bands if band[-1]-band[0]+1>=max(4,region.shape[0]*.18)]
    if not bands:return None
    band=max(bands,key=lambda b:int(mask[b[0]:b[-1]+1].sum()))
    return region[max(0,band[0]-1):min(region.shape[0],band[-1]+2)]


def validate_readings(readings, threshold=.65):
    votes={}
    originals={}
    for reading in readings:
        text=clean_text(reading['text']);confidence=reading['confidence']
        if text and math.isfinite(confidence) and 0.5<=confidence<=1:
            value=key(text)
            votes.setdefault(value,[]).append(confidence)
            originals.setdefault(value,[]).append((confidence,text))
    accepted=[(value,scores) for value,scores in votes.items() if len(scores)>=2 and max(scores)>=threshold]
    if len(accepted)!=1 or len(votes)!=1:
        return None
    value,scores=accepted[0]
    text=max(originals[value],key=lambda item:item[0])[1]
    return dict(text=text,confidence=max(scores),agreementMinimumConfidence=min(scores))


class DungeonOCR:
    def __init__(self, reader=None, engine=None):
        self.engine=engine or CONFIG.get('engine','paddle')
        if self.engine!='paddle':raise ValueError('PaddleOCR만 지원합니다.')
        if reader is None:
            from .paddle_reader import PaddleKoreanReader
            reader=PaddleKoreanReader()
        self.reader=reader


    def analyze_detected(self,frame,location,gate_boxes,allow_without_gates=False):
        if location['status']!='detected' or not (allow_without_gates or has_dungeon_hud(gate_boxes)):
            return dict(kind='dungeon_observation',engine=self.engine,ocr={},dungeonName=None,
                        difficulty=None,dungeonVisible=False,panelDetection=location)
        result=self.read_regions(frame,location['regions'])
        result['panelDetection']=location
        return self.verify_context(result)

    def analyze_gateless(self,frame,region):
        """무관문 레이드 전용 패널의 [난이도] 제목 줄. 일반 UI에는 호출하지 않습니다."""
        line=region  # Direct YOLO text-line box; no panel-relative crop.
        result=self.read_regions(frame,{'dungeonName':line})
        value=result.get('dungeonName')
        match=re.fullmatch(r'\[?\s*([^\[\]]+?)\s*\]\s*(.+)',value['text']) if value else None
        if match:
            result['difficulty']=dict(text=match[1].strip(),confidence=value['confidence'])
            result['dungeonName']=dict(text=match[2],confidence=value['confidence'])
        else:result.update(dungeonName=None,difficulty=None)
        return self.verify_context(result)

    def verify_context(self,result):
        # Both texts come from freshly detected YOLO text regions and OCR voting.
        # Content names and mode/stage labels are not constrained by a dictionary.
        values=[result.get(field) for field in FIELDS]
        visible=all(value and clean_text(value.get('text',''))
                    and isinstance(value.get('confidence'),(int,float))
                    and math.isfinite(value['confidence'])
                    and CONFIG['minimumConfidence']<=value['confidence']<=1 for value in values)
        if visible:
            for value in values:value['text']=clean_text(value['text'])
        result['dungeonVisible']=visible
        if not visible:
            result['dungeonName']=None
            result['difficulty']=None
        return result


    def read_regions(self,panel,regions):
        import cv2
        result=dict(kind='dungeon_observation',engine=self.engine,ocr={})
        pending=[]
        for field in FIELDS:
            if field not in regions:continue
            l,t,r,b=regions[field]
            # Text-box padding follows the detected glyph height, never a panel position.
            padding=max(1,round((b-t)*.15))
            region=panel[max(0,t-padding):min(panel.shape[0],b+padding),max(0,l-padding):min(panel.shape[1],r+padding)]
            if not region.size:
                result[field]=None
                result['ocr'][field]=dict(region=[l,t,r,b],raw=[],status='empty_detection')
                continue
            if field=='dungeonName':
                from .character_vision import trim_name_line
                region=trim_name_line(region,max_gap=24)
                if region is None:
                    result[field]=None
                    result['ocr'][field]=dict(region=[l,t,r,b],raw=[],status='no_text_pixels')
                    continue
            else:
                region=trim_difficulty_line(region)
                if region is None:
                    result[field]=None
                    result['ocr'][field]=dict(region=[l,t,r,b],raw=[],status='no_text_pixels')
                    continue
            gray=cv2.cvtColor(region,cv2.COLOR_BGR2GRAY)
            if field=='difficulty' and 0<int(gray.max())<110 and int(gray.max())>int(gray.min()):
                gray=cv2.normalize(gray,None,0,255,cv2.NORM_MINMAX)
            mask=cv2.threshold(gray,130 if field=='dungeonName' else 110,255,cv2.THRESH_BINARY)[1]
            points=cv2.findNonZero(mask)
            readings=[]
            if points is not None:
                x,y,w,h=cv2.boundingRect(points)
                crop=gray[max(0,y-2):min(gray.shape[0],y+h+2),max(0,x-2):min(gray.shape[1],x+w+2)]
                enlarged=cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
                for variant,image in [('gray',crop),('enlarged',enlarged),('inverted',255-enlarged)]:
                    pending.append((field,variant,image))
            result['ocr'][field]=dict(region=[l,t,r,b],raw=readings,
                status='unrecognized_or_unverified')
        from .paddle_reader import recognize_images
        outputs=recognize_images(self.reader,[item[2] for item in pending])
        if len(outputs)!=len(pending):raise RuntimeError('OCR 일괄 처리 결과 수가 입력과 다릅니다.')
        for (field,variant,_),values in zip(pending,outputs):
            if len(values)==1:
                result['ocr'][field]['raw'].append(dict(variant=variant,text=values[0][1],confidence=float(values[0][2])))
        for field,entry in result['ocr'].items():
            result[field]=validate_readings(entry['raw'],threshold=CONFIG['minimumConfidence'])
            if result[field]:entry['status']='accepted'
        return result


class DungeonTracker:
    def __init__(self, confirmations=3, max_gap=.8, replacement_seconds=10):
        if confirmations<2 or max_gap<=0 or replacement_seconds<=0:raise ValueError('던전 확인 설정 오류')
        self.required=confirmations;self.max_gap=max_gap;self.replacement_seconds=replacement_seconds
        self.reset()

    def reset(self):
        self.last=None;self.confirmed=None;self.replacement=None;self.replacement_since=None
        self.absence_since=None;self.transition_until=None
        self.candidates={f:None for f in FIELDS};self.counts={f:0 for f in FIELDS}

    def capture_interrupted(self):
        self.last = None
        self.counts = {field: 0 for field in FIELDS}
        self.replacement = None
        self.replacement_since = None

    def update(self,seconds,observation):
        if not math.isfinite(seconds) or (self.last is not None and seconds<=self.last):
            raise ValueError('관측 시각은 유한하고 증가해야 합니다.')
        if self.last is not None and seconds-self.last>self.max_gap:
            self.counts={f:0 for f in FIELDS}
            self.replacement=None;self.replacement_since=None
        self.last=seconds
        result=dict(sourceSeconds=seconds,engine=observation.get('engine'),ocr=observation.get('ocr',{}),preview={})
        result['diagnosticStatus']=observation.get('diagnosticStatus','text_unverified')
        result['regionSource']=observation.get('regionSource')
        for field in ('raidKind','currentRaidPanel','raidPanelVisible','completionOverlay','raidBounds'):
            result[field]=observation.get(field)
        for field in FIELDS:
            value=observation.get(field)
            name=value.get('text') if value and math.isfinite(value.get('confidence',0)) and value.get('confidence',0)>=CONFIG['minimumConfidence'] else None
            name=clean_text(name) if name else None
            result['preview'][field]=name
            same=name is not None and self.candidates[field] is not None and key(name)==key(self.candidates[field])
            self.counts[field]=self.counts[field]+1 if same else (1 if name is not None else 0)
            if not same:self.candidates[field]=name
            result[field]=self.candidates[field] if self.counts[field]>=self.required else None
        known=sum(result[f] is not None for f in FIELDS)
        result['contextStatus']='ocr_verified' if known==2 else ('ocr_partial' if known else 'ocr_pending')
        preview=result['preview']
        current=tuple(key(preview[f]) for f in FIELDS) if all(preview.values()) else None
        result['transitionConfirmed']=False
        if observation.get('transitionSignal') and current is None and self.confirmed is not None:
            if self.absence_since is None:self.absence_since=seconds
            if seconds-self.absence_since>=1:self.transition_until=seconds+15
        else:self.absence_since=None
        if self.transition_until is not None and seconds>self.transition_until:self.transition_until=None
        if self.confirmed is None and known==2:
            self.confirmed={f:result[f] for f in FIELDS}
        if self.confirmed is not None:
            confirmed=tuple(key(self.confirmed[f]) for f in FIELDS)
            if current is None or current==confirmed:
                self.replacement=None;self.replacement_since=None
                if current==confirmed:self.transition_until=None
            elif self.transition_until is not None and known==2:
                self.confirmed=dict(preview);confirmed=current
                self.replacement=None;self.replacement_since=None;self.transition_until=None
                result['transitionConfirmed']=True
            elif current!=self.replacement:
                self.replacement=current;self.replacement_since=seconds
            elif seconds-self.replacement_since>=self.replacement_seconds:
                self.confirmed=dict(preview)
                confirmed=current;self.replacement=None;self.replacement_since=None
            result.update(self.confirmed)
            # 표시용 보존 정보는 현재 관문 기록의 근거로 사용하지 않습니다.
            result['contextStatus']='ocr_verified' if current==confirmed else 'ocr_held'
            result['replacementElapsed']=seconds-self.replacement_since if self.replacement_since is not None else 0
        return result


def event_context(context):
    """호출자가 같은 프레임에 대응하는 안정화된 관측을 전달합니다."""
    if context is None:
        return dict(dungeonName=None,difficulty=None,contextStatus='ocr_pending')
    values={field:context.get(field) for field in FIELDS}
    for field in FIELDS:
        values[field]=clean_text(values[field]) if values[field] else None
    count=sum(value is not None for value in values.values())
    return dict(**values,contextStatus='ocr_held' if context.get('contextStatus')=='ocr_held' else ('ocr_verified' if count==2 else ('ocr_partial' if count else 'ocr_pending')),
                dungeonObservation=context)
