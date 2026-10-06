"""Completion text is read only inside two agreeing YOLO detections."""
import math
import re
import unicodedata
from .ui_regions import UIRegionDetector, get_box, contained


def parse_completion(text,confidence):
    if not math.isfinite(confidence) or confidence<.8:return None
    value=re.sub(r'\s+','',unicodedata.normalize('NFKC',text))
    if value=='던전클리어':return dict(kind='dungeon_clear',gate=None)
    match=re.fullmatch(r'([1-9][0-9]*)관문돌파',value)
    return dict(kind='gate_breakthrough',gate=int(match[1])) if match else None


class CompletionOverlayDetector:
    def __init__(self,reader,config,detector=None):
        self.reader=reader
        self.config=dict(config)
        self.detector=detector or UIRegionDetector(config)

    def analyze(self,frame):
        regions=self.detector.locate(frame)
        overlay=get_box(regions,'completion_overlay');text=get_box(regions,'completion_text')
        result=dict(status='missing',regions=regions,raw=[])
        if overlay is None:return result
        result['status']='text_unverified'
        if text is None or not contained(text,overlay):return result
        l,t,r,b=text
        values=self.reader.recognize(frame[t:b,l:r])
        result['raw']=[dict(text=v[1],confidence=float(v[2])) for v in values]
        if len(values)!=1:return result
        parsed=parse_completion(values[0][1],float(values[0][2]))
        if parsed:result.update(parsed,status='verified')
        return result
