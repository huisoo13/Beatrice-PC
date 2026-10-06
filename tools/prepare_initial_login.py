"""오프라인 전체 화면 라벨 생성. 좌표는 원본 주석이며 런타임에 사용하지 않습니다."""
import hashlib
import json
from pathlib import Path
from PIL import Image,ImageFilter
from train_dungeon_panel import prepare

ROOT=Path(__file__).resolve().parents[1]
def main():
    base=json.loads((ROOT/'data/annotations/character-variable-switch-0928.json').read_text(encoding='utf-8'))
    classes=base['classes']+['server_table','selected_character_card','selected_character_name','game_start_button','loading_progress']
    raw=ROOT/'data/raw/initial-login-0930-v2';raw.mkdir(parents=True,exist_ok=True)
    shots=Path('C:/Program Files (x86)/Smilegate/Games/LOSTARK/EFGame/Screenshots')
    specs=[(shots/'Screenshot_260930_135351.jpg',[('server_table',[745,385,1305,777])]),
           (shots/'Screenshot_260930_135402.jpg',[('selected_character_card',[642,709,823,758]),
              ('selected_character_name',[684,722,731,741]),('game_start_button',[857,784,1023,828])]),
           (ROOT/'outputs/initial-login/evidence/frame-155.jpg',[('loading_progress',[300,744,1740,837])]),
           (ROOT/'outputs/initial-login/evidence/frame-160.jpg',[])]
    images=base['images'][:]
    for index,(source,spec) in enumerate(specs):
        im=Image.open(source).convert('RGB');w,h=im.size
        boxes=[{'class':k,'xyxy':[round(v*w/2048) for v in coords]} for k,coords in spec]
        for variant in range(8):
            canvas=im.copy()
            if variant%2:
                canvas=im.filter(ImageFilter.GaussianBlur(40))
                for box in boxes:canvas.paste(im.crop(box['xyxy']),box['xyxy'][:2])
            factor=[1,.8,.65,.9][variant//2]
            scaled=canvas.resize((round(w*factor),round(h*factor)))
            canvas=Image.new('RGB',(w,h),(24,24,24))
            x=round((w-scaled.width)*(.2 if variant%2 else .8));y=round((h-scaled.height)*.5)
            canvas.paste(scaled,(x,y))
            path=raw/f'sample-{index}-{variant}.png';canvas.save(path)
            labels=[{'class':b['class'],'xyxy':[round(b['xyxy'][0]*factor+x),round(b['xyxy'][1]*factor+y),
                         round(b['xyxy'][2]*factor+x),round(b['xyxy'][3]*factor+y)]} for b in boxes]
            images.append(dict(path='../raw/initial-login-0930-v2/'+path.name,split='train',sessionId='initial-login-0930',
                source=str(source),synthetic=variant!=0,boxes=labels,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if index==1:
            # 실제 탐지 카드 전체를 재검사하는 학습 경로. OCR 하위 영역은 다시 YOLO가 찾는다.
            parent=boxes[0]['xyxy'];line=boxes[1]['xyxy'];card=im.crop(parent)
            for n,factor in enumerate((1,1.5,2,3,4,5)):
                zoom=card.resize((round(card.width*factor),round(card.height*factor)))
                path=raw/f'card-{n}.png';zoom.save(path)
                coords=[round((line[0]-parent[0])*factor),round((line[1]-parent[1])*factor),
                        round((line[2]-parent[0])*factor),round((line[3]-parent[1])*factor)]
                images.append(dict(path='../raw/initial-login-0930-v2/'+path.name,split='train',sessionId='initial-login-0930',
                    synthetic=True,boxes=[{'class':'selected_character_name','xyxy':coords}]))
    doc=dict(classes=classes,images=images,evaluationPurpose='training_reconstruction_only_not_independent',
             annotationMethod='visual annotations plus existing labels; background blur, translation and scale augmentation')
    manifest=ROOT/'data/annotations/character-initial-login-0930-v2.json'
    manifest.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    print(prepare(manifest,ROOT/'data/processed/character-initial-login-0930-v2',classes,True))

if __name__=='__main__':main()
