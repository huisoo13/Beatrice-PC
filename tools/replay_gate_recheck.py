"""Replay stored recognition reports, without inference or writing user records."""
import argparse,copy,json,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from beatrice.live import LiveCoordinator
from beatrice.storage import Store

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('session',type=Path)
    parser.add_argument('--start',type=int,default=8700)
    parser.add_argument('--end',type=int,default=9540)
    args=parser.parse_args()
    rows=[json.loads(line) for line in (args.session/'observations.jsonl').read_text(encoding='utf-8').splitlines()]
    store=Store(':memory:');live=LiveCoordinator(store)
    report=None;events=[];requests=[];early=[];first_complete=None;observations=0
    for row in rows:
        if not args.start<=row['sequence']<=args.end:continue
        path=args.session/f"event-{row['sequence']:08d}.json"
        if path.exists():report=json.loads(path.read_text(encoding='utf-8'))
        if report is None:continue
        if live.identity.current is None and row.get('character'):
            live.identity.current=row['character'];live.identity.blocked=False
        dungeon=copy.deepcopy(report['state']['dungeon'])
        dungeon['completionOverlay']=row.get('completion') or {}
        boxes=copy.deepcopy(report['gates'])
        # Repeated log rows reuse the preceding full report only if their gate
        # states match. This refuses an unrecorded recognition transition.
        assert [box['state'] for box in boxes]==row['gates'],row['sequence']
        if len(boxes)==2 and all(box['state']=='완료' for box in boxes) and first_complete is None:
            first_complete=row['observedAt']
        state=live.update(datetime.fromisoformat(row['observedAt']),{},boxes,dungeon)
        changed=state['result'].get('changedRecords',[])
        events.extend(dict(sequence=row['sequence'],record=record) for record in changed)
        if state['result'].get('gateRecheckRequested'):requests.append(row['sequence'])
        if row['sequence']==8838:early=copy.deepcopy(store.state_records())
        observations+=1
    records=store.state_records()
    assert [record['gate'] for record in early]==[1],early
    assert [record['gate'] for record in records]==[1,2],records
    gate2=next(record for record in records if record['gate']==2)
    assert first_complete and gate2['observedAt']>=first_complete
    assert gate2['evidenceType']=='direct'
    print(json.dumps(dict(passed=True,observations=observations,recheckSequences=requests,
        earlyRecords=early,events=events,firstBothCompleted=first_complete,records=records),ensure_ascii=False,indent=2))
    store.close()

if __name__=='__main__':main()
