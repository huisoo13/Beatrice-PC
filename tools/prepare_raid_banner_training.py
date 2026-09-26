"""보존된 실제 진단과 기존 라벨로 완료 배너·무관문 레이드 재현 학습 세트를 구성합니다."""
import copy,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    document=json.loads((ROOT/'data/annotations/dungeon-completion-v2-0923.json').read_text(encoding='utf-8'))
    document['classes']+=['quest_complete_banner','gateless_raid_panel']
    banner=dict(class_='quest_complete_banner',xyxy=[1300,35,2150,290])
    banner={'class':banner['class_'],'xyxy':banner['xyxy']}
    for item in document['images']:
        if Path(item['path']).name in ('completion-216.jpg','completion-218.jpg','completion-219.jpg','negative-260910_213142.png'):
            item['boxes'].append(copy.deepcopy(banner))
    raw=ROOT/'data/raw/raid-banner-0924';raw.mkdir(parents=True,exist_ok=True)
    def add(folder,slot,name,labels):
        source=ROOT/'outputs'/folder/f'frame-{slot:03d}.jpg';target=raw/(name+'.jpg')
        shutil.copyfile(source,target)
        document['images'].append(dict(path='../raw/raid-banner-0924/'+target.name,
            sessionId=folder,split='train',boxes=labels))
    panel={'class':'gateless_raid_panel','xyxy':[0,45,405,125]}
    for slot in (11,40,75,100,108,110,112,120,140,0):
        add('state-failure-0923',slot,f'gateless-{slot}',[copy.deepcopy(panel)]+([copy.deepcopy(banner)] if slot in (110,112) else []))
    for slot in (0,12,24,27,29,31):
        add('normal-quest-review-0924',slot,f'normal-{slot}',[copy.deepcopy(banner)] if slot in (27,29) else [])
    for slot in (133,175,1,31,80,121,127):
        add('exception-completion-0924',slot,f'excluded-{slot}',[])
    # 새 클래스 학습 후 기존 1막 패널의 신뢰도가 떨어진 재현 사례를 보완합니다.
    for slot in (68,71):
        add('live-dungeon-failure',slot,f'act1-{slot}',[
            {'class':'dungeon_panel','xyxy':[0,36,360,240]},
            {'class':'gate_panel','xyxy':[32,112,320,200]}])
    # 아래 목표/도전 과제 내용은 가변 영역입니다. 헤더 라벨에 포함하지 않습니다.
    from PIL import Image,ImageDraw
    for slot in (40,75,108,110):
        source=raw/f'gateless-{slot}.jpg'
        for variant in range(2):
            image=Image.open(source);draw=ImageDraw.Draw(image)
            draw.rectangle((5,145,400,355),fill=(15,18,23))
            if variant:
                for y in (180,230,280):draw.rectangle((30,y,360,y+12),fill=(70,80,95))
            target=raw/f'gateless-{slot}-variable-{variant}.png';image.save(target)
            document['images'].append(dict(path='../raw/raid-banner-0924/'+target.name,
                sessionId='state-failure-0923',split='train',synthetic=True,
                boxes=[copy.deepcopy(panel)]+([copy.deepcopy(banner)] if slot==110 else [])))
    out=ROOT/'data/annotations/raid-banner-header-v2-0924.json'
    out.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    from train_dungeon_panel import prepare
    print(prepare(out,ROOT/'data/datasets/raid-banner-header-v2-0924',document['classes'],True))

if __name__=='__main__':main()
