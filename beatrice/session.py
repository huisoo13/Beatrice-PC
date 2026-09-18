"""캐릭터 인식 모듈과 관문 추적/저장을 연결하는 단일 작업자용 세션 상태입니다."""
import copy
from datetime import datetime, timezone
import json
import unicodedata
import uuid
from .gates import GateTracker
from .dungeon import event_context


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('시간대가 포함된 datetime이 필요합니다.')
    return value.astimezone(timezone.utc)


def iso(value):
    return aware(value).isoformat(timespec='microseconds')


class RecordingSession:
    def __init__(self, store):
        self.store = store
        self.begin_character_change()

    def begin_character_change(self):
        # 캡처 시 프레임에 이 토큰을 붙입니다. 변경 전 큐의 프레임은 거부됩니다.
        self.token = str(uuid.uuid4())
        self.character = None
        self.tracker = None
        self.settings = None
        return self.token

    def confirm_character(self, character_key, character_name, session_id, expected_gates,
                          time_basis, is_test=False, source_id=None):
        self.begin_character_change()
        key = unicodedata.normalize('NFC', character_key).strip()
        name = unicodedata.normalize('NFC', character_name).strip()
        if not key or not name or not session_id or type(expected_gates) is not int or expected_gates < 1:
            raise ValueError('캐릭터 식별자·이름·진행 ID·관문 수가 필요합니다.')
        if time_basis not in ('live_capture', 'recording_start_plus_offset', 'synthetic_test'):
            raise ValueError('알 수 없는 시각 기준')
        if time_basis == 'synthetic_test' and not is_test:
            raise ValueError('합성 시각은 테스트로 표시해야 합니다.')
        settings = dict(expectedGates=expected_gates, timeBasis=time_basis, isTest=bool(is_test),
                        sourceID=source_id, trackerVersion=1)
        checkpoint = self.store.load(key, session_id, settings)
        tracker = GateTracker(session_id, expected_gates)
        if checkpoint:
            tracker.slots = checkpoint['slots']
            tracker.stable = tuple(checkpoint['stable']) if checkpoint['stable'] is not None else None
            tracker.emitted = set(checkpoint['emitted'])
            tracker.last_time = checkpoint['lastTime']
            tracker.last_valid = checkpoint['lastValid']
        # 재시작/캐릭터 재확인 시 후보의 연속 횟수는 복구하지 않습니다.
        self.character = dict(key=key, name=name, session=session_id)
        self.settings = settings
        self.tracker = tracker
        return self.token

    def observe(self, token, captured_at, boxes, dungeon_context=None):
        if token != self.token or self.character is None:
            return dict(status='character_unconfirmed_or_stale_frame', events=[])
        timestamp = aware(captured_at).timestamp()
        if self.tracker.last_time is not None and timestamp <= self.tracker.last_time:
            return dict(status='already_processed_or_out_of_order', events=[])
        # DB 실패 시 원래 메모리 상태도 그대로 유지하여 동일 프레임을 재시도할 수 있습니다.
        trial = copy.deepcopy(self.tracker)
        result = trial.update(timestamp, boxes)
        events = []
        for candidate in result['events']:
            identity = json.dumps([self.character['key'], self.character['session'], candidate['gate']],ensure_ascii=False)
            events.append(dict(schemaVersion=1, eventID=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
                eventType='gate_completed', characterKey=self.character['key'], characterName=self.character['name'],
                sessionID=self.character['session'], gate=candidate['gate'], state='완료',
                observedAt=iso(datetime.fromtimestamp(candidate['firstObservedSeconds'],timezone.utc)),
                confirmedAt=iso(captured_at), savedAt=iso(datetime.now(timezone.utc)),
                timeBasis=self.settings['timeBasis'], isTest=self.settings['isTest'],
                sourceID=self.settings['sourceID'], **event_context(dungeon_context)))
        checkpoint = dict(slots=trial.slots,stable=trial.stable,emitted=sorted(trial.emitted),
                          lastTime=trial.last_time,lastValid=trial.last_valid)
        inserted = self.store.commit(self.character['key'],self.character['session'],checkpoint,events)
        self.tracker = trial
        return dict(status=result['status'],observedAt=iso(captured_at),stableStates=trial.stable,
                    events=inserted)
