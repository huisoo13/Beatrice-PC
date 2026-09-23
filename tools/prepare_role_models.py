"""기존 학습 라벨과 분류 헤드를 캐릭터/던전 역할별로 분리합니다."""
import copy,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import torch
    from ultralytics import YOLO
    from tools.train_dungeon_panel import prepare
    source=json.loads((ROOT/'data/annotations/ui-live-name.json').read_text(encoding='utf-8'))
    for role,indices,weights in [('character',list(range(5)),'models/ui-menu-recovery.pt'),('dungeon',[5,6],'models/ui-regions.pt')]:
        classes=[source['classes'][i] for i in indices]
        document=copy.deepcopy(source);document['classes']=classes
        document['evaluationPurpose']='training_reconstruction_only_not_independent'
        for item in document['images']:item['boxes']=[box for box in item['boxes'] if box['class'] in classes]
        manifest=ROOT/f'data/annotations/{role}-roles.json'
        manifest.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
        prepare(manifest,ROOT/f'outputs/{role}-roles-dataset',classes,reconstruction=True)
        model=YOLO(str(ROOT/weights));model.model.float();head=model.model.model[-1]
        # 동일한 클래스의 학습된 로짓을 보존하여 새 분류 헤드를 무작위로 초기화하지 않습니다.
        for name in ('cv3','one2one_cv3'):
            for branch in getattr(head,name):
                layer=branch[-1]
                layer.weight=torch.nn.Parameter(layer.weight[indices].detach().clone())
                layer.bias=torch.nn.Parameter(layer.bias[indices].detach().clone())
                layer.out_channels=len(indices)
        head.nc=len(indices);head.no=head.nc+head.reg_max*4
        model.model.yaml['nc']=head.nc
        model.model.names=dict(enumerate(classes))
        model.save(str(ROOT/f'outputs/{role}-roles-seed.pt'))
        config=dict(mode='yolo',weights=f'models/{role}-regions.pt',classes=classes,confidence=.7,imageSize=1280,nmsIou=.4)
        (ROOT/f'config/{role}-regions.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
        print(role,'prepared',flush=True)

if __name__=='__main__':main()
