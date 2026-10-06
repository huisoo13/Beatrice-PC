"""이벤트, 동기화 대기, 관문 체크포인트를 한 트랜잭션으로 저장합니다."""
import json
from contextlib import nullcontext
import sqlite3
from pathlib import Path
from .record_identity import record_id, existing_time, stamp_local


class Store:
    def __init__(self, path, catalog=None):
        self.catalog = catalog
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2, 3, 4):
            raise ValueError('지원하지 않는 DB 버전')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS sessions (
            character_key TEXT NOT NULL, session_id TEXT NOT NULL,
            settings TEXT NOT NULL, checkpoint TEXT,
            PRIMARY KEY(character_key, session_id));
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, character_key TEXT NOT NULL,
            character_name TEXT NOT NULL, session_id TEXT NOT NULL,
            gate INTEGER NOT NULL CHECK(gate > 0), observed_at TEXT NOT NULL,
            confirmed_at TEXT NOT NULL, saved_at TEXT NOT NULL,
            schema_version INTEGER NOT NULL, payload TEXT NOT NULL,
            UNIQUE(character_key, session_id, gate),
            FOREIGN KEY(character_key, session_id) REFERENCES sessions(character_key, session_id));
        CREATE TABLE IF NOT EXISTS outbox (
            event_id TEXT PRIMARY KEY REFERENCES events(event_id),
            status TEXT NOT NULL CHECK(status IN ('pending','test_only','uploaded')),
            attempts INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pending_segments (
            segment_id TEXT PRIMARY KEY, context TEXT, checkpoint TEXT,
            status TEXT NOT NULL DEFAULT 'unresolved');
        CREATE TABLE IF NOT EXISTS pending_events (
            event_id TEXT PRIMARY KEY, segment_id TEXT NOT NULL REFERENCES pending_segments(segment_id),
            payload TEXT NOT NULL, resolved_event_id TEXT);
        CREATE TABLE IF NOT EXISTS gate_states (
            owner TEXT NOT NULL, dungeon_key TEXT NOT NULL, gate INTEGER NOT NULL CHECK(gate>0),
            payload TEXT NOT NULL, PRIMARY KEY(owner,dungeon_key,gate));
        CREATE TABLE IF NOT EXISTS drive_changes (
            id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL, revision INTEGER NOT NULL);
        INSERT OR IGNORE INTO drive_changes VALUES(1,lower(hex(randomblob(16))),0);
        CREATE TABLE IF NOT EXISTS drive_uploads (
            account TEXT PRIMARY KEY, epoch TEXT NOT NULL, revision INTEGER NOT NULL);
        ''')
        if version<3:
            from .dungeon import key
            with self.db:
                for payload,settings in self.db.execute('SELECT payload,settings FROM events JOIN sessions USING(character_key,session_id) ORDER BY confirmed_at'):
                    event=json.loads(payload)
                    if not event.get('dungeonName'):continue
                    event.update(state='완료',recordType='gate_state',expectedGates=json.loads(settings)['expectedGates'],evidenceType='legacy_completion')
                    self.db.execute('INSERT OR IGNORE INTO gate_states VALUES (?,?,?,?)',
                        (event['characterKey'],key(event['dungeonName']),event['gate'],json.dumps(event,ensure_ascii=False)))
                self.db.execute('PRAGMA user_version=3')
        if version<4:
            with self.db:
                self.db.execute("DELETE FROM gate_states WHERE json_extract(payload,'$.state') IS NOT '완료'")
                self.db.execute('PRAGMA user_version=4')
        self.db.executescript('''
        CREATE TRIGGER IF NOT EXISTS completion_only_insert BEFORE INSERT ON gate_states
        WHEN json_extract(NEW.payload,'$.state') IS NOT '완료'
        BEGIN SELECT RAISE(ABORT,'Only completed gates may be stored'); END;
        CREATE TRIGGER IF NOT EXISTS completion_only_update BEFORE UPDATE ON gate_states
        WHEN json_extract(NEW.payload,'$.state') IS NOT '완료'
        BEGIN SELECT RAISE(ABORT,'Only completed gates may be stored'); END;
        ''')
        # Add metadata without changing record contents or scheduling an upload.
        with self.db:
            for owner,dungeon,gate,payload in self.db.execute('SELECT owner,dungeon_key,gate,payload FROM gate_states').fetchall():
                row=json.loads(payload)
                if row.get('characterName') and row.get('dungeonName') and ('recordID' not in row or 'updatedAt' not in row):
                    row['recordID']=record_id(row['characterName'],row['dungeonName'],0 if row.get('completionScope')=='raid' else gate)
                    row['updatedAt']=existing_time(row)
                    self.db.execute('UPDATE gate_states SET payload=? WHERE owner=? AND dungeon_key=? AND gate=?',
                        (json.dumps(row,ensure_ascii=False),owner,dungeon,gate))

    def load(self, character_key, session_id, settings, transactional=True):
        encoded = json.dumps(settings, sort_keys=True, ensure_ascii=False)
        with self.db if transactional else nullcontext():
            self.db.execute('INSERT OR IGNORE INTO sessions VALUES (?,?,?,NULL)',
                            (character_key, session_id, encoded))
        row = self.db.execute('SELECT settings,checkpoint FROM sessions WHERE character_key=? AND session_id=?',
                              (character_key, session_id)).fetchone()
        if row[0] != encoded:
            raise ValueError('동일 세션의 관문 수·시각 기준·출처가 다릅니다. 올바른 세션 ID를 사용해주세요.')
        return json.loads(row[1]) if row[1] else None

    def commit(self, character_key, session_id, checkpoint, events, transactional=True):
        inserted = []
        with self.db if transactional else nullcontext():
            for event in events:
                cursor = self.db.execute('''INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(character_key,session_id,gate) DO NOTHING''',
                    (event['eventID'], character_key, event['characterName'], session_id,
                     event['gate'], event['observedAt'], event['confirmedAt'], event['savedAt'],
                     event['schemaVersion'], json.dumps(event, ensure_ascii=False)))
                if cursor.rowcount:
                    self.db.execute('INSERT INTO outbox(event_id,status) VALUES (?,?)',
                                    (event['eventID'], 'test_only' if event['isTest'] else 'pending'))
                    inserted.append(event)
            cursor = self.db.execute('UPDATE sessions SET checkpoint=? WHERE character_key=? AND session_id=?',
                                     (json.dumps(checkpoint, ensure_ascii=False), character_key, session_id))
            if cursor.rowcount != 1:
                raise ValueError('저장할 진행 세션이 없습니다.')
        return inserted

    def new_segment(self, segment_id):
        with self.db:
            self.db.execute('INSERT INTO pending_segments(segment_id) VALUES (?)', (segment_id,))

    def save_pending(self, segment_id, context, checkpoint, events):
        with self.db:
            row=self.db.execute('SELECT context,status FROM pending_segments WHERE segment_id=?',(segment_id,)).fetchone()
            encoded=json.dumps(context,sort_keys=True,ensure_ascii=False)
            if row is None or row[1]!='unresolved' or (row[0] is not None and row[0]!=encoded):
                raise ValueError('보류 구간의 진행 정보가 다릅니다.')
            self.db.execute('UPDATE pending_segments SET context=?,checkpoint=? WHERE segment_id=?',
                            (encoded,json.dumps(checkpoint),segment_id))
            for event in events:
                self.db.execute('INSERT OR IGNORE INTO pending_events VALUES (?,?,?,NULL)',
                                (event['eventID'],segment_id,json.dumps(event,ensure_ascii=False)))

    def pending_records(self):
        return [dict(json.loads(payload),segmentID=segment,resolvedEventID=resolved)
                for segment,payload,resolved in self.db.execute(
                    'SELECT segment_id,payload,resolved_event_id FROM pending_events ORDER BY rowid')]

    def records(self):
        return [dict(json.loads(payload), syncStatus=status) for payload,status in self.db.execute(
            'SELECT payload,status FROM events JOIN outbox USING(event_id) ORDER BY confirmed_at,event_id')]

    def state_records(self,owner=None,dungeon_key=None):
        sql='SELECT payload FROM gate_states';conditions=[];values=[]
        if owner is not None:conditions.append('owner=?');values.append(owner)
        if dungeon_key is not None and self.catalog is None:conditions.append('dungeon_key=?');values.append(dungeon_key)
        if conditions:sql+=' WHERE '+' AND '.join(conditions)
        rows = [json.loads(row[0]) for row in self.db.execute(sql+' ORDER BY owner,dungeon_key,gate',values)]
        if dungeon_key is not None and self.catalog is not None:
            from .dungeon import key
            matcher = self.catalog()
            candidates = matcher.dungeon_candidates(dungeon_key)
            names = {dungeon_key}
            if len(candidates) == 1:names.add(key(candidates[0]))
            def belongs(row):
                aliases = {key(row['dungeonName']),
                           key(row.get('ocrOriginal', {}).get('dungeonName') or row['dungeonName'])}
                # A later catalog download must not create a second completion
                # beside a previously saved OCR-only record. Do not rewrite it.
                match = matcher.match(row['dungeonName'], row['difficulty'], row['gate'],
                                      row.get('completionScope') == 'raid')
                if match['status'] == 'matched':aliases.add(key(match['dungeonName']))
                return bool(names.intersection(aliases))
            rows = [r for r in rows if belongs(r)]
        return rows

    def save_states(self,owner,dungeon_key,records,transactional=True):
        """검증된 전체 배열에서 완료만 저장합니다. 진행 상태는 호출자 메모리에 남습니다."""
        from .gates import STATES
        if not records or [r['gate'] for r in records]!=list(range(1,len(records)+1)):
            raise ValueError('전체 관문 배열이 필요합니다.')
        if any(r['state'] not in STATES for r in records):raise ValueError('관문 상태 오류')
        return self.save_completions(owner,dungeon_key,[r for r in records if r['state']=='완료'],len(records),transactional)

    def save_completions(self,owner,dungeon_key,records,expected_gates,transactional=True):
        """완료 행만 원자적으로 추가합니다. 기존 완료의 내용과 시각은 보존합니다."""
        if not records:return []
        gates=[r['gate'] for r in records]
        if (not 1<=expected_gates<=8 or len(set(gates))!=len(gates) or
            any(type(g) is not int or not 1<=g<=expected_gates for g in gates) or
            any(r['state']!='완료' for r in records)):raise ValueError('완료 관문 배열 오류')
        changed=[]
        matcher = self.catalog() if self.catalog is not None else None
        with self.db if transactional else nullcontext():
            old={r['gate']:r for r in self.state_records(owner,dungeon_key)}
            if max((r.get('expectedGates',r['gate']) for r in old.values()),default=0)>expected_gates:
                raise ValueError('기존 전체 관문보다 적은 배열입니다.')
            for record in records:
                from .dungeon import key
                record = matcher.record(record) if matcher is not None else record
                storage_key = key(record['dungeonName']) if matcher is not None else dungeon_key
                previous=old.get(record['gate'])
                if previous is None and storage_key != dungeon_key:
                    previous=next((r for r in self.state_records(owner,storage_key) if r['gate']==record['gate']),None)
                if previous and previous['state']=='완료':continue
                if previous and all(previous.get(f)==record.get(f) for f in
                        ('state','difficulty','characterName','dungeonName','completionScope')):continue
                row=dict(record,expectedGates=expected_gates,recordType='gate_state')
                row=stamp_local(row,previous)
                self.db.execute('INSERT INTO gate_states VALUES (?,?,?,?) ON CONFLICT(owner,dungeon_key,gate) DO UPDATE SET payload=excluded.payload',
                    (owner,storage_key,row['gate'],json.dumps(row,ensure_ascii=False)))
                changed.append(row)
            if any(r['state']=='완료' and r.get('characterName') and r.get('dungeonName')
                   and r.get('difficulty') and not r.get('isTest')
                   and r.get('timeBasis')!='synthetic_test' for r in changed):
                # Persist the upload obligation in the same transaction as completion.
                self.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
        return changed

    def drive_revision(self):
        return self.db.execute('SELECT epoch,revision FROM drive_changes WHERE id=1').fetchone()

    def drive_pending(self,account):
        row=self.db.execute('''SELECT c.epoch,c.revision FROM drive_changes c
            LEFT JOIN drive_uploads u ON u.account=? AND u.epoch=c.epoch
            WHERE c.id=1 AND c.revision>COALESCE(u.revision,0)''',(account,)).fetchone()
        return tuple(row) if row else None

    def acknowledge_drive(self,account,epoch,revision):
        with self.db:
            if self.drive_revision()[0]!=epoch:return
            self.db.execute('''INSERT INTO drive_uploads VALUES(?,?,?)
                ON CONFLICT(account) DO UPDATE SET epoch=excluded.epoch,
                revision=CASE WHEN drive_uploads.epoch=excluded.epoch
                    THEN MAX(drive_uploads.revision,excluded.revision) ELSE excluded.revision END''',
                (account,epoch,revision))

    def reset_drive_queue(self):
        """Part of the caller's clear/restore transaction; don't publish old pending data."""
        self.db.execute('UPDATE drive_changes SET epoch=lower(hex(randomblob(16))),revision=0 WHERE id=1')
        self.db.execute('DELETE FROM drive_uploads')

    def clear_all(self):
        """분석 작업자가 정지한 뒤 호출합니다. 모델/설정은 보존합니다."""
        with self.db:
            for table in ("gate_states", "outbox", "pending_events", "events", "pending_segments", "sessions"):
                self.db.execute(f"DELETE FROM {table}")
            self.reset_drive_queue()

    def close(self):
        self.db.close()
