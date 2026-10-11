"""YOLO/OCR frame analysis, independent of Qt, capture, storage and Drive."""
import json
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FrameRecognition:
    character: dict
    dungeon: dict
    gates: list
    detected_at: float
    character_at: float


class RecognitionPipeline:
    def __init__(self,root,progress=lambda message: None):
        self.root=Path(root);self.progress=progress

    def prepare(self):
        from ..character_vision import CharacterVision
        from ..dungeon import DungeonOCR
        from ..ui_regions import load_config,UIRegionDetector
        from ..dungeon_observer import DungeonObserver
        from ..completion_overlay import CompletionOverlayDetector
        self.config=load_config()
        if self.config['mode']!='yolo':raise ValueError('YOLO 탐지만 지원합니다.')
        self.detector=UIRegionDetector(self.config,progress=lambda message:self.progress('1 / 3 · '+message))
        self.progress('1 / 3 · 한국어 OCR 모델을 불러오는 중…')
        dungeon=DungeonOCR()
        self.character=CharacterVision(reader=dungeon.reader)
        self.dungeon_observer=DungeonObserver(dungeon)
        self.progress('1 / 3 · 완료 표시 모델을 불러오는 중…')
        config=json.loads((self.root/'config/completion-overlay.json').read_text(encoding='utf-8'))
        self.completion=CompletionOverlayDetector(dungeon.reader,config)

    def analyze_character(self,frame,seconds,confirmed_name=None):
        regions=self.detector.locate_character(frame)
        detected_at=time.monotonic()
        identity=self.character.analyze_detected(frame,regions,seconds=seconds,confirmed_name=confirmed_name)
        return regions,identity,detected_at,time.monotonic()

    def analyze_dungeon(self,frame,regions,identity,seconds,completion_enabled=False,still_current=lambda:True):
        regions=self.detector.locate_dungeon(frame,regions)
        blocked=any(regions.get(k,{}).get('status','missing')!='missing' for k in ('game_menu','switch_dialog')) or identity.get('switchLoading',False)
        blocked=blocked or any(identity.get(k) for k in ('serverSelection','characterSelection','loginLoading','selectionUncertain'))
        dungeon,boxes=self.dungeon_observer.analyze(frame,regions,seconds,blocked=blocked)
        if not still_current():return None
        if not blocked and completion_enabled:dungeon['completionOverlay']=self.completion.analyze(frame)
        if not still_current():return None
        return dungeon,boxes

    def analyze(self,frame,seconds,confirmed_name=None,completion_enabled=False,still_current=lambda:True):
        regions,identity,detected_at,character_at=self.analyze_character(frame,seconds,confirmed_name)
        if confirmed_name is None:
            return FrameRecognition(identity,{},[],detected_at,character_at) if still_current() else None
        result=self.analyze_dungeon(frame,regions,identity,seconds,completion_enabled,still_current)
        if result is None:return None
        return FrameRecognition(identity,*result,detected_at,character_at)
