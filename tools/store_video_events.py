"""녹화 시작 절대시각과 확인된 캐릭터 신호를 주입해 SQLite 기록을 재생합니다."""
import argparse
from datetime import datetime,timedelta
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.storage import Store
from beatrice.session import aware
from beatrice.deferred_session import DeferredRecordingSession as RecordingSession


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('observations',type=Path)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--character-key',required=True)
    p.add_argument('--character-name',required=True)
    p.add_argument('--session-id',required=True)
    p.add_argument('--expected-gates',type=int,required=True)
    p.add_argument('--recording-start',required=True,help='시간대 포함 ISO 8601, 예: 2026-09-16T09:00:00+09:00')
    p.add_argument('--test-data',action='store_true',help='가상 캐릭터/시각이면 필수. 업로드 제외.')
    p.add_argument('--identity-confirmed-at',type=float,default=0,help='테스트에서 이름 확정을 지연할 영상 초. --test-data 필수')
    a=p.parse_args()
    if a.identity_confirmed_at<0 or (a.identity_confirmed_at>0 and not a.test_data):
        p.error('이름 확정 지연은 0 이상의 테스트 전용 값입니다.')
    start=aware(datetime.fromisoformat(a.recording_start))
    data=json.loads(a.observations.read_text())
    source={'videoSha256':data['meta'].get('sourceSha256'), 'recordingStart':start.isoformat()}
    if not source['videoSha256']:raise ValueError('영상 원본 해시가 필요합니다.')
    store=Store(a.db)
    try:
        session=RecordingSession(store)
        context=dict(session_id=a.session_id,expected_gates=a.expected_gates,
            time_basis='synthetic_test' if a.test_data else 'recording_start_plus_offset',is_test=a.test_data,source_id=source)
        if a.identity_confirmed_at>0:
            session.prepare_pending_run(**context)
        else:
            session.confirm_character(a.character_key,a.character_name,**context)
        inserted=0
        for row in data['observations']:
            if session.character is None and row['videoSeconds']>=a.identity_confirmed_at:
                session.confirm_character(a.character_key,a.character_name,**context)
                inserted+=len(session.last_resolved_events)
            result=session.observe(session.token,start+timedelta(seconds=row['videoSeconds']),row['boxes'],row.get('dungeonContext'))
            inserted+=len(result['events'])
        print(json.dumps(dict(inserted=inserted,records=store.records(),pending=store.pending_records()),ensure_ascii=False,indent=2))
    finally:store.close()

if __name__=='__main__':main()
