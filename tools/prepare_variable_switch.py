"""Offline reviewed labels/augmentation for the item-warning switch dialog.

Pixel coordinates below describe this saved training image only. Runtime loads
the trained detector, never these coordinates or the item-list crop.
"""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from tools.train_dungeon_panel import prepare

def main():
    raw=ROOT/'data/raw/variable-switch-0928';raw.mkdir(parents=True,exist_ok=True)
    doc=json.loads((ROOT/'data/annotations/character-direct-reinforced-0926.json').read_text('utf8'))
    image=cv2.imread(str(ROOT/'outputs/switch-review-0928/frame-038.jpg'))
    report=json.loads((ROOT/'outputs/switch-review-0928/frame-038.json').read_text('utf8'))
    base=[dict(class_=k,xyxy=report['character']['detections'][k]['xyxy']) for k in ('game_menu','current_name_line')]
    base=[{'class':b['class_'],'xyxy':b['xyxy']} for b in base]
    dialog=[1358,348,2083,1194];target=[1681,992,1765,1023]
    boxes=base+[{'class':'switch_dialog','xyxy':dialog},{'class':'target_name_line','xyxy':target}]
    def add(name,frame,labels,synthetic=False):
        dest=raw/(name+'.png');cv2.imwrite(str(dest),frame)
        doc['images'].append(dict(path='../raw/variable-switch-0928/'+dest.name,split='train',sessionId='260928-variable-dialog',synthetic=synthetic,boxes=labels,sourceParent='outputs/switch-review-0928/frame-038.jpg'))
    add('original',image,boxes)
    # Six actual item rows. Reorder/repeat/remove rows and move the footer intact.
    x1,y1,x2,y2=dialog;list_top=477;list_bottom=974
    tiles=[image[round(list_top+i*(list_bottom-list_top)/6):round(list_top+(i+1)*(list_bottom-list_top)/6),x1:x2] for i in range(6)]
    for index,count in enumerate((1,2,3,4,5,7)):
        chosen=[tiles[(i*5+index)%6] for i in range(count)]
        panel=np.concatenate([image[y1:list_top,x1:x2],*chosen,image[list_bottom:y2,x1:x2]],axis=0)
        delta=panel.shape[0]-(y2-y1);dy=-delta//2
        # Restore actual neighboring menu pixels where the shorter popup exposes
        # its background; do not stretch a one-pixel strip into an artifact.
        frame=image.copy()
        background=cv2.imread(str(ROOT/'outputs/switch-review-0928/frame-040.jpg'))
        frame[y1:y2,x1:x2]=(background[y1:y2,x1:x2]*.7).astype(np.uint8)
        frame[y1+dy:y1+dy+panel.shape[0],x1:x2]=panel
        labels=copy.deepcopy(base)+[{'class':'switch_dialog','xyxy':[x1,y1+dy,x2,y2+delta+dy]},
                    {'class':'target_name_line','xyxy':[target[0],target[1]+delta+dy,target[2],target[3]+delta+dy]}]
        add(f'items-{count}',frame,labels,True)
        for scale in (.75,.9):
            small=cv2.resize(frame,None,fx=scale,fy=scale);canvas=np.zeros_like(frame);dx=60;oy=35
            canvas[oy:oy+small.shape[0],dx:dx+small.shape[1]]=small
            transformed=[dict(b,xyxy=[round(b['xyxy'][0]*scale)+dx,round(b['xyxy'][1]*scale)+oy,round(b['xyxy'][2]*scale)+dx,round(b['xyxy'][3]*scale)+oy]) for b in labels]
            add(f'items-{count}-{scale}',canvas,transformed,True)
    path=ROOT/'data/annotations/character-variable-switch-0928.json'
    doc['annotationMethod']='Existing reviewed data plus manually reviewed variable item dialog; synthetic row counts/content and whole-frame scale variants.'
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
    preview=image.copy()
    for b in boxes:
        l,t,r,bottom=b['xyxy'];cv2.rectangle(preview,(l,t),(r,bottom),(0,255,0),2)
    out=ROOT/'outputs/variable-switch-0928';out.mkdir(exist_ok=True)
    cv2.imwrite(str(out/'labels.jpg'),preview)
    print(prepare(path,ROOT/'data/datasets/character-variable-switch-clean-0928',doc['classes'],True))
if __name__=='__main__':main()
