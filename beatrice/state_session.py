"""전체 관문 상태는 메모리에서 추적하고 완료만 영속 저장합니다."""
import copy
import uuid
from datetime import datetime,timezone
from .gates import GateTracker
from .dungeon import key
from .session import iso


class StateSession:
    def __init__(self,store):
        self.store=store;self.begin_character_change()

    def begin_character_change(self):
        self.token=str(uuid.uuid4());self.owner='pending:'+self.token
        self.character=None;self.tracker=None;self.pending_tracker=None;self.run=None
        return self.token

    def prepare_pending_run(self,session_id,expected_gates,*args,**kwargs):
        self.run=session_id
        self.pending_tracker=GateTracker(session_id,expected_gates,max_sample_gap=5,snapshot_mode=True)

    def confirm_character(self,character_key,character_name,session_id,expected_gates,*args,**kwargs):
        previous_owner=self.owner;self.owner=character_key
        try:
            with self.store.db:
                pending=self.store.state_records(previous_owner) if previous_owner.startswith('pending:') else []
                groups={key(r['dungeonName']) for r in pending}
                for group in groups:
                    rows=[dict(r,characterKey=character_key,characterName=character_name) for r in pending if key(r['dungeonName'])==group]
                    known=self.store.state_records(character_key,group)
                    expected=max(r.get('expectedGates') or r['gate'] for r in rows)
                    if max((r.get('expectedGates',r['gate']) for r in known),default=0)>expected:
                        # 이름 확정 전에 잡힌 짧은 배열은 기존 전체 기록을 대체하지 않습니다.
                        continue
                    self.store.save_completions(character_key,group,rows,expected,transactional=False)
                    self.store.db.execute('DELETE FROM gate_states WHERE owner=? AND dungeon_key=?',(previous_owner,group))
        except Exception:
            self.owner=previous_owner;raise
        self.character=dict(key=character_key,name=character_name)
        self.run=session_id
        self.tracker=self.pending_tracker or GateTracker(session_id,expected_gates,max_sample_gap=5,snapshot_mode=True)
        self.pending_tracker=None
        return self.token

    def observe(self,token,at,boxes,dungeon):
        if token!=self.token:return dict(status='stale_frame',events=[])
        tracker=self.tracker or self.pending_tracker
        if tracker is None:return dict(status='waiting',events=[])
        trial=copy.deepcopy(tracker)
        group=key(dungeon['dungeonName']);previous=self.store.state_records(self.owner,group)
        # 재입장·재시작에도 저장된 완료를 해제하지 않습니다.
        if previous and trial.stable is None:
            trial.stable=tuple(next((r['state'] for r in previous if r['gate']==i),'진행 전') for i in range(1,trial.expected+1))
            trial.stable=tuple('완료' if s=='완료' else '진행 전' for s in trial.stable)
        result=trial.update(at.timestamp(),boxes);changed=[]
        if result['status']=='stable':
            highest=max([i for i,s in enumerate(result['observedStates']) if s=='완료']+
                        [r['gate']-1 for r in previous if r['state']=='완료'],default=-1)
            rows=[]
            for i,state in enumerate(trial.stable):
                inferred=state=='완료' and result['observedStates'][i]!='완료' and i<highest
                rows.append(dict(gate=i+1,state=state,characterKey=self.character['key'] if self.character else None,
                    characterName=self.character['name'] if self.character else None,dungeonName=dungeon['dungeonName'],difficulty=dungeon['difficulty'],
                    observedAt=iso(at),confirmedAt=iso(at),savedAt=iso(datetime.now(timezone.utc)),
                    completedAt=None if inferred or state!='완료' else iso(at),
                    evidenceType='later_gate_completion' if inferred else 'direct',timeBasis='live_capture',
                    completionScope='raid' if dungeon.get('raidKind')=='gateless' else 'gate'))
            changed=self.store.save_states(self.owner,group,rows)
        if self.character:self.tracker=trial
        else:self.pending_tracker=trial
        completions=[r for r in changed if r['state']=='완료']
        return dict(status=result['status'],stableStates=trial.stable,changedRecords=changed,
                    events=completions if self.character else [],pendingEvents=completions if not self.character else [])

    def complete_banner(self,at,dungeon,gate):
        """확정된 현재 배열의 대상만 완료로 갱신. 다른 미완료 관문의 상태는 유지합니다."""
        tracker=self.tracker or self.pending_tracker
        group=key(dungeon['dungeonName'])
        gateless=dungeon.get('raidKind')=='gateless'
        if tracker is None:return []
        states=tracker.stable or (('진행중',) if gateless else ())
        if len(states)!=tracker.expected or not 1<=gate<=len(states):return []
        rows=[dict(gate=i+1,state=state,characterKey=self.character['key'] if self.character else None,
                       characterName=self.character['name'] if self.character else None,
                       dungeonName=dungeon['dungeonName'],difficulty=dungeon['difficulty'],
                       completionScope='raid' if gateless else 'gate') for i,state in enumerate(states)]
        saved={r['gate']:r for r in self.store.state_records(self.owner,group)}
        rows=[dict(saved.get(r['gate'],r)) for r in rows]
        for row in rows:
            if row['gate']<=gate and row['state']!='완료':
                direct=row['gate']==gate
                row.update(state='완료',observedAt=iso(at),confirmedAt=iso(at),savedAt=iso(datetime.now(timezone.utc)),
                    completedAt=iso(at) if direct else None,evidenceType=(dungeon.get('completionOverlay') or {}).get('kind','completion_banner') if direct else 'later_gate_completion',
                    timeBasis='live_capture',completionScope='raid' if gateless else 'gate')
        changed=self.store.save_states(self.owner,group,rows)
        tracker.stable=tuple(r['state'] for r in rows)
        tracker.clear_candidate()
        return changed
