"""입력 출처와 분리된 라이브 관측 → 기존 SQLite 세션 연결."""
import uuid
from .dungeon import key
from .character import CharacterTracker
from .state_session import StateSession
from .completion_banner import CompletionBanner

class LiveCoordinator:
    def __init__(self,store):
        self.identity=CharacterTracker(max_gap=5)
        self.session=StateSession(store)
        self.context=None;self.context_pair=None;self.candidate=None;self.count=0
        self.banner=CompletionBanner();self.last_array_at=None;self.recent_icon_completion=None
    def confirm(self,name):
        if self.context is None:return
        run,n=self.context
        self.session.confirm_character('name:'+name,name,run,n,'live_capture',is_test=True)
        self.session.tracker.max_gap=5
    def update(self,at,character,boxes,dungeon):
        identity=self.identity.update(at.timestamp(),character)
        suspended=any(a['type']=='suspend' for a in identity['actions'])
        if suspended:
            self.session.begin_character_change();self.context=None;self.context_pair=None;self.candidate=None;self.count=0
            self.banner.reset();self.last_array_at=None;self.recent_icon_completion=None
        # 이름 확인은 메뉴에서 이루어지므로 당시 던전 UI가 가려져도 기존 보류 구간을 확정합니다.
        for action in identity['actions']:
            if action['type']=='confirmed':self.confirm(action['name'])
        frame_pair=tuple(key(dungeon[f]) for f in ('dungeonName','difficulty')) if dungeon.get('contextStatus')=='ocr_verified' else None
        gateless=dungeon.get('raidKind')=='gateless' and dungeon.get('currentRaidPanel') and frame_pair is not None
        if gateless:
            # 단일 콘텐츠 상태를 기존 원자적 저장 경로로 전달하는 내부 슬롯입니다.
            bounds=dungeon.get('raidBounds')
            boxes=[dict(state='진행중',confidence=1.,xyxy=bounds)] if bounds else []
        valid=frame_pair is not None and 1<=len(boxes)<=8 and all(b['confidence']>=.5 for b in boxes)
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
        signature=(*pair,len(boxes),dungeon.get('raidKind') or 'gated') if valid else None
        self.count=self.count+1 if signature is not None and signature==self.candidate else (1 if signature else 0)
        self.candidate=signature
        result={}
        banner_target=None
        if signature and not suspended:
            # 추적기는 모드별로 구분하되 저장 키는 캐릭터·던전·관문입니다.
            run=str(uuid.uuid5(uuid.NAMESPACE_URL,'beatrice-test:'+repr(signature)))
            context=(run,len(boxes))
            if self.context!=context:
                if self.context is not None:self.session.begin_character_change()
                self.last_array_at=None;self.recent_icon_completion=None
                self.context=context
                self.context_pair=pair
                if identity['recordingAllowed']:self.confirm(identity['currentName'])
                else:
                    self.session.prepare_pending_run(run,len(boxes),'live_capture',is_test=True)
                    self.session.pending_tracker.max_gap=5
            tracker=self.session.tracker or self.session.pending_tracker
            progress=[i+1 for i,state in enumerate(tracker.stable or ()) if state=='진행중']
            if gateless:banner_target=(self.session.token,pair,1)
            elif self.last_array_at is not None and at.timestamp()-self.last_array_at<=10 and len(progress)==1:
                banner_target=(self.session.token,pair,progress[0])
            result=self.session.observe(self.session.token,at,boxes,dungeon)
            if result.get('status')=='stable':self.last_array_at=at.timestamp()
            completed=[r['gate'] for r in result.get('changedRecords',[]) if r['state']=='완료' and r['evidenceType']=='direct']
            if completed:self.recent_icon_completion=(self.session.token,pair,max(completed),at.timestamp())
        else:
            tracker=self.session.tracker or self.session.pending_tracker
            if tracker is not None:tracker.clear_candidate()
        eligible=bool(not suspended and frame_pair is not None and dungeon.get('currentRaidPanel')
                      and frame_pair==self.context_pair and not count_mismatch)
        recent=self.recent_icon_completion
        if not self.banner.active and recent and recent[:2]==(self.session.token,frame_pair) and at.timestamp()-recent[3]<=5:
            # 아이콘 확정 직후 늦게 나타난 같은 배너를 다음 관문에 붙이지 않습니다.
            banner_target=recent[:3]
        if self.banner.active:
            held=self.banner.target
            if held and held[:2]==(self.session.token,frame_pair):banner_target=held
        elif eligible and banner_target is None and self.last_array_at is not None and at.timestamp()-self.last_array_at<=10:
            tracker=self.session.tracker or self.session.pending_tracker
            progress=[i+1 for i,state in enumerate(tracker.stable or ()) if state=='진행중'] if tracker else []
            if len(progress)==1:banner_target=(self.session.token,frame_pair,progress[0])
        preview=dungeon.get('preview',{})
        raw_pair=tuple(key(preview[f]) for f in ('dungeonName','difficulty')) if all(preview.get(f) for f in ('dungeonName','difficulty')) else frame_pair
        scene=(self.session.token,raw_pair,dungeon.get('raidKind')) if dungeon.get('currentRaidPanel') and raw_pair else None
        trigger=self.banner.update(at.timestamp(),bool(dungeon.get('completionBanner')),eligible,banner_target,scene)
        if trigger:
            changed=self.session.complete_banner(at,dungeon,trigger[2])
            self.banner.commit()
            self.recent_icon_completion=(*trigger,at.timestamp())
            result.setdefault('changedRecords',[]).extend(changed)
            result.setdefault('events' if self.session.character else 'pendingEvents',[]).extend(changed)
            if changed:result['bannerCompleted']=True
        if result.get('bannerCompleted'):
            status='완료 배너 확인 · '+('레이드' if gateless else '관문')+(' 완료 저장됨' if self.session.character else ' 완료 임시 저장 · 캐릭터 확인 대기')
        elif not valid:
            reasons={'region_missing':'관문 영역 재탐지 중','gate_unverified':'관문 상태 재확인 중',
                     'reuse_rejected':'화면 변경 확인 중','text_unverified':'던전명·모드 재확인 중'}
            status=reasons.get(dungeon.get('diagnosticStatus'),'던전명·모드 재확인 중')
            if count_mismatch:status='관문 수 불일치 · 전체 관문 재확인 중'
            if dungeon.get('contextStatus')=='ocr_held':status='이전 던전명 유지 · '+status
        elif result.get('events'):status='관문 완료 저장됨'
        elif result.get('pendingEvents'):status='관문 완료 임시 저장 · 캐릭터 확인 대기'
        elif self.count<3:status='현재 관문 감지 중 · 던전 정보 확인 중'
        elif result.get('status') in ('uncertain','waiting'):status='현재 관문 감지 중 · 관문 배열 재확인 중'
        elif result.get('status')=='candidate':status='현재 관문 감지 중 · 상태 변경 확인 중'
        elif not identity['recordingAllowed']:status='현재 관문 감지 중 · 캐릭터 확인 대기'
        else:status='현재 관문 감지 중 · 완료 변화 대기'
        return dict(identity=identity,result=result,dungeon=dungeon,recordingStatus=status)
