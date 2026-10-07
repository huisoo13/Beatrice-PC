"""Exercise the exact engine entry point without pre-importing model modules."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

root = Path(__file__).resolve().parents[1]
data = root / 'outputs/cold-start-probe' / str(time.time_ns())
data.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, BEATRICE_DATA_DIR=str(data), PYTHONIOENCODING='utf-8')
child = subprocess.Popen([sys.executable, '-u', str(root/'app_launcher.py'), '--engine', '--engine-startup-check'],
                         cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding='utf-8')
messages = queue.Queue()
def read():
    for line in child.stdout:
        messages.put(line)
threading.Thread(target=read, daemon=True).start()
started = time.monotonic()
try:
    while time.monotonic()-started < 50:
        try: line = messages.get(timeout=1)
        except queue.Empty:
            if child.poll() is not None: break
            continue
        value = json.loads(line)
        status = value.get('status', value.get('message', value.get('type')))
        print(status, flush=True)
        if value.get('type') == 'snapshot' and not value.get('busy') and not value.get('error'):
            child.wait(timeout=15)
            print(f'COLD START PASS in {time.monotonic()-started:.2f}s', flush=True)
            break
        if value.get('error') or value.get('type') == 'error':
            raise RuntimeError(status)
    else:
        raise TimeoutError('COLD START STALLED')
finally:
    if child.poll() is None:
        child.kill(); child.wait(timeout=5)
    child.stdin.close(); child.stdout.close(); child.stderr.close()
