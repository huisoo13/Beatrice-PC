"""Compare retained panel detections before/after removing obsolete classes."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--weights',required=True);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2,numpy as np,torch
    torch.set_num_threads(2)
    from beatrice.ui_regions import UIRegionDetector
    cfg=json.loads((ROOT/'config/dungeon-regions.json').read_text(encoding='utf-8'));cfg.pop('elementConfig',None)
    baseline=UIRegionDetector(cfg)
    clean=dict(cfg,weights=args.weights,classes=['dungeon_panel','gateless_raid_panel'])
    candidate=UIRegionDetector(clean)
    manifest=json.loads((ROOT/'data/annotations/dungeon-parents-clean-0929.json').read_text(encoding='utf-8'))
    rows=[]
    def inspect(regions,boxes):
        errors=[]
        for kind in clean['classes']:
            expected=[b['xyxy'] for b in boxes if b['class']==kind];entry=regions.get(kind,{})
            if not expected:
                if entry.get('status')!='missing':errors.append(kind+':unexpected')
            elif entry.get('status')!='detected':errors.append(kind+':missing_or_ambiguous')
            else:
                a=expected[0];b=entry['xyxy'];intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
                if intersection/union<.5:errors.append(kind+':bounds')
        return errors
    for i,row in enumerate(manifest['images']):
        frame=cv2.imdecode(np.fromfile(ROOT/'data/annotations'/row['path'],dtype=np.uint8),cv2.IMREAD_COLOR)
        old=inspect(baseline.locate(frame),row['boxes']);new=inspect(candidate.locate(frame),row['boxes'])
        rows.append(dict(index=i,path=row['path'],baselineErrors=old,candidateErrors=new,regression=not old and bool(new)))
        if new:print(i,new,flush=True)
    report=dict(total=len(rows),baselinePassed=sum(not r['baselineErrors'] for r in rows),candidatePassed=sum(not r['candidateErrors'] for r in rows),regressions=sum(r['regression'] for r in rows),rows=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:v for k,v in report.items() if k!='rows'})
    if report['regressions']:raise SystemExit(1)

if __name__=='__main__':main()
