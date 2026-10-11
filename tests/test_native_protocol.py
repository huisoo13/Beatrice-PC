import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest


class NativeProtocolTests(unittest.TestCase):
    def test_timer_exception_stops_worker_before_unlocking(self):
        from beatrice.instance_lock import InstanceLock
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, BEATRICE_DATA_DIR=directory, BEATRICE_FIXTURE_CRASH='1', PYTHONIOENCODING='utf-8')
            child = subprocess.Popen([sys.executable, str(root/'tests/support/native_fixture_engine.py')],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=env, cwd=root)
            reader = threading.Thread(target=child.stdout.read, daemon=True)
            reader.start()
            try:
                self.assertNotEqual(child.wait(timeout=15), 0)
                self.assertTrue((Path(directory)/'worker-stopped').is_file())
                lock = InstanceLock(Path(directory)/'app.lock')
                self.assertTrue(lock.acquire())
                lock.release()
            finally:
                if child.poll() is None: child.kill(); child.wait(timeout=5)
                child.stdin.close(); child.stdout.close(); child.stderr.close()
                reader.join(timeout=1)

    def test_utf8_pipes_restart_delete_and_graceful_eof(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, BEATRICE_DATA_DIR=directory, PYTHONIOENCODING='utf-8')
            child = subprocess.Popen([sys.executable, str(root/'tests/support/native_fixture_engine.py')],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding='utf-8', env=env, cwd=root)
            messages = queue.Queue()
            def read():
                for line in child.stdout:
                    try: messages.put(json.loads(line))
                    except ValueError: messages.put(dict(type='invalid', line=line))
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            def until(predicate):
                for _ in range(100):
                    value = messages.get(timeout=5)
                    self.assertNotEqual(value['type'], 'invalid', value)
                    if predicate(value): return value
                self.fail('Expected message not received')
            def send(value):
                child.stdin.write(json.dumps(value)+'\n'); child.stdin.flush()
            try:
                first = until(lambda v: v['type']=='snapshot' and v['profile'].get('active'))
                self.assertEqual(first['profile']['character'], '샘플 캐릭터')
                self.assertEqual(first['profile']['dungeonSubtitle'], '하드 · 2관문')
                self.assertEqual(len(first['records']), 1)
                send(dict(type='restart'))
                until(lambda v: v['type']=='snapshot' and v['busy'])
                restored = until(lambda v: v['type']=='snapshot' and not v['busy'] and v['profile'].get('active'))
                self.assertEqual(len(restored['records']), 1)
                send(dict(type='delete'))
                until(lambda v: v['type']=='snapshot' and not v['records'] and not v['busy'])
                child.stdin.close()  # Parent window exiting cannot leave an orphan worker.
                until(lambda v: v['type']=='stopped')
                self.assertEqual(child.wait(timeout=10), 0)
                log = (Path(directory)/'runtime.log').read_text(encoding='utf-8')
                self.assertIn('fixture library stdout', log)
                self.assertIn('fixture library stderr', log)
                if sys.platform == 'win32': self.assertIn('fixture Win32 stdout', log)
            finally:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=5)
                child.stdout.close(); child.stderr.close()
                if not child.stdin.closed: child.stdin.close()
                reader.join(timeout=1)


    def test_drive_commands_round_trip_over_real_pipes_without_network(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env=dict(os.environ,BEATRICE_DATA_DIR=directory,BEATRICE_FIXTURE_DRIVE='1',PYTHONIOENCODING='utf-8')
            child=subprocess.Popen([sys.executable,str(root/'tests/support/native_fixture_engine.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',env=env,cwd=root)
            messages=queue.Queue()
            def read():
                for line in child.stdout:messages.put(json.loads(line))
            reader=threading.Thread(target=read,daemon=True);reader.start()
            def until(predicate):
                for _ in range(200):
                    value=messages.get(timeout=10)
                    self.assertNotIn('fixture-secret',json.dumps(value))
                    self.assertNotIn('fixture-access',json.dumps(value))
                    if predicate(value):return value
                self.fail('Expected Drive message not received')
            def send(value):child.stdin.write(json.dumps(value)+'\n');child.stdin.flush()
            try:
                until(lambda v:v['type']=='snapshot' and v['startupReady'])
                send(dict(type='google_login'))
                signed=until(lambda v:v['type']=='snapshot' and v['google']['signedIn'])
                self.assertEqual(signed['google']['email'],'fixture@example.com')
                send(dict(type='drive_upload'))
                until(lambda v:v['type']=='snapshot' and '읽기 검증 완료' in v['drive']['message'])
                send(dict(type='drive_download'))
                preview=until(lambda v:v['type']=='drive_preview')
                send(dict(type='drive_restore',previewId=preview['previewId'],apply=False))
                cancelled=until(lambda v:v['type']=='snapshot' and not v['busy'] and '취소' in v['drive']['message'])
                self.assertEqual(cancelled['records'][0]['character'],'샘플 캐릭터')
                send(dict(type='drive_download'))
                preview=until(lambda v:v['type']=='drive_preview')
                send(dict(type='drive_restore',previewId=preview['previewId'],apply=True))
                restored=until(lambda v:v['type']=='snapshot' and not v['busy'] and '복원 완료' in v['drive']['message'])
                self.assertEqual(restored['records'][0]['character'],'원격 캐릭터')
                self.assertTrue(list((Path(directory)/'drive-backups').glob('*.sqlite3')))
                child.stdin.close();until(lambda v:v['type']=='stopped')
                self.assertEqual(child.wait(timeout=10),0)
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
                if not child.stdin.closed:child.stdin.close()
                child.stdout.close();child.stderr.close();reader.join(timeout=1)


    def test_engine_import_does_not_load_qt(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,'-c',"import sys; import beatrice.native_bridge; assert not any(m.startswith(('PySide6','shiboken6')) for m in sys.modules)"],cwd=root,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
