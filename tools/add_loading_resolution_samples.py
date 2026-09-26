"""Append the four user-supplied loading screens to the direct-character dataset."""
import json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PIL import Image
from tools.train_dungeon_panel import prepare

def main():
    path=ROOT/'data/annotations/character-direct-0926.json';doc=json.loads(path.read_text('utf8'))
    samples={
        '115411':(2048,1152,[270,250,1920,840],[368,716,480,742],[1690,1034,2048,1152],False),
        '115635':(1920,1080,[250,235,1810,790],[347,672,455,696],[1590,974,1920,1080],False),
        '115556':(1920,1080,[430,315,1595,727],[494,637,586,657],[1670,860,1920,945],True),
        '115452':(2048,1152,[456,333,1695,775],[534,680,620,701],[1780,918,2048,1008],True),
    }
    for time,(dw,dh,menu,name,loading,letterbox) in samples.items():
        source=Path('C:/Program Files (x86)/Smilegate/Games/LOSTARK/EFGame/Screenshots')/f'Screenshot_260926_{time}.jpg'
        dest=ROOT/'data/raw/direct-regions-0926'/source.name;shutil.copy2(source,dest)
        with Image.open(dest) as im:w,h=im.size
        boxes=[{'class':kind,'xyxy':[round(b[0]*w/dw),round(b[1]*h/dh),round(b[2]*w/dw),round(b[3]*h/dh)]}
               for kind,b in [('game_menu',menu),('current_name_line',name),('loading_indicator',loading)]]
        doc['images'].append(dict(path='../raw/direct-regions-0926/'+source.name,split='train',sessionId='260926-loading',source=str(source),synthetic=False,resolution=[w,h],letterboxed=letterbox,boxes=boxes))
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
    prepare(path,ROOT/'data/datasets/character-direct-loading-0926',doc['classes'],True)
    cfgpath=ROOT/'outputs/direct-regions-0926/character.json';cfg=json.loads(cfgpath.read_text('utf8'))
    cfg.update(trainingRun='character-direct-loading-0926',weights='outputs/training/character-direct-loading-0926/weights/best.pt')
    cfgpath.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
    print(len(doc['images']))

if __name__=='__main__':main()
