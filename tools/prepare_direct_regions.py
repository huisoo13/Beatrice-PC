"""One-time annotation migration; coordinates here are labels, never runtime ROIs."""
import os,sys,json,copy,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
import cv2,numpy as np,torch
from ultralytics import YOLO
from beatrice.character_vision import trim_name_line
from beatrice.dungeon import trim_difficulty_line
from tools.legacy_gate_annotations import relative_box,gate_crop_box
from tools.train_dungeon_panel import prepare

DC=['dungeon_panel','gate_panel','quest_complete_banner','gateless_raid_panel','dungeon_name','difficulty','gate_in_progress','gate_completed','gate_not_started','gateless_title']
TIMES=['113751','113722','113715','113933','113925','113915','113907','113835','113831','113822','113817','113811','113755']
# Reviewed at the display sizes specified with each row, transformed to original pixels.
# menu,name,dialog,target; dungeon rows: panel,name,difficulty,first,second.
LABELS={
'113751':(1920,1080,[[250,235,1810,790],[340,672,460,696],None,None]),
'113715':(2048,1152,[[270,250,1920,840],[360,716,492,742],None,None]),
'113722':(2048,1152,[[270,250,1920,840],[360,716,492,742],[822,474,1227,683],[991,525,1057,549]]),
'113755':(1920,1080,[[250,235,1810,790],[340,672,460,696],[771,440,1149,640],[930,492,990,516]]),
'113831':(1920,1080,[[430,315,1595,727],[494,637,586,657],None,None]),
'113835':(1920,1080,[[430,315,1595,727],[494,637,586,657],[817,464,1103,616],[937,501,983,521]]),
'113817':(2048,1152,[[456,333,1695,775],[527,680,625,701],None,None]),
'113822':(2048,1152,[[456,333,1695,775],[527,680,625,701],[872,495,1176,656],[998,537,1049,556]]),
'113933':(1920,1080,[[0,30,272,189],[73,44,202,67],[98,70,175,92],[61,104,97,144],[174,105,209,144]]),
'113925':(2048,1152,[[0,32,291,202],[78,47,216,72],[103,73,190,98],[64,110,105,156],[183,109,228,156]]),
'113907':(1920,1080,[[0,155,205,279],[55,168,153,186],[73,186,133,204],[46,212,76,243],[132,212,161,243]]),
'113915':(2048,1152,[[0,166,219,298],[59,179,163,199],[78,200,141,218],[49,225,80,261],[141,225,172,261]]),
}

def refine(frame,box,mode='name'):
    l,t,r,b=map(round,box);crop=frame[t:b,l:r]
    trimmed=trim_difficulty_line(crop) if mode=='difficulty' else trim_name_line(crop,max_gap=max(16,crop.shape[0]))
    if trimmed is None:return [l,t,r,b]
    match=cv2.matchTemplate(crop,trimmed,cv2.TM_SQDIFF);_,_,(x,y),_=cv2.minMaxLoc(match)
    return [max(0,l+x-2),max(0,t+y-2),min(frame.shape[1],l+x+trimmed.shape[1]+2),min(frame.shape[0],t+y+trimmed.shape[0]+2)]

def main():
    torch.set_num_threads(4)
    raw=ROOT/'data/raw/direct-regions-0926';raw.mkdir(parents=True,exist_ok=True)
    out=ROOT/'outputs/direct-regions-0926';out.mkdir(parents=True,exist_ok=True)
    gate=YOLO(str(ROOT/'models/gates-yolo26n-first.pt'))
    char=json.loads((ROOT/'data/annotations/character-loading-0925.json').read_text('utf8'))
    dungeon=json.loads((ROOT/'data/annotations/raid-banner-header-v2-0924.json').read_text('utf8'));dungeon['classes']=DC
    for row in char['images']:
        frame=cv2.imread(str(ROOT/'data/annotations'/row['path']))
        for box in row['boxes']:
            if box['class'] in ('current_name_line','target_name_line'):box['xyxy']=refine(frame,box['xyxy'])
        menu=next((b for b in row['boxes'] if b['class']=='game_menu'),None)
        name=next((b for b in row['boxes'] if b['class']=='current_name_line'),None)
        if menu and name:
            menu['xyxy']=[min(menu['xyxy'][0],name['xyxy'][0]-5),menu['xyxy'][1],menu['xyxy'][2],menu['xyxy'][3]]
    stateclass={'진행중':'gate_in_progress','완료':'gate_completed','진행 전':'gate_not_started'}
    for row in dungeon['images']:
        frame=cv2.imread(str(ROOT/'data/annotations'/row['path']))
        old={b['class']:b['xyxy'] for b in row['boxes']}
        if 'dungeon_panel' in old:
            panel=old['dungeon_panel']
            for field,rect,mode in [('dungeon_name',[.02,.07,.98,.26],'name'),('difficulty',[.15,.25,.85,.46],'difficulty')]:
                row['boxes'].append(dict(**{'class':field},xyxy=refine(frame,relative_box(panel,rect,frame.shape),mode)))
            l,t,r,b=gate_crop_box(old['gate_panel'],frame.shape)
            pred=gate.predict(cv2.resize(frame[t:b,l:r],(320,112)),imgsz=320,conf=.65,device='cpu',verbose=False)[0]
            for box in pred.boxes:
                x1,y1,x2,y2=box.xyxy[0].tolist()
                row['boxes'].append({'class':stateclass[gate.names[int(box.cls[0])]],'xyxy':[round(l+x1*(r-l)/320),round(t+y1*(b-t)/112),round(l+x2*(r-l)/320),round(t+y2*(b-t)/112)]})
        if 'gateless_raid_panel' in old:
            rect=relative_box(old['gateless_raid_panel'],[.06,.45,.97,.86],frame.shape)
            row['boxes'].append({'class':'gateless_title','xyxy':refine(frame,rect)})
    for time in TIMES:
        source=Path('C:/Program Files (x86)/Smilegate/Games/LOSTARK/EFGame/Screenshots')/f'Screenshot_260926_{time}.jpg'
        dest=raw/source.name;shutil.copy2(source,dest)
        frame=cv2.imread(str(dest));h,w=frame.shape[:2]
        c=[];d=[]
        if time in LABELS:
            dw,dh,boxes=LABELS[time]
            names=(['dungeon_panel','dungeon_name','difficulty','gate_in_progress','gate_not_started'] if time in ('113933','113925','113907','113915') else ['game_menu','current_name_line','switch_dialog','target_name_line'])
            for name,box in zip(names,boxes):
                if box is None:continue
                rect=[round(box[0]*w/dw),round(box[1]*h/dh),round(box[2]*w/dw),round(box[3]*h/dh)]
                (d if name in DC else c).append({'class':name,'xyxy':rect})
            if d:
                gates=[b['xyxy'] for b in d if b['class'].startswith('gate_')]
                d.append({'class':'gate_panel','xyxy':[min(b[0] for b in gates)-3,min(b[1] for b in gates)-3,max(b[2] for b in gates)+3,max(b[3] for b in gates)+3]})
        base=dict(path='../raw/direct-regions-0926/'+dest.name,split='train',sessionId='260926-resolution',source=str(source),synthetic=False,resolution=[w,h],letterboxed=time in ('113915','113907','113835','113831','113822','113817','113811'))
        char['images'].append(dict(base,boxes=c));dungeon['images'].append(dict(base,boxes=d))
    for name,doc in [('character',char),('dungeon',dungeon)]:
        doc['annotationMethod']='reviewed direct element boxes; old gate predictions are offline annotation proposals'
        path=ROOT/f'data/annotations/{name}-direct-0926.json';path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
        cfg=json.loads((ROOT/f'config/{name}-regions.json').read_text('utf8'));cfg['classes']=doc['classes'];cfg['trainingManifest']=str(path.relative_to(ROOT)).replace('\\','/');cfg['trainingRun']=f'{name}-direct-0926'
        cfg['weights']=f'outputs/training/{name}-direct-0926/weights/best.pt'
        (out/f'{name}.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
        prepare(path,ROOT/f'data/datasets/{name}-direct-0926',doc['classes'],True)
        # Contact sheet of every text/icon label for human review.
        tiles=[]
        for i,row in enumerate(doc['images']):
            frame=cv2.imread(str(ROOT/'data/annotations'/row['path']))
            for box in row['boxes']:
                if box['class'] in ('game_menu','switch_dialog','dungeon_panel','gate_panel','quest_complete_banner','gateless_raid_panel'):continue
                l,t,r,b=box['xyxy'];crop=frame[t:b,l:r];scale=min(360/crop.shape[1],64/crop.shape[0]);crop=cv2.resize(crop,None,fx=scale,fy=scale)
                tile=np.full((92,400,3),235,np.uint8);cv2.putText(tile,f'{i}: {box["class"]}',(3,17),0,.45,(0,0,0),1);tile[25:25+crop.shape[0],:crop.shape[1]]=crop;tiles.append(tile)
        for start in range(0,len(tiles),40):
            page=tiles[start:start+40];page += [np.full((92,400,3),235,np.uint8)]*((-len(page))%4)
            sheet=np.vstack([np.hstack(page[j:j+4]) for j in range(0,len(page),4)])
            cv2.imwrite(str(out/f'{name}-labels-{start//40}.jpg'),sheet)
        print(name,len(doc['images']),flush=True)

if __name__=='__main__':main()
