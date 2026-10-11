import json
from pathlib import Path
import tempfile
import unittest

from beatrice.record_identity import record_id, UNKNOWN_UPDATED_AT
from beatrice.drive_data import validate_records, export_records, encode_records, decode_records, restore_records
from beatrice.storage import Store


def row(**kwargs):
    return dict(dict(characterName='테스트', dungeonName='던전', difficulty='하드', gate=1, state='완료'), **kwargs)


def synced(at='2026-09-27T01:00:00.000Z', **kwargs):
    result = row(**kwargs)
    return dict(result, recordID=record_id(result['characterName'], result['dungeonName'], result['gate']), updatedAt=at)


class IdentityTests(unittest.TestCase):
    def test_cross_platform_vector_and_unambiguous_components(self):
        self.assertEqual(record_id('테스트', '던전', 1),
                         'br1_484a542054cff3d5084717252fe53348a525e41428b2f5d3db47c0e4ed4a67a7')
        self.assertNotEqual(record_id('ab', 'c', 1), record_id('a', 'bc', 1))
        self.assertNotEqual(record_id('테스트', '던전', 0), record_id('테스트', '던전', 1))

    def test_dungeon_normalization_and_other_identity_components(self):
        self.assertEqual(record_id('이름', '[던전: 이름]', 1), record_id('이름', '던전이름', 1))
        self.assertNotEqual(record_id('이름', '던전', 1), record_id('이름2', '던전', 1))
        self.assertNotEqual(record_id('이름', '던전', 1), record_id('이름', '던전2', 1))
        self.assertNotEqual(record_id('이름', '던전', 1), record_id('이름', '던전', 2))

    def test_legacy_json_gets_stable_metadata_not_current_time(self):
        one = decode_records(json.dumps([row()]).encode())
        two = decode_records(json.dumps([row()]).encode())
        self.assertEqual(one, two)
        self.assertEqual(one[0]['updatedAt'], UNKNOWN_UPDATED_AT)
        self.assertEqual(decode_records(encode_records(one)), one)

    def test_duplicate_ids_choose_newest_independent_of_order(self):
        old = synced()
        new = synced('2026-09-27T12:00:00+09:00', state='완료', difficulty='노말')
        expected = validate_records([new])
        self.assertEqual(validate_records([old, new]), expected)
        self.assertEqual(validate_records([new, old, new]), expected)
        self.assertEqual(expected[0]['updatedAt'], '2026-09-27T03:00:00.000Z')
        self.assertEqual(old['recordID'], new['recordID'])

    def test_same_timestamp_conflict_and_forged_identity_rejected(self):
        with self.assertRaises(ValueError):
            validate_records([synced(), synced(difficulty='노말')])
        wrong = synced()
        wrong['recordID'] = 'some-uuid'
        with self.assertRaises(ValueError):
            validate_records([wrong])
        for at in ('bad', None, '2026-09-27T00:00:00', '2026-13-01T00:00:00Z'):
            with self.subTest(at=at), self.assertRaises(ValueError):
                validate_records([synced(at)])


class StoredIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'records.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.close())

    def save(self, **kwargs):
        self.store.save_states('name:테스트', '던전', [row(**dict(dict(state='완료'),**kwargs))])
        return self.store.state_records()[0]

    def test_completion_freezes_identity_time_and_difficulty(self):
        first = self.save()
        repeated = self.save()
        self.assertEqual(first['updatedAt'], repeated['updatedAt'])
        changed = self.save(difficulty='노말')
        completed = self.save(state='완료', difficulty='노말')
        self.assertEqual(first['recordId'], completed['recordId'])
        self.assertEqual(first['recordId'], changed['recordId'])
        self.assertEqual(first,changed)
        self.assertEqual(first,completed)
        self.assertEqual(changed['difficulty'], '하드')
        self.assertEqual(len(self.store.state_records()), 1)
        self.assertEqual(self.save(state='완료', difficulty='노말'), completed)
        self.assertEqual(self.save(state='완료', difficulty='하드'), completed)

    def test_export_restore_and_restart_preserve_both_fields(self):
        self.save()
        rows, _ = export_records(self.store)
        restore_records(self.store, rows, Path(self.temp.name) / 'backups')
        self.assertEqual(export_records(self.store)[0], rows)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(export_records(self.store)[0], rows)

    def test_legacy_local_metadata_uses_saved_time_and_schedules_new_drive_json(self):
        legacy = dict(row(state='완료'), savedAt='2026-09-26T15:00:00+09:00')
        with self.store.db:
            self.store.db.execute('DROP TRIGGER completion_only_insert')
            self.store.db.execute('PRAGMA user_version=4')
            self.store.db.execute('INSERT INTO gate_states VALUES (?,?,?,?)',
                ('name:테스트', '던전', 1, json.dumps(legacy)))
        self.store.close()
        self.store = Store(self.path)
        actual = self.store.state_records()[0]
        self.assertEqual(actual['updatedAt'], '2026-09-26T06:00:00.000Z')
        self.assertEqual(actual['recordId'], record_id('테스트', '던전', 1))
        self.assertIsNotNone(self.store.drive_pending('account'))

    def test_gateless_id_uses_external_zero(self):
        self.save(completionScope='raid')
        rows, _ = export_records(self.store)
        self.assertEqual(rows[0]['gateNumber'], 0)
        self.assertEqual(rows[0]['gateNumber'], 0)
        self.assertEqual(rows[0]['recordId'], self.store.history_records()[0]['recordId'])
        self.assertRegex(rows[0]['recordId'], r'^br2_[0-9a-f]{32}$')
        restore_records(self.store, rows, Path(self.temp.name) / 'backups')
        self.assertEqual(export_records(self.store)[0], rows)


if __name__ == '__main__':
    unittest.main()
