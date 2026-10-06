"""Offline UI-only compositing; October 1 failed session is never training input."""
import json, random
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
from train_dungeon_panel import prepare

ROOT=Path(__file__).resolve().parents[1]

def main():
    rng=random.Random(1001)
    base=json.loads((ROOT/'data/annotations/character-initial-login-0930-v2.json').read_text(encoding='utf-8'))
    # Retain old character/server/card-crop examples, remove broad loading labels.
    rows=[r for r in base['images'] if not any(b['class']=='loading_progress' for b in r['boxes'])]
    raw=ROOT/'data/raw/login-invariants-1001';raw.mkdir(parents=True,exist_ok=False)
    shot=Path('C:/Program Files (x86)/Smilegate/Games/LOSTARK/EFGame/Screenshots/Screenshot_260930_135402.jpg')
    selection=Image.open(shot).convert('RGB').resize((2048,857))
    loading=Image.open(ROOT/'outputs/initial-login/evidence/frame-155.jpg').convert('RGB').resize((2048,857))
    # Tight offline annotations: no loading picture/tip text is part of the object.
    assets=[('selected_character_card',selection.crop((642,709,823,758))),
            ('game_start_button',selection.crop((857,784,1023,828))),
            ('loading_progress',loading.crop((303,809,1738,834)))]
    backgrounds=[Image.open(ROOT/'outputs/initial-login/evidence/frame-160.jpg').convert('RGB'),
                 selection.crop((0,0,2048,650)),loading.crop((250,80,1750,700))]
    for i in range(96):
        w,h=1280,720
        if i%4==0:
            canvas=Image.new('RGB',(w,h),tuple(rng.randrange(15,190) for _ in range(3)))
        else:
            bg=backgrounds[i%len(backgrounds)]
            canvas=bg.resize((w,h)).filter(ImageFilter.GaussianBlur(rng.choice([0,2,8])))
            canvas=ImageEnhance.Brightness(canvas).enhance(rng.uniform(.3,1.2))
        boxes=[]
        kinds=[i%3] if i%2 else [0,1,2]
        # Separate random bands only for synthetic placement; never runtime coordinates.
        for j,kind in enumerate(kinds):
            label,asset=assets[kind];asset=asset.copy()
            if kind==2:
                # Vary progress using real track/filled pixels; retain both ends.
                track=asset.crop((600,0,asset.width,asset.height)).resize(asset.size)
                length=round(asset.width*rng.uniform(.04,.96))
                fill=asset.crop((0,0,355,asset.height)).resize((length,asset.height))
                track.paste(fill,(0,0));asset=track
            scale=rng.uniform(.43,.8) if kind==2 else rng.uniform(.6,1.5)
            asset=asset.resize((round(asset.width*scale),round(asset.height*scale)))
            asset=ImageEnhance.Brightness(asset).enhance(rng.uniform(.45,1.15))
            x=rng.randrange(5,w-asset.width-5)
            lo=j*(h//len(kinds));hi=(j+1)*(h//len(kinds))-asset.height
            y=rng.randrange(lo,max(lo+1,hi))
            canvas.paste(asset,(x,y));boxes.append(dict(**{'class':label},xyxy=[x,y,x+asset.width,y+asset.height]))
            if kind==0:
                boxes.append({'class':'selected_character_name','xyxy':[x+round(42*scale),y+round(13*scale),x+round(89*scale),y+round(32*scale)]})
        path=raw/f'composite-{i:03}.png';canvas.save(path)
        rows.append(dict(path='../raw/login-invariants-1001/'+path.name,split='train',sessionId='login-invariants-1001',synthetic=True,boxes=boxes))
    # Other buttons / unselected cards are hard negatives, at varying locations.
    for i in range(12):
        canvas=Image.new('RGB',(1280,720),(20+i,20+i,20+i))
        for coords in [(1027,784,1189,828),(836,709,1018,758),(445,710,627,758)]:
            asset=selection.crop(coords);canvas.paste(asset,(rng.randrange(900),rng.randrange(600)))
        path=raw/f'negative-{i:02}.png';canvas.save(path)
        rows.append(dict(path='../raw/login-invariants-1001/'+path.name,split='train',sessionId='login-invariants-1001',synthetic=True,boxes=[]))
    doc=dict(classes=base['classes'],images=rows,evaluationPurpose='training_reconstruction_only_not_independent',
             heldOutSession='8dee6418f53f4795baeaf639545ab632',annotationMethod='UI-only assets on varied backgrounds, random positions/scales/brightness/progress; tight progress bar')
    manifest=ROOT/'data/annotations/login-invariants-1001.json'
    manifest.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    print(prepare(manifest,ROOT/'data/processed/login-invariants-1001',doc['classes'],True))

if __name__=='__main__':main()
