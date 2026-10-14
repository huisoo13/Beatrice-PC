import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from beatrice.character_catalog import CharacterCatalog
from beatrice.character_record_service import CharacterRecordService
from beatrice.character_info import from_cache
from beatrice.completion_record import canonical, recognition_record, validate
from beatrice.drive_data import encode_records, decode_records, export_records, restore_records
from beatrice.lostark import LostArkNetworkError, LostArkMaintenanceError
from beatrice.storage import Store

AT = '2026-10-14T07:00:00+00:00'


def cached(level='1,774.16'):
    return dict(profile=dict(CharacterName='후이수', CharacterClassName='바드',
                             ServerName='아만', ItemAvgLevel=level), fetchedAt=AT)


class CharacterRecordTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(Path(self.folder.name)/'records.db')
        self.addCleanup(self.store.close)
        self.api = Mock()
        self.now = 1000
        self.available = True
        self.catalog = CharacterCatalog(self.folder.name, key_available=lambda:self.available,
            client_factory=lambda:self.api, clock=lambda:self.now)

    def save(self, dungeon='던전'):
        return self.store.save_completions('x', dungeon, [dict(characterName='후이수',
            dungeonName=dungeon, difficulty='하드', gate=1, state='완료', observedAt=AT)], 1)[0]

    def sync(self, service, name='후이수'):
        return service.sync(name, self.store.history_records())

    def finish(self, service):
        self.catalog.ensure([])
        self.catalog.pending[3].join(timeout=2)
        self.assertTrue(self.catalog.settled)
        self.catalog.poll()
        self.sync(service)

    def test_backfill_once_preserves_record_identity_times_and_rewards(self):
        row = self.save()
        self.catalog.characters['후이수'] = cached()
        revision = self.store.drive_revision()[1]
        CharacterRecordService(self.store, self.catalog)
        updated = self.store.history_records()[0]
        for field in ('recordId','observedAt','createdAt','contentName','difficulty','gateNumber'):
            self.assertEqual(updated[field],row[field])
        self.assertNotIn('source',updated['characterInfo'])
        self.assertEqual(updated['characterInfo']['itemLevel'],'1,774.16')
        self.assertGreater(updated['updatedAt'],row['updatedAt'])
        self.assertEqual(self.store.state_records(),[updated])
        self.assertEqual(self.store.drive_revision()[1],revision+1)
        self.catalog.characters['후이수'] = cached('1,800.00')
        CharacterRecordService(self.store,self.catalog)
        self.assertEqual(self.store.history_records(),[updated])

    def test_new_record_gets_fresh_info_old_record_and_display_remain_fixed(self):
        old = self.save('기존던전')
        self.catalog.characters['후이수'] = cached()
        service = CharacterRecordService(self.store,self.catalog)
        self.sync(service)
        new = self.save('새던전')
        self.sync(service)
        self.api.characters.siblings.return_value = [cached('1,780.16')['profile']]
        self.finish(service)
        rows = {row['recordId']:row for row in self.store.history_records()}
        self.assertEqual(rows[old['recordId']]['characterInfo']['itemLevel'],'1,774.16')
        self.assertEqual(rows[new['recordId']]['characterInfo']['itemLevel'],'1,780.16')
        self.assertFalse(self.store.pending_character_records())
        from beatrice.native_presentation import record_view
        views=self.catalog.decorate([record_view(row) for row in rows.values()],lambda job:None)
        self.assertEqual({row['itemLevel'] for row in views},{'1,774.16','1,780.16'})
        before=self.api.characters.siblings.call_count
        self.sync(service); self.catalog.ensure([])
        self.assertEqual(self.api.characters.siblings.call_count,before)

    def test_failure_freezes_fallback_and_later_cache_refresh_cannot_rewrite_record(self):
        self.catalog.characters['후이수'] = cached()
        service=CharacterRecordService(self.store,self.catalog)
        self.sync(service); self.save(); self.sync(service)
        self.api.characters.siblings.side_effect=LostArkMaintenanceError(retry_after=900)
        self.finish(service)
        frozen=self.store.history_records()[0]
        self.assertNotIn('source',frozen['characterInfo'])
        self.now += 900
        self.api.characters.siblings.side_effect=None
        self.api.characters.siblings.return_value=[cached('1,800.00')['profile']]
        self.finish(service)
        self.assertEqual(self.store.history_records(),[frozen])
        self.assertEqual(self.catalog.info('후이수')['itemLevel'],'1,800.00')

    def test_no_key_uses_cache_or_empty_without_requests(self):
        self.available=False
        service=CharacterRecordService(self.store,self.catalog)
        self.save(); self.sync(service)
        self.assertIsNone(self.store.history_records()[0]['characterInfo']['className'])
        self.catalog.ensure([])
        self.api.characters.siblings.assert_not_called()
        self.catalog.characters['후이수']=cached()
        self.save('두번째'); self.sync(service)
        self.assertEqual([r for r in self.store.history_records() if r['contentName']=='두번째'][0]['characterInfo']['itemLevel'],'1,774.16')

    def test_name_changes_refresh_cached_character_and_repeated_snapshots_do_not(self):
        service=CharacterRecordService(self.store,self.catalog)
        self.catalog.characters['후이수']=cached()
        self.api.characters.siblings.return_value=[cached()['profile']]
        self.sync(service);self.finish(service)
        self.sync(service);self.catalog.ensure([])
        self.api.characters.siblings.assert_called_once_with('후이수')
        self.now += 1
        self.sync(service,'다른캐릭터')
        self.api.characters.siblings.return_value=[dict(cached()['profile'],CharacterName='다른캐릭터')]
        self.finish(service)
        self.assertEqual(self.api.characters.siblings.call_args.args,('다른캐릭터',))

    def test_save_during_inflight_refresh_waits_for_a_newer_response(self):
        service=CharacterRecordService(self.store,self.catalog)
        release=threading.Event()
        self.addCleanup(release.set)
        self.api.characters.siblings.side_effect=lambda name: release.wait(2) and [cached()['profile']]
        self.sync(service); self.catalog.ensure([])
        self.save(); self.sync(service)
        release.set();self.catalog.pending[3].join(timeout=2);self.catalog.poll();self.sync(service)
        self.assertEqual(len(self.store.pending_character_records()),1)
        self.now += 1
        self.api.characters.siblings.side_effect=None
        self.api.characters.siblings.return_value=[cached('1,790.00')['profile']]
        self.finish(service)
        self.assertEqual(self.store.history_records()[0]['characterInfo']['itemLevel'],'1,790.00')
        self.assertEqual(self.api.characters.siblings.call_count,2)

    def test_drive_roundtrip_preserves_info_and_accepts_version_four(self):
        self.save();self.catalog.characters['후이수']=cached()
        CharacterRecordService(self.store,self.catalog)
        rows=export_records(self.store)[0]
        payload=encode_records(rows)
        self.assertEqual(json.loads(payload)['schemaVersion'],5)
        restore_records(self.store,decode_records(payload),Path(self.folder.name)/'backups')
        self.assertEqual(self.store.history_records(),rows)
        old=json.loads(payload);old['schemaVersion']=4
        self.assertEqual(decode_records(json.dumps(old).encode()),rows)
        row=rows[0]
        self.assertEqual(canonical(recognition_record(row))['characterInfo'],row['characterInfo'])

    def test_pending_new_record_resumes_after_restart(self):
        service=CharacterRecordService(self.store,self.catalog)
        self.save();self.sync(service)
        restarted=CharacterRecordService(self.store,self.catalog)
        self.api.characters.siblings.return_value=[cached('1,800.00')['profile']]
        self.finish(restarted)
        self.assertFalse(self.store.pending_character_records())

    def test_key_removed_while_pending_freezes_cache_instead_of_waiting_forever(self):
        self.catalog.characters['후이수']=cached()
        service=CharacterRecordService(self.store,self.catalog)
        self.save();self.sync(service)
        self.available=False
        self.catalog.credentials_changed()
        self.sync(service)
        frozen=self.store.history_records()[0]
        self.assertNotIn('source',frozen['characterInfo'])
        self.assertEqual(frozen['characterInfo']['itemLevel'],'1,774.16')
        self.sync(service)
        self.assertEqual(self.store.history_records(),[frozen])

    def test_snapshot_validation_rejects_bad_level_local_paths_and_wrong_types(self):
        row=self.save();info=from_cache(cached())
        for change in [dict(itemLevel='NaN'),dict(itemLevel=True),dict(className=1),
                       dict(fetchedAt='bad'),dict(unexpected=[]),dict(iconPath='C:/secret.svg')]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate(dict(row,characterInfo=dict(info,**change)))

    def test_old_source_is_read_compatibly_but_not_exported(self):
        row=self.save();info=dict(from_cache(cached()),source='cache_backfill')
        cleaned=validate(dict(row,characterInfo=info))
        self.assertNotIn('source',cleaned['characterInfo'])
        self.assertNotIn('source',json.loads(encode_records([dict(row,characterInfo=info)]))['records'][0]['characterInfo'])

    def test_source_cleanup_preserves_values_and_moves_pending_to_database(self):
        row=self.save();info=dict(from_cache(cached()),source='pending')
        # Fixture represents a file written by the previous application version.
        old=dict(row,characterInfo=info)
        with self.store.transaction():
            self.store.db.execute('UPDATE completion_history SET payload=? WHERE record_id=?',
                                  (json.dumps(old),row['recordId']))
        self.assertEqual(self.store.remove_character_info_source(),1)
        cleaned=self.store.history_records()[0]
        self.assertEqual(cleaned['characterInfo'],from_cache(cached()))
        for field in ('recordId','observedAt','createdAt','contentName'):
            self.assertEqual(cleaned[field],old[field])
        self.assertEqual(len(self.store.pending_character_records()),1)
        self.assertTrue(self.store.set_character_info(row['recordId'],from_cache(cached('1,800.00')),finalize_pending=True))
        self.assertFalse(self.store.pending_character_records())
        self.assertFalse(self.store.set_character_info(row['recordId'],from_cache(cached()),finalize_pending=True))
