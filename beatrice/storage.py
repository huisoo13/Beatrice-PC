"""이벤트, 동기화 대기, 관문 체크포인트를 한 트랜잭션으로 저장합니다."""
import json
from contextlib import nullcontext, contextmanager, closing
import sqlite3
from pathlib import Path
from .record_identity import existing_time
from .completion_record import canonical, validate, new_record, recognition_record, period, deduplicate


class Store:
    def __init__(self, path, catalog=None):
        self.catalog = catalog
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        if str(path) != ':memory:' and self.db.execute('PRAGMA user_version').fetchone()[0]<5 and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='gate_states'").fetchone():
            from datetime import datetime, timezone
            backup = Path(path).with_name(Path(path).name + '.pre-v5-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.bak')
            self.backup_to(backup)
        from .storage_schema import initialize_schema
        try:initialize_schema(self.db)
        except Exception:
            self.db.close()
            raise

        # Preserve existing completions independently of weekly recognition checkpoints.
        with self.db:
            for payload, in self.db.execute('SELECT payload FROM gate_states').fetchall():
                self.remember_completion(json.loads(payload))

    def remember_completion(self, row):
        if row.get('state', '완료') != '완료' or not row.get('characterName'):
            return False
        row = validate(canonical(row))
        previous = self.db.execute('SELECT payload FROM completion_history WHERE record_id=?', (row['recordId'],)).fetchone()
        if previous:
            previous = json.loads(previous[0])
            new_time = existing_time(row)
            if row['recordId'].startswith('br1_') and period(previous) is not None and period(row) is not None and period(previous)!=period(row):
                from .record_identity import occurrence_id
                row['recordId'] = occurrence_id(row['recordId'], row['observedAt'])
                previous = self.db.execute('SELECT payload FROM completion_history WHERE record_id=?', (row['recordId'],)).fetchone()
                previous = json.loads(previous[0]) if previous else None
            if previous and existing_time(previous) >= new_time:
                return False
        self.db.execute('INSERT INTO completion_history VALUES(?,?) ON CONFLICT(record_id) DO UPDATE SET payload=excluded.payload',
                        (row['recordId'], json.dumps(row,ensure_ascii=False)))
        return True

    def history_records(self):
        return [json.loads(payload) for payload, in self.db.execute('SELECT payload FROM completion_history ORDER BY record_id')]

    def repeat_start(self):
        return self.db.execute('SELECT period_start FROM weekly_repeat WHERE id=1').fetchone()[0]

    def pending_character_records(self):
        return [json.loads(payload) for payload, in self.db.execute(
            'SELECT h.payload FROM completion_history h JOIN record_character_pending p USING(record_id)')]

    def remove_character_info_source(self):
        """Remove legacy source only, preserving values and pending state locally."""
        changed = 0
        with self.transaction():
            for row in self.history_records():
                info = row.get('characterInfo')
                if not isinstance(info, dict) or 'source' not in info: continue
                if info['source'] == 'pending':
                    self.db.execute('INSERT OR IGNORE INTO record_character_pending VALUES(?)', (row['recordId'],))
                cleaned = dict(info)
                cleaned.pop('source')
                self._write_character_info(row, cleaned)
                changed += 1
        return changed

    def set_character_info(self, record_id, info, *, pending=False, finalize_pending=False):
        """Attach once, or finalize this new record's pending API snapshot once."""
        from .character_info import validate_info
        info = validate_info(info)
        with self.transaction():
            found = self.db.execute('SELECT payload FROM completion_history WHERE record_id=?', (record_id,)).fetchone()
            if found is None: return False
            row = json.loads(found[0])
            waiting = self.db.execute('SELECT 1 FROM record_character_pending WHERE record_id=?', (record_id,)).fetchone()
            if 'characterInfo' in row and not (finalize_pending and waiting):
                return False
            self._write_character_info(row, info)
            if pending:
                self.db.execute('INSERT OR IGNORE INTO record_character_pending VALUES(?)', (record_id,))
            else:
                self.db.execute('DELETE FROM record_character_pending WHERE record_id=?', (record_id,))
        return True

    def _write_character_info(self, row, info):
        from datetime import datetime, timezone, timedelta
        row['characterInfo'] = info
        previous = datetime.fromisoformat(row['updatedAt'].replace('Z', '+00:00'))
        updated = max(datetime.now(timezone.utc), previous + timedelta(microseconds=1))
        row['updatedAt'] = updated.isoformat(timespec='microseconds').replace('+00:00', 'Z')
        row = validate(row)
        body = json.dumps(row, ensure_ascii=False)
        self.db.execute('UPDATE completion_history SET payload=? WHERE record_id=?', (body, row['recordId']))
        self.db.execute("UPDATE gate_states SET payload=? WHERE json_extract(payload,'$.recordId')=?", (body, row['recordId']))
        if not row['isTest']:self.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')

    def roll_week(self, now=None):
        from .weekly import week_start
        start = week_start(now)
        with self.db:
            if self.repeat_start() >= start:
                return False
            self.db.execute('UPDATE weekly_repeat SET period_start=? WHERE id=1', (start,))
        # No history/Drive payload/queue is changed by a weekly reset.
        return True

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
        start = self.repeat_start()
        if start:
            rows = [r for r in rows if period(r)==start]
        if dungeon_key is not None and self.catalog is not None:
            from .dungeon import key
            matcher = self.catalog()
            candidates = list(dict.fromkeys(matcher.dungeon_candidates(dungeon_key) + matcher.stored_candidates(dungeon_key)))
            names = {dungeon_key}
            if len(candidates) == 1:names.add(key(candidates[0]))
            def belongs(row):
                aliases = {key(row['contentName']),
                           key(row.get('ocrOriginal', {}).get('contentName') or row['contentName'])}
                # A later catalog download must not create a second completion
                # beside a previously saved OCR-only record. Do not rewrite it.
                candidates = matcher.record_candidates(recognition_record(row), exact_only=False)
                if len(candidates) == 1:
                    aliases.add(key(candidates[0]))
                return bool(names.intersection(aliases))
            rows = [r for r in rows if belongs(r)]
        return rows

    def save_states(self,owner,dungeon_key,records,transactional=True):
        """검증된 전체 배열에서 완료만 저장합니다. 진행 상태는 호출자 메모리에 남습니다."""
        from .gates import STATES
        records=[recognition_record(r) for r in records]
        if not records or [r['gate'] for r in records]!=list(range(1,len(records)+1)):
            raise ValueError('전체 관문 배열이 필요합니다.')
        if any(r['state'] not in STATES for r in records):raise ValueError('관문 상태 오류')
        return self.save_completions(owner,dungeon_key,[r for r in records if r['state']=='완료'],len(records),transactional)

    def save_completions(self,owner,dungeon_key,records,expected_gates,transactional=True):
        """Only confirmed characters produce durable completions. Weekly lockout ignores difficulty."""
        if not records:return []
        records=[recognition_record(r) for r in records]
        gates=[r['gate'] for r in records]
        if (not 1<=expected_gates<=8 or len(set(gates))!=len(gates) or
            any(type(g) is not int or not 1<=g<=expected_gates for g in gates) or
            any(r['state']!='완료' for r in records)):raise ValueError('완료 관문 배열 오류')
        if any(not r.get('characterName') for r in records):return []
        changed=[]
        matcher = self.catalog() if self.catalog is not None else None
        with self.db if transactional else nullcontext():
            if transactional and not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            for record in records:
                from .dungeon import key
                record = matcher.record(record) if matcher is not None else record
                number=0 if record.get('completionScope')=='raid' else record['gate']
                test=bool(record.get('isTest') or record.get('timeBasis')=='synthetic_test')
                owner=('test:' if test else '')+'name:'+record['characterName']
                storage_key = key(record['dungeonName'])
                known=self.state_records(owner,dungeon_key)+self.state_records(owner,storage_key)
                if max((r['expectedGates'] for r in known),default=0)>expected_gates:
                    raise ValueError('기존 전체 관문보다 적은 배열입니다.')
                if any(r['gateNumber']==number for r in known):continue
                row=new_record(record,0 if number==0 else expected_gates)
                self.db.execute('INSERT INTO gate_states VALUES (?,?,?,?) ON CONFLICT(owner,dungeon_key,gate) DO UPDATE SET payload=excluded.payload',
                    (owner,storage_key,number,json.dumps(row,ensure_ascii=False)))
                self.remember_completion(row)
                changed.append(row)
            if any(not r['isTest'] for r in changed):
                self.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
        return changed

    def refresh_catalog_matches(self, matcher):
        """Backfill exact rewards atomically, preserving completion identity and observed time."""
        from datetime import datetime,timedelta,timezone
        changed=[]
        with self.db:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            for identity,payload in self.db.execute('SELECT record_id,payload FROM completion_history').fetchall():
                previous=json.loads(payload)
                row=matcher.refresh_record_match(previous)
                if row==previous:continue
                now=datetime.now(timezone.utc)
                old=datetime.fromisoformat(previous['updatedAt'].replace('Z','+00:00'))
                row['updatedAt']=max(now,old+timedelta(milliseconds=1)).isoformat(timespec='milliseconds').replace('+00:00','Z')
                row=validate(row)
                encoded=json.dumps(row,ensure_ascii=False)
                self.db.execute('UPDATE completion_history SET payload=? WHERE record_id=?',(encoded,identity))
                self.db.execute("UPDATE gate_states SET payload=? WHERE json_extract(payload,'$.recordId')=?",(encoded,row['recordId']))
                changed.append(row)
            if any(not row['isTest'] for row in changed):
                self.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
        return changed

    def drive_revision(self):
        return self.db.execute('SELECT epoch,revision FROM drive_changes WHERE id=1').fetchone()

    def correct_completion(self, record_id, content_name, matcher, *, expected_updated_at):
        """Correct a reviewed OCR title without replacing identity or completion times."""
        from .dungeon import key
        from datetime import datetime,timedelta,timezone
        with self.db:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            found=self.db.execute('SELECT payload FROM completion_history WHERE record_id=?',(record_id,)).fetchone()
            if found is None:raise ValueError('정정할 완료 기록이 없습니다.')
            previous=json.loads(found[0])
            if previous['updatedAt']!=expected_updated_at:raise ValueError('기록이 변경되었습니다. 다시 확인해주세요.')
            row=dict(previous)
            row.pop('catalogMatch',None)
            row['contentName']=content_name
            row['ocrOriginal']=dict(contentName=content_name,difficulty=row['difficulty'],gateNumber=row['gateNumber'])
            row=matcher.record(row)
            if row.get('catalogMatch',{}).get('status')!='matched':raise ValueError('정정한 제목의 정확한 공용 매칭이 필요합니다.')
            # Keep the actual original OCR for audit and old-runtime alias lockout.
            if 'ocrOriginal' in previous:row['ocrOriginal']=previous['ocrOriginal']
            names={key(row['contentName']),key(row['catalogMatch']['fieldName'])}
            for other in self.history_records():
                if other['recordId']==record_id or other['characterName']!=row['characterName'] or other['isTest']!=row['isTest'] or other['gateNumber']!=row['gateNumber']:continue
                if period(row) is not None and period(other)==period(row) and names.intersection({key(other['contentName']),*(key(n) for n in matcher.record_candidates(other))}):
                    raise ValueError('같은 주간에 정정 대상 관문 기록이 이미 있습니다.')
            old=datetime.fromisoformat(previous['updatedAt'].replace('Z','+00:00'))
            row['updatedAt']=max(datetime.now(timezone.utc),old+timedelta(milliseconds=1)).isoformat(timespec='milliseconds').replace('+00:00','Z')
            row=validate(row);encoded=json.dumps(row,ensure_ascii=False)
            checkpoint=self.db.execute("SELECT owner,dungeon_key,gate FROM gate_states WHERE json_extract(payload,'$.recordId')=?",(record_id,)).fetchall()
            for owner,dungeon,gate in checkpoint:
                target=self.db.execute('SELECT payload FROM gate_states WHERE owner=? AND dungeon_key=? AND gate=?',(owner,key(row['contentName']),gate)).fetchone()
                if target and json.loads(target[0])['recordId']!=record_id:raise ValueError('정정 대상 체크포인트가 이미 있습니다.')
                self.db.execute('DELETE FROM gate_states WHERE owner=? AND dungeon_key=? AND gate=?',(owner,dungeon,gate))
                self.db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',(owner,key(row['contentName']),gate,encoded))
            self.db.execute('UPDATE completion_history SET payload=? WHERE record_id=?',(encoded,record_id))
            if not row['isTest']:self.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
        return row

    def set_gold_reward(self, record_id, received):
        """Attach verified receipt once; repeated runs cannot replace a known result."""
        from datetime import datetime,timedelta,timezone
        if type(received) is not bool:raise ValueError('확인된 골드 보상 여부가 필요합니다.')
        with self.db:
            if not self.db.in_transaction:self.db.execute('BEGIN IMMEDIATE')
            found=self.db.execute('SELECT payload FROM completion_history WHERE record_id=?',(record_id,)).fetchone()
            if found is None:raise ValueError('보상을 연결할 완료 기록이 없습니다.')
            previous=json.loads(found[0])
            if previous.get('goldReward') is not None:
                if previous['goldReward']!=received:raise ValueError('확정된 골드 보상 결과는 덮어쓸 수 없습니다.')
                return previous
            old=datetime.fromisoformat(previous['updatedAt'].replace('Z','+00:00'))
            row=validate(dict(previous,goldReward=received,updatedAt=max(datetime.now(timezone.utc),old+timedelta(milliseconds=1)).isoformat(timespec='milliseconds').replace('+00:00','Z')))
            encoded=json.dumps(row,ensure_ascii=False)
            self.db.execute('UPDATE completion_history SET payload=? WHERE record_id=?',(encoded,record_id))
            self.db.execute("UPDATE gate_states SET payload=? WHERE json_extract(payload,'$.recordId')=?",(encoded,record_id))
            if not row['isTest']:self.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
        return row

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

    def clear_all(self, transactional=True):
        """분석 작업자가 정지한 뒤 호출합니다. 모델/설정은 보존합니다."""
        with self.transaction() if transactional else nullcontext():
            for table in ("gate_states", "completion_history", "outbox", "pending_events", "events", "pending_segments", "sessions"):
                self.db.execute(f"DELETE FROM {table}")
            self.reset_drive_queue()


    @contextmanager
    def transaction(self, snapshot=False):
        """Keep a multi-operation write or read snapshot on this connection."""
        with self.db:
            if snapshot:
                self.db.execute('BEGIN')
            yield

    @staticmethod
    def snapshot_existing(source, destination):
        """Read-only SQLite snapshot including WAL; never migrate or change the source."""
        source=Path(source).resolve()
        destination=Path(destination).resolve()
        if source==destination:raise ValueError('원본과 백업 경로는 달라야 합니다.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original:
            with closing(sqlite3.connect(destination)) as target:original.backup(target)
        return destination

    def backup_to(self, path):
        with closing(sqlite3.connect(path)) as destination:
            self.db.backup(destination)

    def resolve_pending(self, segment, mappings):
        """Called inside the character-confirmation transaction."""
        self.db.executemany('UPDATE pending_events SET resolved_event_id=? WHERE event_id=?', mappings)
        self.db.execute("UPDATE pending_segments SET status='resolved' WHERE segment_id=?", (segment,))

    def assign_pending_character(self, previous_owner, character_key, character_name):
        """Legacy compatibility API: unconfirmed completions are never promoted."""
        return None

    def import_completion(self, owner, dungeon, row):
        """Preserve incoming identifiers and times; unknown observations don't enter a weekly lockout."""
        row=validate(canonical(row))
        owner=('test:' if row['isTest'] else '')+'name:'+row['characterName']
        changed = self.remember_completion(row)
        if not self.repeat_start() or period(row)==self.repeat_start():
            self.db.execute("""INSERT INTO gate_states VALUES (?,?,?,?)
                ON CONFLICT(owner,dungeon_key,gate) DO UPDATE SET payload=excluded.payload
                WHERE json_extract(excluded.payload,'$.updatedAt') > json_extract(gate_states.payload,'$.updatedAt')""",
                (owner, dungeon, row['gateNumber'], json.dumps(row, ensure_ascii=False)))
        return changed

    def replace_history(self, rows):
        from .dungeon import key
        with self.transaction():
            self.clear_all(transactional=False)
            matcher=self.catalog() if self.catalog is not None else None
            def name(row):
                candidates=matcher.record_candidates(row,exact_only=False) if matcher else []
                return candidates[0] if len(candidates)==1 else row['contentName']
            for row in deduplicate(rows,name):
                self.import_completion('name:'+row['characterName'], key(row['contentName']), row)

    def recover_weekly_history(self, data, now=None):
        from .weekly import week_start
        with self.transaction():
            self.db.execute('CREATE TABLE IF NOT EXISTS imported_weekly_sources (path TEXT PRIMARY KEY)')
            self.db.execute('CREATE TABLE IF NOT EXISTS history_export_initialized (id INTEGER PRIMARY KEY CHECK(id=1))')
            first_history_export = self.db.execute('SELECT 1 FROM history_export_initialized').fetchone() is None
            imported = {r[0] for r in self.db.execute('SELECT path FROM imported_weekly_sources')}
            changed = False
            for source in sorted((Path(data)/'weekly-records').glob('*.sqlite3')):
                name = str(source.resolve())
                if name in imported:
                    continue
                with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as old:
                    for payload, in old.execute('SELECT payload FROM gate_states'):
                        row=json.loads(payload)
                        if row.get('state','완료')!='완료' or not row.get('characterName'):continue
                        row=validate(canonical(row))
                        from .dungeon import key
                        changed=self.import_completion('name:'+row['characterName'],key(row['contentName']),row) or changed
                self.db.execute('INSERT INTO imported_weekly_sources VALUES(?)', (name,))
            publish_legacy = first_history_export and any(
                r.get('characterName') and r.get('contentName') and r.get('difficulty') and not r.get('isTest')
                for r in self.history_records())
            if changed or publish_legacy:
                self.db.execute('UPDATE drive_changes SET revision=revision+1 WHERE id=1')
            self.db.execute('INSERT OR IGNORE INTO history_export_initialized VALUES(1)')

    def close(self):
        self.db.close()
