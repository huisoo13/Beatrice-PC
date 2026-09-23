"""입력 출처와 분리된 라이브 관측 → 기존 SQLite 세션 연결."""
import uuid
from .dungeon import key
from .character import CharacterTracker
from .state_session import StateSession

class LiveCoordinator:
    def __init__(self,store):
        self.identity=CharacterTracker(max_gap=5)
        self.session=StateSession(store)
        self.context=None;self.context_pair=None;self.candidate=None;self.count=0
    def confirm(self,name):
        if self.context is None:return
        run,n=self.context
        self.session.confirm_character('name:'+name,name,run,n,'live_capture',is_test=True)
        self.session.tracker.max_gap=5
    def update(self,at,character,boxes,dungeon):
        identity=self.identity.update(at.timestamp(),character)
        suspended=any(a['type']=='suspend' for a in identity['actions'])
        if suspended:self.session.begin_character_change();self.context=None;self.context_pair=None;self.candidate=None;self.count=0
        # 이름 확인은 메뉴에서 이루어지므로 당시 던전 UI가 가려져도 기존 보류 구간을 확정합니다.
        for action in identity['actions']:
            if action['type']=='confirmed':self.confirm(action['name'])
        valid=dungeon.get('contextStatus')=='ocr_verified' and 1<=len(boxes)<=8 and all(b['confidence']>=.5 for b in boxes)
        pair=tuple(key(dungeon[f]) for f in ('dungeonName','difficulty')) if valid else None
        active_tracker=self.session.tracker or self.session.pending_tracker
        locked=active_tracker is not None and active_tracker.stable is not None
        count_mismatch=bool(valid and locked and self.context is not None and pair==self.context_pair and len(boxes)!=self.context[1])
        if valid:
            owner='name:'+identity['currentName'] if identity['recordingAllowed'] else self.session.owner
            known=self.session.store.state_records(owner,pair[0])
            expected=max((r.get('expectedGates',r['gate']) for r in known),default=0)
            count_mismatch=count_mismatch or bool(expected and len(boxes)!=expected)
        if count_mismatch:valid=False
        signature=(dungeon.get('dungeonName'),dungeon.get('difficulty'),len(boxes)) if valid else None
        self.count=self.count+1 if signature is not None and signature==self.candidate else (1 if signature else 0)
        self.candidate=signature
        result={}
        if signature and not suspended:
            # 추적기는 모드별로 구분하되 저장 키는 캐릭터·던전·관문입니다.
            run=str(uuid.uuid5(uuid.NAMESPACE_URL,'beatrice-test:'+repr(signature)))
            context=(run,len(boxes))
            if self.context!=context:
                if self.context is not None:self.session.begin_character_change()
                self.context=context
                self.context_pair=pair
                if identity['recordingAllowed']:self.confirm(identity['currentName'])
                else:
                    self.session.prepare_pending_run(run,len(boxes),'live_capture',is_test=True)
                    self.session.pending_tracker.max_gap=5
            result=self.session.observe(self.session.token,at,boxes,dungeon)
        else:
            tracker=self.session.tracker or self.session.pending_tracker
            if tracker is not None:tracker.clear_candidate()
        if not valid:
            reasons={'region_missing':'관문 영역 재탐지 중','gate_unverified':'관문 상태 재확인 중',
                     'reuse_rejected':'화면 변경 확인 중','text_unverified':'던전명·모드 재확인 중'}
            status=reasons.get(dungeon.get('diagnosticStatus'),'던전명·모드 재확인 중')
            if count_mismatch:status='관문 수 불일치 · 전체 관문 재확인 중'
            if dungeon.get('contextStatus')=='ocr_held':status='이전 던전명 유지 · '+status
        elif result.get('events'):status='관문 완료 저장됨'
        elif result.get('pendingEvents'):status='관문 완료 임시 저장 · 캐릭터 확인 대기'
        elif result.get('changedRecords'):status='전체 관문 상태 갱신됨'
        elif self.count<3:status='현재 관문 감지 중 · 던전 정보 확인 중'
        elif result.get('status') in ('uncertain','waiting'):status='현재 관문 감지 중 · 관문 배열 재확인 중'
        elif result.get('status')=='candidate':status='현재 관문 감지 중 · 상태 변경 확인 중'
        elif not identity['recordingAllowed']:status='현재 관문 감지 중 · 캐릭터 확인 대기'
        else:status='현재 관문 감지 중 · 완료 변화 대기'
        return dict(identity=identity,result=result,dungeon=dungeon,recordingStatus=status)
