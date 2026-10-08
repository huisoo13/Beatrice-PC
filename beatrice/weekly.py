"""Wednesday 06:00 Korea repetition reset; completion history is retained."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOREA = timezone(timedelta(hours=9))


def week_start(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('시간대가 필요합니다.')
    local = now.astimezone(KOREA)
    start = local.replace(hour=6, minute=0, second=0, microsecond=0)
    start -= timedelta(days=(local.weekday()-2) % 7)
    if local < start:
        start -= timedelta(days=7)
    return start.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def database_path(data, now=None):
    return Path(data) / 'records.sqlite3'


def open_week(data, catalog=None, now=None):
    """One persistent history DB; recover all previous weekly databases without removing them."""
    import json
    import sqlite3
    from contextlib import closing
    from .storage import Store
    from .record_identity import existing_time
    store = Store(database_path(data), catalog=catalog)
    try:
        with store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS imported_weekly_sources (path TEXT PRIMARY KEY)')
            store.db.execute('CREATE TABLE IF NOT EXISTS history_export_initialized (id INTEGER PRIMARY KEY CHECK(id=1))')
            first_history_export = store.db.execute('SELECT 1 FROM history_export_initialized').fetchone() is None
            imported = {r[0] for r in store.db.execute('SELECT path FROM imported_weekly_sources')}
            changed = False
            for source in sorted((Path(data)/'weekly-records').glob('*.sqlite3')):
                name = str(source.resolve())
                if name in imported:
                    continue
                with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as old:
                    for payload, in old.execute('SELECT payload FROM gate_states'):
                        row=json.loads(payload)
                        if not row.get('recordID'):
                            from .record_identity import record_id, existing_time
                            if not row.get('characterName') or not row.get('dungeonName'):
                                continue
                            row=dict(row,recordID=record_id(row['characterName'],row['dungeonName'],0 if row.get('completionScope')=='raid' else row['gate']),updatedAt=existing_time(row))
                        changed = store.remember_completion(row) or changed
                        if existing_time(row) >= week_start(now):
                            from .dungeon import key
                            owner = row.get('characterKey') or 'name:' + row['characterName']
                            store.db.execute("""INSERT INTO gate_states VALUES(?,?,?,?)
                                ON CONFLICT(owner,dungeon_key,gate) DO UPDATE SET payload=excluded.payload
                                WHERE json_extract(excluded.payload,'$.updatedAt') > json_extract(gate_states.payload,'$.updatedAt')""",
                                (owner,key(row['dungeonName']),row['gate'],json.dumps(row,ensure_ascii=False)))
                store.db.execute('INSERT INTO imported_weekly_sources VALUES(?)', (name,))
            publish_legacy = first_history_export and any(
                r.get('state')=='완료' and r.get('characterName') and r.get('dungeonName') and r.get('difficulty')
                and not r.get('isTest') and r.get('timeBasis')!='synthetic_test'
                for r in store.history_records())
            if changed or publish_legacy:
                store.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
            store.db.execute('INSERT OR IGNORE INTO history_export_initialized VALUES(1)')
        store.roll_week(now)
    except Exception:
        store.close()
        raise
    return store
