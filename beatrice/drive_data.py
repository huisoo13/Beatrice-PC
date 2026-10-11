"""Versioned PC record JSON, legacy reads and transactional restore."""
from collections import defaultdict
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import uuid

from .dungeon import key
from .gates import STATES
from .record_identity import record_id, normalized_time

from .completion_record import canonical, validate, deduplicate

LEGACY_FIELDS = {'characterName','dungeonName','difficulty','gate','state'}
MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 10000


def validate_records(records):
    if not isinstance(records,list) or len(records)>MAX_RECORDS:
        raise ValueError('기록은 최대 10,000개의 JSON 배열이어야 합니다.')
    by_id={}
    for row in records:
        if not isinstance(row,dict):raise ValueError('기록은 JSON 객체여야 합니다.')
        if 'contentName' not in row:
            if set(row) not in (LEGACY_FIELDS,LEGACY_FIELDS|{'recordID','updatedAt'}):
                raise ValueError('이전 기록 필드 오류')
            if row['state'] not in STATES:raise ValueError('이전 상태 값 오류')
            if type(row['gate']) is not int or not 0<=row['gate']<=8:raise ValueError('이전 관문 오류')
            for field in ('characterName','dungeonName','difficulty'):
                if not isinstance(row[field],str) or not row[field].strip() or len(row[field])>200 or any(ord(c)<32 for c in row[field]):raise ValueError('이전 이름 오류')
            if 'updatedAt' in row:normalized_time(row['updatedAt'])
            if row['state']!='완료':continue
            if 'recordID' in row and row['recordID']!=record_id(row['characterName'],row['dungeonName'],row['gate']) and not re.fullmatch(r'br2_[0-9a-f]{32}',str(row['recordID'])):
                raise ValueError('이전 recordID 오류')
            row=canonical(row)
        value=validate(row)
        if not key(value['contentName']):raise ValueError('콘텐츠명 오류')
        previous=by_id.get(value['recordId'])
        if previous:
            if previous['updatedAt']==value['updatedAt'] and previous!=value:
                raise ValueError('같은 recordId와 수정 시각에 서로 다른 기록이 있습니다.')
            if previous['updatedAt']>=value['updatedAt']:continue
        by_id[value['recordId']]=value
    legacy_groups=defaultdict(set)
    for r in by_id.values():
        if r['recordId'].startswith('br1_'):
            legacy_groups[(r['characterName'],key(r['contentName']))].add(r['gateNumber'])
    if any(0 in gates and gates!={0} for gates in legacy_groups.values()):raise ValueError('관문 없는 콘텐츠와 관문 기록이 혼합되어 있습니다.')
    return sorted(deduplicate(by_id.values()),key=lambda r:(r['characterName'],key(r['contentName']),r['gateNumber'],r['recordId']))


def merge_records(local,incoming,now=None):
    return validate_records(validate_records(local)+validate_records(incoming))


def export_records(store):
    rows=store.history_records()
    records=[row for row in rows if not row['isTest']]
    return validate_records(records),len(rows)-len(records)


def encode_records(records):
    body=json.dumps({'schemaVersion':4,'records':[row for row in validate_records(records) if not row['isTest']]},ensure_ascii=False,indent=2).encode('utf-8')
    if len(body)>MAX_BYTES:raise ValueError('JSON 파일은 4 MiB 이하여야 합니다.')
    return body


def export_snapshot(store):
    """Read rows and completion revision from the same SQLite snapshot."""
    with store.transaction(snapshot=True):
        revision = store.drive_revision()
        records, omitted = export_records(store)
    return records, omitted, revision


def decode_records(body):
    if len(body) > MAX_BYTES:
        raise ValueError('JSON 파일은 4 MiB 이하여야 합니다.')
    def unique_object(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('JSON에 중복 항목 이름이 있습니다.')
            result[k] = v
        return result
    try:
        value = json.loads(body.decode('utf-8-sig'), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError('올바른 UTF-8 JSON 파일이 아닙니다.') from None
    if isinstance(value,dict):
        if set(value)!={'schemaVersion','records'} or type(value['schemaVersion']) is not int or value['schemaVersion']!=4:raise ValueError('지원하지 않는 기록 JSON 버전')
        value=value['records']
    return validate_records(value)


def restore_records(store, records, backup_directory):
    """Call only after the capture worker has settled and UI writes are locked."""
    records = validate_records(records)
    now = datetime.now(timezone.utc)
    directory = Path(backup_directory)
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / (now.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex + '.sqlite3')
    # SQLite backup includes WAL data, unlike copying the .sqlite3 file.
    store.backup_to(backup)
    store.replace_history(records)
    return backup
