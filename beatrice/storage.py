"""이벤트, 동기화 대기, 관문 체크포인트를 한 트랜잭션으로 저장합니다."""
import json
from contextlib import nullcontext
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2, 3):
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
        if dungeon_key is not None:conditions.append('dungeon_key=?');values.append(dungeon_key)
        if conditions:sql+=' WHERE '+' AND '.join(conditions)
        return [json.loads(row[0]) for row in self.db.execute(sql+' ORDER BY owner,dungeon_key,gate',values)]

    def save_states(self,owner,dungeon_key,records,transactional=True):
        """검증된 전체 배열만 한 트랜잭션으로 갱신. 완료 행은 변경하지 않습니다."""
        from .gates import STATES
        if not records or [r['gate'] for r in records]!=list(range(1,len(records)+1)):
            raise ValueError('전체 관문 배열이 필요합니다.')
        if any(r['state'] not in STATES for r in records):raise ValueError('관문 상태 오류')
        changed=[]
        with self.db if transactional else nullcontext():
            old={r['gate']:r for r in self.state_records(owner,dungeon_key)}
            if max((r.get('expectedGates',r['gate']) for r in old.values()),default=0)>len(records):
                raise ValueError('기존 전체 관문보다 적은 배열입니다.')
            for record in records:
                previous=old.get(record['gate'])
                if previous and (previous['state']=='완료' or previous['state']==record['state']):continue
                row=dict(record,expectedGates=len(records),recordType='gate_state')
                self.db.execute('INSERT INTO gate_states VALUES (?,?,?,?) ON CONFLICT(owner,dungeon_key,gate) DO UPDATE SET payload=excluded.payload',
                    (owner,dungeon_key,row['gate'],json.dumps(row,ensure_ascii=False)))
                changed.append(row)
        return changed

    def clear_all(self):
        """분석 작업자가 정지한 뒤 호출합니다. 모델/설정은 보존합니다."""
        with self.db:
            for table in ("gate_states", "outbox", "pending_events", "events", "pending_segments", "sessions"):
                self.db.execute(f"DELETE FROM {table}")

    def close(self):
        self.db.close()
