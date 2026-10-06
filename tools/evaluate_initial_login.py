"""Compare old character coverage and new login classes; reconstruction only."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))

def main():
    import cv2,numpy as np,torch
    torch.set_num_threads(4)
    from beatrice.ui_regions import UIRegionDetector
    parser=argparse.ArgumentParser();parser.add_argument('weights');parser.add_argument('--output',required=True);parser.add_argument('--baseline',action='store_true');parser.add_argument('--image-size',type=int);parser.add_argument('--config',default='config/character-regions.json');args=parser.parse_args()
    path=ROOT/'data/annotations/character-initial-login-0930.json'
    doc=json.loads(path.read_text(encoding='utf-8'))
    config=json.loads((ROOT/args.config).read_text(encoding='utf-8'))
    config.update(weights=args.weights,classes=doc['classes'][:5] if args.baseline else doc['classes'])
    if args.image_size:config['imageSize']=args.image_size
    detector=UIRegionDetector(config)
    rows=[]
    for item in doc['images']:
        source=(path.parent/item['path']).resolve()
        frame=cv2.imdecode(np.fromfile(source,dtype=np.uint8),cv2.IMREAD_COLOR)
        found=detector.locate(frame)
        expected=set(b['class'] for b in item['boxes'] if b['class'] in config['classes'])
        actual=set(k for k,v in found.items() if v['status']=='detected')
        rows.append(dict(path=item['path'],expected=sorted(expected),actual=sorted(actual),missing=sorted(expected-actual),extra=sorted(actual-expected),regions=found))
    result=dict(weights=args.weights,images=len(rows),passed=sum(not r['missing'] and not r['extra'] for r in rows),rows=rows)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
if __name__=='__main__':main()
