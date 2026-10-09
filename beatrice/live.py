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
        self.banner=CompletionBanner();self.completion_context=None;self.completion_seen_at=None
        self.gate_recheck=None
    def confirm(self,name):
        if self.context is None:return
        run,n=self.context
        self.session.confirm_character('name:'+name,name,run,n,'live_capture',is_test=True)
        self.session.tracker.max_gap=5
    def capture_interrupted(self):
        """Keep confirmed state; unavailable capture cannot count as an observation."""
        self.candidate=None;self.count=0
        self.gate_recheck=None
        self.identity.candidate=None;self.identity.count=0
        self.identity.recovery_count=0;self.identity.login_count=0;self.identity.login_recovery=0
        self.banner.count=0;self.banner.last=None
        for tracker in (self.session.tracker,self.session.pending_tracker):
            if tracker is not None:tracker.clear_candidate()
    def update(self,at,character,boxes,dungeon):
        identity=self.identity.update(at.timestamp(),character)
        suspended=any(a['type']=='suspend' for a in identity['actions'])
        if suspended:
            self.session.begin_character_change();self.context=None;self.context_pair=None;self.candidate=None;self.count=0
            self.banner.reset();self.completion_context=None;self.completion_seen_at=None
            self.gate_recheck=None
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
        if signature and not suspended:
            # 추적기는 모드별로 구분하되 저장 키는 캐릭터·던전·관문입니다.
            run=str(uuid.uuid5(uuid.NAMESPACE_URL,'beatrice-test:'+repr(signature)))
            context=(run,len(boxes))
            if self.context!=context:
                if self.context is not None:self.session.begin_character_change()
                self.completion_context=None;self.completion_seen_at=None
                self.gate_recheck=None
                self.context=context
                self.context_pair=pair
                if identity['recordingAllowed']:self.confirm(identity['currentName'])
                else:
                    self.session.prepare_pending_run(run,len(boxes),'live_capture',is_test=True)
                    self.session.pending_tracker.max_gap=5
            result=self.session.observe(self.session.token,at,boxes,dungeon)
            tracker=self.session.tracker or self.session.pending_tracker
            if tracker and tracker.stable is not None:
                self.completion_context=dict(dungeon)
                self.completion_seen_at=at.timestamp()
        else:
            tracker=self.session.tracker or self.session.pending_tracker
            if tracker is not None:tracker.clear_candidate()
        # A new visible header invalidates the old context immediately, even while
        # the display tracker deliberately retains its previous title for 10 seconds.
        preview=dungeon.get('preview',{})
        different=any(preview.get(f) and key(preview[f])!=self.context_pair[i]
                      for i,f in enumerate(('dungeonName','difficulty'))) if self.context_pair else False
        different=different or bool(frame_pair and self.context_pair and frame_pair!=self.context_pair)
        if different or count_mismatch:
            self.completion_context=None;self.completion_seen_at=None
        # Fresh matching title/mode still identifies the raid when an icon is
        # temporarily unreadable. Reuse only its already-confirmed gate count.
        tracker=self.session.tracker or self.session.pending_tracker
        if (not suspended and not different and not count_mismatch
            and frame_pair is not None and frame_pair==self.context_pair
            and dungeon.get('currentRaidPanel') and self.context is not None
            and tracker is not None and tracker.stable is not None
            and len(tracker.stable)==self.context[1]):
            self.completion_context=dict(dungeon)
            self.completion_seen_at=at.timestamp()
        if self.completion_seen_at is not None and at.timestamp()-self.completion_seen_at>120:
            self.completion_context=None;self.completion_seen_at=None
        overlay=dungeon.get('completionOverlay') or {}
        held=self.completion_context
        # Banners on gated content request a new observation; they never supply
        # completed states or infer the last gate from generic clear text.
        gate=None;banner_target=None
        is_gateless=bool(held and held.get('raidKind')=='gateless')
        if held and self.context:
            if overlay.get('kind')=='dungeon_clear':
                banner_target=1 if is_gateless else 'all_gates'
                if is_gateless:gate=1
            elif overlay.get('kind')=='gate_breakthrough' and not is_gateless:
                gate=overlay.get('gate')
                if isinstance(gate,int) and not isinstance(gate,bool) and 1<=gate<=self.context[1]:
                    banner_target=gate
        eligible=bool(not suspended and held and overlay.get('status')=='verified' and banner_target is not None)
        target=(self.session.token,self.context_pair,banner_target) if eligible else None
        visible=overlay.get('status') not in (None,'missing','not_requested')
        scene=(self.session.token,self.context_pair)
        recheck_decision=None
        if self.gate_recheck:
            if not held or self.gate_recheck['scene']!=scene or at.timestamp()>self.gate_recheck['until']:
                self.gate_recheck=None
                recheck_decision='gate_recheck_cancelled'
            elif valid and result.get('status')=='stable':
                # StateSession already required repeated fresh icon observations.
                self.gate_recheck=None
                recheck_decision='gate_recheck_confirmed'
        trigger=self.banner.update(at.timestamp(),visible,eligible,target,scene)
        decision='missing' if not visible else 'context_unavailable' if not held else 'text_or_gate_unverified' if not eligible else 'confirming'
        if trigger:
            if is_gateless:
                evidence=dict(held,completionOverlay=overlay)
                changed=self.session.complete_banner(at,evidence,1)
                result.setdefault('changedRecords',[]).extend(changed)
                result.setdefault('events' if self.session.character else 'pendingEvents',[]).extend(changed)
                decision='saved' if changed else 'already_completed'
                if changed:result['bannerCompleted']=True
            else:
                self.gate_recheck=dict(scene=scene,until=at.timestamp()+10)
                result['gateRecheckRequested']=True
                decision='gate_recheck_requested'
            self.banner.commit()
        elif self.gate_recheck:decision='gate_recheck_pending'
        elif recheck_decision:decision=recheck_decision
        elif self.banner.consumed:decision='already_consumed'
        result['gateRecheckPending']=self.gate_recheck is not None
        result['completionDecision']=dict(reason=decision,gate=gate,context=held,observation=overlay)
        if result.get('bannerCompleted'):
            status='완료 배너 확인 · '+('레이드' if held and held.get('raidKind')=='gateless' else '관문')+(' 완료 저장됨' if self.session.character else ' 완료 임시 저장 · 캐릭터 확인 대기')
        elif result.get('gateRecheckPending') and not result.get('events') and not result.get('pendingEvents'):
            status='완료 표시 확인 · 관문 상태 재확인 중'
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
