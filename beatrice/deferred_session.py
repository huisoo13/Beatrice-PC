"""이름 미확정 구간의 관문 이벤트를 SQLite에 보관하고 같은 구간만 확정합니다."""
import copy
from datetime import datetime, timezone
import json
import uuid
from .session import RecordingSession, aware, iso
from .gates import GateTracker
from .dungeon import event_context


def checkpoint(tracker):
    return dict(slots=tracker.slots,stable=tracker.stable,emitted=sorted(tracker.emitted),
                lastTime=tracker.last_time,lastValid=tracker.last_valid)


class DeferredRecordingSession(RecordingSession):
    def begin_character_change(self):
        segment_id=str(uuid.uuid4())
        self.store.new_segment(segment_id)
        token=super().begin_character_change()
        self.segment_id=segment_id
        self.pending_context=None
        self.pending_tracker=None
        return token

    def prepare_pending_run(self, session_id, expected_gates, time_basis, is_test=False, source_id=None):
        """관문 분석기가 확인한 진행 정보. 이전 캐릭터의 진행 ID를 자동 복사하지 않습니다."""
        if self.character is not None:
            raise ValueError('캐릭터 미확정 상태에서만 보류 진행을 설정합니다.')
        if not session_id or type(expected_gates) is not int or expected_gates<1:
            raise ValueError('진행 ID와 관문 수가 필요합니다.')
        if time_basis not in ('live_capture','recording_start_plus_offset','synthetic_test'):
            raise ValueError('알 수 없는 시각 기준')
        if time_basis=='synthetic_test' and not is_test:
            raise ValueError('합성 시각은 테스트 전용입니다.')
        context=dict(sessionID=session_id,expectedGates=expected_gates,timeBasis=time_basis,
                     isTest=bool(is_test),sourceID=source_id,trackerVersion=1)
        if self.pending_context is not None:
            if self.pending_context!=context:
                raise ValueError('보류 중 다른 레이드 진행으로 바뀌면 새 구간을 시작해주세요.')
            return
        tracker=GateTracker(session_id,expected_gates)
        self.store.save_pending(self.segment_id,context,checkpoint(tracker),[])
        self.pending_context=context
        self.pending_tracker=tracker

    def observe(self, token, captured_at, boxes, dungeon_context=None):
        if self.character is not None or token!=self.token:
            return super().observe(token,captured_at,boxes,dungeon_context)
        if self.pending_tracker is None:
            return dict(status='pending_run_context_required',events=[],pendingEvents=[])
        timestamp=aware(captured_at).timestamp()
        if self.pending_tracker.last_time is not None and timestamp<=self.pending_tracker.last_time:
            return dict(status='already_processed_or_out_of_order',events=[],pendingEvents=[])
        trial=copy.deepcopy(self.pending_tracker)
        result=trial.update(timestamp,boxes)
        events=[]
        for item in result['events']:
            events.append(dict(schemaVersion=1,eventID=str(uuid.uuid5(uuid.NAMESPACE_URL,
                f"pending:{self.segment_id}:{item['gate']}")),eventType='gate_completed',
                sessionID=self.pending_context['sessionID'],gate=item['gate'],state='완료',
                observedAt=iso(datetime.fromtimestamp(item['firstObservedSeconds'],timezone.utc)),
                confirmedAt=iso(captured_at),savedAt=iso(datetime.now(timezone.utc)),
                timeBasis=self.pending_context['timeBasis'],isTest=self.pending_context['isTest'],
                sourceID=self.pending_context['sourceID'],evidence=dict(boxes=boxes),
                characterName=None,characterKey=None,**event_context(dungeon_context)))
        self.store.save_pending(self.segment_id,self.pending_context,checkpoint(trial),events)
        self.pending_tracker=trial
        return dict(status='character_pending',events=[],pendingEvents=events,stableStates=trial.stable)

    def confirm_character(self, character_key, character_name, session_id, expected_gates,
                          time_basis, is_test=False, source_id=None):
        # 다른 캐릭터로 넘어간 구간/재시작 이전 구간을 이름 하나로 소급 배정하지 않습니다.
        segment=self.segment_id
        context=self.pending_context
        trial=self.pending_tracker
        settings=dict(expectedGates=expected_gates,timeBasis=time_basis,isTest=bool(is_test),
                      sourceID=source_id,trackerVersion=1)
        if context is not None and context!=dict(settings,sessionID=session_id):
            raise ValueError('확정할 캐릭터의 진행 정보가 보류 구간과 다릅니다.')
        # 기존 세션 초기화는 DB 트랜잭션 전에 수행하지 않습니다.
        import unicodedata
        key=unicodedata.normalize('NFC',character_key).strip()
        name=unicodedata.normalize('NFC',character_name).strip()
        if not key or not name or not session_id or type(expected_gates) is not int or expected_gates<1:
            raise ValueError('캐릭터 식별자·이름·진행 ID·관문 수가 필요합니다.')
        if time_basis not in ('live_capture','recording_start_plus_offset','synthetic_test') or (time_basis=='synthetic_test' and not is_test):
            raise ValueError('시각 기준을 확인해주세요.')
        inserted=[]
        with self.store.db:
            previous=self.store.load(key,session_id,settings,transactional=False)
            restored=GateTracker(session_id,expected_gates)
            if previous:
                restored.slots=previous['slots'];restored.stable=tuple(previous['stable']) if previous['stable'] is not None else None
                restored.emitted=set(previous['emitted']);restored.last_time=previous['lastTime'];restored.last_valid=previous['lastValid']
            if trial is not None and (restored.last_time is None or (trial.last_time is not None and trial.last_time>restored.last_time)):
                selected=copy.deepcopy(trial)
                selected.emitted |= restored.emitted
            else:
                selected=restored
            selected.clear_candidate()
            final=[]
            mappings=[]
            for pending in self.store.pending_records():
                if pending['segmentID']!=segment or pending['resolvedEventID'] is not None:
                    continue
                identity=json.dumps([key,session_id,pending['gate']],ensure_ascii=False)
                event_id=str(uuid.uuid5(uuid.NAMESPACE_URL,identity))
                event={k:v for k,v in pending.items() if k not in ('segmentID','resolvedEventID')}
                event.update(eventID=event_id,characterKey=key,characterName=name,
                    identityConfirmedAt=iso(datetime.now(timezone.utc)),pendingEventID=pending['eventID'],
                    segmentID=segment)
                final.append(event);mappings.append((event_id,pending['eventID']))
            inserted=self.store.commit(key,session_id,checkpoint(selected),final,transactional=False)
            self.store.db.executemany('UPDATE pending_events SET resolved_event_id=? WHERE event_id=?',mappings)
            self.store.db.execute("UPDATE pending_segments SET status='resolved' WHERE segment_id=?",(segment,))
        self.character=dict(key=key,name=name,session=session_id)
        self.settings=settings;self.tracker=selected
        self.token=str(uuid.uuid4())
        self.pending_context=None;self.pending_tracker=None
        self.last_resolved_events=inserted
        return self.token
