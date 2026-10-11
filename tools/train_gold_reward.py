"""Prepare reviewed reward panels and dim variants; coordinates are training labels only."""
import argparse
import json
from pathlib import Path
from PIL import Image,ImageEnhance
from train_dungeon_panel import prepare

ROOT=Path(__file__).resolve().parents[1]
CLASSES=['reward_panel','reward_gate_title','gold_reward_present','gold_reward_absent']

def build(output):
    raw=ROOT/'data/raw/gold-reward-1011';raw.mkdir(parents=True,exist_ok=True)
    session=Path('C:/Users/Huisoo/AppData/Local/BeatricePC/completion-diagnostics/20261011T053841Z-92af6174')
    sources=[('gold',ROOT/'data/raw/dungeon-completion-0923/completion-230.jpg',True),
             ('no-gold',Path('C:/Users/Huisoo/AppData/Local/Temp/codex-clipboard-4402bfe3-adff-4304-aa71-1ece48a0d1d3.png'),False)]
    rows=[]
    def append(path,boxes):
        rows.append(dict(path=path.relative_to(ROOT/'data/annotations').as_posix() if path.is_relative_to(ROOT/'data/annotations') else '../../'+path.relative_to(ROOT).as_posix(),split='train',sessionId='reward-reconstruction-1011',boxes=boxes))
    for name,path,present in sources:
        saved=raw/(name+'.png')
        original=Image.open(saved if saved.exists() else path).convert('RGB');original.save(saved)
        panel=[2960,30,3440,1100];title=[3108,82,3326,128]
        section=[2985,620,3410,763]
        for scale in (1,.75,1.25):
            for brightness in (1,.75,.5,.35):
                image=ImageEnhance.Brightness(original).enhance(brightness)
                for crop_number,bounds in enumerate((None,panel,[2900,0,3440,1100],[2940,0,3440,1150],[2920,0,3440,1100],[2940,50,3440,1100])):
                    crop=bounds is not None
                    current=image.crop(bounds) if crop else image
                    current=current.resize((round(current.width*scale),round(current.height*scale)))
                    dest=raw/f'{name}-{scale}-{brightness}-{crop_number}.png';current.save(dest)
                    boxes=[]
                    for kind,coords in ([('reward_gate_title',title),('gold_reward_present' if present else 'gold_reward_absent',section)] if crop else [('reward_panel',panel)]):
                        x,y=bounds[:2] if crop else (0,0)
                        boxes.append(dict(class_=kind,xyxy=[round((coords[0]-x)*scale),round((coords[1]-y)*scale),round((coords[2]-x)*scale),round((coords[3]-y)*scale)]))
                    append(dest,[{'class':b['class_'],'xyxy':b['xyxy']} for b in boxes])
    negatives=[session/'event-00000075.jpg',ROOT/'data/raw/exhard-gate-panel-1008/event-00005765.jpg',
               Path('C:/Users/Huisoo/AppData/Local/Temp/codex-clipboard-f8a17d28-9aef-4749-a905-2a37f2d6c30c.png'),
               Path('C:/Users/Huisoo/AppData/Local/Temp/codex-clipboard-5d431379-7c3c-4e9a-ab2c-e5d1edfaf94f.png')]
    for i,path in enumerate(negatives):
        saved=raw/f'negative-{i}-0.png'
        im=Image.open(saved if saved.exists() else path).convert('RGB')
        for crop in (False,True):
            dest=raw/f'negative-{i}-{int(crop)}.png';(im.crop((2970,0,3440,1100)) if crop else im).save(dest);append(dest,[])
    manifest=ROOT/'data/annotations/gold-reward-context-1011.json'
    manifest.write_text(json.dumps(dict(classes=CLASSES,evaluationPurpose='training_reconstruction_only_not_independent',images=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    return prepare(manifest,output,CLASSES,True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'data/datasets/gold-reward-context-1011')
    parser.add_argument('--parent',action='store_true');args=parser.parse_args()
    if args.parent:
        doc=json.loads((ROOT/'data/annotations/gold-reward-context-1011.json').read_text(encoding='utf-8'))
        doc['classes']=['reward_panel'];doc['images']=[row for row in doc['images'] if Path(row['path']).stem.endswith('-0')]
        manifest=ROOT/'data/annotations/gold-reward-panel-1011.json';manifest.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
        print(prepare(manifest,args.output,doc['classes'],True))
    else:print(build(args.output))
