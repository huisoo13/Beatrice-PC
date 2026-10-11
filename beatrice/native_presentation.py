"""Convert domain observations and history into desktop presentation data."""
from datetime import datetime
from .content_match import ContentMatcher, record_detail


def record_view(row, cached=None, *, matcher=None):
    """Retain the stored matching decision and expose completed records only."""
    from .completion_record import recognition_record
    row=recognition_record(row)
    when = datetime.fromisoformat(row['observedAt']).astimezone().strftime('%Y.%m.%d %H:%M') if row.get('observedAt') else '완료 시각 미상'
    matcher = ContentMatcher(cached) if matcher is None else matcher
    detail = record_detail(row, cached, matcher=matcher)
    dungeon, mode = matcher.display_record_context(row)
    if row.get('ocrOriginal'): detail['ocrOriginal'] = row['ocrOriginal']
    return dict(character=row.get('characterName') or '캐릭터 확인 대기',
                dungeon=dungeon or '확인 대기', mode=mode or '확인 대기',
                gate=row.get('gateName') or ('레이드 전체' if row.get('completionScope') == 'raid' else f"{row['gate']}관문"),
                date=when, observedAt=row['observedAt'], detail=detail)


def empty_profile():
    return dict(character='캐릭터 확인 대기', message='캐릭터 미설정', active=False, characterState='unset')


def character_view(identity):
    status = identity.get('status')
    allowed = bool(identity.get('recordingAllowed') and identity.get('currentName'))
    name = identity.get('currentName') if allowed else identity.get('pendingName') or identity.get('previewName') or identity.get('currentName')
    if status in ('switching', 'initial_login_loading', 'initial_login_selection'):
        name = identity.get('pendingName') or name
        message = '캐릭터 변경 중' if status == 'switching' else '캐릭터 선택 중'
        state = 'selecting'
    elif allowed: message, state = '플레이 중', 'playing'
    elif status == 'awaiting_current_confirmation' and name: message, state = '캐릭터 확인 중', 'selecting'
    else: message, state = '캐릭터 미설정', 'unset'
    return dict(character=name or '캐릭터 확인 대기', message=message, active=state == 'playing', characterState=state)


def progress_unit(value):
    dungeon = value.get('dungeon', {})
    if dungeon.get('raidKind') == 'gateless': return '레이드 전체'
    result = value.get('result', {})
    states = result.get('observedStates', result.get('stableStates')) or []
    gate = next((i for i, state in enumerate(states, 1) if state == '진행중'), None)
    return f'{gate}관문' if gate else ''


def observation_view(value, matcher=None):
    profile = character_view(value.get('identity', {}))
    dungeon = value.get('dungeon', {})
    name, difficulty = dungeon.get('dungeonName'), dungeon.get('difficulty')
    if matcher: name, difficulty = matcher.display_context(name, difficulty)
    visible = bool(name and dungeon.get('contextStatus') in ('ocr_verified', 'ocr_held', 'ocr_partial'))
    profile.update(dungeon=name if visible else None,
        dungeonSubtitle=' · '.join(filter(None, [difficulty, progress_unit(value)])) if visible else '',
        dungeonState='진행 중', diagnostics=value.get('recordingStatus', ''))
    return profile


class DungeonFooter:
    """Display-only retention; never supplies context to completion recording."""
    def __init__(self):
        self.context = None
        self.unit = ''
        self.last_panel_seen = None

    def update(self, value, now):
        if value.get('identity',{}).get('recordingAllowed') is False:
            self.context=None;self.unit='';self.last_panel_seen=None
            return
        dungeon = value.get('dungeon', {})
        panel = dungeon.get('raidPanelVisible', dungeon.get('currentRaidPanel', False))
        if panel: self.last_panel_seen = now
        if dungeon.get('dungeonName') and dungeon.get('contextStatus') in ('ocr_verified', 'ocr_held', 'ocr_partial'):
            pair = dungeon.get('dungeonName'), dungeon.get('difficulty')
            previous = (self.context.get('dungeonName'), self.context.get('difficulty')) if self.context else None
            if pair != previous: self.unit = ''
            current_unit = progress_unit(value)
            if dungeon.get('contextStatus') != 'ocr_held' or (panel and current_unit): self.unit = current_unit
            self.context = dict(dungeonName=pair[0], difficulty=pair[1])
            # A held context received as the first observation starts one bounded grace period.
            if self.last_panel_seen is None: self.last_panel_seen = now

    def view(self, matcher, now):
        if not self.context or self.last_panel_seen is None or now-self.last_panel_seen >= 30:
            return dict(dungeon=None, dungeonSubtitle='', dungeonState='진행 중')
        name, difficulty = matcher.display_context(self.context['dungeonName'], self.context['difficulty'])
        return dict(dungeon=name, dungeonSubtitle=' · '.join(filter(None, [difficulty, self.unit])), dungeonState='진행 중')
