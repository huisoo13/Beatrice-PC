"""학습 이미지 재현 검사와 OCR 결과 미리보기. 독립 정확도 평가가 아닙니다."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.character_vision import CharacterVision


def iou(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
    return area/union if union else 0


def main():
    import cv2
    from PIL import Image,ImageDraw,ImageFont
    model=CharacterVision()
    font=ImageFont.truetype('/System/Library/Fonts/AppleSDGothicNeo.ttc',22)
    doc=json.loads((ROOT/'data/annotations/character-review-v1.json').read_text())
    out=ROOT/'outputs/character-recognition';out.mkdir(parents=True,exist_ok=True)
    rows=[];cards=[]
    for item in doc['images']:
        frame=cv2.imread(str(ROOT/item['path']))
        result=model.analyze(frame)
        remaining=list(result['detections']);matched=0
        for truth in item['boxes']:
            candidates=[d for d in remaining if d['kind']==truth['class'] and iou(d['xyxy'],truth['xyxy'])>=.5]
            if candidates:
                best=max(candidates,key=lambda d:iou(d['xyxy'],truth['xyxy']))
                remaining.remove(best);matched+=1
        row=dict(id=item['id'],expected=len(item['boxes']),matched=matched,extras=len(remaining),observation=result)
        rows.append(row)
        card=Image.new('RGB',(1050,330),'#17202d');draw=ImageDraw.Draw(card)
        draw.text((15,10),f"{item['id']} {item['title']} | 박스 {matched}/{len(item['boxes'])}",font=font,fill='white')
        original=Image.open(ROOT/item['path'])
        for index,(kind,field,region) in enumerate([('current_name','currentName',(940,875,1090,950)),('target_name','targetName',(1645,635,1795,710))]):
            tile=original.crop(region).resize((450,225));td=ImageDraw.Draw(tile)
            for detection in result['detections']:
                if detection['kind']==kind:
                    x1,y1,x2,y2=detection['xyxy'];td.rectangle(((x1-region[0])*3,(y1-region[1])*3,(x2-region[0])*3,(y2-region[1])*3),outline='#49efad',width=3)
            card.paste(tile,(15+index*520,48))
            value=result[field]
            text=f"{value['text']} ({value['confidence']:.2f})" if value else '읽기 보류 / 영역 없음'
            if value and value['confidence'] < .65:
                text='보류: '+text
            draw.text((15+index*520,280),('현재: ' if index==0 else '대상: ')+text,font=font,fill='white')
        cards.append(card)
    report=dict(purpose='training_reconstruction_only',rows=rows,
                matched=sum(r['matched'] for r in rows),expected=sum(r['expected'] for r in rows),extras=sum(r['extras'] for r in rows))
    (out/'training-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    preview=Image.new('RGB',(2100,990))
    for i,card in enumerate(cards):preview.paste(card,((i%2)*1050,(i//2)*330))
    preview.save(out/'training-preview.jpg')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
