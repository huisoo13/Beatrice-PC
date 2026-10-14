"""SQLite schema and legacy metadata migrations; no application lifecycle."""
import json
from .record_identity import record_id, existing_time


def initialize_schema(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0, 1, 2, 3, 4, 5):
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
    CREATE TABLE IF NOT EXISTS record_character_pending (
        record_id TEXT PRIMARY KEY REFERENCES completion_history(record_id) ON DELETE CASCADE);
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
            db.execute("DELETE FROM gate_states WHERE json_extract(payload,'$.state') IS NOT '완료' AND json_extract(payload,'$.contentName') IS NULL")
            db.execute('PRAGMA user_version=4')
    if version>=5:
        completion_constraints(db)
        return
    db.execute('DROP TRIGGER IF EXISTS completion_only_insert')
    db.execute('DROP TRIGGER IF EXISTS completion_only_update')
    db.executescript('''
    CREATE TRIGGER IF NOT EXISTS completion_only_insert BEFORE INSERT ON gate_states
    WHEN json_extract(NEW.payload,'$.state') IS NOT '완료' AND json_extract(NEW.payload,'$.contentName') IS NULL
    BEGIN SELECT RAISE(ABORT,'Only completed gates may be stored'); END;
    CREATE TRIGGER IF NOT EXISTS completion_only_update BEFORE UPDATE ON gate_states
    WHEN json_extract(NEW.payload,'$.state') IS NOT '완료' AND json_extract(NEW.payload,'$.contentName') IS NULL
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

    from .completion_record import canonical,validate
    with db:
        db.execute('DROP TRIGGER IF EXISTS completion_only_insert')
        db.execute('DROP TRIGGER IF EXISTS completion_only_update')
        db.execute("CREATE TABLE gate_states_v5 (owner TEXT NOT NULL,dungeon_key TEXT NOT NULL,gate INTEGER NOT NULL CHECK(gate>=0),payload TEXT NOT NULL,PRIMARY KEY(owner,dungeon_key,gate))")
        for owner,dungeon,gate,payload in db.execute('SELECT owner,dungeon_key,gate,payload FROM gate_states').fetchall():
            old=json.loads(payload)
            if not old.get('characterName') or old.get('state','완료')!='완료':continue
            row=validate(canonical(old))
            owner=('test:' if row['isTest'] else '')+'name:'+row['characterName']
            db.execute('INSERT OR REPLACE INTO gate_states_v5 VALUES(?,?,?,?)',(owner,dungeon,row['gateNumber'],json.dumps(row,ensure_ascii=False)))
        db.execute('DROP TABLE gate_states')
        db.execute('ALTER TABLE gate_states_v5 RENAME TO gate_states')
        for identity,payload in db.execute('SELECT record_id,payload FROM completion_history').fetchall():
            old=json.loads(payload)
            if not old.get('characterName') or old.get('state','완료')!='완료':
                db.execute('DELETE FROM completion_history WHERE record_id=?',(identity,));continue
            row=validate(canonical(old))
            db.execute('UPDATE completion_history SET payload=? WHERE record_id=?',(json.dumps(row,ensure_ascii=False),identity))
        if any(not json.loads(payload)['isTest'] for payload, in db.execute('SELECT payload FROM gate_states UNION ALL SELECT payload FROM completion_history')):
            db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
        db.execute('PRAGMA user_version=5')

    completion_constraints(db)


def completion_constraints(db):
    from .completion_record import validate
    def valid(payload,gate):
        try:
            row=validate(json.loads(payload))
            return int(row['gateNumber']==gate)
        except (ValueError,TypeError,KeyError):return 0
    db.create_function('valid_completion',2,valid)
    db.executescript("""
        CREATE TRIGGER IF NOT EXISTS completion_only_insert BEFORE INSERT ON gate_states
        WHEN valid_completion(NEW.payload,NEW.gate)=0
        BEGIN SELECT RAISE(ABORT,'Canonical completion required'); END;
        CREATE TRIGGER IF NOT EXISTS completion_only_update BEFORE UPDATE ON gate_states
        WHEN valid_completion(NEW.payload,NEW.gate)=0
        BEGIN SELECT RAISE(ABORT,'Canonical completion required'); END;
    """)
