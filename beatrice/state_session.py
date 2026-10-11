"""전체 관문 상태는 메모리에서 추적하고 완료만 영속 저장합니다."""
import copy
import uuid
from .gates import GateTracker
from .dungeon import key
from .session import iso
from .completion_record import recognition_record


class StateSession:
    def __init__(self,store,is_test=False):
        self.is_test=bool(is_test)
        self.store=store;self.begin_character_change()

    def begin_character_change(self):
        self.token=str(uuid.uuid4());self.owner='pending:'+self.token
        self.character=None;self.tracker=None;self.pending_tracker=None;self.run=None
        return self.token

    def capture_interrupted(self):
        if self.tracker is not None:self.tracker.clear_candidate()

    def prepare_pending_run(self,*args,**kwargs):
        """Compatibility entry point: no tracking before character confirmation."""
        return None

    def confirm_character(self,character_key,character_name,session_id,expected_gates,*args,**kwargs):
        self.owner=('test:' if self.is_test else '')+'name:'+character_name
        self.character=dict(key=character_key,name=character_name)
        self.run=session_id
        self.tracker=GateTracker(session_id,expected_gates,max_sample_gap=5,snapshot_mode=True)
        self.pending_tracker=None
        return self.token

    def observe(self,token,at,boxes,dungeon):
        if token!=self.token:return dict(status='stale_frame',events=[])
        if self.character is None:return dict(status='waiting',events=[])
        tracker=self.tracker
        if tracker is None:return dict(status='waiting',events=[])
        trial=copy.deepcopy(tracker)
        group=key(dungeon['dungeonName']);previous=[recognition_record(r) for r in self.store.state_records(self.owner,group)]
        # 재입장·재시작에도 저장된 완료를 해제하지 않습니다.
        if previous and trial.stable is None:
            trial.stable=tuple(next((r['state'] for r in previous if r['gate']==i),'진행 전') for i in range(1,trial.expected+1))
            trial.stable=tuple('완료' if s=='완료' else '진행 전' for s in trial.stable)
        result=trial.update(at.timestamp(),boxes);changed=[]
        if result['status']=='stable':
            rows=[]
            for i,state in enumerate(trial.stable):
                rows.append(dict(gate=i+1,state=state,characterName=self.character['name'],dungeonName=dungeon['dungeonName'],difficulty=dungeon['difficulty'],
                    observedAt=iso(at),isTest=self.is_test,
                    completionScope='raid' if dungeon.get('raidKind')=='gateless' else 'gate'))
            changed=self.store.save_states(self.owner,group,rows)
        self.tracker=trial
        completions=changed
        return dict(status=result['status'],stableStates=trial.stable,
                    observedStates=result.get('observedStates'),changedRecords=changed,
                    events=completions,pendingEvents=[])

    def complete_banner(self,at,dungeon,gate):
        """확정된 현재 배열의 대상만 완료로 갱신. 다른 미완료 관문의 상태는 유지합니다."""
        if self.character is None:return []
        tracker=self.tracker
        group=key(dungeon['dungeonName'])
        gateless=dungeon.get('raidKind')=='gateless'
        if tracker is None:return []
        states=tracker.stable or (('진행중',) if gateless else ())
        if len(states)!=tracker.expected or not 1<=gate<=len(states):return []
        rows=[dict(gate=i+1,state=state,characterName=self.character['name'],
                       dungeonName=dungeon['dungeonName'],difficulty=dungeon['difficulty'],
                       completionScope='raid' if gateless else 'gate') for i,state in enumerate(states)]
        saved={r['gate']:r for r in map(recognition_record,self.store.state_records(self.owner,group))}
        rows=[dict(saved.get(r['gate'],r)) for r in rows]
        for row in rows:
            if row['gate']<=gate and row['state']!='완료':
                row.update(state='완료',observedAt=iso(at),isTest=self.is_test,completionScope='raid' if gateless else 'gate')
        changed=self.store.save_states(self.owner,group,rows)
        tracker.stable=tuple(r['state'] for r in rows)
        tracker.clear_candidate()
        return changed
