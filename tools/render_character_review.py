"""캐릭터 인식 영역 수작업 초안 렌더링. YOLO/OCR 예측이 아닙니다."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
COLORS={'current_name':'#73e6a4','target_name':'#ffc76a','switch_dialog':'#66beff'}
LABELS={'current_name':'현재 이름 영역','target_name':'변경 대상 이름 영역','switch_dialog':'변경 확인창'}

def main():
 data=json.loads((ROOT/'data/annotations/character-review-v1.json').read_text())
 out=ROOT/'outputs/character-label-review';out.mkdir(parents=True,exist_ok=True)
 font=ImageFont.truetype('/System/Library/Fonts/AppleSDGothicNeo.ttc',23)
 small=ImageFont.truetype('/System/Library/Fonts/AppleSDGothicNeo.ttc',20)
 cards=[]
 for item in data['images']:
  original=Image.open(ROOT/item['path']).convert('RGB')
  card=Image.new('RGB',(1240,760),'#101820');draw=ImageDraw.Draw(card)
  draw.text((20,12),item['id']+'  '+item['title'],font=font,fill='white')
  draw.text((20,48),'수작업 라벨 초안 · 모델/OCR 결과 아님',font=small,fill='#ced5dd')
  crop=(760,325,2840,1065);scale=1200/(crop[2]-crop[0]);img=original.crop(crop).resize((1200,round((crop[3]-crop[1])*scale)));card.paste(img,(20,90));draw=ImageDraw.Draw(card)
  for box in item['boxes']:
   x1,y1,x2,y2=box['xyxy'];assert 0<=x1<x2<=3440 and 0<=y1<y2<=1440
   color=COLORS[box['class']];rect=((x1-crop[0])*scale+20,(y1-crop[1])*scale+90,(x2-crop[0])*scale+20,(y2-crop[1])*scale+90)
   draw.rectangle(rect,outline=color,width=3)
   if box['class']=='switch_dialog':draw.text((rect[0],rect[1]-27),LABELS[box['class']],font=small,fill=color,stroke_width=1,stroke_fill='black')
  for column,role in enumerate(['current_name','target_name']):
   found=[b for b in item['boxes'] if b['class']==role]
   x=20+column*600
   if not found:
    draw.text((x,555),'변경 확인창 없음',font=font,fill='#ced5dd');continue
   b=found[0];x1,y1,x2,y2=b['xyxy'];context=(x1-25,y1-20,x2+25,y2+30)
   zoom=original.crop(context).resize(((context[2]-context[0])*3,(context[3]-context[1])*3))
   zoom.thumbnail((570,190));card.paste(zoom,(x,560));draw=ImageDraw.Draw(card)
   factor=zoom.width/(context[2]-context[0]);draw.rectangle((x+25*factor,560+20*factor,x+(x2-context[0])*factor,560+(y2-context[1])*factor),outline=COLORS[role],width=3)
   draw.text((x,527),f"{LABELS[role]} · 정답 초안: {b['text']}",font=small,fill=COLORS[role])
  card.save(out/(item['id']+'.png'));cards.append(card)
 for start in range(0,len(cards),3):
  sheet=Image.new('RGB',(1240,760*len(cards[start:start+3])))
  for j,card in enumerate(cards[start:start+3]):sheet.paste(card,(0,j*760))
  sheet.save(out/f'page{start//3+1}.png')
 print(f'{len(cards)}장 라벨 렌더링 완료')
if __name__=='__main__':main()
