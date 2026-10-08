"""Load production models on the native host worker, without capture or user DB."""
import os
import sys
import faulthandler
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
root = Path(__file__).resolve().parents[1]
data = root/'outputs/native-model-probe'
data.mkdir(parents=True, exist_ok=True)
for folder in ('yolo','matplotlib','paddle'): (data/folder).mkdir(exist_ok=True)
os.environ['BEATRICE_DATA_DIR'] = str(data)
os.environ['YOLO_CONFIG_DIR'] = str(data/'yolo')
os.environ['MPLCONFIGDIR'] = str(data/'matplotlib')
os.environ['PADDLE_PDX_CACHE_HOME'] = str(data/'paddle')
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['YOLO_AUTOINSTALL'] = 'false'

if __name__ == '__main__':
    from PySide6.QtCore import QCoreApplication
    from unittest.mock import patch
    from beatrice import engine_worker as engine
    trace = (data/'stacks.log').open('w')
    faulthandler.dump_traceback_later(20, repeat=True, file=trace)
    if '--bridge' in sys.argv or '--launcher' in sys.argv:
        from contextlib import ExitStack
        from beatrice import native_bridge
        obs_probe = '--obs' in sys.argv
        if obs_probe:
            import threading
            class HeldInput:
                def __iter__(self): return self
                def __next__(self): threading.Event().wait()
            sys.stdin = HeldInput()
        events = []
        def factory():
            instance = engine.Worker()
            instance.progress.connect(events.append)
            instance.failed.connect(lambda value: events.append('FAIL: ' + value))
            instance.finished.connect(QCoreApplication.instance().quit)
            if obs_probe: instance.ready.connect(lambda _: instance.stop_event.set())
            return instance
        with ExitStack() as stack:
            if not obs_probe:
                capture = stack.enter_context(patch('beatrice.obs_capture.ObsCapture'))
                capture.return_value.prepare.return_value = False
            stack.enter_context(patch.object(native_bridge,'load_api_key',side_effect=native_bridge.ContentError('probe: network disabled')))
            stack.enter_context(patch.object(engine,'find_clients',return_value=[]))
            if '--launcher' in sys.argv:
                import app_launcher
                original = native_bridge.main
                sys.argv = ['app_launcher.py','--engine']
                with patch.object(native_bridge,'main',side_effect=lambda: original(factory)):
                    result = app_launcher.main()
            else: result = native_bridge.main(factory)
        (data/'bridge-result.json').write_text(json.dumps(events,ensure_ascii=False),encoding='utf-8')
        sys.exit(result)
    app = QCoreApplication([])
    worker = engine.Worker()
    failures = []
    worker.progress.connect(lambda value: print(value, flush=True))
    worker.failed.connect(lambda value: failures.append(value) or print('FAIL:',value,flush=True))
    worker.finished.connect(app.quit)
    with patch('beatrice.obs_capture.ObsCapture') as capture:
        capture.return_value.prepare.return_value = False
        worker.start()
        app.exec()
    faulthandler.cancel_dump_traceback_later()
    print('MODEL INITIALIZATION', 'FAIL' if failures else 'PASS',flush=True)
    sys.exit(bool(failures))
