"""Balance rare completed icons and review real all-completed frames for full-frame training."""
import sys,os,json,copy,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
import cv2,numpy as np,torch
from ultralytics import YOLO
from tools.train_dungeon_panel import prepare
from tools.legacy_gate_annotations import gate_crop_box

def main():
    torch.set_num_threads(2)
    raw=ROOT/'data/raw/direct-reinforcement-0926';raw.mkdir(parents=True,exist_ok=True)
    for role in ('character','dungeon'):
        path=ROOT/f'data/annotations/{role}-direct-0926.json';doc=json.loads(path.read_text('utf8'))
        original=copy.deepcopy(doc['images'])
        for i,row in enumerate(original):
            # Different transform from the evaluation probe. Full original image preserved.
            eligible=(row.get('sessionId','').startswith('260926') if role=='character' else any(b['class']=='gate_completed' for b in row['boxes']) or row.get('sessionId')=='260926-resolution' and bool(row['boxes']))
            if not eligible:continue
            frame=cv2.imread(str(ROOT/'data/annotations'/row['path']));h,w=frame.shape[:2]
            for v,(scale,dx,dy) in enumerate(((.9,110,65),(.72,60,170))):
                small=cv2.resize(frame,(round(w*scale),round(h*scale)));canvas=np.zeros((h+120,w+140,3),np.uint8)
                canvas[dy:dy+small.shape[0],dx:dx+small.shape[1]]=small
                dest=raw/f'{role}-{i}-{v}.jpg';cv2.imwrite(str(dest),canvas)
                boxes=[dict(b,xyxy=[round(b['xyxy'][0]*scale)+dx,round(b['xyxy'][1]*scale)+dy,round(b['xyxy'][2]*scale)+dx,round(b['xyxy'][3]*scale)+dy]) for b in row['boxes']]
                doc['images'].append(dict(row,path='../raw/direct-reinforcement-0926/'+dest.name,boxes=boxes,synthetic=True,transform=dict(scale=scale,offset=[dx,dy]),sourceParent=row['path']))
        if role=='dungeon':
            model=YOLO(str(ROOT/'models/gates-yolo26n-first.pt'))
            reference=copy.deepcopy(original[33])
            classes={'진행중':'gate_in_progress','완료':'gate_completed','진행 전':'gate_not_started'}
            tiles=[]
            for seq in (145,150,155,159,160,169,170,175,180,185):
                src=ROOT/f'outputs/gate-delay-review-0923/frame-{seq%180:03d}.jpg';frame=cv2.imread(str(src))
                dest=raw/f'completion-{seq}.jpg';shutil.copy2(src,dest)
                boxes=[b for b in copy.deepcopy(reference['boxes']) if b['class'] in ('dungeon_panel','gate_panel','dungeon_name','difficulty')]
                rowbox=next(b['xyxy'] for b in boxes if b['class']=='gate_panel');l,t,r,b=gate_crop_box(rowbox,frame.shape)
                prediction=model.predict(cv2.resize(frame[t:b,l:r],(320,112)),imgsz=320,conf=.65,device='cpu',verbose=False)[0]
                states=[]
                for item in prediction.boxes:
                    x1,y1,x2,y2=item.xyxy[0].tolist();state=model.names[int(item.cls[0])];states.append(state)
                    boxes.append({'class':classes[state],'xyxy':[round(l+x1*(r-l)/320),round(t+y1*(b-t)/112),round(l+x2*(r-l)/320),round(t+y2*(b-t)/112)]})
                # Ambiguous old-model observations must be reviewed, not silently used.
                crop=frame[:260,:420].copy();cv2.putText(crop,str(seq),(280,245),0,1,(255,255,255),2);tiles.append(crop)
                if len(states)==2:
                    doc['images'].append(dict(path='../raw/direct-reinforcement-0926/'+dest.name,boxes=boxes,split='train',sessionId='gate-delay-0923',synthetic=False,source=str(src)))
                print(seq,states,flush=True)
            cv2.imwrite(str(ROOT/'outputs/direct-regions-0926/completion-label-review.jpg'),np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)]))
        out=ROOT/f'data/annotations/{role}-direct-reinforced-0926.json';out.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
        prepare(out,ROOT/f'data/datasets/{role}-direct-reinforced-0926',doc['classes'],True)
        print(role,len(doc['images']),flush=True)

if __name__=='__main__':main()
