"""Offline reviewed labels and dim variants; no runtime screen coordinates."""
import json,random
from pathlib import Path
from PIL import Image,ImageEnhance
from train_dungeon_panel import prepare
ROOT=Path(__file__).resolve().parents[1]

def main():
    rng=random.Random(1006)
    base=json.loads((ROOT/'data/annotations/login-marker-1001.json').read_text(encoding='utf-8'))
    raw=ROOT/'data/raw/login-dim-1006';raw.mkdir(parents=True,exist_ok=False)
    # Coordinates reviewed on 2048x857 previews, used only to build training labels.
    cards={0:([640,707,822,759],[680,721,722,740]),
           10:([836,707,1017,759],[875,721,922,740]),
           11:([1031,707,1212,759],[1070,721,1123,740]),
           15:([836,707,1017,759],[875,721,922,740])}
    for frame,(card,name) in cards.items():
        source=Image.open(ROOT/f'outputs/fast-selection-20261001-234948/frame-{frame:03}.jpg').convert('RGB').resize((2048,857))
        labels=[dict(class_='selected_character_card',xyxy=card),dict(class_='selected_character_name',xyxy=name),dict(class_='game_start_button',xyxy=[856,784,1022,829])]
        for n in range(8):
            factor=1 if n==0 else rng.uniform(.4,1.15)
            im=ImageEnhance.Brightness(source).enhance(factor)
            path=raw/f'full-{frame:03}-{n}.png';im.save(path)
            base['images'].append(dict(path='../raw/login-dim-1006/'+path.name,split='train',sessionId='fast-selection-1001',synthetic=n!=0,boxes=[{'class':b['class_'],'xyxy':b['xyxy']} for b in labels]))
        # Train the same model's existing card-local retry with varied borders.
        for n in range(12):
            pad=rng.randint(0,25);l,t,r,b=card
            crop=source.crop((l-pad,t-pad,r+pad,b+pad))
            crop=ImageEnhance.Brightness(crop).enhance(rng.uniform(.45,1.15))
            path=raw/f'card-{frame:03}-{n}.png';crop.save(path)
            boxes=[{'class':label['class_'],'xyxy':[label['xyxy'][0]-l+pad,label['xyxy'][1]-t+pad,label['xyxy'][2]-l+pad,label['xyxy'][3]-t+pad]} for label in labels[:2]]
            base['images'].append(dict(path='../raw/login-dim-1006/'+path.name,split='train',sessionId='fast-selection-1001',synthetic=True,boxes=boxes))
    base['annotationMethod']+='; manually reviewed fast selection and dim password frames; entire source session is training/reconstruction, never independent validation'
    p=ROOT/'data/annotations/login-dim-1006.json';p.write_text(json.dumps(base,ensure_ascii=False,indent=2),encoding='utf-8')
    print(prepare(p,ROOT/'data/processed/login-dim-1006',base['classes'],True))

if __name__=='__main__':main()
