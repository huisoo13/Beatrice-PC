from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
import sqlite3
from beatrice.storage import Store
from beatrice.deferred_session import DeferredRecordingSession
from beatrice.character import CharacterTracker,CharacterRecordingBridge


class DeferredTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'events.sqlite'
        self.store=Store(self.path);self.session=DeferredRecordingSession(self.store)
        self.start=datetime(2026,9,17,10,tzinfo=timezone(timedelta(hours=9)))
        self.i=0
        self.run=dict(session_id='run',expected_gates=1,time_basis='synthetic_test',is_test=True)

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def prepare(self):
        self.session.prepare_pending_run(**self.run)

    def confirm(self,name='A'):
        return self.session.confirm_character(character_key=name,character_name=name,**self.run)

    def feed(self):
        for state in ['진행중']*3+['완료']*3:
            self.session.observe(self.session.token,self.start+timedelta(seconds=self.i*.2),
                [dict(state=state,confidence=.99,xyxy=[60,130,100,180])]);self.i+=1

    def test_pending_then_promote_keeps_times_and_outbox(self):
        self.prepare();self.feed()
        pending=self.store.pending_records()[0]
        self.assertEqual(self.store.records(),[])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
        self.confirm()
        event=self.store.records()[0]
        self.assertEqual(event['characterName'],'A')
        self.assertEqual(event['observedAt'],pending['observedAt'])
        self.assertEqual(event['confirmedAt'],pending['confirmedAt'])
        self.assertEqual(event['savedAt'],pending['savedAt'])
        self.assertEqual(event['syncStatus'],'test_only')
        self.assertEqual(self.store.pending_records()[0]['resolvedEventID'],event['eventID'])

    def test_confirmed_saves_directly(self):
        self.confirm();self.feed()
        self.assertEqual(len(self.store.records()),1)
        self.assertEqual(self.store.pending_records(),[])

    def test_unresolved_previous_segment_never_assigned_to_next(self):
        self.prepare();self.feed();old=self.session.segment_id
        self.session.begin_character_change();self.prepare();self.feed();self.confirm('B')
        self.assertEqual(len(self.store.records()),1)
        unresolved=[p for p in self.store.pending_records() if p['resolvedEventID'] is None]
        self.assertEqual(len(unresolved),1)
        self.assertEqual(unresolved[0]['segmentID'],old)

    def test_restart_preserves_pending_but_does_not_guess_owner(self):
        self.prepare();self.feed();self.store.close()
        self.store=Store(self.path);self.session=DeferredRecordingSession(self.store)
        self.confirm('B')
        self.assertEqual(len(self.store.pending_records()),1)
        self.assertIsNone(self.store.pending_records()[0]['resolvedEventID'])
        self.assertEqual(self.store.records(),[])

    def test_duplicate_same_character_run_is_not_uploaded_twice(self):
        self.confirm();self.feed()
        self.session.begin_character_change();self.prepare();self.feed();self.confirm()
        self.assertEqual(len(self.store.records()),1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM outbox').fetchone()[0],1)
        self.assertIsNotNone(self.store.pending_records()[0]['resolvedEventID'])

    def test_promotion_failure_is_atomic_and_retryable(self):
        self.prepare();self.feed();token=self.session.token
        self.store.db.execute("CREATE TRIGGER fail_queue BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.confirm()
        self.assertEqual(self.session.token,token)
        self.assertIsNone(self.session.character)
        self.assertEqual(self.store.records(),[])
        self.assertIsNone(self.store.pending_records()[0]['resolvedEventID'])
        self.store.db.execute('DROP TRIGGER fail_queue');self.confirm()
        self.assertEqual(len(self.store.records()),1)

    def test_wrong_context_and_old_frame_rejected(self):
        self.prepare();self.feed();old=self.session.token
        with self.assertRaises(ValueError):
            self.session.confirm_character('A','A','other',1,'synthetic_test',True)
        self.session.begin_character_change()
        self.assertEqual(self.session.observe(old,self.start,[])['status'],'character_unconfirmed_or_stale_frame')

    def test_bridge_promotes_without_discarding_pending(self):
        self.prepare();self.feed()
        bridge=CharacterRecordingBridge(self.session,lambda name:dict(character_key=name,**self.run))
        bridge.apply(dict(recordingAllowed=True,actions=[dict(type='confirmed',name='B')]))
        self.assertEqual(self.store.records()[0]['characterName'],'B')

    def test_pending_write_failure_does_not_advance_memory(self):
        self.prepare()
        self.store.db.execute("CREATE TRIGGER fail_pending BEFORE INSERT ON pending_events BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.feed()
        self.assertEqual(self.store.pending_records(),[])
        self.assertEqual(self.session.pending_tracker.stable,('진행중',))
        self.store.db.execute('DROP TRIGGER fail_pending')
        result=self.session.observe(self.session.token,self.start+timedelta(seconds=self.i*.2),
            [dict(state='완료',confidence=.99,xyxy=[60,130,100,180])])
        self.assertEqual(len(result['pendingEvents']),1)

    def test_v1_migration_preserves_existing_events(self):
        self.confirm();self.feed()
        self.store.db.executescript('DROP TABLE pending_events; DROP TABLE pending_segments; PRAGMA user_version=1;')
        self.store.close();self.store=Store(self.path)
        self.assertEqual(self.store.db.execute('PRAGMA user_version').fetchone()[0],5)
        self.assertEqual(len(self.store.records()),1)
        self.assertEqual(self.store.pending_records(),[])

    def test_cancel_preserves_character_without_recording_boundary(self):
        tracker=CharacterTracker()
        obs=dict(currentName=dict(text='후이수',confidence=.99),currentRegionVisible=True)
        for i in range(3):tracker.update(i*.5,obs)
        tracker.update(1.5,dict(obs,switchDialog=True))
        for i in range(3):result=tracker.update(2+i*.5,obs)
        self.assertTrue(result['recordingAllowed'])
        self.assertEqual(result['actions'],[])
        for i in range(3):result=tracker.update(4+i*.5,dict(obs,normalMenu=True))
        self.assertTrue(result['recordingAllowed'])
        self.assertEqual(result['currentName'],'후이수')

    def test_only_loading_after_dialog_creates_one_boundary(self):
        tracker=CharacterTracker()
        self.assertEqual(tracker.update(0,dict(switchDialog=True))['actions'],[])
        self.assertEqual(tracker.update(.5,dict(switchDialog=True))['actions'],[])
        self.assertEqual(tracker.update(1,dict(switchLoading=True))['actions'],[dict(type='suspend')])
        self.assertEqual(tracker.update(1.5,dict(switchLoading=True))['actions'],[])

if __name__=='__main__':unittest.main()
