import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock

from PySide6.QtWidgets import QApplication
from beatrice import desktop
from beatrice.game_window import Client,find_clients


class ClientDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.data=patch.object(desktop,'DATA',Path(self.tmp.name));self.data.start();self.addCleanup(self.data.stop)
        self.active=patch.object(desktop,'client_active',return_value=True).start()
        self.alive=patch.object(desktop,'client_alive',return_value=True).start()
        self.search=patch.object(desktop,'find_clients',return_value=[]).start()
        self.addCleanup(patch.stopall)
        self.worker=desktop.Worker()
        self.window=desktop.Window(self.worker,[])
        self.window.process_pids=frozenset({200})
        self.addCleanup(self.window.close)
        self.client=Client(100,200,'LOSTARK')

    def test_missing_client_receives_background_poll_without_ui_window_search(self):
        self.window.process_pids=frozenset()
        self.assertEqual(self.window.status_label.text(),'클라이언트 실행 대기')
        self.assertIn('#dc2626',self.window.status_dot.styleSheet())
        self.window.tick();self.search.assert_not_called()
        self.search.return_value=[self.client]
        self.window.process_changed((frozenset({200}),''))
        self.assertEqual(self.window.client,self.client)
        self.assertTrue(self.window.analyzing)
        self.assertEqual(self.worker.requested()[1],self.client)
        self.assertEqual(self.window.status_label.text(),'내장 OBS · 첫 게임 프레임 대기')
        self.assertIn('#ca8a04',self.window.status_dot.styleSheet())

    def test_process_before_window_waits_for_window_creation(self):
        self.window.process_changed((frozenset({200}),''))
        self.assertEqual(self.window.status_label.text(),'클라이언트 시작 중 · 게임 창 생성 대기')
        self.search.return_value=[self.client];self.window.tick()
        self.assertEqual(self.window.client,self.client)

    def test_poll_detects_exit_and_clears_client(self):
        self.window.apply_clients([self.client])
        self.window.process_changed((frozenset(),''))
        self.assertIsNone(self.window.client)
        self.search.reset_mock();self.window.tick();self.search.assert_not_called()

    def test_process_query_failure_is_visible(self):
        self.window.process_changed((frozenset(),'프로세스 확인 실패'))
        self.assertIn('프로세스 확인 실패',self.window.status_label.text())
        self.search.reset_mock();self.window.tick();self.search.assert_not_called()

    def test_background_client_can_analyze_and_wait_for_actual_frames(self):
        self.active.return_value=False;self.window.apply_clients([self.client])
        self.assertTrue(self.window.analyzing)
        self.assertEqual(self.worker.requested()[1],self.client)
        self.window.detail.setText('분석 중 · 게임 창 직접 캡처');self.window.update_status()
        self.assertEqual(self.window.status_label.text(),'분석 중')
        self.window.worker_status(self.window.generation,'최소화 상태 · 새 게임 프레임 대기')
        self.assertEqual(self.window.status_label.text(),'최소화 상태 · 새 게임 프레임 대기')
        self.assertIn('#ca8a04',self.window.status_dot.styleSheet())

    def test_refresh_same_client_does_not_restart_analysis(self):
        self.search.return_value=[self.client];self.window.start()
        command=self.worker.requested()
        self.window.refresh()
        self.assertEqual(command,self.worker.requested())
        self.assertTrue(self.window.analyzing)

    def test_relaunch_changes_session_and_discards_old_signals(self):
        self.search.return_value=[self.client];self.window.start()
        old_generation=self.window.generation
        self.search.return_value=[];self.window.refresh()
        self.assertEqual(self.worker.requested()[1],None)
        replacement=Client(100,201,'LOSTARK')
        self.search.return_value=[replacement];self.window.process_changed((frozenset({201}),''))
        self.assertEqual(self.worker.requested()[1],replacement)
        self.window.worker_status(old_generation,'old message')
        self.window.update_observation({'generation':old_generation})
        self.assertNotIn('old message',self.window.detail.text())

    def test_delete_waits_for_analysis_then_automatically_resumes(self):
        self.search.return_value=[self.client];self.window.apply_clients([self.client])
        with patch.object(self.window.store,'clear_all') as clear:
            self.window.delete()
            paused=self.window.generation
            self.assertFalse(self.window.delete_button.isEnabled())
            self.assertIsNone(self.worker.requested()[1]);clear.assert_not_called()
            self.window.refresh()  # Process polling cannot resume a pending delete.
            self.assertIsNone(self.worker.requested()[1])
            self.window.command_settled(paused-1);clear.assert_not_called()
            self.window.command_settled(paused);clear.assert_called_once()
            self.assertIsNone(self.window.maintenance)
            self.assertEqual(self.worker.requested()[1],self.client)
            self.assertTrue(self.window.analyzing)

    def test_restore_pauses_until_settled_and_resumes_after_completion(self):
        self.search.return_value=[self.client];self.window.apply_clients([self.client])
        def begin():self.window.drive.busy=True
        action=Mock(side_effect=begin)
        self.window.prepare_restore(action)
        action.assert_not_called()
        self.window.command_settled(self.window.generation)
        action.assert_called_once()
        self.window.refresh();self.assertIsNone(self.worker.requested()[1])
        self.window.drive.busy=False;self.window.drive_changed()
        self.assertEqual(self.worker.requested()[1],self.client)
        self.assertIsNone(self.window.maintenance)

    def test_prepared_startup_target_is_kept_without_another_selection(self):
        self.worker.select(7,self.client);self.worker.settled_generation=7
        window=desktop.Window(self.worker,[self.client])
        try:
            self.assertEqual(window.generation,7)
            self.assertEqual(self.worker.requested(),(7,self.client))
            self.assertTrue(window.analyzing)
            self.assertFalse(hasattr(window,'start_button'))
            self.assertFalse(hasattr(window,'stop_button'))
        finally:window.close()

    def test_restore_started_without_game_keeps_new_game_paused(self):
        from beatrice.drive_ui import DRIVE_SCOPE
        self.window.drive.login.session={'account':{'sub':'test'},'scopes':[DRIVE_SCOPE]}
        self.window.drive.login.pending=None
        with patch('beatrice.drive_ui.threading.Thread'):
            self.window.drive.begin('download')
            self.assertEqual(self.window.maintenance,'restore')
            self.window.command_settled(self.window.generation)
            self.assertTrue(self.window.drive.busy)
            self.window.apply_clients([self.client])
            self.assertFalse(self.window.analyzing)
            self.assertIsNone(self.worker.requested()[1])
            self.window.drive.pending=None;self.window.drive.busy=False
            self.search.return_value=[self.client];self.window.drive_changed()
            self.assertTrue(self.window.analyzing)

    def test_pending_record_action_blocks_automatic_upload(self):
        self.window.prepare_restore(Mock())
        with patch.object(self.window.store,'drive_pending') as pending:
            self.window.drive.check_auto_upload();pending.assert_not_called()

    def test_blue_only_after_observation(self):
        self.search.return_value=[self.client];self.window.start()
        self.assertNotEqual(self.window.status_label.text(),'분석 중')
        self.window.update_observation(dict(generation=self.window.generation,
            identity=dict(currentName='name',recordingAllowed=True),dungeon={},
            size='1920 × 1080',milliseconds=10))
        self.assertEqual(self.window.status_label.text(),'분석 중')
        self.assertIn('#2563eb',self.window.status_dot.styleSheet())

    def test_startup_enters_main_even_without_client(self):
        with patch.object(desktop.Worker,'start'):
            startup=desktop.Startup()
            startup.open_main([])
            self.assertIsNotNone(startup.window)
            self.assertEqual(startup.window.status_label.text(),'클라이언트 실행 대기')
            startup.window.close();startup.close()
            self.app.processEvents()

    def test_refresh_button_reloads_from_splash_after_worker_finishes(self):
        with patch.object(desktop.Worker,'start') as start:
            startup=desktop.Startup();self.app.processEvents()
            startup.open_main([self.client]);old_worker=startup.worker;old_window=startup.window
            old_window.start()
            with patch.object(old_worker,'isRunning',return_value=True):
                old_window.refresh_button.click()
                self.assertTrue(startup.isVisible())
                self.assertFalse(old_window.isVisible())
                self.assertFalse(old_window.timer.isActive())
                self.assertTrue(old_worker.stop_event.is_set())
                self.assertIs(startup.worker,old_worker)
                startup.restart()  # Repeated requests cannot create another worker.
                self.assertEqual(start.call_count,1)
            old_worker.finished.emit()
            self.assertIsNot(startup.worker,old_worker)
            self.assertEqual(start.call_count,2)
            self.assertIsNone(startup.window)
            startup.worker.ready.emit([])
            self.assertTrue(startup.window.isVisible())
            self.assertFalse(startup.window.analyzing)
            startup.window.close();startup.close();self.app.processEvents()

    def test_refresh_recovers_failed_startup(self):
        with patch.object(desktop.Worker,'start') as start:
            startup=desktop.Startup();self.app.processEvents()
            startup.startup_failed('model failure')
            old_worker=startup.worker
            startup.window.refresh_button.click()
            self.assertIsNot(startup.worker,old_worker)
            self.assertTrue(startup.isVisible())
            self.assertEqual(start.call_count,2)
            startup.worker.ready.emit([])
            self.assertEqual(startup.window.error,'')
            startup.window.close();startup.close();self.app.processEvents()

    def test_closing_during_refresh_does_not_restart(self):
        with patch.object(desktop.Worker,'start') as start:
            startup=desktop.Startup();self.app.processEvents();startup.open_main([])
            with patch.object(startup.worker,'isRunning',return_value=True):
                startup.window.refresh_button.click();startup.close()
                self.assertTrue(startup.closing)
            startup.worker.finished.emit()
            self.assertEqual(start.call_count,1)
            self.assertIsNone(startup.window)
            self.assertFalse(startup.isVisible())
            self.app.processEvents()

    def test_non_windows_discovery_is_empty(self):
        with patch('beatrice.game_window.sys.platform','linux'):
            self.assertEqual(find_clients(),[])

    @unittest.skipUnless(os.name=='nt','Windows enumeration callback')
    def test_executable_identity_ignores_title_version_and_rejects_browser(self):
        titles={100:'LOST ARK (64-bit, DX11) v.3.23.5.2',
                101:'LOST ARK (future environment) v.99',102:'LOSTARK guide'}
        api=Mock()
        api.GetWindowTextLengthW.side_effect=lambda hwnd:len(titles[hwnd])
        api.IsWindowVisible.return_value=True
        api.GetWindowTextW.side_effect=lambda hwnd,buffer,size:setattr(buffer,'value',titles[hwnd])
        api.GetWindowThreadProcessId.side_effect=lambda hwnd,pid:setattr(pid._obj,'value',hwnd)
        api.EnumWindows.side_effect=lambda callback,data:[callback(hwnd,0) for hwnd in titles]
        with patch('beatrice.game_window.api',return_value=api),patch(
                'beatrice.game_window.process_name',side_effect=lambda pid:'chrome.exe' if pid==102 else 'lostark.exe'):
            self.assertEqual([c.hwnd for c in find_clients()],[100,101])


if __name__=='__main__':unittest.main()
