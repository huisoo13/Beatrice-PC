"""사용자가 제공한 화면 및 보존된 승인 라벨로 현재 해상도 재현 학습을 준비합니다.

합성 이미지는 명시적으로 표시하며 독립 평가 데이터로 사용하지 않습니다.
"""
import json
import hashlib
from pathlib import Path
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
SCREENSHOTS=Path('C:/Program Files (x86)/Smilegate/Games/LOSTARK/EFGame/Screenshots')
DEST=ROOT/'data/raw/ui-bootstrap'
CLASSES=json.loads((ROOT/'config/ui-regions.json').read_text(encoding='utf-8'))['classes']
MENU=[780,320,2820,1050]
CURRENT=[780,893,1210,932]


def main():
    DEST.mkdir(parents=True,exist_ok=True)
    items=[];cards=[]
    def add(key,image,boxes,source,session,synthetic=False):
        path=DEST/(key+'.png');image.save(path)
        items.append(dict(path='../raw/ui-bootstrap/'+path.name,split='train',sessionId=session,
            source=source,synthetic=synthetic,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),boxes=boxes))
        preview=image.copy();draw=ImageDraw.Draw(preview)
        for box in boxes:
            draw.rectangle(box['xyxy'],outline='lime',width=4)
            draw.text((box['xyxy'][0],box['xyxy'][1]),box['class'],fill='lime')
        preview.thumbnail((688,288));card=Image.new('RGB',(688,315));card.paste(preview);ImageDraw.Draw(card).text((5,293),key,fill='white');cards.append(card)
    def box(name,coords):return {'class':name,'xyxy':coords}
    for key in ('260916_172657','260916_172713','260921_134229','260921_134230'):
        source=SCREENSHOTS/f'Screenshot_{key}.jpg';image=Image.open(source).convert('RGB')
        boxes=[box('game_menu',MENU),box('current_name_line',CURRENT)]
        if key=='260916_172713':
            boxes += [box('switch_dialog',[1470,586,1970,850]),box('target_name_line',[1530,651,1910,691])]
        if key.startswith('260921'):
            boxes += [box('loading_indicator',[2990,1270,3440,1440])]
        add(key,image,boxes,str(source),key[:6])
    # 보존된 잘라낸 이미지를 전체 화면에 재배치합니다. 독립 원본은 아닙니다.
    annotations=json.loads((ROOT/'data/annotations/character-review-v1.json').read_text(encoding='utf-8'))
    for item in annotations['images']:
        image=Image.open(SCREENSHOTS/'Screenshot_260916_172657.jpg').convert('RGB')
        crop=Image.open(ROOT/f"data/character-first/images/{item['id']}.png").convert('RGB')
        image.paste(crop,(800,550))
        boxes=[box('game_menu',MENU),box('current_name_line',CURRENT)]
        for original in item['boxes']:
            if original['class']=='switch_dialog':boxes.append(box('switch_dialog',original['xyxy']))
            elif original['class']=='target_name':boxes.append(box('target_name_line',[1530,651,1910,691]))
        add('reconstructed-'+item['id'],image,boxes,item['path'],item['sessionId'],True)
    source=Path('C:/Users/Huisoo/AppData/Local/Temp/codex-clipboard-da8e40b4-9941-45e2-a977-a98a56ff3f5c.png')
    image=Image.open(source).convert('RGB').crop((0,480,3440,1920))
    add('dungeon-single',image,[box('dungeon_panel',[0,36,360,240]),box('gate_panel',[32,112,352,224])],str(source),'dungeon-single')
    for key in ('260910_213151','260910_213142','260813_213601','260406_185131'):
        source=SCREENSHOTS/f'Screenshot_{key}.jpg'
        add('negative-'+key,Image.open(source).convert('RGB'),[],str(source),key[:6])
    manifest=dict(classes=CLASSES,annotationMethod='assistant_visual_review_and_existing_approved_labels',
        evaluationPurpose='training_reconstruction_only_not_independent',images=items)
    (ROOT/'data/annotations/ui-bootstrap.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    sheet=Image.new('RGB',(1376,315*((len(cards)+1)//2)))
    for i,card in enumerate(cards):sheet.paste(card,((i%2)*688,(i//2)*315))
    sheet.save(ROOT/'outputs/ui-bootstrap-labels.jpg')
    print(f'{len(items)} images; reconstruction only; 6 synthetic composites; review outputs/ui-bootstrap-labels.jpg')


if __name__=='__main__':main()
