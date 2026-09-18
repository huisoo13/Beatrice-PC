"""수작업 정답 초안 JSON을 렌더링합니다. 탐지 모델을 실행하지 않습니다."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
COLORS = {'진행중': '#50c9ff', '완료': '#80ed99', '진행 전': '#ffc766'}


def render(annotation, output, font_path):
    data = json.loads(annotation.read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(font_path), 25)
    title_font = ImageFont.truetype(str(font_path), 30)
    small = ImageFont.truetype(str(font_path), 21)
    cards = []
    for item in data['images']:
        original = Image.open(ROOT / item['path']).convert('RGB')
        if original.size != (item['width'], item['height']):
            raise ValueError(f"이미지 크기 불일치: {item['id']}")
        # 원본은 수정하지 않고 화면 왼쪽 위를 3배 확대합니다.
        crop = (40, 100, 340, 240)
        scale = 3
        card = Image.new('RGB', (1000, 560), '#101820')
        card.paste(original.crop(crop).resize((900, 420)), (50, 90))
        draw = ImageDraw.Draw(card)
        draw.text((30, 16), f"{item['id']}  {item['title']}", font=title_font, fill='white')
        draw.text((30, 56), '수작업 라벨 초안 · 모델 탐지 결과 아님 · 원본 영역 3배 확대', font=small, fill='#c3ced8')
        for box in item['boxes']:
            x1,y1,x2,y2 = box['xyxy']
            if not (0 <= x1 < x2 <= original.width and 0 <= y1 < y2 <= original.height):
                raise ValueError('잘못된 박스 좌표')
            state = box['state']
            if state not in data['classes']:
                raise ValueError('알 수 없는 상태')
            rect = ((x1-crop[0])*scale+50, (y1-crop[1])*scale+90,
                    (x2-crop[0])*scale+50, (y2-crop[1])*scale+90)
            color = COLORS[state]
            draw.rectangle(rect, outline=color, width=3)
            label = f"{box['gate']}관문 · {state}"
            width = draw.textbbox((0,0),label,font=font)[2]
            tx = (rect[0]+rect[2]-width)/2
            ty = 390
            draw.line(((rect[0]+rect[2])/2,rect[3],(rect[0]+rect[2])/2,ty-4),fill=color,width=2)
            draw.rectangle((tx-5,ty-3,tx+width+5,ty+35),fill='#101820')
            draw.text((tx,ty),label,font=font,fill=color)
        counts = {state: sum(b['state']==state for b in item['boxes']) for state in data['classes']}
        summary = ' / '.join(f'{s} {n}개' for s,n in counts.items())
        draw.rectangle((0, 510, 1000, 560), fill='#101820')
        draw.text((30,521),summary,font=font,fill='white')
        card.save(output / f"{item['id']}.png")
        cards.append(card)
    sheet = Image.new('RGB',(1000,560*len(cards)),'#101820')
    for index,card in enumerate(cards):
        sheet.paste(card,(0,index*560))
    sheet.save(output/'review-sheet.png')
    print(f"{len(cards)}개 이미지, {sum(len(i['boxes']) for i in data['images'])}개 박스 렌더링: {output}")


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations',type=Path,default=ROOT/'data/annotations/review-v1.json')
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/label-review')
    parser.add_argument('--font',type=Path,required=True,help='한국어를 지원하는 TTF/TTC 글꼴')
    args=parser.parse_args()
    render(args.annotations,args.output,args.font)
