"""Exercise Qt shutdown with real embedded OBS, isolated data and no game/network."""
import argparse
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QWidget
from beatrice import desktop
from beatrice.obs_capture import ObsCapture
from beatrice.process_watch import ProcessWatch


class QuietPublicContent(QWidget):
    cached=None
    def __init__(self,root,data,parent=None):super().__init__(parent)
    def shutdown(self):pass


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['main','splash'],default='main')
    mode=parser.parse_args().mode
    captures=[];children=[];watches=[];failures=[]
    class TrackedCapture(ObsCapture):
        def __init__(self,*args):super().__init__(*args);captures.append(self)
        def _start(self):
            super()._start();children.append(self.process)
    def watch(callback):
        result=ProcessWatch(callback,snapshot=lambda:frozenset());watches.append(result);return result
    app=QApplication([])
    with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
        stack.enter_context(patch.object(desktop,'DATA',Path(folder)))
        stack.enter_context(patch.object(desktop,'PublicContentPanel',QuietPublicContent))
        stack.enter_context(patch.object(desktop,'ProcessWatch',side_effect=watch))
        stack.enter_context(patch('beatrice.obs_capture.ObsCapture',TrackedCapture))
        for name in ('character_vision.CharacterVision','dungeon.DungeonOCR','dungeon.DungeonTracker',
                     'live.LiveCoordinator','ui_regions.UIRegionDetector','dungeon_observer.DungeonObserver',
                     'completion_overlay.CompletionOverlayDetector','completion_diagnostic.CompletionDiagnostic',
                     'recognition_diagnostic.RecognitionDiagnostic'):
            stack.enter_context(patch('beatrice.'+name))
        startup=desktop.Startup();startup.show()
        startup.worker.failed.connect(failures.append)
        if mode=='main':startup.worker.ready.connect(lambda clients:QTimer.singleShot(100,startup.window.close))
        else:
            startup.worker.progress.connect(lambda text:QTimer.singleShot(100,startup.close) if text.startswith('2 / 3') else None)
        deadline=QTimer();deadline.setSingleShot(True)
        def timeout():
            failures.append('Qt shutdown timed out');startup.worker.stop_event.set();app.quit()
        deadline.timeout.connect(timeout);deadline.start(20000)
        app.exec();deadline.stop()
        if not startup.worker.wait(5000):raise RuntimeError('Analysis worker survived shutdown')
        result=dict(mode=mode,passed=not failures,errors=failures,
                    workerRunning=startup.worker.isRunning(),
                    children=[dict(pid=p.pid,exitCode=p.poll()) for p in children],
                    watcherAlive=any(w.is_alive() for w in watches),
                    statusThreadAlive=any(c.status_thread and c.status_thread.is_alive() for c in captures),
                    captureResourcesClosed=all(c.process is None and c.memory is None and c.log is None for c in captures))
        if not children or any(p.poll() is None for p in children) or result['watcherAlive'] or result['statusThreadAlive'] or not result['captureResourcesClosed']:
            result['passed']=False
        output=desktop.ROOT/'outputs/embedded-obs-probe';output.mkdir(parents=True,exist_ok=True)
        (output/f'shutdown-{mode}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
        if not result['passed']:raise RuntimeError('Shutdown left resources running')


if __name__=='__main__':main()
