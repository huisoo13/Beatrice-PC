"""Weekly repetition resets must preserve history, sync IDs and upload obligations."""
from datetime import datetime
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from beatrice.weekly import week_start, database_path, open_week
from beatrice.drive_data import merge_records, validate_records, encode_records, export_snapshot, export_records, restore_records
from beatrice.storage import Store


def at(value):return datetime.fromisoformat(value.replace('Z','+00:00'))


def row(gate=1, updated='2026-10-07T00:00:00.000Z', **changes):
    return validate_records([dict(dict(characterName='캐릭터',dungeonName='던전',difficulty='하드',gate=gate,state='완료'),**changes)])[0] | {'updatedAt':updated,'observedAt':updated}


class WeeklyTests(unittest.TestCase):
    def test_boundary_exact_and_independent_of_device_timezone(self):
        self.assertEqual(week_start(at('2026-10-07T05:59:59+09:00')),'2026-09-29T21:00:00.000Z')
        self.assertEqual(week_start(at('2026-10-07T06:00:00+09:00')),'2026-10-06T21:00:00.000Z')
        self.assertEqual(week_start(at('2026-10-14T05:59:59+09:00')),'2026-10-06T21:00:00.000Z')
        self.assertEqual(week_start(at('2026-10-06T21:00:00Z')),'2026-10-06T21:00:00.000Z')

    def test_merge_keeps_old_history_and_compares_only_matching_ids(self):
        old=row(updated='2026-09-01T00:00:00.000Z')
        newer=row(updated='2026-10-08T00:00:00.000Z',difficulty='노말')
        self.assertEqual(merge_records([], [old]),[old])
        self.assertEqual(merge_records([old,row(2)],[newer]),validate_records([newer,row(2)]))
        self.assertEqual(merge_records([newer],[old]),[newer])
        self.assertEqual(merge_records([newer],[newer]),[newer])
        with self.assertRaises(ValueError):merge_records([row()],[row(difficulty='노말')])

    def test_reset_preserves_payload_pending_upload_and_repeated_completion(self):
        with tempfile.TemporaryDirectory() as data:
            store=open_week(data,now=at('2026-10-08T00:00:00Z'))
            try:
                def save(timestamp):
                    value=dict(row(),observedAt=timestamp)

                    with patch('beatrice.record_identity.datetime',wraps=datetime) as clock:
                        clock.now.return_value=at(timestamp)
                        return store.save_completions('name:캐릭터','던전',[value],1)
                first=save('2026-10-08T00:00:00Z')[0]
                self.assertEqual(save('2026-10-08T01:00:00Z'),[])
                before=export_snapshot(store)
                store.roll_week(at('2026-10-14T06:00:00+09:00'))
                self.assertEqual(store.state_records(),[])
                self.assertEqual(export_snapshot(store),before)
                self.assertEqual(len(store.history_records()),1)
                store.acknowledge_drive('account',*before[2])
                self.assertIsNone(store.drive_pending('account'))
                second=save('2026-10-14T00:00:00Z')[0]
                self.assertNotEqual(first['recordId'],second['recordId'])
                self.assertEqual(len(store.state_records()),1)
                exported=export_records(store)[0]
                self.assertEqual(len(exported),2)
                self.assertEqual(len({r['recordId'] for r in exported}),2)
                self.assertTrue(all(set(r)==set(__import__('beatrice.completion_record',fromlist=['FIELDS']).FIELDS) for r in exported))
                # Acknowledging the old snapshot cannot acknowledge the later completion.
                store.acknowledge_drive('account',*before[2])
                self.assertIsNotNone(store.drive_pending('account'))
                restore_records(store,exported,Path(data)/'backups')
                self.assertEqual(export_records(store)[0],exported)
            finally:store.close()
            reopened=open_week(data,now=at('2026-10-15T00:00:00Z'))
            try:self.assertEqual(len(export_records(reopened)[0]),2)
            finally:reopened.close()

    def test_history_failure_rolls_back_checkpoint_and_upload_obligation(self):
        with tempfile.TemporaryDirectory() as data:
            store=open_week(data,now=at('2026-10-08T00:00:00Z'))
            try:
                before=store.drive_revision()
                store.db.execute("CREATE TRIGGER fail_history BEFORE INSERT ON completion_history BEGIN SELECT RAISE(ABORT,'test'); END")
                with self.assertRaises(sqlite3.IntegrityError):
                    store.save_completions('name:캐릭터','던전',[dict(row(),observedAt='2026-10-08T00:00:00Z')],1)
                self.assertEqual(store.state_records(),[])
                self.assertEqual(store.history_records(),[])
                self.assertEqual(store.drive_revision(),before)
            finally:store.close()

    def test_legacy_completions_all_remain_but_only_current_week_blocks_repeats(self):
        with tempfile.TemporaryDirectory() as data:
            old=Store(database_path(data))
            with old.db:
                for gate,updated in ((1,'2026-10-06T20:59:59.999Z'),(2,'2026-10-07T00:00:00.000Z')):
                    old.db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',('name:캐릭터','던전',gate,json.dumps(row(gate,updated))))
            old.close()
            new=open_week(data,now=at('2026-10-08T00:00:00Z'))
            try:
                self.assertEqual([r['gateNumber'] for r in new.state_records()],[2])
                self.assertEqual(len(export_records(new)[0]),2)
                before=export_snapshot(new)
                new.roll_week(at('2026-10-14T06:00:00+09:00'))
                self.assertEqual(new.state_records(),[])
                self.assertEqual(export_snapshot(new),before)
            finally:new.close()

    def test_recover_all_prior_week_databases_once_without_collapsing_repeats(self):
        with tempfile.TemporaryDirectory() as data:
            for name,updated in (('2026-09-29','2026-10-01T00:00:00.000Z'),('2026-10-06','2026-10-08T00:00:00.000Z')):
                old=Store(Path(data)/'weekly-records'/(name+'.sqlite3'))
                with old.db:old.db.execute('INSERT INTO gate_states VALUES(?,?,?,?)',('name:캐릭터','던전',1,json.dumps(row(updated=updated))))
                old.close()
            new=open_week(data,now=at('2026-10-08T01:00:00Z'))
            before=export_snapshot(new)
            self.assertEqual(len(before[0]),2)
            self.assertEqual(len(new.state_records()),1)
            new.close()
            reopened=open_week(data,now=at('2026-10-08T02:00:00Z'))
            try:self.assertEqual(export_snapshot(reopened),before)
            finally:reopened.close()
            self.assertEqual(len(list((Path(data)/'weekly-records').glob('*.sqlite3'))),2)
