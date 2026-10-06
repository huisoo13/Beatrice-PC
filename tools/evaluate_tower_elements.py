"""Compare child detector geometry on the existing reviewed reconstruction corpus."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--weights',required=True);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--title-confidence',type=float);args=p.parse_args()
    import cv2,numpy as np,torch
    from beatrice.ui_regions import UIRegionDetector
    torch.set_num_threads(2)
    cfg=json.loads((ROOT/'config/dungeon-elements.json').read_text(encoding='utf-8'))
    candidate=dict(cfg,weights=args.weights,classConfidence=dict(cfg.get('classConfidence',{})))
    if args.title_confidence is not None:candidate['classConfidence']['dungeon_name']=args.title_confidence
    models=[UIRegionDetector(cfg),UIRegionDetector(candidate)]
    doc=json.loads((ROOT/'data/annotations/dungeon-elements-0926.json').read_text(encoding='utf-8'))
    rows=[]
    for row in doc['images']:
        frame=cv2.imdecode(np.fromfile(ROOT/'data/annotations'/row['path'],dtype=np.uint8),cv2.IMREAD_COLOR)
        errors=[]
        for model in models:
            regions=model.locate(frame);fail=[]
            for kind in cfg['classes']:
                expected=sorted((b['xyxy'] for b in row['boxes'] if b['class']==kind),key=lambda b:b[0])
                actual=sorted((b['xyxy'] for b in regions[kind]['candidates']),key=lambda b:b[0])
                if len(expected)!=len(actual):fail.append(kind+':count');continue
                for a,b in zip(expected,actual):
                    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
                    if inter/union<.5:fail.append(kind+':bounds')
            errors.append(fail)
        rows.append(dict(path=row['path'],baselineErrors=errors[0],candidateErrors=errors[1]))
    report=dict(total=len(rows),baselinePassed=sum(not r['baselineErrors'] for r in rows),candidatePassed=sum(not r['candidateErrors'] for r in rows),regressions=sum(not r['baselineErrors'] and bool(r['candidateErrors']) for r in rows),rows=rows)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print({k:v for k,v in report.items() if k!='rows'})


if __name__=='__main__':main()
