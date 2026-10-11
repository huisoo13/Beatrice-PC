"""Prepare reviewed chapter-title samples and replay actual YOLO/OCR geometry.

Coordinates below are training annotations, never runtime crop rules.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN = (19, 63, 75, 113)


def prepare(session, output):
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw
    from beatrice.ui_regions import UIRegionDetector
    from tools.train_dungeon_panel import prepare as dataset
    manifest = ROOT/'data/annotations/dungeon-elements-title-1011.json'
    if manifest.exists():raise ValueError('Existing reviewed annotations must not be overwritten')
    raw = ROOT/'data/raw/title-elements-1011'
    raw.mkdir(parents=True, exist_ok=True);output.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT/'config/dungeon-elements.json').read_text(encoding='utf-8'))
    detector = UIRegionDetector(config)
    doc = json.loads((ROOT/'data/annotations'/Path(config['trainingManifest']).name).read_text(encoding='utf-8'))
    doc['annotationMethod'] = 'Existing reviewed elements plus complete first-digit title annotations; brightness and resize augmentation'
    doc['evaluationPurpose'] = 'reconstruction_and_same_session_replay_not_independent'
    rows=[];preview=Image.new('RGB',(740,450*len(TRAIN)),'white');draw=ImageDraw.Draw(preview)
    for index, seq in enumerate(TRAIN):
        name=f'event-{seq:08d}';source=session/(name+'.jpg')
        report=json.loads((session/(name+'.json')).read_text(encoding='utf-8'))
        l,t,r,b=report['dungeon']['raidBounds']
        frame=cv2.imdecode(np.fromfile(source,dtype=np.uint8),cv2.IMREAD_COLOR)
        crop=frame[t:b,l:r];found=detector.locate(crop)
        boxes=[dict(class_=kind,xyxy=item['xyxy']) for kind,entry in found.items() for item in entry['candidates']]
        boxes=[{'class':v['class_'],'xyxy':v['xyxy']} for v in boxes if v['class_']!='dungeon_name']
        # Visually reviewed full title: includes narrow leading 1 and final glyph.
        title=[39-l,59-t,326-l,89-t]
        boxes.append({'class':'dungeon_name','xyxy':title})
        original=raw/(name+'.jpg');shutil.copy2(source,original)
        picture=Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB))
        annotated=picture.copy();ImageDraw.Draw(annotated).rectangle(title,outline='lime',width=2)
        preview.paste(annotated.resize((picture.width*2,picture.height*2)),(0,index*450+25))
        draw.text((0,index*450),name,fill='black')
        for brightness,scale in ((1,1),(.75,1),(.5,1),(.35,1),(1,.75),(.5,.75),(1,1.25)):
            image=Image.fromarray(np.clip(np.asarray(picture).astype(np.float32)*brightness,0,255).astype(np.uint8))
            image=image.resize((round(image.width*scale),round(image.height*scale)))
            path=raw/f'{name}-v{brightness}-s{scale}.png';image.save(path)
            scaled=[dict(bx,xyxy=[value*scale for value in bx['xyxy']]) for bx in boxes]
            row=dict(path='../raw/title-elements-1011/'+path.name,split='train',sessionId=session.name,
                boxes=scaled,sourceParent='../raw/title-elements-1011/'+original.name,
                brightness=brightness,scale=scale,synthetic=brightness!=1 or scale!=1,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            rows.append(row)
    preview.save(output/'review-labels.png');doc['images'].extend(rows)
    manifest.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    path=dataset(manifest,ROOT/'data/datasets/dungeon-elements-title-1011',doc['classes'],True)
    print(dict(images=len(doc['images']),added=len(rows),dataset=str(path)))


def evaluate(weights, session, output, baseline=None):
    import cv2
    import numpy as np
    from beatrice.ui_regions import UIRegionDetector, dungeon_location, detected_gates
    from beatrice.dungeon import DungeonOCR, key
    from tools.evaluate_exhard_elements import errors
    ocr=DungeonOCR()
    config=json.loads((ROOT/'config/dungeon-elements.json').read_text(encoding='utf-8'))
    configs=[dict(config,weights=str(baseline or config['weights'])),dict(config,weights=str(weights))]
    models=[UIRegionDetector(c) for c in configs]
    manifest=json.loads((ROOT/'data/annotations/dungeon-elements-exhard-reinforced-1008.json').read_text(encoding='utf-8'))
    old=[];chapters=[]
    for index,row in enumerate(manifest['images']):
        frame=cv2.imdecode(np.fromfile(ROOT/'data/annotations'/row['path'],dtype=np.uint8),cv2.IMREAD_COLOR)
        checks=[errors(row,m.locate(frame),config['classes']) for m in models]
        old.append(dict(path=row['path'],baselineErrors=checks[0],candidateErrors=checks[1]))
        if index in (0,36,37,72,73,74,75):
            wanted='2' if index==0 else '1' if index in (36,37) else '3'
            readings=[]
            for model in models:
                box=model.locate(frame)['dungeon_name'].get('xyxy')
                result=ocr.read_regions(frame,{'dungeonName':box}) if box else {}
                name=(result.get('dungeonName') or {}).get('text','')
                readings.append(dict(name=name,passed=key(name).startswith(wanted+'막')))
            chapters.append(dict(path=row['path'],chapter=wanted,baseline=readings[0],candidate=readings[1]))
    augmented=[]
    additions=json.loads((ROOT/'data/annotations/dungeon-elements-title-1011.json').read_text(encoding='utf-8'))
    for row in additions['images']:
        if 'title-elements-1011' not in row['path']:continue
        frame=cv2.imdecode(np.fromfile(ROOT/'data/annotations'/row['path'],dtype=np.uint8),cv2.IMREAD_COLOR)
        regions=models[1].locate(frame)
        wanted=next(b['xyxy'] for b in row['boxes'] if b['class']=='dungeon_name')
        found=regions['dungeon_name'].get('xyxy')
        # Check actual bright glyph edges, not empty annotation margins or IoU.
        # Brightness here is known synthetic training metadata, not runtime logic.
        l,t,r,b=map(round,wanted)
        gray=cv2.cvtColor(frame[t:b,l:r],cv2.COLOR_BGR2GRAY)
        points=cv2.findNonZero(cv2.threshold(gray,130*row['brightness'],255,cv2.THRESH_BINARY)[1])
        glyphs=None
        if points is not None:
            x,y,w,h=cv2.boundingRect(points);glyphs=[l+x,t+y,l+x+w,t+y+h]
        complete=bool(found and glyphs and found[0]<=glyphs[0] and found[2]>=glyphs[2])
        augmented.append(dict(path=row['path'],brightness=row['brightness'],scale=row['scale'],
            complete=complete,wanted=wanted,glyphBounds=glyphs,found=found,errors=errors(row,regions,config['classes'])))
    parent_config=json.loads((ROOT/'config/dungeon-regions.json').read_text(encoding='utf-8'))
    parents=[UIRegionDetector(parent_config) for _ in models]
    for parent,child in zip(parents,models):parent.element_detector=child
    replay=[]
    for source in sorted(session.glob('event-*.json')):
        report=json.loads(source.read_text(encoding='utf-8'));name=(report.get('dungeon',{}).get('dungeonName') or {}).get('text','')
        if '대지' not in name:continue
        frame=cv2.imdecode(np.fromfile(source.with_suffix('.jpg'),dtype=np.uint8),cv2.IMREAD_COLOR)
        predictions=[]
        for parent in parents:
            regions=parent.locate(frame);location=dungeon_location(regions,frame.shape)
            result=ocr.analyze_detected(frame,location,detected_gates(regions),allow_without_gates=True)
            read=(result.get('dungeonName') or {}).get('text')
            predictions.append(dict(name=read,passed=key(read or '')==key('1막: 대지를 부수는 업화의 궤적'),ocr=result.get('ocr')))
        replay.append(dict(file=source.name,trainingSource=int(source.stem.split('-')[1]) in TRAIN,baseline=predictions[0],candidate=predictions[1]))
    summary=dict(oldTotal=len(old),oldBaselinePassed=sum(not r['baselineErrors'] for r in old),oldCandidatePassed=sum(not r['candidateErrors'] for r in old),
        regressions=sum(not r['baselineErrors'] and bool(r['candidateErrors']) for r in old),replayTotal=len(replay),
        replayBaselinePassed=sum(r['baseline']['passed'] for r in replay),replayCandidatePassed=sum(r['candidate']['passed'] for r in replay),
        augmentedTotal=len(augmented),augmentedEdgesPassed=sum(r['complete'] for r in augmented),
        chapterTotal=len(chapters),chapterCandidatePassed=sum(r['candidate']['passed'] for r in chapters))
    output.write_text(json.dumps(dict(summary=summary,old=old,replay=replay,augmented=augmented,chapters=chapters),ensure_ascii=False,indent=2),encoding='utf-8');print(summary)
    if (summary['regressions'] or not replay or summary['replayCandidatePassed']!=len(replay)
            or summary['chapterCandidatePassed']!=len(chapters) or summary['augmentedEdgesPassed']!=len(augmented)):
        raise SystemExit('Candidate not ready for activation')


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','evaluate']);p.add_argument('--session',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--weights',type=Path);p.add_argument('--baseline',type=Path);args=p.parse_args()
    if args.command=='prepare':prepare(args.session,args.output)
    else:
        if args.weights is None:p.error('--weights is required')
        evaluate(args.weights,args.session,args.output,args.baseline)


if __name__=='__main__':main()
