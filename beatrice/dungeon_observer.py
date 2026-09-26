"""Fresh direct YOLO elements are the only source of dungeon OCR and gate geometry."""
import math
from .ui_regions import dungeon_location,contained,get_box,detected_gates


class DungeonObserver:
    def __init__(self,ocr):
        self.ocr=ocr

    def reset(self):
        pass  # No cached coordinates to reuse on a new frame.

    def analyze(self,frame,regions,seconds,blocked=False):
        if not math.isfinite(seconds):raise ValueError('관측 시각 오류')
        gated=get_box(regions,'dungeon_panel');gateless=get_box(regions,'gateless_raid_panel')
        conflict=any(regions.get(k,{}).get('status')=='ambiguous' for k in ('dungeon_panel','gateless_raid_panel')) or bool(gated and gateless)
        blocked=blocked or conflict
        banner=regions.get('quest_complete_banner',{}).get('status')=='detected'
        kind='gateless' if gateless else 'gated'
        gates=[]
        observation=dict(kind='dungeon_observation',engine=self.ocr.engine,ocr={},dungeonName=None,difficulty=None,dungeonVisible=False)
        if not blocked and gateless:
            title=get_box(regions,'gateless_title')
            if title and contained(title,gateless):observation=self.ocr.analyze_gateless(frame,title)
        elif not blocked and gated:
            location=dungeon_location(regions,frame.shape)
            gates=detected_gates(regions)
            observation=self.ocr.analyze_detected(frame,location,gates,allow_without_gates=True)
        valid=bool(observation.get('dungeonVisible') and observation.get('dungeonName') and observation.get('difficulty'))
        if not valid:gates=[]
        observation.update(raidKind=kind,raidBounds=gateless or gated,currentRaidPanel=bool((gated or gateless) and not blocked),
            completionBanner=banner,regionSource='yolo_direct',regionAgeSeconds=0,
            diagnosticStatus='verified' if valid else 'text_unverified' if gated or gateless else 'region_missing',
            transitionSignal=not blocked and not gated and not gateless)
        return observation,gates
