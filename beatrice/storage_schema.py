"""SQLite schema and legacy metadata migrations; no application lifecycle."""
import json
from .record_identity import record_id, existing_time


def initialize_schema(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0, 1, 2, 3, 4):
        raise ValueError('지원하지 않는 DB 버전')
    db.executescript('''
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
    CREATE TABLE IF NOT EXISTS completion_history (
        record_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS weekly_repeat (
        id INTEGER PRIMARY KEY CHECK(id=1), period_start TEXT NOT NULL);
    INSERT OR IGNORE INTO weekly_repeat VALUES(1,'');
    CREATE TABLE IF NOT EXISTS drive_changes (
        id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT NOT NULL, revision INTEGER NOT NULL);
    INSERT OR IGNORE INTO drive_changes VALUES(1,lower(hex(randomblob(16))),0);
    CREATE TABLE IF NOT EXISTS drive_uploads (
        account TEXT PRIMARY KEY, epoch TEXT NOT NULL, revision INTEGER NOT NULL);
    ''')
    if version<3:
        from .dungeon import key
        with db:
            for payload,settings in db.execute('SELECT payload,settings FROM events JOIN sessions USING(character_key,session_id) ORDER BY confirmed_at'):
                event=json.loads(payload)
                if not event.get('dungeonName'):continue
                event.update(state='완료',recordType='gate_state',expectedGates=json.loads(settings)['expectedGates'],evidenceType='legacy_completion')
                db.execute('INSERT OR IGNORE INTO gate_states VALUES (?,?,?,?)',
                    (event['characterKey'],key(event['dungeonName']),event['gate'],json.dumps(event,ensure_ascii=False)))
            db.execute('PRAGMA user_version=3')
    if version<4:
        with db:
            db.execute("DELETE FROM gate_states WHERE json_extract(payload,'$.state') IS NOT '완료'")
            db.execute('PRAGMA user_version=4')
    db.executescript('''
    CREATE TRIGGER IF NOT EXISTS completion_only_insert BEFORE INSERT ON gate_states
    WHEN json_extract(NEW.payload,'$.state') IS NOT '완료'
    BEGIN SELECT RAISE(ABORT,'Only completed gates may be stored'); END;
    CREATE TRIGGER IF NOT EXISTS completion_only_update BEFORE UPDATE ON gate_states
    WHEN json_extract(NEW.payload,'$.state') IS NOT '완료'
    BEGIN SELECT RAISE(ABORT,'Only completed gates may be stored'); END;
    ''')
    # Add metadata without changing record contents or scheduling an upload.
    with db:
        for owner,dungeon,gate,payload in db.execute('SELECT owner,dungeon_key,gate,payload FROM gate_states').fetchall():
            row=json.loads(payload)
            if row.get('characterName') and row.get('dungeonName') and ('recordID' not in row or 'updatedAt' not in row):
                row['recordID']=record_id(row['characterName'],row['dungeonName'],0 if row.get('completionScope')=='raid' else gate)
                row['updatedAt']=existing_time(row)
                db.execute('UPDATE gate_states SET payload=? WHERE owner=? AND dungeon_key=? AND gate=?',
                    (json.dumps(row,ensure_ascii=False),owner,dungeon,gate))
