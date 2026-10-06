"""UI row context and real tight progress labels, without October 1 evidence."""
import json,random
from pathlib import Path
from PIL import Image,ImageEnhance,ImageDraw
from train_dungeon_panel import prepare
ROOT=Path(__file__).resolve().parents[1]

def main():
    rng=random.Random(10012)
    base=json.loads((ROOT/'data/annotations/login-invariants-1001.json').read_text(encoding='utf-8'))
    # Wider vertical margin around the thin bar, excluding tip text.
    rows=base['images']
    for r in rows:
        for b in r['boxes']:
            if b['class']=='loading_progress':
                with Image.open((ROOT/'data/annotations'/r['path']).resolve()) as im:
                    pad=round((b['xyxy'][3]-b['xyxy'][1])*.5)
                    b['xyxy'][1]=max(0,b['xyxy'][1]-pad);b['xyxy'][3]=min(im.height,b['xyxy'][3]+pad)
    raw=ROOT/'data/raw/login-contexts-1001';raw.mkdir(parents=True,exist_ok=False)
    source=Image.open('C:/Program Files (x86)/Smilegate/Games/LOSTARK/EFGame/Screenshots/Screenshot_260930_135402.jpg').convert('RGB').resize((2048,857))
    ui=source.crop((425,678,1610,834))
    labels=[('selected_character_card',[217,31,398,80]),('selected_character_name',[259,44,306,63]),('game_start_button',[432,106,598,150])]
    backgrounds=[source.crop((0,0,2048,650)),Image.open(ROOT/'outputs/initial-login/evidence/frame-160.jpg').convert('RGB')]
    for i in range(32):
        canvas=backgrounds[i%2].resize((2048,857))
        factor=rng.uniform(.65,1.25);patch=ui.resize((round(ui.width*factor),round(ui.height*factor)))
        patch=ImageEnhance.Brightness(patch).enhance(rng.uniform(.35,1.1))
        x=rng.randrange(0,2048-patch.width);y=rng.randrange(0,857-patch.height)
        canvas.paste(patch,(x,y))
        boxes=[{'class':k,'xyxy':[x+round(a*factor),y+round(b*factor),x+round(c*factor),y+round(d*factor)]} for k,(a,b,c,d) in labels]
        p=raw/f'row-{i:02}.png';canvas.save(p)
        rows.append(dict(path='../raw/login-contexts-1001/'+p.name,split='train',sessionId='login-contexts-1001',synthetic=True,boxes=boxes))
    load=Image.open(ROOT/'outputs/initial-login/evidence/frame-155.jpg').convert('RGB').resize((2048,857))
    for i in range(12):
        canvas=ImageEnhance.Brightness(load).enhance(.6+i*.035)
        boxes=[{'class':'loading_progress','xyxy':[300,802,1740,848]}]
        if i%3==2:
            ImageDraw.Draw(canvas).rectangle((0,800,2048,857),fill='black');boxes=[]
        p=raw/f'loading-{i:02}.png';canvas.save(p)
        rows.append(dict(path='../raw/login-contexts-1001/'+p.name,split='train',sessionId='login-contexts-1001',synthetic=True,boxes=boxes))
    base['annotationMethod']+='; intact UI row contexts; real tight bar with text-only loading negatives'
    path=ROOT/'data/annotations/login-contexts-1001.json';path.write_text(json.dumps(base,ensure_ascii=False,indent=2),encoding='utf-8')
    print(prepare(path,ROOT/'data/processed/login-contexts-1001',base['classes'],True))

if __name__=='__main__':main()
