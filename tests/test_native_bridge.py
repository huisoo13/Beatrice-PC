"""Protocol/controller regression tests. No models, OBS, game or network are started."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from beatrice import desktop
from beatrice.game_window import Client
from beatrice.native_bridge import Host, observation_view, record_view


class FakeWorker(QObject):
    progress = Signal(str)
    ready = Signal(list)
    observation = Signal(dict)
    process_changed = Signal(object)
    status = Signal(int, str)
    failed = Signal(str)
    settled = Signal(int)
    finished = Signal()
    def __init__(self):
        super().__init__()
        self.stop_event = threading.Event()
        self.running = False
        self.command = (0, None)
    def start(self): self.running = True
    def isRunning(self): return self.running
    def select(self, generation, client): self.command = generation, client
    def requested(self): return self.command
    def finish(self):
        self.running = False
        self.finished.emit()


class NativeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = patch.object(desktop, 'DATA', Path(self.folder.name))
        self.patch.start()
        self.messages = []
        self.workers = []
        def factory():
            worker = FakeWorker()
            self.workers.append(worker)
            return worker
        self.host = Host(self.app, self.messages.append, factory)
        self.host.next_check = float('inf')
        self.host.start()

    def tearDown(self):
        self.host.timer.stop()
        self.host.command_timer.stop()
        if not self.host.closing: self.host.store.close()
        self.patch.stop()
        self.folder.cleanup()

    def seed(self):
        row = dict(characterName='캐릭터', dungeonName='던전', difficulty='하드', gate=1,
                   state='완료', observedAt='2026-10-07T12:00:00+00:00')
        self.host.store.save_completions('name:캐릭터', '던전', [row], 2)
        return row

    def ready(self):
        self.workers[-1].ready.emit([])

    def test_catalog_thread_waits_until_models_are_initialized(self):
        self.host.next_check = 0
        with patch('beatrice.native_bridge.load_api_key') as api_key:
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
        with patch.object(desktop, 'find_clients', return_value=[client]):
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
        self.assertIsNone(observation_view(value)['dungeon'])

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

    def test_character_status_hides_capture_engine_diagnostics(self):
        self.ready()
        self.host.profile['character'] = '후이수'
        for raw, expected in [('내장 OBS 엔진 연결 중', '게임 화면 연결 중'),
                              ('OBS 새 게임 프레임 대기', '게임 화면 대기'),
                              ('OBS 최소화 상태 · 변경된 게임 프레임 대기', '게임 최소화')]:
            self.host.worker_status(self.host.generation, raw)
            self.assertEqual(self.host.profile['character'], '후이수')
            self.assertEqual(self.host.profile['message'], expected)
            self.assertEqual(self.host.status, raw)


if __name__ == '__main__': unittest.main()
