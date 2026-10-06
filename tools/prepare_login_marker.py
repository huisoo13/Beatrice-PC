"""Learn the moving luminous progress marker, excluding variable picture/text."""
import json,random
from pathlib import Path
from PIL import Image,ImageDraw,ImageEnhance
from train_dungeon_panel import prepare
ROOT=Path(__file__).resolve().parents[1]

def main():
    rng=random.Random(10013)
    base=json.loads((ROOT/'data/annotations/login-contexts-1001.json').read_text(encoding='utf-8'))
    rows=[r for r in base['images'] if not any(b['class']=='loading_progress' for b in r['boxes'])]
    raw=ROOT/'data/raw/login-marker-1001';raw.mkdir(parents=True,exist_ok=False)
    source=Image.open(ROOT/'outputs/initial-login/evidence/frame-155.jpg').convert('RGB').resize((2048,857))
    marker=source.crop((592,802,673,842))
    track=source.crop((800,809,1700,834)).resize((1435,25))
    body=source.crop((310,810,540,833))
    backgrounds=[source.crop((0,0,2048,750)),Image.open(ROOT/'outputs/initial-login/evidence/frame-160.jpg').convert('RGB')]
    for i in range(72):
        canvas=backgrounds[i%2].resize((2048,857)) if i%3 else Image.new('RGB',(2048,857),(rng.randrange(100),rng.randrange(100),rng.randrange(100)))
        if i>=56:
            canvas=source.copy();ImageDraw.Draw(canvas).rectangle((0,800,2048,857),fill='black')
        bar=Image.new('RGB',(1435,46));bar.paste(track,(0,7))
        progress=rng.randrange(85,1380)
        bar.paste(body.resize((progress-25,23)),(0,8));bar.paste(marker,(progress-60,0))
        scale=rng.uniform(.6,1.25) if i<56 else 1
        patch=bar.resize((round(bar.width*scale),round(bar.height*scale)))
        patch=ImageEnhance.Brightness(patch).enhance(rng.uniform(.75,1.15))
        x=rng.randrange(2048-patch.width);y=rng.randrange(857-patch.height)
        if i>=56:x,y=303,802
        canvas.paste(patch,(x,y))
        box=[x+round((progress-60)*scale),y,x+round((progress+21)*scale),y+round(40*scale)]
        p=raw/f'marker-{i:03}.png';canvas.save(p)
        rows.append(dict(path='../raw/login-marker-1001/'+p.name,split='train',sessionId='login-marker-1001',synthetic=True,boxes=[{'class':'loading_progress','xyxy':box}]))
    base['images']=rows;base['annotationMethod']+='; loading_progress is luminous moving marker, not the long empty track'
    p=ROOT/'data/annotations/login-marker-1001.json';p.write_text(json.dumps(base,ensure_ascii=False,indent=2),encoding='utf-8')
    print(prepare(p,ROOT/'data/processed/login-marker-1001',base['classes'],True))

if __name__=='__main__':main()
