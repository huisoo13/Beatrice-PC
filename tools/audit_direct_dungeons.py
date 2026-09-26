"""Replay the existing 55-frame dungeon text regression set through direct detections."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2,torch
    torch.set_num_threads(2)
    from beatrice.ui_regions import UIRegionDetector
    from beatrice.dungeon import DungeonOCR,key
    from beatrice.dungeon_observer import DungeonObserver
    detector=UIRegionDetector(json.loads(a.config.read_text('utf8')));observer=DungeonObserver(DungeonOCR())
    cases=json.loads((ROOT/'outputs/gate-completion-review-0923/audit-cases.json').read_text('utf8'));rows=[]
    for index,c in enumerate(cases):
        frame=cv2.imread(str(ROOT/c['path']));regions=detector.locate(frame);obs,gates=observer.analyze(frame,regions,index)
        expected=('1막 : 대지를 부수는 업화의 궤적','싱글 모드') if c['sequence'] in range(67,74) else ('고통의 마녀, 세르카','매칭 모드')
        passed=all(obs.get(f) and key(obs[f]['text'])==key(v) for f,v in zip(('dungeonName','difficulty'),expected)) if c['positive'] else not obs['dungeonVisible']
        rows.append(dict(**c,passed=bool(passed),observation=obs,gates=gates,regions=regions));print(c['sequence'],bool(passed),flush=True)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    print(sum(r['passed'] for r in rows),len(rows),flush=True)
if __name__=='__main__':main()
