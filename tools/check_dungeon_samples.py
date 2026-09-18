"""제공된 정지 이미지 OCR을 정답 전사와 비교하고 결과를 시각화합니다."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.dungeon import DungeonOCR


def main():
    import cv2
    from PIL import Image,ImageDraw,ImageFont
    ocr=DungeonOCR();rows=[];cards=[]
    expected=[('고통의 마녀, 세르카','하드'),('종막 : 최후의 날','노말'),('서막 : 붉어진 백야의 나선','하드'),('1막 : 대지를 부수는 업화의 궤적','노말')]+[('어둠군단장 카멘','하드')]*3
    font=ImageFont.truetype('/System/Library/Fonts/AppleSDGothicNeo.ttc',20)
    for i,truth in enumerate(expected,1):
        path=ROOT/f'data/raw/SAMPLE_{i:03d}.jpg';frame=cv2.imread(str(path));obs=ocr.analyze(frame)
        actual=[obs[field]['text'] if obs[field] else None for field in ['dungeonName','difficulty']]
        rows.append(dict(source=str(path),expected=dict(zip(['dungeonName','difficulty'],truth)),observation=obs,exactName=actual[0]==truth[0],exactDifficulty=actual[1]==truth[1]))
        card=Image.new('RGB',(1100,230),'#14202c');image=Image.open(path).crop((20,50,360,125)).resize((1020,150));card.paste(image,(10,5))
        draw=ImageDraw.Draw(card);draw.text((10,155),f"SAMPLE_{i:03d} | 이름: {actual[0] or '미확정'} | 난이도: {actual[1] or '미확정'}",font=font,fill='white')
        draw.text((10,190),'원본 화면의 글자와 OCR 결과를 비교하세요. 미확정은 원문 보존.',font=font,fill='#c0ccd8');cards.append(card)
    out=ROOT/'outputs/dungeon-samples';out.mkdir(parents=True,exist_ok=True)
    report=dict(purpose='development_samples_not_independent_evaluation',nameCorrect=sum(r['exactName'] for r in rows),difficultyCorrect=sum(r['exactDifficulty'] for r in rows),total=len(rows),rows=rows)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    sheet=Image.new('RGB',(1100,230*len(cards)))
    for i,card in enumerate(cards):sheet.paste(card,(0,i*230))
    sheet.save(out/'preview.jpg');print({k:v for k,v in report.items() if k!='rows'})

if __name__=='__main__':main()
