"""Verify video OCR outcomes and completion-only storage in isolated memory DBs.

Character and dungeon context are seeded deliberately; this is not a test of
those models. The completion observations come from actual full-frame inference.
"""
import argparse,json,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from beatrice.live import LiveCoordinator
from beatrice.storage import Store

def main():
    p=argparse.ArgumentParser();p.add_argument('report',type=Path);args=p.parse_args()
    rows=json.loads(args.report.read_text(encoding='utf-8'))['rows'];checks=[]
    windows={1:(18.5,22),2:(33.5,37),3:(22.5,26),4:(37,39.5)}
    for number in range(1,5):
        selected=[r for r in rows if r['source']==f'SAMPLE_{number:03d}']
        store=Store(':memory:');live=LiveCoordinator(store)
        live.identity.current='영상검증';live.identity.blocked=False
        start=datetime(2026,9,29,tzinfo=timezone.utc)
        for i in range(3):
            live.update(start+timedelta(seconds=i-4),{},[
                dict(state='진행중',confidence=1,xyxy=[0,0,20,20]),
                dict(state='진행 전',confidence=1,xyxy=[30,0,50,20])],
                dict(dungeonName=f'샘플{number}',difficulty='하드',contextStatus='ocr_verified',raidKind='gated',currentRaidPanel=True))
        triggers=[];errors=[]
        for row in selected:
            observation=row['result'];seconds=row['seconds']
            if observation['status']=='verified':
                lo,hi=windows[number]
                if not lo<=seconds<=hi:errors.append(f'false_completion_at_{seconds}')
                expected='gate_breakthrough' if number==3 else 'dungeon_clear'
                if observation['kind']!=expected or (number==3 and observation['gate']!=1):errors.append('wrong_semantics')
            state=live.update(start+timedelta(seconds=seconds),{},[],dict(completionOverlay=observation))
            if state['result'].get('bannerCompleted'):triggers.append(seconds)
        records=store.state_records();expected_count=1 if number==3 else 2
        if len(triggers)!=1:errors.append('expected_one_completion_event')
        if len(records)!=expected_count or any(r['state']!='완료' for r in records):errors.append('wrong_saved_records')
        checks.append(dict(video=number,passed=not errors,errors=errors,completionSeconds=triggers,records=records));store.close()
    transforms=[r for r in rows if 'transformed' in r]
    for row in transforms:
        name=row['source'];expected='gate_breakthrough' if 'gate1' in name else 'dungeon_clear'
        checks.append(dict(source=name,transformed=row['transformed'],passed=row['result'].get('status')=='verified' and row['result'].get('kind')==expected))
    result=dict(passed=sum(c['passed'] for c in checks),total=len(checks),checks=checks)
    args.report.with_suffix('.checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(result['passed'],result['total'])
    if not all(c['passed'] for c in checks):raise SystemExit(1)

if __name__=='__main__':main()
