"""기존 관측 JSON에서 한 세션의 관문 완료 이벤트를 재생합니다."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.gates import GateTracker


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('observations',type=Path)
    p.add_argument('--expected-gates',type=int,required=True,help='사람이 확인한 총 관문 수')
    p.add_argument('--session-id',required=True,help='영상 하나에 고유한 진행 세션 ID')
    p.add_argument('--output',type=Path,default=ROOT/'outputs/events-video002.json')
    a=p.parse_args();data=json.loads(a.observations.read_text())
    tracker=GateTracker(a.session_id,a.expected_gates)
    timeline=[];events=[]
    for row in data['observations']:
        result=tracker.update(row['videoSeconds'],row['boxes']);timeline.append(result);events.extend(result['events'])
    report=dict(schemaVersion=1,scope='single_video_session_replay',sessionID=a.session_id,
                sourceObservations=str(a.observations.resolve()),expectedGates=a.expected_gates,
                assumptions=['영상 전체가 동일 진행 세션', '관문 수를 사람이 지정', '한 세션에서 각 관문은 최대 한 번 완료'],
                thresholds=dict(confirmations=3,minConfidence=.5,maxCenterDistancePixels=25,maxSampleGapSeconds=.6),
                events=events,timeline=timeline)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(events,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
