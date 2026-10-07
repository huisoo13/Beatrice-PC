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
    def test_utf8_pipes_restart_delete_and_graceful_eof(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, BEATRICE_DATA_DIR=directory, PYTHONIOENCODING='utf-8', QT_QPA_PLATFORM='offscreen')
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
