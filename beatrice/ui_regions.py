"""전체 화면 UI 탐지. 메뉴 누락 시 보완 모델로 캐릭터 영역만 추가 탐지합니다."""
import json
import math
from pathlib import Path
from .dungeon_panel import relative_box,load_config as dungeon_config

ROOT=Path(__file__).resolve().parents[1]


def load_config():
    return json.loads((ROOT/'config/ui-regions.json').read_text(encoding='utf-8'))


def contained(inner,outer):
    return (outer[0]<=inner[0]<inner[2]<=outer[2] and
            outer[1]<=inner[1]<inner[3]<=outer[3])


def suppress_duplicates(items,threshold=.4):
    """같은 클래스의 겹친 후보만 정리합니다. 떨어진 후보는 모호성 검사용으로 남깁니다."""
    kept=[]
    for item in sorted(items,key=lambda value:value['confidence'],reverse=True):
        a=item['xyxy']
        duplicate=False
        for previous in kept:
            b=previous['xyxy']
            overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-overlap
            if union>0 and overlap/union>=threshold:duplicate=True;break
        if not duplicate:kept.append(item)
    return kept


class UIRegionDetector:
    def __init__(self,config=None,model=None,recovery_model=None):
        self.config=config or load_config()
        if self.config.get('architecture')=='split' and model is None:
            self.character_detector=UIRegionDetector(json.loads((ROOT/self.config['characterConfig']).read_text(encoding='utf-8')))
            self.dungeon_detector=UIRegionDetector(json.loads((ROOT/self.config['dungeonConfig']).read_text(encoding='utf-8')))
            return
        load_recovery=model is None
        if model is None:
            path=ROOT/self.config['weights']
            if not path.is_file():raise ValueError('통합 UI 모델을 현재 해상도 데이터로 학습한 뒤 yolo 모드를 켜주세요.')
            from ultralytics import YOLO
            model=YOLO(str(path))
        if [model.names[i] for i in range(len(model.names))]!=self.config['classes']:
            raise ValueError('통합 UI 모델 클래스와 설정이 다릅니다.')
        self.model=model
        if recovery_model is None and load_recovery and self.config.get('menuRecoveryWeights'):
            recovery_path=ROOT/self.config['menuRecoveryWeights']
            if not recovery_path.is_file():raise ValueError('메뉴 보완 모델 파일이 없습니다.')
            recovery_model=YOLO(str(recovery_path))
        if recovery_model is not None and [recovery_model.names[i] for i in range(len(recovery_model.names))]!=self.config['classes']:
            raise ValueError('메뉴 보완 모델 클래스와 설정이 다릅니다.')
        self.recovery_model=recovery_model

    def locate(self,frame):
        if hasattr(self,'character_detector'):
            character=self.character_detector.locate(frame)
            visible=any(character.get(k,{}).get('status')!='missing' for k in ('game_menu','switch_dialog'))
            dungeon=({k:dict(status='missing',candidates=[],reason='character_ui_visible') for k in self.dungeon_detector.config['classes']}
                     if visible else self.dungeon_detector.locate(frame))
            return dict(character,**dungeon)
        regions=self._locate(frame,self.model)
        if regions.get('game_menu',{}).get('status')=='missing' and self.recovery_model is not None:
            recovered=self._locate(frame,self.recovery_model)
            if recovered['game_menu']['status']=='detected':
                for kind in ('game_menu','current_name_line','switch_dialog','target_name_line','loading_indicator'):
                    if regions[kind]['status']=='missing' and recovered[kind]['status']!='missing':
                        regions[kind]=dict(recovered[kind],source='menu_recovery_yolo')
        return regions

    def _locate(self,frame,model):
        prediction=model.predict(frame,imgsz=self.config['imageSize'],conf=self.config['confidence'],
            iou=.5,device='cpu',verbose=False)[0]
        groups={name:[] for name in self.config['classes']}
        h,w=frame.shape[:2]
        for box in prediction.boxes:
            kind=int(box.cls[0]);score=float(box.conf[0]);coords=box.xyxy[0].tolist()
            if kind<0 or kind>=len(groups) or not math.isfinite(score) or score<self.config['confidence']:continue
            if len(coords)!=4 or not all(math.isfinite(v) for v in coords):continue
            x1,y1,x2,y2=coords
            if not (0<=x1<x2<=w and 0<=y1<y2<=h):continue
            groups[self.config['classes'][kind]].append(dict(xyxy=[math.floor(x1),math.floor(y1),math.ceil(x2),math.ceil(y2)],confidence=score))
        groups={kind:suppress_duplicates(items,self.config.get('nmsIou',.4)) for kind,items in groups.items()}
        return {kind:dict(status='detected' if len(items)==1 else ('missing' if not items else 'ambiguous'),
                         candidates=items,**(items[0] if len(items)==1 else {})) for kind,items in groups.items()}


def get_box(regions,kind):
    item=regions.get(kind,{})
    return item.get('xyxy') if item.get('status')=='detected' else None


def dungeon_location(regions,shape):
    panel=get_box(regions,'dungeon_panel')
    if panel is None:return dict(status=regions.get('dungeon_panel',{}).get('status','missing'),regions={})
    fields={name:relative_box(panel,relative,shape) for name,relative in dungeon_config()['regions'].items()}
    gates=get_box(regions,'gate_panel')
    # 통합 모드는 관문 패널도 직접 탐지하며 던전 패널과 포함 관계를 확인합니다.
    if gates is None or not contained(gates,panel):return dict(status='gate_panel_missing_or_outside',regions={})
    fields['gates']=gates
    if any(r-l<2 or b-t<2 for l,t,r,b in fields.values()):return dict(status='too_small',regions={})
    return dict(status='detected',xyxy=panel,regions=fields)
