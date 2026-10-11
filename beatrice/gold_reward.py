"""Learned reward panel interpretation, independent of completion and persistence."""
import json
from .ui_regions import UIRegionDetector,get_box,contained,ROOT
from .completion_overlay import parse_completion


class GoldRewardDetector:
    def __init__(self,reader,config,detector=None,parent_detector=None):
        self.reader=reader;self.config=config
        self.detector=detector or UIRegionDetector(config)
        self.parent_detector=parent_detector or (UIRegionDetector(json.loads((ROOT/config['parentConfig']).read_text(encoding='utf-8'))) if detector is None and config.get('parentConfig') else self.detector)
        self.next_at=0

    def analyze(self,frame,seconds):
        if seconds<self.next_at:return dict(status='not_requested')
        self.next_at=seconds+self.config.get('intervalSeconds',.75)
        regions=self.parent_detector.locate(frame);panel=get_box(regions,'reward_panel')
        result=dict(status='missing',regions=regions)
        if panel is None:return result
        # Allow learned parent-border error. This expands the detected panel,
        # never defines a title/currency ROI or a screen-relative location.
        l,t,r,b=panel;h,w=frame.shape[:2]
        x_margin=round((r-l)*.025);y_margin=round((b-t)*.1)
        l,t,r,b=max(0,l-x_margin),max(0,t-y_margin),min(w,r+x_margin),min(h,b)
        result['cropBounds']=[l,t,r,b]
        found=self.detector.locate(frame[t:b,l:r]);result['elements']=found
        title=get_box(found,'reward_gate_title')
        present=get_box(found,'gold_reward_present');absent=get_box(found,'gold_reward_absent')
        result['status']='unverified'
        outer=[0,0,r-l,b-t]
        if title is None or not contained(title,outer):return result
        # Explicit absent class is required: failed gold detection is never false.
        if (present is None)==(absent is None):return result
        if any(found.get(kind,{}).get('status')=='ambiguous' for kind in ('gold_reward_present','gold_reward_absent')):return result
        section=present or absent
        if not contained(section,outer):return result
        x,y,z,w=title;image=frame[t+y:t+w,l+x:l+z]
        import cv2
        # Normalize dimmed text using image intensities, never a screen coordinate.
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        normalized=cv2.normalize(gray,None,0,255,cv2.NORM_MINMAX)
        values=self.reader.recognize(normalized)
        result['raw']=[dict(text=v[1],confidence=float(v[2])) for v in values]
        if len(values)!=1:return result
        parsed=parse_completion(values[0][1],float(values[0][2]))
        if not parsed or parsed['kind']!='gate_breakthrough' or not 1<=parsed['gate']<=8:return result
        kind='gold_reward_present' if present else 'gold_reward_absent'
        result.update(status='verified',gate=parsed['gate'],received=present is not None,confidence=found[kind]['confidence'])
        return result
