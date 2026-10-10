"""Owner-thread event delivery, cleanup and cross-process exclusion."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from beatrice.thread_events import Event,EventLoop
from beatrice.instance_lock import InstanceLock
from beatrice.engine_worker import Worker

ROOT=Path(__file__).resolve().parents[1]


class ThreadRuntimeTests(unittest.TestCase):
    def test_background_events_preserve_order_and_execute_on_owner(self):
        loop=EventLoop();event=Event();received=[];owner=threading.get_ident()
        event.connect(lambda number:loop.dispatch(lambda value:received.append((value,threading.get_ident())),number))
        thread=threading.Thread(target=lambda:[event.emit(i) for i in range(20)])
        thread.start();thread.join()
        self.assertEqual(received,[])
        loop.drain()
        self.assertEqual(received,[(i,owner) for i in range(20)])

    def test_worker_always_delivers_failure_then_finished(self):
        class BrokenWorker(Worker):
            def run(self):raise RuntimeError('test failure')
        worker=BrokenWorker();received=[]
        worker.failed.connect(lambda message:received.append(('failed',message)))
        worker.finished.connect(lambda:received.append(('finished',None)))
        worker.start();worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(received,[('failed','test failure'),('finished',None)])

    def test_cancelled_timer_does_not_run(self):
        loop=EventLoop();callback=Mock()
        timer=loop.call_later(.01,callback);timer.stop()
        with patch('beatrice.thread_events.time.monotonic',return_value=time.monotonic()+1):loop.drain()
        callback.assert_not_called()

    def test_repeating_timer_can_cancel_itself(self):
        loop=EventLoop();calls=[]
        def callback():calls.append(1);timer.stop()
        timer=loop.call_later(.01,callback,repeat=True)
        with patch('beatrice.thread_events.time.monotonic',return_value=time.monotonic()+1):
            loop.drain();loop.drain()
        self.assertEqual(calls,[1])

    def test_loop_quit_from_background_is_delivered_on_owner(self):
        loop=EventLoop();thread=threading.Thread(target=loop.quit)
        thread.start();thread.join()
        self.assertFalse(loop.stopping)
        self.assertEqual(loop.run(),0)
        self.assertTrue(loop.stopping)

    def test_loop_rejects_non_owner_drain(self):
        loop=EventLoop();errors=[]
        def other():
            try:loop.drain()
            except RuntimeError as error:errors.append(str(error))
        thread=threading.Thread(target=other);thread.start();thread.join()
        self.assertEqual(len(errors),1)

    def test_process_lock_blocks_second_process_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'app.lock';lock=InstanceLock(path)
            code="from beatrice.instance_lock import InstanceLock; import sys; l=InstanceLock(sys.argv[1]); ok=l.acquire(); l.release(); sys.exit(0 if ok else 2)"
            def attempt():return subprocess.run([sys.executable,'-c',code,str(path)],cwd=ROOT,capture_output=True,timeout=5).returncode
            self.assertTrue(lock.acquire())
            try:self.assertEqual(attempt(),2)
            finally:lock.release()
            self.assertEqual(attempt(),0)

    def test_terminated_process_does_not_leave_stale_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'app.lock'
            code="from beatrice.instance_lock import InstanceLock; import sys,time; l=InstanceLock(sys.argv[1]); assert l.acquire(); print('ready',flush=True); time.sleep(30)"
            child=subprocess.Popen([sys.executable,'-c',code,str(path)],cwd=ROOT,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'ready')
                lock=InstanceLock(path);self.assertFalse(lock.acquire())
                child.terminate();child.wait(timeout=5)
                self.assertTrue(lock.acquire());lock.release()
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
                child.stdout.close()

if __name__=='__main__':unittest.main()
