"""Build parent and child YOLO datasets from reviewed boxes (no runtime ROI constants)."""
import json,sys,copy,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
from tools.train_dungeon_panel import prepare

def main():
    source=json.loads((ROOT/'data/annotations/dungeon-direct-reinforced-0926.json').read_text('utf8'))
    parent_classes=['dungeon_panel','gate_panel','quest_complete_banner','gateless_raid_panel']
    children=['gate_panel','dungeon_name','difficulty','gate_in_progress','gate_completed','gate_not_started','gateless_title']
    parent=dict(source,classes=parent_classes,images=[]);child=dict(source,classes=children,images=[])
    raw=ROOT/'data/raw/direct-elements-0926';raw.mkdir(parents=True,exist_ok=True)
    for i,row in enumerate(source['images']):
        parent['images'].append(dict(row,boxes=[b for b in row['boxes'] if b['class'] in parent_classes]))
        panels=[b for b in row['boxes'] if b['class'] in ('dungeon_panel','gateless_raid_panel')]
        frame=cv2.imread(str(ROOT/'data/annotations'/row['path']))
        if not panels:
            if i in (11,12,13,14,44,45,51,52,53,54,55,56):
                # Negative full frames, resized by the training loader as usual.
                child['images'].append(dict(row,boxes=[]))
            continue
        panel=panels[0];l,t,r,b=panel['xyxy'];crop=frame[t:b,l:r];dest=raw/f'{i:03d}.png';cv2.imwrite(str(dest),crop)
        boxes=[]
        for item in row['boxes']:
            if item['class'] not in children:continue
            x1,y1,x2,y2=item['xyxy']
            if not (l<=x1<x2<=r and t<=y1<y2<=b):raise ValueError((i,item,panel))
            boxes.append(dict(item,xyxy=[x1-l,y1-t,x2-l,y2-t]))
        child['images'].append(dict(row,path='../raw/direct-elements-0926/'+dest.name,boxes=boxes,sourceParent=row['path'],sourceDetection=panel))
    for name,doc in [('dungeon-parents',parent),('dungeon-elements',child)]:
        unique=[];seen={}
        for row in doc['images']:
            digest=hashlib.sha256((ROOT/'data/annotations'/row['path']).read_bytes()).hexdigest()
            if digest in seen:
                if sorted(row['boxes'],key=lambda v:(v['class'],v['xyxy']))!=sorted(seen[digest]['boxes'],key=lambda v:(v['class'],v['xyxy'])):
                    raise ValueError('Identical pixels have conflicting annotations')
                continue
            seen[digest]=row;unique.append(row)
        doc['images']=unique
        path=ROOT/f'data/annotations/{name}-0926.json';path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
        destination=ROOT/f'data/datasets/{name}-0926'
        if not destination.exists():prepare(path,destination,doc['classes'],True)
        print(name,len(doc['images']),flush=True)

if __name__=='__main__':main()
