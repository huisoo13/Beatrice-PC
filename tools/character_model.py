"""승인한 캐릭터 영역의 YOLO26n 기능 학습. 독립 평가 데이터는 아직 없습니다."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for key, folder in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib')]:
    os.environ.setdefault(key, str(ROOT/'outputs'/folder))
    Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
ROIS = {'portrait': (900, 850, 1140, 960), 'dialog': (1440, 560, 2000, 880)}
DATA = ROOT/'data/character-regions-first'


def prepare():
    from PIL import Image
    import yaml
    doc = json.loads((ROOT/'data/annotations/character-review-v1.json').read_text())
    if doc['reviewStatus'] != 'approved':
        raise ValueError('라벨 승인이 필요합니다.')
    for folder in ['images', 'labels']:
        (DATA/folder).mkdir(parents=True, exist_ok=True)
    for item in doc['images']:
        source = ROOT/item['path']
        if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('원본 해시가 다릅니다.')
        im = Image.open(source)
        if im.size != (3440,1440):
            raise ValueError('현재는 3440x1440 전용입니다.')
        for region, (l,t,r,b) in ROIS.items():
            lines=[]
            for box in item['boxes']:
                if (box['class']=='current_name') != (region=='portrait'):
                    continue
                x1,y1,x2,y2=box['xyxy']
                if not(l<=x1<x2<=r and t<=y1<y2<=b):
                    raise ValueError('박스가 ROI를 벗어납니다.')
                values=[((x1+x2)/2-l)/(r-l),((y1+y2)/2-t)/(b-t),(x2-x1)/(r-l),(y2-y1)/(b-t)]
                lines.append(str(doc['classes'].index(box['class']))+' '+' '.join(f'{v:.9f}' for v in values))
            key=item['id']+'_'+region
            im.crop((l,t,r,b)).save(DATA/'images'/f'{key}.png')
            (DATA/'labels'/f'{key}.txt').write_text('\n'.join(lines)+('\n' if lines else ''))
    (DATA/'dataset.yaml').write_text(yaml.safe_dump(dict(path=str(DATA),train='images',val='images',names=doc['classes'])))
    (DATA/'manifest.json').write_text(json.dumps(dict(rois=ROIS,purpose='training_reconstruction_not_independent_evaluation',images=doc['images']),ensure_ascii=False,indent=2))
    print('원본 6장 → 부분 이미지 12장, 12박스 준비. train=val: 기능 확인 전용.')


def train(epochs):
    import torch
    torch.set_num_threads(4)
    from ultralytics import YOLO
    YOLO(str(ROOT/'models/yolo26n.pt')).train(data=str(DATA/'dataset.yaml'),epochs=epochs,imgsz=640,batch=3,nbs=3,
        device='cpu',workers=0,project=str(ROOT/'outputs/training'),name='character-regions-v2',exist_ok=False,
        seed=42,optimizer='AdamW',lr0=.001,patience=0,freeze=10,mosaic=0,mixup=0,fliplr=0,flipud=0,
        degrees=0,shear=0,perspective=0,translate=.02,scale=.1,hsv_h=0,hsv_s=.1,hsv_v=.15,
        plots=False,val=False,amp=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','train'])
    parser.add_argument('--epochs',type=int,default=80)
    args=parser.parse_args()
    prepare() if args.command=='prepare' else train(args.epochs)
