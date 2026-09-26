"""전체 게임 화면의 던전 패널 라벨을 검증하고 YOLO 학습 데이터를 만듭니다."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def prepare(manifest,destination,classes=None,reconstruction=False):
    from PIL import Image
    import yaml
    document=json.loads(manifest.read_text(encoding='utf-8'))
    classes=classes or ['dungeon_panel']
    if document.get('classes')!=classes or not document.get('images'):
        raise ValueError('설정과 같은 클래스 순서의 전체 화면 라벨이 필요합니다.')
    seen=set();sessions={};rows=[];positive={'train':0,'val':0};negative={'train':0,'val':0}
    coverage={split:set() for split in positive}
    for index,item in enumerate(document['images']):
        split=item['split'];session=item['sessionId']
        if split not in positive or not session:raise ValueError('train/val과 sessionId가 필요합니다.')
        if session in sessions and sessions[session]!=split:
            raise ValueError('같은 플레이 세션을 train/val로 나눌 수 없습니다.')
        sessions[session]=split
        source=(manifest.parent/item['path']).resolve()
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if digest in seen:raise ValueError('중복 이미지가 있습니다.')
        seen.add(digest)
        with Image.open(source) as im:w,h=im.size
        labels=[]
        for box in item['boxes']:
            if isinstance(box,dict):
                class_id=classes.index(box['class']);coords=box['xyxy']
            else:
                if len(classes)!=1:raise ValueError('통합 라벨에는 class와 xyxy를 지정해주세요.')
                class_id=0;coords=box
            if len(coords)!=4 or not all(math.isfinite(v) for v in coords):raise ValueError('박스 좌표 오류')
            x1,y1,x2,y2=coords
            if not 0<=x1<x2<=w or not 0<=y1<y2<=h:raise ValueError('박스가 원본을 벗어납니다.')
            labels.append(f'{class_id} {(x1+x2)/2/w:.9f} {(y1+y2)/2/h:.9f} {(x2-x1)/w:.9f} {(y2-y1)/h:.9f}')
            coverage[split].add(class_id)
        (positive if labels else negative)[split]+=1
        rows.append((index,split,source,labels,digest))
    if reconstruction:
        if positive['train']==0 or negative['train']==0 or len(coverage['train'])!=len(classes):
            raise ValueError('재현 학습에도 모든 클래스와 음성 학습 이미지가 필요합니다.')
        document['evaluationPurpose']='training_reconstruction_only_not_independent'
    elif not all(positive.values()) or not all(negative.values()):
        raise ValueError('train과 val 각각 던전 화면과 비던전 화면이 필요합니다.')
    if not reconstruction and any(len(values)!=len(classes) for values in coverage.values()):
        raise ValueError('train과 val 각각 모든 UI 클래스의 라벨이 필요합니다.')
    if destination.exists():raise ValueError('기존 데이터셋을 덮어쓰지 않습니다. 새 출력 경로를 지정해주세요.')
    for index,split,source,labels,digest in rows:
        image_dir=destination/'images'/split;label_dir=destination/'labels'/split
        image_dir.mkdir(parents=True,exist_ok=True);label_dir.mkdir(parents=True,exist_ok=True)
        with Image.open(source) as im:im.convert('RGB').save(image_dir/f'{index:05d}.png')
        (label_dir/f'{index:05d}.txt').write_text('\n'.join(labels),encoding='utf-8')
    (destination/'dataset.yaml').write_text(yaml.safe_dump(dict(path=str(destination.resolve()),
        train='images/train',val='images/train' if reconstruction else 'images/val',names=dict(enumerate(classes)))),encoding='utf-8')
    (destination/'manifest.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    return destination/'dataset.yaml'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('manifest',type=Path);prep.add_argument('--output',required=True,type=Path)
    prep.add_argument('--classes-config',type=Path,help='통합 UI 학습 시 config/ui-regions.json 지정')
    prep.add_argument('--reconstruction',action='store_true',help='학습 이미지 재현만 평가. 독립 정확도 평가가 아닙니다.')
    train=sub.add_parser('train');train.add_argument('dataset',type=Path)
    train.add_argument('--weights',required=True,type=Path);train.add_argument('--epochs',type=int,default=80)
    train.add_argument('--device',default='cpu');train.add_argument('--name',default='dungeon-panel')
    train.add_argument('--imgsz',type=int,default=1280);train.add_argument('--freeze',type=int,default=0)
    train.add_argument('--lr',type=float,default=.001)
    train.add_argument('--nominal-batch-size',type=int,default=64,help='Gradient accumulation target; use a smaller value for small direct-element datasets.')
    train.add_argument('--shuffle',action='store_true',help='Use square batches with shuffled samples instead of rectangular aspect sorting.')
    args=parser.parse_args()
    if args.command=='prepare':
        classes=json.loads(args.classes_config.read_text(encoding='utf-8'))['classes'] if args.classes_config else None
        print(prepare(args.manifest,args.output,classes,args.reconstruction));return
    if not args.weights.is_file() or not args.dataset.is_file():raise ValueError('로컬 모델과 데이터셋이 필요합니다.')
    for key,folder in [('YOLO_CONFIG_DIR','ultralytics-config'),('MPLCONFIGDIR','matplotlib')]:
        os.environ.setdefault(key,str(ROOT/'outputs'/folder))
        Path(os.environ[key]).mkdir(parents=True,exist_ok=True)
    from ultralytics import YOLO
    import torch
    torch.set_num_threads(4)
    YOLO(str(args.weights)).train(data=str(args.dataset.resolve()),epochs=args.epochs,imgsz=args.imgsz,
        batch=2,device=args.device,workers=0,project=str(ROOT/'outputs/training'),name=args.name,
        exist_ok=False,seed=42,fliplr=0,flipud=0,mosaic=0,mixup=0,degrees=0,
        translate=.08,scale=.15,plots=False,amp=False,freeze=args.freeze,optimizer='AdamW',lr0=args.lr,
        patience=0,val=False,hsv_h=0,hsv_s=.1,hsv_v=.1,rect=not args.shuffle,nbs=args.nominal_batch_size)


if __name__=='__main__':main()
