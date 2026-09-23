"""던전 영역의 짧은 누락을 현재 화면 검증으로만 보완합니다."""
import copy
import math
from .ui_regions import dungeon_location,contained
from .dungeon import key
from .dungeon_panel import predict_panel_gates


class DungeonObserver:
    def __init__(self, ocr, gate_model, reuse_seconds=3):
        if not math.isfinite(reuse_seconds) or reuse_seconds<=0:
            raise ValueError('영역 재사용 시간은 양수여야 합니다.')
        self.ocr=ocr;self.gate_model=gate_model;self.reuse_seconds=reuse_seconds
        self.reset()

    def reset(self):
        self.cached=None;self.verified_at=None;self.shape=None;self.pair=None
        self.expected_gates=None

    def analyze(self, frame, regions, seconds, blocked=False):
        if not math.isfinite(seconds):raise ValueError('관측 시각 오류')
        if (blocked or self.shape!=frame.shape or
            (self.verified_at is not None and not 0<=seconds-self.verified_at<=self.reuse_seconds)):
            self.reset()
        location=dungeon_location(regions,frame.shape)
        transition_signal=not blocked and location['status']=='missing'
        reused=False
        aligned=False
        if blocked:
            location=dict(status='character_ui_visible',regions={})
        elif location['status']!='detected':
            # 모호하거나 서로 충돌하는 새 박스를 과거 위치로 덮지 않습니다.
            missing=all(regions.get(k,{}).get('status')=='missing' for k in ('dungeon_panel','gate_panel'))
            panel=regions.get('dungeon_panel',{})
            aligned=False
            if (self.cached is not None and panel.get('status')=='detected' and
                regions.get('gate_panel',{}).get('status')=='missing'):
                a=panel['xyxy'];b=self.cached['xyxy']
                overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
                aligned=union>0 and overlap/union>=.9 and contained(self.cached['regions']['gates'],a)
            if (missing or aligned) and self.cached is not None:
                location=copy.deepcopy(self.cached);reused=True
            else:self.reset()
        gates=predict_panel_gates(self.gate_model,frame,location['regions']['gates'],expected_count=self.expected_gates) if location['status']=='detected' else []
        observation=self.ocr.analyze_detected(frame,location,gates)
        pair=tuple(key(observation[f]['text']) for f in ('dungeonName','difficulty')) if (
            observation.get('dungeonVisible') and all(observation.get(f) for f in ('dungeonName','difficulty'))) else None
        valid=pair is not None
        if reused and (not valid or pair!=self.pair):
            # 유지 중인 이름이나 다른 던전의 OCR로 새 기록을 만들지 않습니다.
            observation.update(dungeonName=None,difficulty=None,dungeonVisible=False)
            gates=[];self.reset()
            observation['diagnosticStatus']='reuse_rejected'
        elif valid:
            if self.pair!=pair or self.expected_gates is None:self.expected_gates=len(gates)
            if not reused:
                self.cached=copy.deepcopy(location);self.verified_at=seconds;self.shape=frame.shape;self.pair=pair
            elif aligned and len(gates)==self.expected_gates:
                # 같은 위치의 새 패널 탐지 + 현재 텍스트 + 전체 관문으로 위치를 재검증합니다.
                self.verified_at=seconds
            observation['diagnosticStatus']='verified'
        else:
            self.reset()
            observation['diagnosticStatus']=('region_missing' if location['status']!='detected' else
                'gate_unverified' if not gates else 'text_unverified')
        observation['regionSource']='verified_previous_region' if reused else 'yolo'
        observation['transitionSignal']=transition_signal
        observation['regionAgeSeconds']=seconds-self.verified_at if reused and self.verified_at is not None else 0
        return observation,gates
