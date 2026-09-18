"""이름 관측을 안정화합니다. 변경 대상만으로 접속 완료를 추정하지 않습니다."""
import math
import unicodedata


def valid_name(reading, minimum=.65):
    if not reading or not math.isfinite(reading.get('confidence',0)) or reading.get('confidence',0) < minimum:
        return None
    name=unicodedata.normalize('NFC', reading.get('text','')).strip()
    if not 2 <= len(name) <= 16 or not all(c.isalnum() for c in name):
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

    def update(self, seconds, observation):
        if not math.isfinite(seconds) or (self.last_time is not None and seconds <= self.last_time):
            raise ValueError('관측 시각은 유한한 값이며 증가해야 합니다.')
        if self.last_time is not None and seconds-self.last_time > self.max_gap:
            self.candidate=None
            self.count=0
        self.last_time=seconds
        actions=[]
        name=valid_name(observation.get('currentName'))
        target=valid_name(observation.get('targetName'))
        dialog=bool(observation.get('switchDialog'))
        if dialog:
            if not self.dialog_open:
                actions.append(dict(type='suspend'))
            self.blocked=True
            self.switching=True
            self.target=target  # 실패한 읽기에 이전 대상 이름을 재사용하지 않습니다.
            self.candidate=None
            self.count=0
            self.saw_absence=False
        elif name is None:
            self.candidate=None
            self.count=0
            if self.switching and not observation.get('currentRegionVisible'):
                self.saw_absence=True
        else:
            # 팝업 직후 남아 있는 초상화는 취소/전환을 구분하지 못합니다.
            eligible=not self.switching or bool(observation.get('normalMenu')) or (self.saw_absence and name != self.current)
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
        self.dialog_open=dialog
        return dict(currentName=self.current,pendingName=self.target,
                    recordingAllowed=not self.blocked,
                    status='awaiting_current_confirmation' if self.blocked else 'confirmed',actions=actions)


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
