"""입력 출처와 분리된 라이브 관측 → 기존 SQLite 세션 연결."""
import uuid
from .character import CharacterTracker
from .deferred_session import DeferredRecordingSession

class LiveCoordinator:
    def __init__(self,store):
        self.identity=CharacterTracker(max_gap=5)
        self.session=DeferredRecordingSession(store)
        self.context=None;self.candidate=None;self.count=0
    def confirm(self,name):
        if self.context is None:return
        run,n=self.context
        self.session.confirm_character('name:'+name,name,run,n,'live_capture',is_test=True)
        self.session.tracker.max_gap=5
    def update(self,at,character,boxes,dungeon):
        identity=self.identity.update(at.timestamp(),character)
        suspended=any(a['type']=='suspend' for a in identity['actions'])
        if suspended:self.session.begin_character_change();self.context=None;self.candidate=None;self.count=0
        # 이름 확인은 메뉴에서 이루어지므로 당시 던전 UI가 가려져도 기존 보류 구간을 확정합니다.
        for action in identity['actions']:
            if action['type']=='confirmed':self.confirm(action['name'])
        valid=dungeon.get('contextStatus')=='ocr_verified' and 1<=len(boxes)<=8 and all(b['confidence']>=.5 for b in boxes)
        signature=(dungeon.get('dungeonName'),dungeon.get('difficulty'),len(boxes)) if valid else None
        self.count=self.count+1 if signature is not None and signature==self.candidate else (1 if signature else 0)
        self.candidate=signature
        result={}
        if signature and self.count>=3 and not suspended:
            # 테스트용: 전체 기록 삭제 전까지 같은 이름/던전/난이도/관문은 한 번만 저장합니다.
            run=str(uuid.uuid5(uuid.NAMESPACE_URL,'beatrice-test:'+repr(signature)))
            context=(run,len(boxes))
            if self.context!=context:
                if self.context is not None:self.session.begin_character_change()
                self.context=context
                if identity['recordingAllowed']:self.confirm(identity['currentName'])
                else:
                    self.session.prepare_pending_run(run,len(boxes),'live_capture',is_test=True)
                    self.session.pending_tracker.max_gap=5
            result=self.session.observe(self.session.token,at,boxes,dungeon)
        else:
            tracker=self.session.tracker or self.session.pending_tracker
            if tracker is not None:tracker.clear_candidate()
        return dict(identity=identity,result=result,dungeon=dungeon)
