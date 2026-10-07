import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock,patch
from PySide6.QtWidgets import QApplication
from beatrice import desktop
from beatrice.game_window import Client


class StartupCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def run_startup(self,clients,replace=False):
        worker=desktop.Worker();events=[]
        capture=Mock(wait_kind='transient',observed_at=None)
        capture.binding_ready=threading.Event();capture.binding_ready.set()
        capture.prepare.side_effect=lambda stop:events.append('engine_ready') or True
        watch=Mock(pids=frozenset(c.pid for c in clients))
        watch.ready=threading.Event();watch.ready.set();watch.stop_event=threading.Event()
        replacement=Client(101,201,'LOSTARK')
        def grab():
            if replace and worker.requested()[1]!=replacement:worker.select(2,replacement)
            else:worker.stop_event.set()
            return None,'waiting'
        capture.grab.side_effect=grab
        def ready(found):
            events.append('main_ready')
            self.assertEqual(found,clients)
            if not replace:worker.stop_event.set()
        worker.ready.connect(ready)
        failures=[];worker.failed.connect(failures.append)
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            stack.enter_context(patch.object(desktop,'DATA',Path(folder)))
            stack.enter_context(patch.object(desktop,'ProcessWatch',return_value=watch))
            stack.enter_context(patch.object(desktop,'find_clients',side_effect=lambda pids:events.append('game_query') or clients))
            stack.enter_context(patch.object(desktop,'client_active',return_value=True))
            stack.enter_context(patch.object(desktop,'client_alive',return_value=True))
            for name in ('character_vision.CharacterVision','dungeon.DungeonOCR','dungeon.DungeonTracker',
                         'live.LiveCoordinator','ui_regions.UIRegionDetector','dungeon_observer.DungeonObserver',
                         'completion_overlay.CompletionOverlayDetector','completion_diagnostic.CompletionDiagnostic',
                         'recognition_diagnostic.RecognitionDiagnostic'):
                stack.enter_context(patch('beatrice.'+name))
            factory=stack.enter_context(patch('beatrice.obs_capture.ObsCapture',return_value=capture))
            worker.run()
            factory.assert_called_once_with(None,Path(folder))
            self.assertEqual(failures,[])
            self.assertFalse((Path(folder)/'errors.log').exists())
        capture.prepare.assert_called_once_with(worker.stop_event)
        capture.close.assert_called_once()
        watch.join.assert_called_once()
        return worker,capture,events,replacement

    def test_engine_is_ready_before_main_even_without_game(self):
        worker,capture,events,_=self.run_startup([])
        self.assertEqual(events,['engine_ready','main_ready'])
        capture.grab.assert_not_called()
        self.assertEqual(worker.requested(),(0,None))

    def test_existing_game_connects_in_splash_and_relaunch_reuses_engine(self):
        client=Client(100,200,'LOSTARK')
        worker,capture,events,replacement=self.run_startup([client],replace=True)
        self.assertEqual(events,['engine_ready','game_query','main_ready'])
        self.assertEqual(capture.bind.call_args_list[0].args,(client,))
        self.assertEqual(capture.bind.call_args_list[-1].args,(replacement,))
        self.assertEqual(worker.settled_generation,2)
