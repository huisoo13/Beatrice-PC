"""현재 이름과 변경 대상을 추적하고 전환 이후의 화면 관측으로 확정합니다."""
import math
import unicodedata


def valid_name(reading, minimum=.65):
    if not reading or not math.isfinite(reading.get('confidence',0)) or reading.get('confidence',0) < minimum:
        return None
    name=unicodedata.normalize('NFC', reading.get('text','')).strip()
    if not 2 <= len(name) <= 12 or not all(c.isalnum() for c in name):
        return None
    return name


class CharacterTracker:
    def __init__(self, confirmations=3, max_gap=.8):
        if confirmations < 2 or max_gap <= 0:
            raise ValueError('연속 관측 수와 간격이 올바르지 않습니다.')
        self.confirmations=confirmations
        self.max_gap=max_gap
        self.current=None
        self.target=None
        self.blocked=True
        self.switching=False
        self.saw_absence=False
        self.candidate=None
        self.count=0
        self.last_time=None
        self.dialog_open=False
        self.switch_deadline=None
        self.menu_returned_at=None
        self.recovery_count=0
        self.target_expires=None
        self.login_candidate=None
        self.login_count=0
        self.login_target=None
        self.login_loading=False
        self.login_recovery=0
        self.login_seen_at=None
        self.login_card=None

    def capture_interrupted(self):
        self.candidate = None
        self.count = 0
        self.recovery_count = 0
        self.login_count = 0
        self.login_recovery = 0

    def update(self, seconds, observation):
        if not math.isfinite(seconds) or (self.last_time is not None and seconds <= self.last_time):
            raise ValueError('관측 시각은 유한한 값이며 증가해야 합니다.')
        if self.last_time is not None and seconds-self.last_time > self.max_gap:
            self.candidate=None
            self.count=0
            self.recovery_count=0
            self.login_count=0;self.login_recovery=0
        self.last_time=seconds
        actions=[]
        # 메뉴 재관측은 최초 접속 흐름을 놓쳤을 때도 항상 사용할 수 있습니다.
        if observation.get('normalMenu') and valid_name(observation.get('currentName')):
            self.login_target=None;self.login_loading=False;self.login_recovery=0
        if self.login_seen_at is not None and seconds-self.login_seen_at>180:
            self.login_target=None;self.login_loading=False;self.login_recovery=0
        if observation.get('serverSelection') or observation.get('characterSelection'):
            if not self.blocked:actions.append(dict(type='suspend'))
            self.blocked=True;self.current=None;self.switching=False;self.target=None
            self.switch_deadline=None;self.login_loading=False;self.login_recovery=0
            selected=valid_name(observation.get('selectedName')) if observation.get('characterSelection') else None
            card=observation.get('selectedCard')
            if card and self.login_card:
                a=card;b=self.login_card
                overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                smaller=min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1]))
                # Compare detected cards, never predetermined screen positions.
                if smaller<=0 or overlap/smaller<.5:
                    self.login_candidate=None;self.login_count=0;self.login_target=None
            if card:self.login_card=list(card)
            if observation.get('serverSelection'):
                self.login_candidate=None;self.login_count=0;self.login_target=None
                self.login_card=None
            elif selected:
                if selected==self.login_candidate:self.login_count+=1
                else:self.login_count=1;self.login_target=None
                self.login_candidate=selected
                if self.login_count>=self.confirmations:self.login_target=selected
            else:
                # 비밀번호 창에 가려진 카드의 OCR 실패는 확정해 둔 대상을 지우지 않습니다.
                self.login_count=0
            self.login_seen_at=seconds
        elif observation.get('loginLoading') and self.login_target:
            self.login_loading=bool(self.login_target)
            self.login_recovery=0
            self.login_seen_at=seconds
        elif self.login_loading:
            self.login_recovery=self.login_recovery+1 if observation.get('loginLoadingAbsent') and not observation.get('selectionUncertain') else 0
            if self.login_recovery>=self.confirmations:
                self.current=self.login_target;self.blocked=False
                actions.append(dict(type='confirmed',name=self.current))
                self.login_target=None;self.login_loading=False;self.login_recovery=0
        if observation.get('serverSelection') or observation.get('characterSelection') or self.login_loading or self.login_target:
            self.last_time=seconds
            return dict(currentName=self.current,pendingName=self.login_target,previewName=self.login_candidate,
                        recordingAllowed=not self.blocked,status='initial_login_loading' if self.login_loading else 'initial_login_selection',actions=actions)
        name=valid_name(observation.get('currentName'))
        target=valid_name(observation.get('targetName'))
        dialog=bool(observation.get('switchDialog'))
        loading=bool(observation.get('switchLoading'))
        eligible=False
        if self.switching and self.target_expires is not None and seconds>self.target_expires:
            self.target=None;self.target_expires=None
        if self.switch_deadline is not None and seconds>self.switch_deadline:
            self.switch_deadline=None
            if not self.switching:self.target=None
        if not dialog and not loading and observation.get('normalMenu'):
            if self.menu_returned_at is None:self.menu_returned_at=seconds
            # 확인 후 팝업이 닫히고 로딩이 나타나기까지 잠깐 메뉴가 보입니다.
            # 한 프레임으로 취소를 단정하지 않고 안정된 메뉴 복귀를 확인합니다.
            if seconds-self.menu_returned_at>=2:
                self.switch_deadline=None
                if not self.switching:self.target=None
        else:
            self.menu_returned_at=None
        if loading:
            if self.switch_deadline is not None and not self.switching:
                actions.append(dict(type='suspend'))
                self.blocked=True
                self.switching=True
                self.switch_deadline=None
                self.target_expires=seconds+120
            # 로딩 중 남아 있는 기존 초상화로 다시 확정하지 않습니다.
            self.candidate=None
            self.count=0
        elif dialog:
            if not self.switching:
                if not self.dialog_open:self.target=None
                self.switch_deadline=seconds+max(3,self.max_gap*2)
                # 읽기 실패는 직전 대상을 지우지 않습니다. 다른 이름이 읽히면 교체합니다.
                if target is not None:self.target=target
            self.candidate=None
            self.count=0
        elif name is None:
            self.candidate=None
            self.count=0
            if self.switching and not observation.get('currentRegionVisible'):
                self.saw_absence=True
        else:
            eligible=not self.switching or name != self.current
            if name != self.current and not self.blocked:
                self.blocked=True
                actions.append(dict(type='suspend'))
            if eligible:
                if name==self.candidate:
                    self.count+=1
                else:
                    self.candidate=name
                    self.count=1
                if self.count >= self.confirmations and (self.blocked or name != self.current):
                    self.current=name
                    self.target=None
                    self.blocked=False
                    self.switching=False
                    self.saw_absence=False
                    actions.append(dict(type='confirmed',name=name))
            else:
                self.candidate=None
                self.count=0
        # 정상 캡처에서 로딩 영역이 연속으로 사라지면 보관한 대상을 확정합니다.
        # 누락된 캡처/불확실한 탐지에는 loadingAbsent를 공급하지 않습니다.
        recover=bool(self.switching and self.target and self.target_expires is not None
                     and seconds<=self.target_expires and observation.get('loadingAbsent')
                     and not dialog and not loading and not observation.get('normalMenu')
                     and not observation.get('currentRegionVisible') and name is None)
        self.recovery_count=self.recovery_count+1 if recover else 0
        if self.recovery_count>=self.confirmations:
            self.current=self.target
            self.target=None;self.blocked=False;self.switching=False;self.saw_absence=False
            self.candidate=None;self.count=0;self.recovery_count=0;self.target_expires=None
            actions.append(dict(type='confirmed',name=self.current))
        self.dialog_open=dialog
        return dict(currentName=self.current,pendingName=self.target,previewName=name if not dialog and not loading and eligible else None,
                    recordingAllowed=not self.blocked,
                    status='switching' if self.switching and self.target else 'awaiting_current_confirmation' if self.blocked else 'confirmed',actions=actions)


class CharacterRecordingBridge:
    """인식 결과 → 기존 저장 세션. 실제 진행 ID/서버 식별은 외부에서 제공합니다."""
    def __init__(self, recording, resolve_context):
        self.recording=recording
        self.resolve_context=resolve_context

    def apply(self, result):
        suspended=any(a['type']=='suspend' for a in result['actions'])
        if suspended or (not result['recordingAllowed'] and self.recording.character is not None):
            self.recording.begin_character_change()
        for action in result['actions']:
            if action['type']=='confirmed':
                context=self.resolve_context(action['name'])
                if context is not None:
                    self.recording.confirm_character(character_name=action['name'],**context)
        return self.recording.token
