"""실제 영상의 캐릭터 인식 결과 + 합성 관문 전환으로 저장 연결을 검증합니다."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from beatrice.character import CharacterRecordingBridge
from beatrice.session import RecordingSession
from beatrice.storage import Store


def main():
    source=ROOT/'outputs/character-recognition/success.json'
    replay=json.loads(source.read_text())
    with tempfile.TemporaryDirectory() as temp:
        store=Store(Path(temp)/'integration.sqlite')
        session=RecordingSession(store)
        bridge=CharacterRecordingBridge(session,lambda name:dict(character_key='test:'+name,
            session_id='character-integration-test',expected_gates=1,time_basis='synthetic_test',
            is_test=True,source_id=replay['sha256']))
        confirmations=[];suspensions=0
        for row in replay['observations']:
            bridge.apply(row['state'])
            for action in row['state']['actions']:
                if action['type']=='confirmed':confirmations.append(action['name'])
                if action['type']=='suspend':
                    suspensions+=1
                    assert session.character is None
        assert confirmations==['후이수','테베체'], confirmations
        assert session.character['name']=='테베체'
        # 영상과 무관한 명시적 테스트 시각입니다. 실제 게임 이벤트가 아닙니다.
        start=datetime(2026,9,17,9,tzinfo=timezone(timedelta(hours=9)))
        for index in range(6):
            boxes=[dict(state='진행중' if index<3 else '완료',confidence=.99,xyxy=[60,130,100,180])]
            session.observe(session.token,start+timedelta(seconds=index*.2),boxes)
        records=store.records()
        assert len(records)==1 and records[0]['characterName']=='테베체'
        assert records[0]['syncStatus']=='test_only'
        report=dict(purpose='real_character_observations_plus_synthetic_gate_and_time',
            source=str(source),confirmations=confirmations,suspensions=suspensions,records=records,
            productionEventCreated=False)
        (ROOT/'outputs/character-recognition/storage-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        store.close()
    print('실제 영상 인식 이름으로 합성 완료 기록 1건 저장 확인: 테베체, test_only')

if __name__=='__main__':main()
