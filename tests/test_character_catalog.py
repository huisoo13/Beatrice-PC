import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
from beatrice.character_catalog import CharacterCatalog
from beatrice.lostark import LostArkAuthError, LostArkNetworkError, LostArkMaintenanceError


def entry(name, job):
    return dict(CharacterName=name, CharacterClassName=job, ServerName='테스트', CharacterLevel=60, ItemAvgLevel='1,700.00')


class CharacterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000.0
        self.api = Mock()
        self.service = self.create()

    def create(self, available=True):
        return CharacterCatalog(self.folder.name, key_available=lambda: available,
                                client_factory=lambda:self.api, clock=lambda:self.now)

    def finish(self, service=None):
        service = service or self.service
        deadline = time.monotonic() + 2
        while not service.settled and time.monotonic() < deadline: time.sleep(.001)
        self.assertTrue(service.settled)
        return service.poll()

    def test_siblings_saved_in_full_reused_for_other_records_and_after_restart(self):
        self.api.characters.siblings.return_value = [entry('본캐','바드'), entry('부캐','도화가')]
        self.service.ensure(['본캐','본캐','부캐'])
        self.service.ensure(['본캐','부캐'])
        self.assertTrue(self.finish())
        self.now += 2
        self.service.ensure(['부캐','본캐','부캐'])
        self.api.characters.siblings.assert_called_once_with('본캐')
        self.api.characters.profile.assert_not_called()
        cached = self.create()
        cached.ensure(['부캐','본캐'])
        self.api.characters.siblings.assert_called_once()
        body = json.loads(self.service.path.read_text(encoding='utf-8'))
        self.assertEqual(body['characters']['부캐']['profile'],entry('부캐','도화가'))
        self.assertNotIn('key',body)
        resolver=Mock(return_value=Path(self.folder.name)/'class.svg')
        records=cached.decorate([{'character':'부캐'},{'character':'부캐'},{'character':'본캐'}],resolver)
        self.assertEqual(records[0]['characterClass'],'도화가')
        self.assertEqual(records[0]['itemLevel'],'1,700.00')
        self.assertTrue(records[0]['characterEmblem'].endswith('class.svg'))
        self.assertEqual(resolver.call_count,2)
        self.assertEqual(cached.character_view('부캐',resolver)['characterClass'],'도화가')

    def test_no_key_no_network_and_missing_emblem_keeps_class(self):
        service=self.create(available=False)
        service.ensure(['본캐'])
        self.api.characters.siblings.assert_not_called()
        self.assertEqual(service.decorate([{'character':'본캐'}],lambda job:None)[0]['characterEmblem'],None)

    def test_different_accounts_are_fetched_once_each(self):
        self.api.characters.siblings.side_effect=[[entry('첫계정','바드')],[entry('다른계정','도화가')]]
        self.service.ensure(['첫계정','다른계정']);self.finish()
        self.now += 2
        self.service.ensure(['첫계정','다른계정']);self.finish()
        self.now += 2
        self.service.ensure(['다른계정','첫계정'])
        self.assertEqual(self.api.characters.siblings.call_count,2)

    def test_auth_failure_blocks_other_names_and_key_change_resumes(self):
        self.api.characters.siblings.side_effect=LostArkAuthError('test')
        self.service.ensure(['첫캐릭']);self.finish()
        self.now += 2
        self.service.ensure(['다른캐릭'])
        self.assertEqual(self.api.characters.siblings.call_count,1)
        self.service.credentials_changed()
        self.api.characters.siblings.side_effect=None
        self.api.characters.siblings.return_value=[entry('다른캐릭','바드')]
        self.service.ensure(['다른캐릭']);self.finish()
        self.assertEqual(self.api.characters.siblings.call_count,2)

    def test_missing_character_negative_cache_survives_restart(self):
        self.api.characters.siblings.return_value=None
        self.service.ensure(['없는캐릭']);self.finish()
        self.now += 2
        self.create().ensure(['없는캐릭'])
        self.api.characters.siblings.assert_called_once()

    def test_maintenance_keeps_cache_blocks_all_names_and_recovers(self):
        self.service.characters = {'본캐': dict(profile=entry('본캐', '바드'), fetchedAt='cached')}
        self.api.characters.siblings.side_effect = LostArkMaintenanceError(retry_after=900)
        self.service.ensure(['새캐릭']); self.finish()
        self.assertEqual(self.service.retry_at['새캐릭'], 1900)
        self.assertEqual(self.service.blocked_until, 1900)
        resolver = lambda job: Path(self.folder.name) / 'class.svg'
        self.assertEqual(self.service.character_view('본캐', resolver)['characterClass'], '바드')
        missing = self.service.character_view('새캐릭', resolver)
        self.assertEqual(missing['characterClass'], '')
        self.assertIsNone(missing['characterEmblem'])
        self.now = 1500
        self.service.ensure(['다른캐릭', '새캐릭'])
        self.api.characters.siblings.assert_called_once()
        restarted = self.create()
        restarted.ensure(['새캐릭'])
        self.api.characters.siblings.assert_called_once()
        self.assertIn('본캐', restarted.characters)
        self.now = 1900
        self.api.characters.siblings.side_effect = None
        self.api.characters.siblings.return_value = [entry('새캐릭', '도화가')]
        self.service.ensure(['새캐릭']); self.finish()
        self.assertEqual(self.service.character_view('새캐릭', resolver)['characterClass'], '도화가')
        self.assertNotIn('새캐릭', self.service.retry_at)

    def test_cancelled_result_is_not_saved(self):
        started, release=threading.Event(),threading.Event()
        self.addCleanup(release.set)
        def fetch(name):
            started.set();release.wait(1);return [entry(name,'바드')]
        self.api.characters.siblings.side_effect=fetch
        self.service.ensure(['본캐']);self.assertTrue(started.wait(1))
        self.service.stop();release.set();self.assertFalse(self.finish())
        self.assertFalse(self.service.path.exists())

    def test_invalid_item_level_is_omitted_without_losing_profession(self):
        for level in ('NaN', 'Infinity', '-1', 'not a level', None):
            profile = dict(entry('본캐','바드'), ItemAvgLevel=level)
            self.service.characters = {'본캐':dict(profile=profile,fetchedAt='cached')}
            view = self.service.character_view('본캐',lambda job:None)
            self.assertEqual(view['itemLevel'],'')
            self.assertEqual(view['characterClass'],'바드')

    def test_corrupt_cache_does_not_break_records(self):
        self.service.path.parent.mkdir(parents=True,exist_ok=True)
        self.service.path.write_text('{broken',encoding='utf-8')
        service=self.create(available=False)
        self.assertEqual(service.decorate([{'character':'본캐'}],lambda job:None)[0]['characterClass'],'')
