from datetime import datetime,timedelta,timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from beatrice.storage import Store
from beatrice.session import RecordingSession


def boxes(*states):
    return [dict(state=s,confidence=.9,xyxy=[60+i*100,130,100+i*100,180]) for i,s in enumerate(states)]


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'test.sqlite'
        self.store=Store(self.path);self.session=RecordingSession(self.store)
        self.start=datetime(2026,9,16,9,tzinfo=timezone(timedelta(hours=9)));self.i=0
        self.confirm()

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def confirm(self,key='char-A',run='run-1'):
        self.token=self.session.confirm_character(key,key,run,2,'synthetic_test',True)

    def feed(self,states,n=1):
        found=[]
        for _ in range(n):
            found+=self.session.observe(self.token,self.start+timedelta(seconds=self.i*.2),boxes(*states))['events'];self.i+=1
        return found

    def complete(self):
        self.feed(('완료','진행중'),3)
        return self.feed(('완료','완료'),3)

    def test_atomic_event_outbox_checkpoint(self):
        e=self.complete()[0]
        self.assertTrue(e['observedAt'].startswith('2026-09-16T00:00:00.600'))
        self.assertEqual(e['characterName'],'char-A')
        self.assertEqual(self.store.records()[0]['syncStatus'],'test_only')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM outbox').fetchone()[0],1)

    def test_restart_requires_identity_and_keeps_completed(self):
        self.complete();self.store.close();self.store=Store(self.path)
        self.session=RecordingSession(self.store)
        self.assertEqual(self.session.observe(self.token,self.start+timedelta(seconds=2),boxes('완료','완료'))['events'],[])
        self.confirm();self.i=20
        self.assertEqual(self.feed(('완료','완료'),4),[])
        self.assertEqual(len(self.store.records()),1)

    def test_other_character_same_run_is_independent(self):
        first=self.complete()[0];self.confirm('char-B')
        second=self.complete()[0]
        self.assertNotEqual(first['eventID'],second['eventID'])
        self.assertEqual(len(self.store.records()),2)

    def test_same_character_new_run(self):
        self.complete();self.confirm(run='run-2');self.complete()
        self.assertEqual(len(self.store.records()),2)

    def test_character_change_rejects_old_frames(self):
        old=self.token;self.session.begin_character_change()
        self.assertEqual(self.session.observe(old,self.start,boxes('완료','완료'))['status'],'character_unconfirmed_or_stale_frame')
        self.confirm('char-B')
        self.assertEqual(self.session.observe(old,self.start,boxes('완료','완료'))['status'],'character_unconfirmed_or_stale_frame')

    def test_database_failure_rolls_back_and_retry(self):
        self.feed(('완료','진행중'),3);self.feed(('완료','완료'),2)
        checkpoint=self.store.db.execute('SELECT checkpoint FROM sessions').fetchone()[0]
        self.store.db.execute("CREATE TRIGGER fail_queue BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.feed(('완료','완료'))
        self.assertEqual(self.store.records(),[])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
        self.assertEqual(self.store.db.execute('SELECT checkpoint FROM sessions').fetchone()[0],checkpoint)
        self.assertEqual(self.session.tracker.stable,('완료','진행중'))
        self.store.db.execute('DROP TRIGGER fail_queue')
        self.assertEqual(len(self.feed(('완료','완료'))),1)

    def test_resume_discards_pending_streak(self):
        self.feed(('완료','진행중'),3);self.feed(('완료','완료'),2)
        self.session=RecordingSession(self.store);self.confirm()
        self.assertEqual(self.feed(('완료','완료'),2),[])
        self.assertEqual(len(self.feed(('완료','완료'))),1)

    def test_timezone_and_conflicting_source(self):
        with self.assertRaises(ValueError):self.session.observe(self.token,datetime(2026,9,16),[])
        with self.assertRaises(ValueError):self.session.confirm_character('char-A','char-A','run-1',3,'synthetic_test',True)

    def test_database_unique_repeated_event(self):
        event=self.complete()[0]
        import json
        checkpoint=json.loads(self.store.db.execute('SELECT checkpoint FROM sessions').fetchone()[0])
        self.assertEqual(self.store.commit('char-A','run-1',checkpoint,[event]),[])
        self.assertEqual(len(self.store.records()),1)

if __name__=='__main__':unittest.main()
