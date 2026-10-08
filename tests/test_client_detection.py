"""Client lifecycle in the current headless host, without Qt screens."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication,QObject,Signal
from beatrice import engine_worker as engine
from beatrice.game_window import Client
from beatrice.native_bridge import Host

class Worker(QObject):
    progress=Signal(str);ready=Signal(list);observation=Signal(dict);process_changed=Signal(object)
    status=Signal(int,str);failed=Signal(str);settled=Signal(int);finished=Signal()
    def __init__(self):
        super().__init__();self.stop_event=threading.Event();self.running=False;self.selection=(0,None)
    def start(self):self.running=True
    def requested(self):return self.selection
    def select(self,generation,client):self.selection=(generation,client)
    def isRunning(self):return self.running

class ClientDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.data=patch.object(engine,'DATA',Path(self.tmp.name));self.data.start();self.addCleanup(self.data.stop)
        self.search=patch.object(engine,'find_clients',return_value=[]);self.find=self.search.start();self.addCleanup(self.search.stop)
        self.active=patch.object(engine,'client_active',return_value=True);self.active.start();self.addCleanup(self.active.stop)
        self.worker=Worker();self.messages=[];self.host=Host(self.app,self.messages.append,lambda:self.worker)
        self.host.start();self.host.next_check=float('inf');self.host.ready([])
        self.client=Client(100,200,'LOSTARK')
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.host.account.shutdown();self.host.drive.shutdown()
        self.host.timer.stop();self.host.command_timer.stop();self.host.store.close()
    def test_no_process_does_not_search_windows(self):
        self.host.process_changed((frozenset(),''));self.host.tick();self.find.assert_not_called()
        self.assertIsNone(self.host.client)
    def test_process_before_window_is_picked_up_on_next_tick(self):
        self.host.process_changed(({200},''));self.assertIsNone(self.host.client)
        self.find.return_value=[self.client];self.host.tick()
        self.assertEqual(self.worker.requested()[1],self.client)
    def test_process_exit_clears_current_target(self):
        self.find.return_value=[self.client];self.host.process_changed(({200},''))
        self.host.process_changed((frozenset(),''));self.assertIsNone(self.worker.requested()[1])
    def test_background_client_and_repeat_scan_do_not_restart(self):
        with patch.object(engine,'client_active',return_value=False):
            self.find.return_value=[self.client];self.host.process_changed(({200},''))
            selection=self.worker.requested();self.host.refresh_clients()
        self.assertEqual(self.worker.requested(),selection)
        self.assertEqual(selection[1],self.client)
    def test_relaunch_changes_generation_and_discards_old_status(self):
        self.find.return_value=[self.client];self.host.process_changed(({200},''));old=self.host.generation
        replacement=Client(100,201,'LOSTARK');self.find.return_value=[replacement]
        self.host.process_changed(({201},''));self.host.worker_status(old,'stale')
        self.assertEqual(self.worker.requested()[1],replacement);self.assertNotEqual(self.host.status,'stale')
    def test_process_query_error_is_shown(self):
        self.host.process_changed((frozenset(),'프로세스 확인 실패'))
        self.assertEqual(self.host.status,'프로세스 확인 실패')
    def test_manual_selection_uses_current_client_list(self):
        second=Client(101,201,'B');self.find.return_value=[self.client,second]
        self.host.process_changed(({200,201},''));self.host.command(dict(type='select',hwnd=101))
        self.assertEqual(self.worker.requested()[1],second)
        self.host.command(dict(type='select',hwnd=999));self.assertEqual(self.worker.requested()[1],second)

if __name__=='__main__':unittest.main()
