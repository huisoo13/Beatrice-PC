"""Exercise engine shutdown with real embedded OBS, isolated data and no game/network."""
import argparse
import json
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from beatrice.thread_events import EventLoop
from beatrice.recognition import service as recognition_service
from beatrice import engine_worker as engine
from beatrice.native_bridge import Host
from beatrice.obs_capture import ObsCapture
from beatrice.process_watch import ProcessWatch
from beatrice.public_content import ContentError


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['main','splash'],default='main')
    mode=parser.parse_args().mode
    captures=[];children=[];watches=[];failures=[]
    class TrackedCapture(ObsCapture):
        def __init__(self,*args):super().__init__(*args);captures.append(self)
        def _start(self):super()._start();children.append(self.process)
    def watch(callback):
        result=ProcessWatch(callback,snapshot=lambda:frozenset());watches.append(result);return result
    app=EventLoop()
    with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
        stack.enter_context(patch.object(engine,'DATA',Path(folder)))
        stack.enter_context(patch('beatrice.catalog_service.load_settings',side_effect=ContentError('probe: network disabled')))
        stack.enter_context(patch.object(recognition_service,'ProcessWatch',side_effect=watch))
        stack.enter_context(patch('beatrice.obs_capture.ObsCapture',TrackedCapture))
        for name in ('character_vision.CharacterVision','dungeon.DungeonOCR','dungeon.DungeonTracker',
                     'live.LiveCoordinator','ui_regions.UIRegionDetector','dungeon_observer.DungeonObserver',
                     'completion_overlay.CompletionOverlayDetector','completion_diagnostic.CompletionDiagnostic',
                     'recognition_diagnostic.RecognitionDiagnostic'):
            stack.enter_context(patch('beatrice.'+name))
        host=Host(app,lambda message:None)
        host.start();host.worker.failed.connect(failures.append)
        stop=lambda:host.command(dict(type='shutdown'))
        if mode=='main':host.worker.ready.connect(lambda clients:app.dispatch(lambda:app.call_later(.1,stop)))
        else:host.worker.progress.connect(lambda text:app.dispatch(lambda:app.call_later(.1,stop)) if text.startswith('2 / 3') else None)
        def timeout():
            failures.append('Engine shutdown timed out');stop()
        deadline=app.call_later(20,timeout)
        app.run();deadline.stop()
        host.worker.join(5)
        if host.worker.is_alive():raise RuntimeError('Analysis worker survived shutdown')
        result=dict(mode=mode,passed=not failures,errors=failures,workerRunning=host.worker.is_alive(),
                    children=[dict(pid=p.pid,exitCode=p.poll()) for p in children],
                    watcherAlive=any(w.is_alive() for w in watches),
                    statusThreadAlive=any(c.status_thread and c.status_thread.is_alive() for c in captures),
                    captureResourcesClosed=all(c.process is None and c.memory is None and c.log is None for c in captures))
        if not children or any(p.poll() is None for p in children) or result['watcherAlive'] or result['statusThreadAlive'] or not result['captureResourcesClosed']:
            result['passed']=False
        output=engine.ROOT/'outputs/embedded-obs-probe';output.mkdir(parents=True,exist_ok=True)
        (output/f'shutdown-{mode}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
        if not result['passed']:raise RuntimeError('Shutdown left resources running')

if __name__=='__main__':main()
