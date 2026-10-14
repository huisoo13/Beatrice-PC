"""Compare reviewed label coverage and false-selection popup negatives."""
import argparse
import json
import sys
import shutil
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.ui_regions import UIRegionDetector
from evaluation_geometry import iou


def compare_names(manifest,items,baseline,rows):
    from beatrice.character_vision import CharacterVision
    from beatrice.ui_regions import get_box
    vision=CharacterVision();results=[]
    for index,item in enumerate(items):
        if not any(b['class']=='selected_character_name' for b in item['boxes']):continue
        image=cv2.imdecode(np.fromfile((manifest.parent/item['path']).resolve(),dtype=np.uint8),cv2.IMREAD_COLOR)
        readings=[]
        for report in (baseline,rows):
            box=get_box(report[index]['regions'],'selected_character_name')
            reading=vision.read_name(image,box) if box else {}
            readings.append(reading.get('accepted'))
        before,after=readings
        expected=item.get('ocrExpected',{}).get('selected_character_name') or (before or {}).get('text')
        results.append(dict(index=index,path=item['path'],before=before,after=after,expected=expected,
                            passed=not expected or bool(after and expected==after['text'])))
    return dict(total=len(results),regressionCount=sum(not r['passed'] for r in results),rows=results)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--weights',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--baseline',type=Path)
    parser.add_argument('--config',type=Path,default=ROOT/'config/character-regions.json')
    parser.add_argument('--compare-names',action='store_true')
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8'));config['weights']=args.weights
    detector=UIRegionDetector(config)
    manifest=ROOT/'data/annotations/character-false-positive-1014.json'
    doc=json.loads(manifest.read_text(encoding='utf-8'))
    baseline=json.loads(args.baseline.read_text(encoding='utf-8'))['rows'] if args.baseline else None
    rows=[];regressions=[];false_positives=[]
    for n,item in enumerate(doc['images']):
        path=(manifest.parent/item['path']).resolve()
        image=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
        regions=detector.locate(image)
        hits=[]
        for index,box in enumerate(item['boxes']):
            entry=regions.get(box['class'],{})
            candidates=entry.get('candidates',[]) or ([entry] if entry.get('status')=='detected' else [])
            if any(iou(c['xyxy'],box['xyxy'])>=.5 for c in candidates):hits.append(index)
        lost=sorted(set(baseline[n]['hits'])-set(hits)) if baseline else []
        if lost:regressions.append(dict(index=n,path=item['path'],lost=[item['boxes'][i]['class'] for i in lost]))
        negative=item.get('sessionId')=='false-selection-1014'
        popup_detections={k:v for k,v in regions.items() if k in ('selected_character_card','selected_character_name','game_start_button') and v.get('status')!='missing'}
        if negative and popup_detections:false_positives.append(dict(index=n,path=item['path'],detections=popup_detections))
        rows.append(dict(path=item['path'],hits=hits,regions=regions,negative=negative))
    result=dict(weights=args.weights,total=len(rows),labelHits=sum(len(r['hits']) for r in rows),
        negativeTotal=sum(r['negative'] for r in rows),falsePositiveCount=len(false_positives),
        regressionCount=len(regressions),regressions=regressions,falsePositives=false_positives,rows=rows,
        purpose='training_reconstruction_not_independent')
    session=Path('C:/Users/Huisoo/AppData/Local/BeatricePC/completion-diagnostics/20261014T084740Z-4d82e109')
    raw=ROOT/'data/raw/character-false-positive-1014'
    followups=[]
    for event in (209,2110):
        saved=raw/f'followup-{event}.jpg'
        if not saved.exists():shutil.copy2(session/f'event-{event:08d}.jpg',saved)
        original=cv2.imdecode(np.fromfile(saved,dtype=np.uint8),cv2.IMREAD_COLOR)
        for scale in (1,.75,1.25):
            for dim in (1,.75,.5,.35):
                frame=cv2.resize(np.clip(original*dim,0,255).astype(np.uint8),None,fx=scale,fy=scale)
                regions=detector.locate(frame)
                unexpected={k:v for k,v in regions.items() if k in ('selected_character_card','selected_character_name','game_start_button') and v.get('status')!='missing'}
                followups.append(dict(event=event,scale=scale,dim=dim,unexpected=unexpected))
    result.update(followups=followups,followupTotal=len(followups),followupFalsePositiveCount=sum(bool(r['unexpected']) for r in followups))
    if args.compare_names:
        if baseline is None:raise ValueError('이름 비교에는 baseline 보고서가 필요합니다.')
        result['nameComparison']=compare_names(manifest,doc['images'],baseline,rows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','falsePositives','regressions','followups')},ensure_ascii=False))


if __name__=='__main__':main()
