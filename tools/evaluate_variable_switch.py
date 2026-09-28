"""Check variable item dialogs and confirm/cancel sequences without a live DB."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2,torch
    torch.set_num_threads(2)
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.character_vision import CharacterVision
    from beatrice.character import CharacterTracker
    detector=UIRegionDetector(json.loads(a.config.read_text('utf8')));vision=CharacterVision()
    def observe(path):
        frame=cv2.imread(str(path))
        return vision.analyze_detected(frame,detector.locate(frame))
    manifest=json.loads((ROOT/'data/annotations/character-variable-switch-0928.json').read_text('utf8'))
    rows=[]
    for item in manifest['images']:
        if item['sessionId']!='260928-variable-dialog':continue
        obs=observe(ROOT/'data/annotations'/item['path'])
        passed=obs['switchDialog'] and not obs['normalMenu'] and (obs['targetName'] or {}).get('text')=='테베체' and not obs['switchLoading']
        rows.append(dict(path=item['path'],passed=passed,observation=obs))
        print(item['path'],passed,flush=True)
    original=observe(ROOT/'outputs/switch-review-0928/frame-039.jpg')
    loading=observe(ROOT/'outputs/switch-review-0928/frame-040.jpg')
    old_menu=observe(ROOT/'outputs/switch-review-0928/frame-030.jpg')
    new_menu=observe(ROOT/'outputs/switch-review-0928/frame-064.jpg')
    def tracker():
        t=CharacterTracker(max_gap=5)
        for second in range(3):t.update(second,old_menu)
        return t
    t=tracker();popup=t.update(3,original);after=t.update(4,loading)
    for second in range(5,8):changed=t.update(second,new_menu)
    c=tracker();c.update(3,original)
    for second in range(4,8):cancelled=c.update(second,old_menu)
    unrelated=c.update(8,loading)
    scenarios=dict(dialog=original['switchDialog'],target=(original['targetName'] or {}).get('text')=='테베체',
        popupKeepsCurrent=popup['recordingAllowed'] and popup['currentName']=='후이수',
        loadingSuspends=not after['recordingAllowed'],newCharacterConfirmed=changed['recordingAllowed'] and changed['currentName']=='테베체',
        cancelKeepsCurrent=cancelled['recordingAllowed'] and cancelled['currentName']=='후이수',
        unrelatedLoadingKeepsCurrent=unrelated['recordingAllowed'])
    result=dict(passed=sum(r['passed'] for r in rows),total=len(rows),rows=rows,scenarios=scenarios,
                purpose='training_reconstruction_and_same_session_adjacent_frames_not_independent')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(result['passed'],result['total'],scenarios,flush=True)
    if not all(scenarios.values()) or result['passed']!=result['total']:sys.exit(1)
if __name__=='__main__':main()
