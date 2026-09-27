import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from beatrice.storage import Store
from beatrice.live import LiveCoordinator


class CompletionOnlyTests(unittest.TestCase):
    def test_v3_migration_preserves_completed_payloads_and_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'records.db'
            store=Store(path)
            complete=dict(gate=1,state='완료',characterName='캐릭터',characterKey='name:캐릭터',
                          dungeonName='던전',difficulty='하드',timeBasis='live_capture')
            store.save_states('name:캐릭터','던전',[complete])
            before=store.state_records();revision=store.drive_revision()
            with store.db:
                store.db.execute('DROP TRIGGER completion_only_insert')
                store.db.execute('PRAGMA user_version=3')
                for owner,state in [('name:캐릭터','진행중'),('pending:old','진행 전')]:
                    store.db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',
                                     (owner,'던전',2,json.dumps(dict(complete,gate=2,state=state))))
                store.db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',
                                 ('pending:done','던전',1,json.dumps(dict(complete,characterName=None,characterKey=None))))
            store.close()
            store=Store(path)
            try:
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0],4)
                self.assertEqual(store.state_records('name:캐릭터'),before)
                self.assertEqual(len(store.state_records('pending:done')),1)
                self.assertEqual(store.state_records('pending:old'),[])
                self.assertEqual(store.drive_revision(),revision)
                with self.assertRaises(sqlite3.IntegrityError),store.db:
                    store.db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',
                                     ('x','던전',2,json.dumps(dict(complete,state='진행중'))))
                with self.assertRaises(sqlite3.IntegrityError),store.db:
                    store.db.execute('UPDATE gate_states SET payload=?',
                                     (json.dumps(dict(complete,state='진행 전')),))
            finally:store.close()

    def test_progress_never_writes_and_pending_completion_promotes_with_full_count(self):
        store=Store(':memory:');self.addCleanup(store.close)
        live=LiveCoordinator(store);now=datetime(2026,9,27,tzinfo=timezone.utc);tick=0
        def feed(states,character=None):
            nonlocal tick
            for _ in range(4):
                tick+=1
                live.update(now+timedelta(seconds=tick),character or {},
                    [dict(state=s,confidence=.99,xyxy=[50*i,0,50*i+30,40]) for i,s in enumerate(states)],
                    dict(dungeonName='던전',difficulty='하드',contextStatus='ocr_verified'))
        writes=store.db.total_changes
        feed(['진행중','진행 전','진행 전'])
        feed(['진행 전','진행중','진행 전'])
        self.assertEqual(store.db.total_changes,writes)
        self.assertEqual(store.state_records(),[])
        feed(['완료','진행중','진행 전'])
        pending=store.state_records();self.assertEqual(len(pending),1)
        self.assertIsNone(pending[0]['characterName']);self.assertEqual(pending[0]['expectedGates'],3)
        feed(['완료','진행중','진행 전'],dict(currentName=dict(text='캐릭터',confidence=.99)))
        rows=store.state_records();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['characterName'],'캐릭터');self.assertEqual(rows[0]['expectedGates'],3)
        self.assertEqual(rows[0]['completedAt'],pending[0]['completedAt'])
        self.assertEqual(live.session.tracker.stable,('완료','진행중','진행 전'))

    def test_restart_discards_progress_but_can_complete_after_fresh_observations(self):
        store=Store(':memory:');self.addCleanup(store.close)
        live=LiveCoordinator(store);now=datetime(2026,9,27,tzinfo=timezone.utc)
        for i in range(5):
            live.update(now+timedelta(seconds=i),dict(currentName=dict(text='캐릭터',confidence=.99)),
                        [dict(state='진행중',confidence=.99,xyxy=[0,0,30,40])],
                        dict(dungeonName='던전',difficulty='하드',contextStatus='ocr_verified'))
        self.assertEqual(store.state_records(),[])
        restarted=LiveCoordinator(store)
        self.assertIsNone(restarted.session.tracker)
        for i in range(5,11):
            restarted.update(now+timedelta(seconds=i),dict(currentName=dict(text='캐릭터',confidence=.99)),
                             [dict(state='완료',confidence=.99,xyxy=[0,0,30,40])],
                             dict(dungeonName='던전',difficulty='하드',contextStatus='ocr_verified'))
        self.assertEqual(len(store.state_records()),1)


if __name__=='__main__':unittest.main()
