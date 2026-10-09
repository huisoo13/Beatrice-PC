"""Compare existing element geometry and full-frame EX Hard gate recognition."""
import argparse,json
from pathlib import Path
import cv2,numpy as np
from beatrice.ui_regions import UIRegionDetector,detected_gates
ROOT=Path(__file__).resolve().parents[1]
def errors(row,regions,classes):
 fail=[]
 for kind in classes:
  wanted=sorted([b['xyxy'] for b in row['boxes'] if b['class']==kind],key=lambda b:b[0])
  found=sorted([b['xyxy'] for b in regions[kind]['candidates']],key=lambda b:b[0])
  if len(wanted)!=len(found):fail.append(kind+':count');continue
  for a,b in zip(wanted,found):
   inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
   union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
   if inter/union<.5:fail.append(kind+':bounds')
 return fail
def main():
 p=argparse.ArgumentParser();p.add_argument('--weights',required=True);p.add_argument('--baseline-weights');p.add_argument('--output',required=True,type=Path);args=p.parse_args()
 cfg=json.loads((ROOT/'config/dungeon-elements.json').read_text(encoding='utf-8'))
 baseline=dict(cfg,weights=args.baseline_weights) if args.baseline_weights else cfg
 models=[UIRegionDetector(baseline),UIRegionDetector(dict(cfg,weights=args.weights))]
 original=json.loads((ROOT/'data/annotations/dungeon-elements-tower-1006.json').read_text(encoding='utf-8'));rows=[]
 for row in original['images']:
  frame=cv2.imdecode(np.fromfile(ROOT/'data/annotations'/row['path'],dtype=np.uint8),cv2.IMREAD_COLOR)
  failures=[errors(row,m.locate(frame),cfg['classes']) for m in models]
  rows.append(dict(path=row['path'],baselineErrors=failures[0],candidateErrors=failures[1]))
 parents=[UIRegionDetector(json.loads((ROOT/'config/dungeon-regions.json').read_text(encoding='utf-8'))) for _ in models]
 for parent,child in zip(parents,models):parent.element_detector=child
 reviewed=json.loads((ROOT/'data/raw/exhard-gate-panel-1008/review.json').read_text(encoding='utf-8'));new=[]
 for row in reviewed['images']:
  image=cv2.imdecode(np.fromfile(ROOT/'data/annotations'/row['sourceParent'],dtype=np.uint8),cv2.IMREAD_COLOR)
  predictions=[];wanted=next(b['class'] for b in row['boxes'] if b['class'] in ['gate_in_progress','gate_completed'])
  expected='완료' if wanted=='gate_completed' else '진행중'
  for parent in parents:
   regions=parent.locate(image);gates=detected_gates(regions)
   predictions.append(dict(passed=len(gates)==1 and gates[0]['state']==expected,gates=gates,gatePanel=regions['gate_panel']))
  new.append(dict(path=row['sourceParent'],usage=row['usage'],baseline=predictions[0],candidate=predictions[1]))
 report=dict(purpose='reviewed_reconstruction_and_untrained_same_session_replay_not_independent',total=len(rows),baselinePassed=sum(not r['baselineErrors'] for r in rows),candidatePassed=sum(not r['candidateErrors'] for r in rows),regressions=sum(not r['baselineErrors'] and bool(r['candidateErrors']) for r in rows),newBaselinePassed=sum(r['baseline']['passed'] for r in new),newCandidatePassed=sum(r['candidate']['passed'] for r in new),newTotal=len(new),holdoutPassed=sum(r['candidate']['passed'] for r in new if r['usage']!='train'),holdoutTotal=sum(r['usage']!='train' for r in new),rows=rows,newRows=new)
 args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print({k:v for k,v in report.items() if k not in ['rows','newRows']})
 if report['regressions'] or report['newCandidatePassed']!=len(new):raise SystemExit('Model not ready for activation')
if __name__=='__main__':main()
