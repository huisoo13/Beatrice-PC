"""Canonical migration, reset-period identity and character-gated recognition."""
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import Mock
from beatrice.completion_record import FIELDS,META,canonical,validate,new_record,recognition_record
from beatrice.drive_data import decode_records,encode_records,restore_records,export_records,merge_records
from beatrice.storage import Store
from beatrice.live import LiveCoordinator
from beatrice.content_match import ContentMatcher
from beatrice.native_presentation import record_view,DungeonFooter
from beatrice.ui_regions import UIRegionDetector

AT='2026-10-08T00:00:00.000Z'


def observation(**changes):
    return dict(dict(characterName='캐릭터',dungeonName='던전',difficulty='하드',gate=1,state='완료',observedAt=AT),**changes)


def completed(**changes):
    row=new_record(observation(),2)
    row.update(changes)
    return validate(row)


class RecordContractTests(unittest.TestCase):
    def test_live_has_only_approved_fields_and_restores_all_times_and_id(self):
        with tempfile.TemporaryDirectory() as folder:
            with closing(Store(Path(folder)/'records.db')) as store:
                row=store.save_completions('name:캐릭터','던전',[observation()],2)[0]
                self.assertEqual(set(row),set(FIELDS))
                self.assertEqual(row['createdAt'],row['updatedAt'])
                exported=export_records(store)[0]
                restore_records(store,exported,Path(folder)/'backups')
                self.assertEqual(store.history_records(),[row])
                self.assertEqual(store.state_records(),[row])
                self.assertEqual(decode_records(encode_records(exported)),exported)

    def test_gateless_legacy_slot_and_nested_names_convert_to_zero(self):
        legacy=observation(completionScope='raid',expectedGates=1,
            ocrOriginal=dict(dungeonName='던전',difficulty='하드',gate=1),
            catalogMatch=dict(status='matched',dungeonName='던전',difficulty='하드',gateName='1관문',
                version={},values=dict(gold=100,fee=10,bound_percentage=.2)))
        row=validate(canonical(legacy))
        self.assertEqual((row['gateNumber'],row['expectedGates']),(0,0))
        self.assertEqual(row['ocrOriginal'],dict(contentName='던전',difficulty='하드',gateNumber=0))
        self.assertEqual(row['catalogMatch']['gateNumber'],0)
        self.assertNotIn('gateName',row['catalogMatch'])
        self.assertEqual(record_view(row)['gate'],'레이드 전체')

    def test_old_drive_preserves_identity_but_does_not_invent_observation_time(self):
        old=observation();old.pop('observedAt')
        row=decode_records(json.dumps([old]).encode())[0]
        self.assertEqual(row['expectedGates'],0)
        self.assertIsNone(row['observedAt']);self.assertIsNone(row['createdAt'])
        self.assertEqual(record_view(row)['date'],'완료 시각 미상')
        self.assertEqual(decode_records(encode_records([row])),[row])

    def test_drive_envelope_version_and_removed_fields_are_rejected(self):
        row=completed()
        body=json.loads(encode_records([row]))
        self.assertEqual(body['schemaVersion'],5)
        for field in ('state','characterKey','evidenceType','completionScope','timeBasis','gateName'):
            with self.subTest(field=field),self.assertRaises(ValueError):validate(dict(row,**{field:'old'}))
        body['schemaVersion']=6
        with self.assertRaises(ValueError):decode_records(json.dumps(body).encode())

    def test_invalid_gate_count_types_and_metadata_abort(self):
        row=completed()
        cases=[dict(gateNumber=True),dict(expectedGates=True),dict(gateNumber=3),dict(isTest=1),
            dict(updatedAt=None),dict(observedAt='2026-10-08T00:00:00'),dict(ocrOriginal={'gateNumber':1})]
        for values in cases:
            with self.subTest(values=values),self.assertRaises(ValueError):validate(dict(row,**values))
        match=dict(status='matched',contentName='던전',difficulty='하드',gateNumber=1,
            version={},values=dict(gold=-1,fee=0,bound_percentage=0))
        with self.assertRaises(ValueError):validate(dict(row,catalogMatch=match))

    def test_test_records_do_not_lock_live_records_or_leave_drive(self):
        store=Store(':memory:');self.addCleanup(store.close)
        store.save_completions('x','던전',[observation(isTest=True)],2)
        live=store.save_completions('x','던전',[observation()],2)
        self.assertEqual(len(live),1)
        self.assertEqual(len(store.history_records()),2)
        self.assertEqual(export_records(store)[1],1)
        self.assertEqual(len(decode_records(encode_records(store.history_records()))),1)

    def test_two_ids_same_week_and_different_modes_merge_as_one_completion(self):
        one=completed()
        two=completed(difficulty='노말',observedAt='2026-10-08T01:00:00.000Z')
        for rows in ([one,two],[two,one]):self.assertEqual(merge_records([],rows),[one])
        next_week=completed(observedAt='2026-10-14T00:00:00.000Z')
        self.assertEqual(len(merge_records([one],[next_week])),2)

    def test_sync_update_time_does_not_move_weekly_lockout(self):
        store=Store(':memory:');self.addCleanup(store.close)
        store.roll_week(datetime.fromisoformat(AT.replace('Z','+00:00')))
        row=completed(updatedAt='2026-10-15T00:00:00.000Z')
        store.import_completion('x','던전',row)
        self.assertEqual(store.state_records(),[row])
        store.roll_week(datetime(2026,10,15,tzinfo=timezone.utc))
        self.assertEqual(store.state_records(),[])
        self.assertEqual(store.history_records(),[row])

    def test_legacy_id_sync_update_does_not_create_a_new_weekly_occurrence(self):
        store=Store(':memory:');self.addCleanup(store.close)
        row=validate(canonical(observation()))
        store.import_completion('x','던전',row)
        modified=dict(row,updatedAt='2026-10-15T00:00:00.000Z')
        store.import_completion('x','던전',modified)
        self.assertEqual(store.history_records(),[modified])

    def test_restore_catalog_aliases_deduplicates_without_rewriting_the_saved_record(self):
        cached=dict(content={'던전':{'하드':{'1관문':dict(gold=100,fee=0,bound_percentage=0)}}})
        matcher=ContentMatcher(cached)
        store=Store(':memory:',catalog=lambda:matcher);self.addCleanup(store.close)
        one=completed(contentName='[던전]')
        two=completed(observedAt='2026-10-08T01:00:00.000Z')
        store.replace_history([one,two])
        self.assertEqual(store.history_records(),[one])

    def test_unknown_observation_is_kept_in_history_without_blocking_this_week(self):
        store=Store(':memory:');self.addCleanup(store.close)
        store.roll_week(datetime.fromisoformat(AT.replace('Z','+00:00')))
        row=completed(observedAt=None,createdAt=None,expectedGates=0)
        store.import_completion('x','던전',row)
        self.assertEqual(store.history_records(),[row]);self.assertEqual(store.state_records(),[])
        self.assertEqual(len(store.save_completions('x','던전',[observation()],2)),1)

    def test_character_only_detector_never_calls_dungeon_model(self):
        detector=UIRegionDetector.__new__(UIRegionDetector)
        detector.character_detector=Mock();detector.character_detector.locate.return_value={}
        detector.dungeon_detector=Mock()
        self.assertEqual(detector.locate_character(object()),{})
        detector.dungeon_detector.locate.assert_not_called()

    def test_unconfirmed_context_is_discarded_and_confirmed_observations_start_fresh(self):
        store=Store(':memory:');self.addCleanup(store.close)
        live=LiveCoordinator(store)
        context=dict(dungeonName='던전',difficulty='하드',contextStatus='ocr_verified')
        boxes=[dict(state='완료',confidence=.99,xyxy=[0,0,20,20])]
        at=datetime.fromisoformat(AT.replace('Z','+00:00'))
        for i in range(4):state=live.update(at+timedelta(seconds=i),{},boxes,context)
        self.assertEqual(state['dungeon'],{});self.assertIsNone(live.context)
        self.assertEqual(store.history_records(),[])
        for i in range(4,8):live.update(at+timedelta(seconds=i),dict(currentName=dict(text='캐릭터',confidence=.99)),boxes,context)
        self.assertEqual(store.history_records(),[])
        live.update(at+timedelta(seconds=8),{},boxes,context)
        self.assertEqual(store.history_records()[0]['observedAt'],'2026-10-08T00:00:08.000Z')
        for i in range(9,12):live.update(at+timedelta(seconds=i),dict(serverSelection=True),boxes,context)
        self.assertIsNone(live.context);self.assertIsNone(live.session.tracker)
        self.assertEqual(len(store.history_records()),1)

    def test_footer_clears_when_character_confirmation_is_lost(self):
        footer=DungeonFooter()
        footer.update(dict(dungeon=dict(dungeonName='던전',difficulty='하드',contextStatus='ocr_verified',currentRaidPanel=True)),0)
        self.assertIsNotNone(footer.context)
        footer.update(dict(identity=dict(recordingAllowed=False)),1)
        self.assertIsNone(footer.context)

    def test_migration_backs_up_wal_and_preserves_known_times_and_legacy_id(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'records.db'
            db=sqlite3.connect(path)
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE gate_states(owner TEXT,dungeon_key TEXT,gate INTEGER,payload TEXT,PRIMARY KEY(owner,dungeon_key,gate))')
            db.execute('PRAGMA user_version=4')
            row=observation(savedAt=AT,confirmedAt=AT,expectedGates=2)
            db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',('name:캐릭터','던전',1,json.dumps(row)))
            db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',('pending:old','던전',1,json.dumps(observation(characterName=None))))
            db.commit()
            snapshot=Store.snapshot_existing(path,Path(folder)/'snapshot.db')
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
            db.close()
            store=Store(snapshot)
            try:
                actual=store.history_records()[0]
                self.assertEqual(actual['observedAt'],AT);self.assertEqual(actual['createdAt'],AT)
                self.assertTrue(actual['recordId'].startswith('br1_'))
                self.assertEqual(set(actual),set(FIELDS))
                self.assertEqual(len(store.history_records()),1)
                self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0],5)
                backups=list(Path(folder).glob('snapshot.db.pre-v5-*.bak'))
                self.assertEqual(len(backups),1)
                with closing(sqlite3.connect(backups[0])) as backup:
                    self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0],4)
                    self.assertEqual(backup.execute('SELECT COUNT(*) FROM gate_states').fetchone()[0],2)
            finally:store.close()

    def test_concurrent_completion_cannot_create_two_history_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'records.db'
            initial=Store(path);initial.close()
            barrier=threading.Barrier(2);saved=[];errors=[]
            def save():
                store=Store(path)
                try:
                    barrier.wait(timeout=5)
                    saved.extend(store.save_completions('name:캐릭터','던전',[observation()],2))
                except Exception as error:errors.append(error)
                finally:store.close()
            workers=[threading.Thread(target=save) for _ in range(2)]
            for worker in workers:worker.start()
            for worker in workers:worker.join(timeout=10)
            self.assertFalse(any(worker.is_alive() for worker in workers));self.assertEqual(errors,[])
            self.assertEqual(len(saved),1)
            store=Store(path)
            try:self.assertEqual(len(store.history_records()),1)
            finally:store.close()


if __name__=='__main__':unittest.main()
