"""전체 화면 UI와 실제 탐지 패널 내부의 글자·관문 요소를 YOLO로 찾습니다."""
import json
import math
from pathlib import Path

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


def merge_text_duplicates(items):
    """Join overlapping detections of one text line, without choosing a screen location."""
    merged=[]
    for item in sorted(items,key=lambda v:v['confidence'],reverse=True):
        a=item['xyxy']
        for previous in merged:
            b=previous['xyxy']
            overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            smaller=min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1]))
            if smaller>0 and overlap/smaller>=.65:
                previous['xyxy']=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
                break
        else:merged.append(dict(item,xyxy=list(a)))
    return merged


class UIRegionDetector:
    def __init__(self,config=None,model=None):
        self.config=config or load_config()
        if self.config.get('architecture')=='split' and model is None:
            self.character_detector=UIRegionDetector(json.loads((ROOT/self.config['characterConfig']).read_text(encoding='utf-8')))
            self.dungeon_detector=UIRegionDetector(json.loads((ROOT/self.config['dungeonConfig']).read_text(encoding='utf-8')))
            return
        if model is None:
            path=ROOT/self.config['weights']
            if not path.is_file():raise ValueError('통합 UI 모델을 현재 해상도 데이터로 학습한 뒤 yolo 모드를 켜주세요.')
            from ultralytics import YOLO
            model=YOLO(str(path))
        if [model.names[i] for i in range(len(model.names))]!=self.config['classes']:
            raise ValueError('통합 UI 모델 클래스와 설정이 다릅니다.')
        self.model=model
        if self.config.get('elementConfig'):
            self.element_detector=UIRegionDetector(json.loads((ROOT/self.config['elementConfig']).read_text(encoding='utf-8')))

    def locate(self,frame):
        if hasattr(self,'character_detector'):
            character=self.character_detector.locate(frame)
            visible=any(character.get(k,{}).get('status','missing')!='missing' for k in
                        ('game_menu','switch_dialog','server_table','loading_progress'))
            card=get_box(character,'selected_character_card')
            name=get_box(character,'selected_character_name')
            visible=visible or bool(card and (get_box(character,'game_start_button') or
                                             (name and contained(name,card))))
            dungeon=({k:dict(status='missing',candidates=[],reason='character_ui_visible') for k in self.dungeon_detector.config['classes']}
                     if visible else self.dungeon_detector.locate(frame))
            return dict(character,**dungeon)
        regions=self._locate(frame,self.model)
        menu=get_box(regions,'game_menu')
        if menu is not None and get_box(regions,'current_name_line') is None and regions.get('switch_dialog',{}).get('status')=='missing':
            l,t,r,b=menu
            found=self._locate(frame[t:b,l:r],self.model)['current_name_line']
            candidates=[dict(item,xyxy=[item['xyxy'][0]+l,item['xyxy'][1]+t,item['xyxy'][2]+l,item['xyxy'][3]+t]) for item in found['candidates']]
            regions['current_name_line']=dict(status=found['status'],candidates=candidates,
                                             **(candidates[0] if len(candidates)==1 else {}))
        card=get_box(regions,'selected_character_card')
        if card is not None and 'selected_character_name' in self.config['classes']:
            l,t,r,b=card
            # 같은 YOLO 모델을 실제 탐지 카드 전체에 적용합니다. 상대 OCR crop 없음.
            found=self._locate(frame[t:b,l:r],self.model)['selected_character_name']
            for padding in (.05,):
                if found['status']!='missing':break
                # 탐지 테두리의 작은 오차만 보완합니다. 이름 위치/크기를 비율로 지정하지 않습니다.
                l,t,r,b=card
                margin=max(1,round((b-t)*padding));h,w=frame.shape[:2]
                l,t,r,b=max(0,l-margin),max(0,t-margin),min(w,r+margin),min(h,b+margin)
                found=self._locate(frame[t:b,l:r],self.model)['selected_character_name']
            candidates=[dict(item,xyxy=[item['xyxy'][0]+l,item['xyxy'][1]+t,item['xyxy'][2]+l,item['xyxy'][3]+t]) for item in found['candidates']]
            candidates=[item for item in candidates if contained(item['xyxy'],card)]
            original=get_box(regions,'selected_character_name')
            # A failed crop retry must not erase a valid full-frame name.
            if not candidates and original and contained(original,card):
                entry=regions['selected_character_name']
                candidates=entry.get('candidates',[]) or [dict(xyxy=original,confidence=entry.get('confidence',0))]
            regions['selected_character_name']=dict(status='detected' if len(candidates)==1 else ('ambiguous' if candidates else 'missing'),candidates=candidates,
                                                    **(candidates[0] if len(candidates)==1 else {}))
        if hasattr(self,'element_detector'):
            kinds=self.element_detector.config['classes']
            elements={kind:dict(status='missing',candidates=[]) for kind in kinds}
            parents=[kind for kind in ('dungeon_panel','gateless_raid_panel') if get_box(regions,kind) is not None]
            ambiguous=any(regions.get(kind,{}).get('status')=='ambiguous' for kind in ('dungeon_panel','gateless_raid_panel'))
            if len(parents)==1 and not ambiguous:
                parent=parents[0];l,t,r,b=get_box(regions,parent)
                found=self.element_detector.locate(frame[t:b,l:r])
                for kind,entry in found.items():
                    if (kind=='gateless_title')!=(parent=='gateless_raid_panel'):continue
                    candidates=[dict(item,xyxy=[item['xyxy'][0]+l,item['xyxy'][1]+t,item['xyxy'][2]+l,item['xyxy'][3]+t]) for item in entry['candidates']]
                    elements[kind]=dict(status=entry['status'],candidates=candidates,**(candidates[0] if len(candidates)==1 else {}))
            regions.update(elements)
        return regions

    def _locate(self,frame,model):
        thresholds=self.config.get('classConfidence',{})
        prediction=model.predict(frame,imgsz=self.config['imageSize'],conf=min([self.config['confidence'],*thresholds.values()]),
            iou=.5,device='cpu',verbose=False)[0]
        groups={name:[] for name in self.config['classes']}
        h,w=frame.shape[:2]
        for box in prediction.boxes:
            kind=int(box.cls[0]);score=float(box.conf[0]);coords=box.xyxy[0].tolist()
            if kind<0 or kind>=len(groups) or not math.isfinite(score):continue
            if score<thresholds.get(self.config['classes'][kind],self.config['confidence']):continue
            if len(coords)!=4 or not all(math.isfinite(v) for v in coords):continue
            x1,y1,x2,y2=coords
            if not (0<=x1<x2<=w and 0<=y1<y2<=h):continue
            groups[self.config['classes'][kind]].append(dict(xyxy=[math.floor(x1),math.floor(y1),math.ceil(x2),math.ceil(y2)],confidence=score))
        text_kinds={'current_name_line','target_name_line','selected_character_name','dungeon_name','difficulty','gateless_title'}
        groups={kind:merge_text_duplicates(items) if kind in text_kinds else suppress_duplicates(items,self.config.get('nmsIou',.4)) for kind,items in groups.items()}
        return {kind:dict(status='detected' if len(items)==1 else ('missing' if not items else 'ambiguous'),
                         candidates=items,**(items[0] if len(items)==1 else {})) for kind,items in groups.items()}


def get_box(regions,kind):
    item=regions.get(kind,{})
    return item.get('xyxy') if item.get('status')=='detected' else None


def dungeon_location(regions,shape):
    panel=get_box(regions,'dungeon_panel')
    if panel is None:return dict(status=regions.get('dungeon_panel',{}).get('status','missing'),regions={})
    fields={field:get_box(regions,kind) for field,kind in
            (('dungeonName','dungeon_name'),('difficulty','difficulty'))}
    if any(box is None or not contained(box,panel) for box in fields.values()):
        return dict(status='text_region_missing_or_outside',regions={})
    return dict(status='detected',xyxy=panel,regions=fields)


def detected_gates(regions):
    """Direct full-frame icon detections; numbering follows screen order, not fixed slots."""
    panel=get_box(regions,'dungeon_panel');row=get_box(regions,'gate_panel')
    if panel is None or row is None or not contained(row,panel):return []
    result=[]
    for kind,state in (('gate_in_progress','진행중'),('gate_completed','완료'),('gate_not_started','진행 전')):
        entry=regions.get(kind,{})
        candidates=entry.get('candidates',[])
        if not candidates and entry.get('status')=='detected':candidates=[entry]
        for item in candidates:
            if contained(item['xyxy'],row):result.append(dict(state=state,confidence=item['confidence'],xyxy=item['xyxy']))
    result.sort(key=lambda box:box['xyxy'][0])
    # Conflicting state predictions for the same icon invalidate the whole array.
    if not 1<=len(result)<=8 or any(a['xyxy'][2]>b['xyxy'][0] for a,b in zip(result,result[1:])):return []
    # A detected row with a large uncovered end is an incomplete observation.
    # Tolerance is the observed icon size, not a pixel slot or screen-relative ROI.
    tolerance=max(b['xyxy'][2]-b['xyxy'][0] for b in result)*2
    if result[0]['xyxy'][0]-row[0]>tolerance or row[2]-result[-1]['xyxy'][2]>tolerance:return []
    return result
