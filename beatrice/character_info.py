"""Portable character metadata captured for a completion, without local paths."""
import copy
from decimal import Decimal, InvalidOperation

FIELDS = {'className', 'itemLevel', 'serverName', 'fetchedAt'}


def validate_info(value):
    if value is None: return None
    if not isinstance(value, dict): raise ValueError('캐릭터 정보 필드 오류')
    value = copy.deepcopy(value)
    value.pop('source', None)  # Read old files, but never write this removed field.
    if set(value) != FIELDS:
        raise ValueError('캐릭터 정보 필드 오류')
    for key in ('className', 'serverName'):
        text = value[key]
        if text is not None and (not isinstance(text, str) or not text.strip() or len(text) > 100 or any(ord(c) < 32 for c in text)):
            raise ValueError('캐릭터 직업·서버 정보 오류')
    level = value['itemLevel']
    if level is not None:
        try:
            if not isinstance(level, str) or len(level) > 30: raise ValueError()
            number = Decimal(level.replace(',', ''))
            if not number.is_finite() or number <= 0: raise ValueError()
        except (InvalidOperation, ValueError):
            raise ValueError('캐릭터 아이템 레벨 오류') from None
    if value['fetchedAt'] is not None:
        if not isinstance(value['fetchedAt'], str): raise ValueError('캐릭터 조회 시각 오류')
        from .record_identity import normalized_time
        normalized_time(value['fetchedAt'])
    return copy.deepcopy(value)


def from_cache(entry):
    profile = (entry or {}).get('profile', {})
    level = str(profile.get('ItemAvgLevel') or '').strip() or None
    try:
        number = Decimal((level or '').replace(',', ''))
        if not number.is_finite() or number <= 0 or len(level) > 30: level = None
    except InvalidOperation: level = None
    fetched = (entry or {}).get('fetchedAt')
    if fetched is not None:
        from .record_identity import normalized_time
        try: normalized_time(fetched)
        except (ValueError, TypeError): fetched = None
    value = dict(className=profile.get('CharacterClassName') or None,
                 itemLevel=level, serverName=profile.get('ServerName') or None,
                 fetchedAt=fetched)
    return validate_info(value)
