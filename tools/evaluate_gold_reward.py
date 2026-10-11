"""Evaluate real reward panels, temporal holdouts, dim variants and hard negatives."""
import argparse,json,sys,time,shutil
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from beatrice.gold_reward import GoldRewardDetector
from beatrice.paddle_reader import PaddleKoreanReader

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--weights',required=True);parser.add_argument('--parent-weights',required=True);args=parser.parse_args()
    config=json.loads((ROOT/'config/gold-reward.json').read_text(encoding='utf-8'));config.update(weights=args.weights,intervalSeconds=0)
    from beatrice.ui_regions import UIRegionDetector
    parent=json.loads((ROOT/'config/gold-reward-panel.json').read_text(encoding='utf-8'));parent['weights']=args.parent_weights
    detector=GoldRewardDetector(PaddleKoreanReader(),config,parent_detector=UIRegionDetector(parent))
    rows=[];raw=ROOT/'data/raw/gold-reward-1011'
    sources=[(raw/'gold.png',True,'training-parent'),(raw/'no-gold.png',False,'training-parent'),
             (ROOT/'data/raw/dungeon-completion-0923/completion-235.jpg',True,'same-session-holdout'),
             (raw/'final-no-gold.png',False,'final-training-parent')]
    session=Path('C:/Users/Huisoo/AppData/Local/BeatricePC/completion-diagnostics/20261011T053841Z-92af6174')
    sources.extend((session/f'event-{n:08d}.jpg',False,'same-session-holdout') for n in (112,125,150,178,207))
    final_session=Path('C:/Users/Huisoo/AppData/Local/BeatricePC/completion-diagnostics/20261011T102237Z-6b11ca8d')
    sources.extend((final_session/f'event-{n:08d}.jpg',False,'final-same-session-holdout') for n in (255,256))
    for path,expected,purpose in sources:
        if purpose.endswith('same-session-holdout'):
            saved=raw/(('final-' if purpose.startswith('final') else '')+path.name)
            if not saved.exists():shutil.copyfile(path,saved)
            path=saved
        original=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
        for scale in (1,.75,1.25):
            for dim in (1,.75,.5,.35):
                frame=cv2.resize(np.clip(original*dim,0,255).astype(np.uint8),None,fx=scale,fy=scale)
                start=time.perf_counter();result=detector.analyze(frame,0)
                title_ok=result.get('scope')=='final' if purpose.startswith('final') else result.get('gate')==1
                rows.append(dict(source=str(path),purpose=purpose,scale=scale,brightness=dim,milliseconds=round((time.perf_counter()-start)*1000,1),passed=result.get('status')=='verified' and result.get('received') is expected and title_ok,result=result))
    for path in sorted(raw.glob('negative-*-0.png')):
        frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR);result=detector.analyze(frame,0)
        rows.append(dict(source=str(path),purpose='hard-negative',passed=result.get('status')!='verified',result=result))
    out=ROOT/'outputs/gold-reward-review/evaluation.json';out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    failures=[{k:v for k,v in r.items() if k!='result'}|{'status':r['result']['status'],'raw':r['result'].get('raw')} for r in rows if not r['passed']]
    print(json.dumps(dict(total=len(rows),passed=sum(r['passed'] for r in rows),failureCount=len(failures),failures=failures[:5]),ensure_ascii=False))

if __name__=='__main__':main()
