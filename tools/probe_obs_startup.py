"""Verify splash-time embedded OBS preparation without a game or external OBS."""
import json
import threading
from pathlib import Path
from beatrice.obs_capture import ObsCapture


def main():
    output=Path(__file__).resolve().parents[1]/'outputs/embedded-obs-probe'
    capture=ObsCapture(None,output);process=None
    try:
        if not capture.prepare(threading.Event()):raise RuntimeError('Engine preparation cancelled')
        process=capture.process
        if not capture.binding_ready.wait(3):raise RuntimeError('Idle target was not acknowledged')
        capture.bind(None)
        if capture.process is not process or process.poll() is not None:
            raise RuntimeError('Prepared engine was not retained')
        if capture.grab()[0] is not None:raise RuntimeError('Idle engine supplied a game frame')
        result=dict(passed=True,pid=process.pid,engineReady=capture.engine_ready.is_set(),
                    idleReady=capture.binding_ready.is_set(),reused=True)
    finally:capture.close()
    result['exitCode']=process.returncode
    if result['exitCode']!=0:raise RuntimeError('Engine shutdown failed')
    (output/'startup-test.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
