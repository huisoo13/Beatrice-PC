"""Portable record identity and UTC modification timestamps (PC/iOS contract)."""
from datetime import datetime, timedelta, timezone
import hashlib
import re
from .dungeon import key

UNKNOWN_UPDATED_AT = '1970-01-01T00:00:00.000Z'


def record_id(character, dungeon, gate):
    parts = (character, key(dungeon), str(gate))
    payload = b'beatrice-record-v1\n'
    for part in parts:
        encoded = part.encode('utf-8')
        payload += str(len(encoded)).encode('ascii') + b':' + encoded
    return 'br1_' + hashlib.sha256(payload).hexdigest()


def normalized_time(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('updatedAt은 시간대를 포함한 ISO 8601 시각이어야 합니다.')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        raise ValueError('updatedAt 시각이 올바르지 않습니다.') from None


def existing_time(row):
    for field in ('updatedAt', 'savedAt', 'confirmedAt', 'observedAt'):
        if row.get(field):
            try:
                return normalized_time(row[field])
            except ValueError:
                continue
    return UNKNOWN_UPDATED_AT


def stamp_local(row, previous=None):
    value = dict(row)
    if not row.get('characterName') or not row.get('dungeonName'):
        value.pop('recordID', None)
    else:
        gate = 0 if row.get('completionScope') == 'raid' else row['gate']
        value['recordID'] = record_id(row['characterName'], row['dungeonName'], gate)
    now = datetime.now(timezone.utc)
    if previous:
        prior = datetime.fromisoformat(existing_time(previous).replace('Z', '+00:00'))
        now = max(now, prior + timedelta(milliseconds=1))
    value['updatedAt'] = now.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    return value
