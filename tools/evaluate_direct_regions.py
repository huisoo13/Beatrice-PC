"""Direct-region reconstruction and transformed-frame checks; never independent accuracy."""
import argparse,json,os,sys,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--role',choices=['character','dungeon'],required=True)
    p.add_argument('--config',type=Path);p.add_argument('--labels-only',action='store_true');p.add_argument('--transforms',action='store_true')
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2,torch,numpy as np
    torch.set_num_threads(2)
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.character_vision import CharacterVision
    from beatrice.dungeon import DungeonOCR
    from beatrice.dungeon_observer import DungeonObserver
    doc=json.loads((ROOT/f'data/annotations/{args.role}-direct-0926.json').read_text('utf8'))
    cfg=json.loads((args.config or ROOT/f'outputs/direct-regions-0926/{args.role}.json').read_text('utf8'))
    detector=None if args.labels_only else UIRegionDetector(cfg)
    ocr=DungeonOCR();vision=CharacterVision(reader=ocr.reader);observer=DungeonObserver(ocr)
    rows=[]
    for index,row in enumerate(doc['images']):
        image=cv2.imread(str(ROOT/'data/annotations'/row['path']))
        variants=[('original',image,row['boxes'])]
        if args.transforms and row.get('sessionId') in ('260926-resolution','260926-loading'):
            # Translate the entire supplied frame into a larger neutral canvas.
            # This tests runtime coordinate independence, not unseen UI artwork.
            h,w=image.shape[:2];resized=cv2.resize(image,(round(w*.8),round(h*.8)))
            moved=np.zeros((h+80,w+180,3),np.uint8);moved[130:130+resized.shape[0],210:210+resized.shape[1]]=resized
            labels=[dict(b,xyxy=[round(b['xyxy'][0]*.8)+210,round(b['xyxy'][1]*.8)+130,round(b['xyxy'][2]*.8)+210,round(b['xyxy'][3]*.8)+130]) for b in row['boxes']]
            variants.append(('translated_scaled',moved,labels))
        for variant,frame,labels in variants:
            expected={b['class'] for b in labels}
            if detector:regions=detector.locate(frame)
            else:
                regions={kind:dict(status='missing',candidates=[]) for kind in doc['classes']}
                for b in labels:regions[b['class']]['candidates'].append(dict(xyxy=b['xyxy'],confidence=1.))
                for entry in regions.values():
                    items=entry['candidates'];entry['status']='detected' if len(items)==1 else 'ambiguous' if items else 'missing'
                    if len(items)==1:entry.update(items[0])
            if args.role=='character':
                result=vision.analyze_detected(frame,regions)
                errors=[]
                transcriptions={0:'테베체',4:'후이수',6:'테베체',8:'테베체',15:'그냥열두글자확인하기위한',16:'힐레우스',17:'후이수',21:'테베체'}
                targets={1:'후이수',5:'테베체',7:'힐레우스',9:'후이수',18:'테베체',22:'후이수'}
                if 'game_menu' in expected and 'switch_dialog' not in expected and 'loading_indicator' not in expected:
                    if not result.get('currentName'):errors.append('current_name_unreadable')
                    if row.get('sessionId')=='260926-resolution' and (result.get('currentName') or {}).get('text')!='힐레우스':errors.append('wrong_current_name')
                    if index in transcriptions and (result.get('currentName') or {}).get('text')!=transcriptions[index]:errors.append('wrong_current_name')
                if 'switch_dialog' in expected and not result.get('switchDialog'):errors.append('dialog_missing')
                if 'target_name_line' in expected and not result.get('targetName'):errors.append('target_unreadable')
                if 'target_name_line' in expected and (result.get('targetName') or {}).get('text')!=targets.get(index,'테베체'):errors.append('wrong_target_name')
                if 'loading_indicator' in expected and not result.get('switchLoading'):errors.append('loading_unverified')
                if not expected and (result.get('currentName') or result.get('switchDialog') or result.get('switchLoading')):errors.append('false_positive')
                gates=[]
            else:
                result,gates=observer.analyze(frame,regions,index)
                errors=[]
                raid=bool(expected & {'dungeon_panel','gateless_raid_panel'})
                if raid and not (result.get('dungeonVisible') and result.get('dungeonName')):errors.append('raid_text_unreadable')
                if 'dungeon_panel' in expected:
                    wanted=[{'gate_in_progress':'진행중','gate_completed':'완료','gate_not_started':'진행 전'}[b['class']] for b in sorted(labels,key=lambda b:b['xyxy'][0]) if b['class'].startswith('gate_') and b['class']!='gate_panel']
                    if [b['state'] for b in gates]!=wanted:errors.append('gate_array_mismatch')
                if not raid and result.get('dungeonVisible'):errors.append('false_raid')
                if row.get('sessionId')=='260926-resolution' and raid:
                    from beatrice.dungeon import key
                    if key((result.get('dungeonName') or {}).get('text',''))!=key('4막 : 파멸의 성채'):errors.append('wrong_dungeon_name')
                    if (result.get('difficulty') or {}).get('text')!='싱글 모드':errors.append('wrong_difficulty')
            rows.append(dict(index=index,path=row['path'],variant=variant,shape=list(frame.shape),passed=not errors,errors=errors,regions=regions,result=result,gates=gates))
            print(index,variant,'PASS' if not errors else errors,flush=True)
    report=dict(purpose='training_reconstruction_and_transformed_samples_not_independent',passed=sum(r['passed'] for r in rows),total=len(rows),rows=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(report['passed'],report['total'],flush=True)

if __name__=='__main__':main()
