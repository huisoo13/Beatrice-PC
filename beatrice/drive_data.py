"""Shared PC/iOS JSON contract and transactional local restore."""
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .dungeon import key
from .gates import STATES
from .record_identity import record_id, normalized_time, existing_time, UNKNOWN_UPDATED_AT

FIELDS = ('characterName', 'dungeonName', 'difficulty', 'gate', 'state')
SYNC_FIELDS = ('recordID', 'updatedAt')
MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 10000


def validate_records(records):
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError('기록은 최대 10,000개의 JSON 배열이어야 합니다.')
    groups = defaultdict(set)
    by_id = {}
    for row in records:
        if not isinstance(row, dict) or set(row) not in (set(FIELDS), set(FIELDS + SYNC_FIELDS)):
            raise ValueError('다섯 기록 항목과 recordID·updatedAt 쌍을 확인해주세요.')
        for field in ('characterName', 'dungeonName', 'difficulty'):
            value = row[field]
            if (not isinstance(value, str) or not value.strip() or len(value) > 200
                    or any(ord(c) < 32 for c in value)):
                raise ValueError('캐릭터명·던전명·난이도 값이 올바르지 않습니다.')
        if type(row['gate']) is not int or not 0 <= row['gate'] <= 8:
            raise ValueError('관문은 1~8, 관문 없는 레이드는 0이어야 합니다.')
        if not isinstance(row['state'], str) or row['state'] not in STATES:
            raise ValueError('상태는 진행 전, 진행중, 완료 중 하나여야 합니다.')
        if not key(row['dungeonName']):
            raise ValueError('던전명이 올바르지 않습니다.')
        identity = record_id(row['characterName'], row['dungeonName'], row['gate'])
        if 'recordID' in row and row['recordID'] != identity:
            raise ValueError('recordID가 캐릭터·던전·관문과 일치하지 않습니다.')
        value = {field: row[field] for field in FIELDS}
        value.update(recordID=identity, updatedAt=normalized_time(row['updatedAt']) if 'updatedAt' in row else UNKNOWN_UPDATED_AT)
        previous = by_id.get(identity)
        if previous:
            if previous['updatedAt'] == value['updatedAt'] and previous != value:
                raise ValueError('같은 recordID와 수정 시각에 서로 다른 기록이 있습니다.')
            if previous['updatedAt'] >= value['updatedAt']:
                continue
        by_id[identity] = value
    validated = list(by_id.values())
    for row in validated:
        groups[(row['characterName'], key(row['dungeonName']))].add(row['gate'])
    for gates in groups.values():
        if gates != {0} and gates != set(range(1, len(gates) + 1)):
            raise ValueError('던전의 전체 관문을 1부터 순서대로 포함해야 합니다.')
    return sorted(validated, key=lambda r: (r['characterName'], key(r['dungeonName']), r['gate']))


def export_records(store):
    records = []
    omitted = 0
    for row in store.state_records():
        if (not row.get('characterName') or not row.get('dungeonName') or not row.get('difficulty')
                or row.get('isTest') or row.get('timeBasis') == 'synthetic_test'):
            omitted += 1
            continue
        record = {field: row[field] for field in FIELDS}
        if row.get('completionScope') == 'raid':
            record['gate'] = 0
        record['recordID'] = record_id(record['characterName'],record['dungeonName'],record['gate'])
        record['updatedAt'] = existing_time(row)
        records.append(record)
    return validate_records(records), omitted


def encode_records(records):
    body = json.dumps(validate_records(records), ensure_ascii=False, indent=2).encode('utf-8')
    if len(body) > MAX_BYTES:
        raise ValueError('JSON 파일은 4 MiB 이하여야 합니다.')
    return body


def export_snapshot(store):
    """Read rows and completion revision from the same SQLite snapshot."""
    with store.db:
        store.db.execute('BEGIN')
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
    return validate_records(value)


def restore_records(store, records, backup_directory):
    """Call only after the capture worker has settled and UI writes are locked."""
    records = validate_records(records)
    now = datetime.now(timezone.utc)
    directory = Path(backup_directory)
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / (now.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex + '.sqlite3')
    # SQLite backup includes WAL data, unlike copying the .sqlite3 file.
    with closing(sqlite3.connect(backup)) as destination:
        store.db.backup(destination)
    grouped = defaultdict(list)
    for row in records:
        grouped[(row['characterName'], key(row['dungeonName']))].append(row)
    at = now.isoformat()
    with store.db:
        for table in ('gate_states', 'outbox', 'pending_events', 'events', 'pending_segments', 'sessions'):
            store.db.execute(f'DELETE FROM {table}')
        store.reset_drive_queue()
        for (character, dungeon), rows in grouped.items():
            owner = 'name:' + character
            for row in rows:
                value = dict(row, gate=row['gate'] or 1, characterKey=owner,
                             expectedGates=len(rows), recordType='gate_state',
                             observedAt=at, confirmedAt=at, savedAt=at, completedAt=None,
                             evidenceType='drive_import', timeBasis='drive_import',
                             completionScope='raid' if row['gate'] == 0 else 'gate')
                store.db.execute('INSERT INTO gate_states VALUES (?,?,?,?)',
                                 (owner, dungeon, value['gate'], json.dumps(value, ensure_ascii=False)))
    return backup
