"""Python thread/callback adapter for the recognition service."""
import os
from pathlib import Path
from threading import Thread
from .thread_events import Event
from .game_window import find_clients,client_alive,client_active
from .recognition import RecognitionEvents,RecognitionService

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('BEATRICE_DATA_DIR',str(Path.home()/'BeatricePC')))


class Worker:
    def __init__(self):
        self._thread=Thread(target=self._execute,name='BeatriceRecognition')
        names=('status','observation','progress','ready','failed','settled','process_changed','obs')
        for name in (*names,'finished'):setattr(self,name,Event())
        events=RecognitionEvents(**{name:getattr(self,name).emit for name in names})
        self.service=RecognitionService(ROOT,DATA,events)

    @property
    def stop_event(self):return self.service.stop_event

    @property
    def process_snapshot(self):return self.service.process_snapshot

    @property
    def settled_generation(self):return self.service.settled_generation

    def select(self,generation,client):self.service.select(generation,client)
    def requested(self):return self.service.requested()
    def process_state(self,pids,error):self.service.process_state(pids,error)
    def capture_wait(self,*args):self.service.capture_wait(*args)

    def run(self):
        self.service.root=ROOT;self.service.data=DATA
        self.service.run()

    def start(self):self._thread.start()
    def join(self,timeout=None):self._thread.join(timeout)
    def is_alive(self):return self._thread.is_alive()

    def _execute(self):
        try:self.run()
        except Exception as error:self.failed.emit(str(error))
        finally:self.finished.emit()
