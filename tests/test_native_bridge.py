"""Protocol/controller regression tests. No models, OBS, game or network are started."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from beatrice.thread_events import Event,EventLoop
from beatrice import engine_worker as engine
from beatrice.game_window import Client
from beatrice.native_bridge import Host, DungeonFooter, observation_view, record_view


class FakeWorker:
    def __init__(self):
        for name in ('progress','ready','observation','process_changed','status','failed','settled','finished'):setattr(self,name,Event())
        self.stop_event = threading.Event()
        self.running = False
        self.command = (0, None)
    def join(self,timeout=None):pass
    def start(self): self.running = True
    def is_alive(self): return self.running
    def select(self, generation, client): self.command = generation, client
    def requested(self): return self.command
    def finish(self):
        self.running = False
        self.finished.emit()


class NativeBridgeTests(unittest.TestCase):
    def test_obs_snapshot_keeps_error_separate_and_rejects_stale_generation(self):
        self.host.obs(self.host.generation,dict(status='캡처 오류',error='OBS 접근 거부'))
        self.assertEqual(self.messages[-1]['obs'],dict(status='캡처 오류',error='OBS 접근 거부'))
        self.host.obs(self.host.generation-1,dict(status='old',error='old'))
        self.assertEqual(self.host.obs_state['error'],'OBS 접근 거부')
        self.host.obs(self.host.generation,dict(status='게임 화면 캡처 중',error=''))
        self.assertEqual(self.messages[-1]['obs']['error'],'')
    @classmethod
    def setUpClass(cls): cls.app = EventLoop()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = patch.object(engine, 'DATA', Path(self.folder.name))
        self.patch.start()
        self.messages = []
        self.workers = []
        def factory():
            worker = FakeWorker()
            self.workers.append(worker)
            return worker
        self.host = Host(self.app, self.messages.append, factory)
        from unittest.mock import Mock
        verified_client = Mock()
        verified_client.news.events.return_value = []
        self.host.lostark_registration.client_factory = lambda **kwargs: verified_client
        self.host.catalog.next_check = float('inf')
        self.host.start()

    def tearDown(self):
        self.host.timer.stop()
        self.host.command_timer.stop()
        if not self.host.closing: self.host.store.close()
        self.patch.stop()
        self.folder.cleanup()

    def test_old_worker_queued_callback_is_ignored_after_restart(self):
        worker=self.host.worker
        thread=threading.Thread(target=lambda:worker.progress.emit('old queued progress'))
        thread.start();thread.join()
        self.host.worker=FakeWorker()
        before=self.host.status
        self.app.drain()
        self.assertEqual(self.host.status,before)

    def test_lostark_api_command_persists_key_without_exposing_it(self):
        import json
        from beatrice.lostark_api import LostArkApiKey
        if os.name != 'nt': self.skipTest('Windows DPAPI')
        self.host.command(dict(type='lostark_api_save', key='dummy-bridge-key'))
        self.host.lostark_registration.pending[2].join(timeout=2)
        self.host.drain_commands()
        result = next(v for v in reversed(self.messages) if v['type'] == 'lostark_api_saved')
        self.assertTrue(result['success'])
        self.assertTrue(result['configured'])
        self.assertNotIn('dummy-bridge-key', json.dumps(self.messages))
        self.assertEqual(LostArkApiKey(self.folder.name).load(), 'dummy-bridge-key')
        self.host.command(dict(type='lostark_api_save', key=''))
        result = next(v for v in reversed(self.messages) if v['type'] == 'lostark_api_saved')
        self.assertFalse(result['success'])
        self.assertTrue(result['configured'])
        self.assertEqual(LostArkApiKey(self.folder.name).load(), 'dummy-bridge-key')

    def test_lostark_api_clear_command_removes_saved_key(self):
        self.host.lostark_api.path.write_bytes(b'encrypted-dummy')
        self.host.lostark_api.configured = True
        self.host.command(dict(type='lostark_api_clear'))
        result = next(v for v in reversed(self.messages) if v['type'] == 'lostark_api_cleared')
        self.assertTrue(result['success'])
        self.assertFalse(result['configured'])
        self.assertFalse(self.host.lostark_api.path.exists())

    def test_character_siblings_reach_record_emblems_without_repeat_calls(self):
        from unittest.mock import Mock
        import time
        if os.name != 'nt': self.skipTest('Windows DPAPI')
        api = Mock()
        api.characters.siblings.return_value = [dict(CharacterName='캐릭터', CharacterClassName='바드', ItemAvgLevel='1,774.16'),
                                                dict(CharacterName='다른캐릭터', CharacterClassName='도화가')]
        with patch('beatrice.character_catalog.LostArkClient.from_saved_key',return_value=api), \
             patch.object(self.host.catalog,'emblem_path',return_value=Path(self.folder.name)/'bard.svg'):
            self.seed()
            self.host.command(dict(type='lostark_api_save',key='dummy-profile-key'))
            self.host.lostark_registration.pending[2].join(timeout=2)
            self.host.drain_commands()
            deadline=time.monotonic()+2
            while not self.host.character_catalog.settled and time.monotonic()<deadline: time.sleep(.001)
            self.host.drain_commands()
            self.host.snapshot();self.host.snapshot()
            latest=next(v for v in reversed(self.messages) if v['type']=='snapshot')
            self.assertEqual(latest['records'][0]['characterClass'],'바드')
            self.assertEqual(latest['records'][0]['itemLevel'],'1,774.16')
            self.host.profile['character']='다른캐릭터'
            self.host.snapshot()
            latest=next(v for v in reversed(self.messages) if v['type']=='snapshot')
            self.assertEqual(latest['profile']['characterClass'],'도화가')
            self.assertTrue(latest['profile']['characterEmblem'].endswith('bard.svg'))
            self.assertTrue(latest['records'][0]['characterEmblem'].endswith('bard.svg'))
            api.characters.siblings.assert_called_once_with('캐릭터')
            api.characters.profile.assert_not_called()

    def seed(self):
        from datetime import datetime, timezone
        row = dict(characterName='캐릭터', dungeonName='던전', difficulty='하드', gate=1,
                   state='완료', observedAt=datetime.now(timezone.utc).isoformat())
        self.host.store.save_completions('name:캐릭터', '던전', [row], 2)
        return row

    def ready(self):
        self.workers[-1].ready.emit([])

    def test_weekly_reset_waits_for_worker_preserves_screen_drive_and_queue(self):
        from datetime import datetime, timedelta, timezone
        from beatrice.weekly import week_start
        from beatrice.drive_data import export_snapshot
        self.ready();self.seed()
        before=export_snapshot(self.host.store)
        future=datetime.now(timezone.utc)+timedelta(days=7)
        roll=self.host.store.roll_week
        with patch('beatrice.native_bridge.week_start',return_value=week_start(future)), \
                patch.object(self.host.store,'roll_week',side_effect=lambda:roll(future)):
            self.host.tick()
            self.assertEqual(self.host.maintenance_action,'weekly')
            self.assertEqual(len(self.host.store.state_records()),1)
            self.workers[-1].settled.emit(self.host.generation)
            self.assertFalse(self.host.maintenance)
            self.assertEqual(self.host.store.state_records(),[])
            self.assertEqual(len(self.host.store.history_records()),1)
            self.assertEqual(export_snapshot(self.host.store),before)
            self.assertEqual(len(self.messages[-1]['records']),1)

    def test_startup_waits_for_catalog_after_worker_ready(self):
        self.host.catalog.settings = {'refreshSeconds': 300}
        self.ready()
        self.assertFalse(self.messages[-1]['startupReady'])
        self.assertEqual(self.messages[-1]['startupStep'], 2)

    def test_startup_catalog_failure_preserves_cache_and_opens_main(self):
        import queue
        for cached in (None, {'checkedAt': '2026-10-07T15:00:00+00:00', 'content': {}}):
            self.host.catalog.settings = {'refreshSeconds': 300}
            self.host.catalog.cached = cached
            self.host.catalog.startup_finished = False
            self.ready()
            results = queue.Queue()
            results.put((None, 'offline'))
            self.host.catalog.pending = threading.Event(), results
            self.host.tick()
            self.assertIs(self.host.catalog.cached, cached)
            self.assertTrue(self.messages[-1]['startupReady'])
            self.assertEqual(self.messages[-1]['startupStep'], 3)

    def test_startup_missing_credentials_does_not_block_main(self):
        from beatrice.public_content import ContentError
        self.host.catalog.settings = {'refreshSeconds': 300}
        self.ready()
        with patch('beatrice.catalog_service.load_api_key', side_effect=ContentError('missing')):
            self.host.refresh_catalog()
        self.assertTrue(self.messages[-1]['startupReady'])

    def test_manual_catalog_refresh_has_persisted_five_minute_cooldown(self):
        self.ready()
        self.host.catalog.settings = {'refreshSeconds': 300}
        with patch('beatrice.native_bridge.time.time', return_value=1000), patch.object(self.host, 'refresh_catalog') as refresh:
            self.host.command({'type': 'catalog_refresh'})
            self.host.command({'type': 'catalog_refresh'})
            refresh.assert_called_once()
        self.assertEqual(self.host.catalog.refresh_available_at, 1300)
        import json
        saved = json.loads(self.host.catalog.cooldown_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['availableAt'], 1300)
        with patch('beatrice.native_bridge.time.time', return_value=1300), patch.object(self.host, 'refresh_catalog') as refresh:
            self.host.command({'type': 'catalog_refresh'})
            refresh.assert_called_once()
        self.assertEqual(self.host.catalog.refresh_available_at, 1600)

    def test_catalog_snapshot_reports_last_successful_update(self):
        self.host.catalog.cached = {'checkedAt': '2026-10-07T15:00:00+00:00', 'content': {}}
        self.host.catalog.message = '갱신 실패'
        self.host.snapshot()
        self.assertEqual(self.messages[-1]['catalogLastUpdated'], '2026-10-07T15:00:00+00:00')

    def test_catalog_thread_waits_until_models_are_initialized(self):
        self.host.catalog.next_check = 0
        with patch('beatrice.catalog_service.load_api_key') as api_key:
            self.host.refresh_catalog()
            self.host.tick()
            api_key.assert_not_called()
        self.ready()
        with patch.object(self.host, 'refresh_catalog') as refresh:
            self.host.tick()
            refresh.assert_called_once()

    def test_delete_waits_for_current_pause_ack_then_resumes(self):
        self.ready(); self.seed()
        client = Client(100, 200, 'LOST ARK')
        self.host.clients = [client]
        self.host.select(client)
        self.host.command(dict(type='delete'))
        generation = self.host.generation
        self.assertEqual(self.workers[-1].command, (generation, None))
        self.assertEqual(len(self.host.store.state_records()), 1)
        self.workers[-1].settled.emit(generation - 1)
        self.assertEqual(len(self.host.store.state_records()), 1)
        self.workers[-1].settled.emit(generation)
        self.assertEqual(self.host.store.state_records(), [])
        self.assertEqual(self.workers[-1].command, (generation + 1, client))
        self.assertFalse(self.host.maintenance)

    def test_restart_cannot_create_second_worker_before_cleanup(self):
        self.ready(); self.seed()
        self.host.command(dict(type='restart'))
        self.assertTrue(self.workers[0].stop_event.is_set())
        self.assertEqual(len(self.workers), 1)
        self.host.command(dict(type='restart'))
        self.assertEqual(len(self.workers), 1)
        self.workers[0].finish()
        self.assertEqual(len(self.workers), 2)
        self.assertFalse(self.host.initialized)
        self.assertTrue(self.workers[1].running)
        self.assertEqual(len(self.host.store.state_records()), 1)

    def test_generation_rejects_stale_observation_and_resets_footer(self):
        self.ready()
        first, second = Client(100, 200, 'A'), Client(101, 201, 'B')
        self.host.clients = [first, second]
        self.host.command(dict(type='select', hwnd=100))
        generation = self.host.generation
        self.host.command(dict(type='select', hwnd=101))
        self.host.observation(dict(generation=generation, identity=dict(currentName='잘못된 캐릭터', recordingAllowed=True)))
        self.assertEqual(self.host.profile['character'], '캐릭터 확인 대기')
        self.assertNotIn('dungeon', self.host.profile)

    def test_startup_watch_does_not_override_worker_initial_selection(self):
        client = Client(100, 200, 'A')
        with patch.object(engine, 'find_clients', return_value=[client]):
            self.host.process_changed(({200}, None))
        self.assertEqual(self.workers[0].command, (0, None))
        self.host.command(dict(type='delete'))
        self.assertFalse(self.host.maintenance)

    def test_snapshot_preserves_rewards_and_avoids_duplicate_emission(self):
        row = self.seed()
        self.host.snapshot()
        snapshot = self.messages[-1]
        self.assertEqual(snapshot['records'][0]['dungeon'], '던전')
        count = len(self.messages)
        self.host.snapshot()
        self.assertEqual(len(self.messages), count)
        row['catalogMatch'] = dict(status='matched', dungeonName='던전', difficulty='하드',
                                  gateName='1관문', values=dict(gold=10000, fee=2000, bound_percentage=.2))
        self.assertEqual(record_view(row)['detail']['values']['gold'], 10000)

    def test_only_current_verified_dungeon_and_stable_gate_are_shown(self):
        value = dict(identity=dict(currentName='후이수', recordingAllowed=True),
                     dungeon=dict(dungeonName='카멘', difficulty='하드', contextStatus='ocr_verified', currentRaidPanel=True),
                     result=dict(stableStates=['완료', '진행중', '진행 전']))
        view = observation_view(value)
        self.assertEqual(view['dungeonSubtitle'], '하드 · 2관문')
        self.assertEqual(view['dungeonState'], '진행 중')
        value['dungeon']['contextStatus'] = 'ocr_held'
        self.assertEqual(observation_view(value)['dungeon'], '카멘')

    def test_shutdown_waits_until_worker_finished(self):
        self.host.command(dict(type='shutdown'))
        self.assertTrue(self.workers[0].stop_event.is_set())
        self.assertNotEqual(self.messages[-1]['type'], 'stopped')
        self.workers[0].finish()
        self.assertEqual(self.messages[-1]['type'], 'stopped')

    def test_footer_uses_current_gate_instead_of_saved_completions(self):
        value = dict(identity=dict(currentName='후이수', recordingAllowed=True),
                     dungeon=dict(dungeonName='카멘', difficulty='하드', contextStatus='ocr_verified', currentRaidPanel=True),
                     result=dict(stableStates=['완료', '완료'], observedStates=['완료', '진행중']))
        view = observation_view(value)
        self.assertEqual(view['dungeonSubtitle'], '하드 · 2관문')
        self.assertEqual(view['dungeonState'], '진행 중')
        value['result']['observedStates'] = None
        self.assertEqual(observation_view(value)['dungeonSubtitle'], '하드')

    def test_character_status_preserves_identity_during_capture_diagnostics(self):
        self.ready()
        self.host.observation(dict(generation=self.host.generation, identity=dict(currentName='후이수', recordingAllowed=True)))
        for raw in ('내장 OBS 엔진 연결 중', 'OBS 새 게임 프레임 대기', 'OBS 최소화 상태', '게임 실행 대기'):
            self.host.worker_status(self.host.generation, raw)
            self.assertEqual(self.host.profile['character'], '후이수')
            self.assertEqual(self.host.profile['message'], '플레이 중')
            self.assertEqual(self.host.profile['characterState'], 'playing')
            self.assertEqual(self.host.status, raw)

    def test_character_states_are_character_specific(self):
        cases = [({}, '캐릭터 미설정', 'unset'),
                 (dict(currentName='후이수', recordingAllowed=True), '플레이 중', 'playing'),
                 (dict(status='switching', currentName='후이수', pendingName='다음'), '캐릭터 변경 중', 'selecting'),
                 (dict(status='initial_login_selection'), '캐릭터 선택 중', 'selecting'),
                 (dict(status='initial_login_loading', pendingName='다음'), '캐릭터 선택 중', 'selecting')]
        for identity, message, state in cases:
            view = observation_view(dict(identity=identity))
            self.assertEqual((view['message'], view['characterState']), (message, state))

    def footer_frame(self, panel=True, held=False):
        return dict(generation=self.host.generation,
            identity=dict(currentName='후이수', recordingAllowed=True),
            dungeon=dict(dungeonName='카멘', difficulty='하드', currentRaidPanel=panel,
                         contextStatus='ocr_held' if held else 'ocr_verified'),
            result={} if held else dict(observedStates=['완료', '진행중']))

    def test_held_dungeon_and_gate_survive_video_until_thirty_seconds(self):
        self.ready()
        with patch('beatrice.native_bridge.time.monotonic', return_value=100):
            self.host.observation(self.footer_frame())
        for now in (101, 129.999):
            with patch('beatrice.native_bridge.time.monotonic', return_value=now):
                self.host.observation(self.footer_frame(panel=False, held=True))
                self.assertEqual(self.host.profile['dungeon'], '카멘')
                self.assertEqual(self.host.profile['dungeonSubtitle'], '하드 · 2관문')
        with patch('beatrice.native_bridge.time.monotonic', return_value=130):
            self.host.tick()
        self.assertIsNone(self.host.profile['dungeon'])

    def test_panel_visibility_extends_grace_even_without_readable_ocr(self):
        from beatrice.content_match import ContentMatcher
        footer = DungeonFooter(); matcher = ContentMatcher()
        footer.update(self.footer_frame(), 100)
        footer.update(dict(dungeon=dict(raidPanelVisible=True, currentRaidPanel=False)), 125)
        self.assertEqual(footer.view(matcher,154.999)['dungeon'], '카멘')
        self.assertIsNone(footer.view(matcher,155)['dungeon'])
        footer.update(dict(dungeon=dict(currentRaidPanel=True)),160)
        self.assertEqual(footer.view(matcher,160)['dungeon'], '카멘')

    def test_no_new_frames_still_expires_after_capture_wait(self):
        self.ready()
        with patch('beatrice.native_bridge.time.monotonic', return_value=10):
            self.host.observation(self.footer_frame())
        self.host.worker_status(self.host.generation,'OBS 새 게임 프레임 대기')
        self.assertEqual(self.host.profile['dungeon'], '카멘')
        with patch('beatrice.native_bridge.time.monotonic', return_value=40): self.host.tick()
        self.assertIsNone(self.host.profile['dungeon'])
        self.assertEqual(self.host.profile['message'], '플레이 중')

    def test_footer_catalog_labels_match_record_and_unknown_preserves_ocr(self):
        from beatrice.content_match import ContentMatcher
        name, typo = '4막: 파멸의 성채', '4막 : 파멸의 성체'
        values = dict(gold=10000, fee=3200, bound_percentage=.5)
        cached = dict(content={name: {'싱글 모드': {'1관문': values, '2관문': values}}})
        matcher = ContentMatcher(cached)
        frame = self.footer_frame()
        frame['dungeon'].update(dungeonName=typo, difficulty='싱글모드')
        view = observation_view(frame, matcher)
        recorded = matcher.record(dict(dungeonName=typo, difficulty='싱글모드', gate=1))
        self.assertEqual(view['dungeon'], recorded['dungeonName'])
        self.assertEqual(view['dungeonSubtitle'], recorded['difficulty']+' · 2관문')
        frame['dungeon'].update(dungeonName='미등록 던전', difficulty='알수없는 모드')
        view = observation_view(frame, matcher)
        self.assertEqual(view['dungeon'], '미등록 던전')
        self.assertEqual(view['dungeonSubtitle'], '알수없는 모드 · 2관문')
    def authorize_drive(self):
        from beatrice.google_auth import DRIVE_SCOPE
        self.ready()
        self.host.account.session=dict(account={'sub':'person','email':'test@example.com'},scopes=[DRIVE_SCOPE])

    def fake_download(self):
        from test_drive_services import FakeJob
        from beatrice.drive_data import validate_records
        rows=validate_records([dict(characterName='원격캐릭터',dungeonName='던전',difficulty='하드',gate=1,state='완료')])
        self.host.drive.pending=dict(job=FakeJob(dict(records=rows,metadata={'createdTime':'2026-10-08T00:00:00Z'})),action='download',account='person')

    def test_drive_restore_waits_for_pause_preview_and_explicit_confirmation(self):
        self.authorize_drive();self.seed()
        with patch('beatrice.drive_service.Job'):
            self.host.command(dict(type='drive_download'))
            generation=self.host.generation
            self.assertEqual(self.workers[-1].command,(generation,None))
            self.assertIsNone(self.host.drive.pending)
            self.host.settled(generation-1);self.assertIsNone(self.host.drive.pending)
            self.host.settled(generation);self.assertIsNotNone(self.host.drive.pending)
            self.host.settled(generation);self.assertTrue(self.host.maintenance)
            self.assertEqual(self.workers[-1].command,(generation,None))
        self.fake_download();self.host.drain_commands()
        preview=next(m for m in self.messages if m['type']=='drive_preview')
        self.assertEqual(self.host.store.state_records()[0]['characterName'],'캐릭터')
        self.host.command(dict(type='drive_restore',previewId='stale',apply=True))
        self.assertTrue(self.host.maintenance)
        self.host.command(dict(type='drive_restore',previewId=preview['previewId'],apply=True))
        self.assertEqual(self.host.store.history_records()[0]['characterName'],'원격캐릭터')
        self.assertFalse(self.host.maintenance)
        self.assertEqual(self.workers[-1].command,(generation+1,None))

    def test_restore_holds_new_game_and_resumes_after_cancel(self):
        self.authorize_drive()
        client=Client(100,200,'LOSTARK')
        with patch('beatrice.drive_service.Job'):
            self.host.command(dict(type='drive_download'));generation=self.host.generation
            self.host.settled(generation)
        with patch.object(engine,'find_clients',return_value=[client]):
            self.host.process_changed(({200},None))
            self.assertEqual(self.workers[-1].command,(generation,None))
            self.fake_download();self.host.drain_commands()
            preview=self.host.drive.preview['id']
            self.host.command(dict(type='delete'))
            self.host.command(dict(type='restart'))
            self.host.command(dict(type='google_logout'))
            self.assertTrue(self.host.maintenance)
            self.assertIsNotNone(self.host.account.session)
            self.host.command(dict(type='drive_restore',previewId=preview,apply=False))
            self.assertEqual(self.workers[-1].command,(generation+1,client))

    def test_download_failure_resumes_analysis_and_keeps_records(self):
        from test_drive_services import FakeJob
        self.authorize_drive();self.seed()
        with patch('beatrice.drive_service.Job'):
            self.host.command(dict(type='drive_download'));self.host.settled(self.host.generation)
        self.host.drive.pending=dict(job=FakeJob(error='offline'),action='download',account='person')
        self.host.drain_commands()
        self.assertFalse(self.host.maintenance)
        self.assertEqual(len(self.host.store.state_records()),1)

    def test_upload_blocks_mutations_and_account_changes_but_keeps_analysis(self):
        self.authorize_drive();self.seed()
        with patch('beatrice.drive_service.Job'):
            self.host.command(dict(type='drive_upload'))
        generation=self.host.generation
        for kind in ('delete','restart','google_logout','drive_download'):
            self.host.command(dict(type=kind))
        self.assertFalse(self.host.maintenance)
        self.assertEqual(self.host.generation,generation)
        self.assertIsNotNone(self.host.account.session)
        self.host.drive.pending=None

    def test_host_automatic_upload_is_suspended_during_record_maintenance(self):
        self.authorize_drive();self.seed()
        self.host.pause_for('delete')
        with patch.object(self.host.drive,'check_auto_upload') as check:
            self.host.tick();check.assert_not_called()

    def test_shutdown_waits_for_network_and_worker_and_preserves_verified_ack(self):
        from test_drive_services import FakeJob
        self.authorize_drive();self.seed()
        job=FakeJob({'id':'file'})
        with patch.object(job,'result',return_value=None):
            self.host.drive.pending=dict(job=job,action='upload',account='person',revision=self.host.store.drive_revision(),count=1,omitted=0,automatic=True)
            self.host.command(dict(type='shutdown'));self.workers[-1].finish()
            self.assertFalse(self.host.closed)
            self.host.drain_commands();self.assertFalse(self.host.closed)
        self.host.drain_commands()
        self.assertTrue(self.host.closed);self.assertEqual(self.messages[-1]['type'],'stopped')
        from beatrice.storage import Store
        check=Store(Path(self.folder.name)/'records.sqlite3')
        try:self.assertIsNone(check.drive_pending('person'))
        finally:check.close()

    def test_public_catalog_commands_keep_cache_after_network_failure(self):
        import queue
        self.ready()
        cached=dict(checkedAt='2026-10-08T00:00:00Z',content={'던전':{'하드':{'1관문':{'gold':100,'fee':20,'bound_percentage':0.2}}}})
        self.host.catalog.cached=cached
        replies=queue.Queue();replies.put((None,'offline'))
        self.host.catalog.pending=threading.Event(),replies
        self.host.tick();self.assertIs(self.host.catalog.cached,cached)
        self.host.command(dict(type='catalog'))
        self.assertEqual(self.messages[-1]['rows'][0]['gold'],100)
        with patch('beatrice.catalog_service.load_api_key',side_effect=ValueError('unused')) as key:
            self.host.command(dict(type='shutdown'));self.host.tick();key.assert_not_called()
        self.workers[-1].finish()


    def test_queued_login_cancel_wins_over_ready_auth_result(self):
        from test_drive_services import FakeJob, session
        self.ready();self.host.account.pending=FakeJob(session())
        self.host.commands.put(dict(type='google_cancel'))
        with patch.object(self.host.account.tokens,'save') as save:
            self.host.drain_commands();save.assert_not_called()
        self.assertIsNone(self.host.account.session)

    def test_queued_shutdown_does_not_persist_ready_login_result(self):
        from test_drive_services import FakeJob, session
        self.ready();self.host.account.pending=FakeJob(session())
        self.host.commands.put(dict(type='shutdown'))
        with patch.object(self.host.account.tokens,'save') as save:
            self.host.drain_commands()
            self.workers[-1].finish()
            save.assert_not_called()
        self.assertTrue(self.host.closed)

    def test_restart_retries_failed_saved_login_restore(self):
        from test_drive_services import session
        self.ready();self.assertTrue(self.host.account.restored)
        self.assertIsNone(self.host.account.session)
        self.host.command(dict(type='restart'));self.workers[-1].finish()
        with patch.object(self.host.account.tokens,'load',return_value=session()),patch.object(self.host.account,'begin') as begin:
            self.ready();begin.assert_called_once_with(False,session())

    def test_drive_view_matches_rejected_commands_after_worker_failure(self):
        self.authorize_drive();self.host.failed('model failure');self.host.snapshot()
        self.assertFalse(self.messages[-1]['drive']['available'])


    def test_restart_clears_previous_error_and_resets_startup_progress(self):
        self.ready();self.host.failed('previous error')
        self.host.command(dict(type='restart'))
        state=self.messages[-1]
        self.assertTrue(state['restarting']);self.assertFalse(state['startupReady'])
        self.assertEqual(state['startupStep'],0);self.assertEqual(state['error'],'')
        self.workers[-1].finish();self.ready()
        self.assertFalse(self.messages[-1]['restarting'])


if __name__ == '__main__': unittest.main()
