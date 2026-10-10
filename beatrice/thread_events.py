"""Standard-library callbacks and an owner-thread event loop."""
import heapq
import queue
import threading
import time
from itertools import count


class Event:
    def __init__(self):
        self._listeners=[];self._lock=threading.Lock()
    def connect(self,callback):
        with self._lock:self._listeners.append(callback)
    def emit(self,*args):
        with self._lock:listeners=tuple(self._listeners)
        for callback in listeners:callback(*args)


class ScheduledCall:
    def __init__(self,callback,interval):
        self.callback=callback;self.interval=interval;self.cancelled=False
    def stop(self):self.cancelled=True


class EventLoop:
    """All callbacks and timers execute on the constructing thread."""
    def __init__(self):
        self.owner=threading.get_ident();self.pending=queue.Queue()
        self.timers=[];self.sequence=count();self.stopping=False
    def dispatch(self,callback,*args):
        if threading.get_ident()==self.owner:callback(*args)
        else:self.pending.put((callback,args))
    def call_later(self,seconds,callback,repeat=False):
        if threading.get_ident()!=self.owner:raise RuntimeError('Timers belong to the event-loop thread')
        if seconds<=0:raise ValueError('Timer interval must be positive')
        call=ScheduledCall(callback,seconds if repeat else None)
        heapq.heappush(self.timers,(time.monotonic()+seconds,next(self.sequence),call))
        return call
    def drain(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Event-loop callbacks belong to the owner thread')
        for _ in range(100):
            try:callback,args=self.pending.get_nowait()
            except queue.Empty:break
            callback(*args)
            if self.stopping:return
        now=time.monotonic()
        while self.timers and self.timers[0][0]<=now:
            _,_,call=heapq.heappop(self.timers)
            if call.cancelled:continue
            call.callback()
            if self.stopping:return
            if call.interval is not None and not call.cancelled:
                heapq.heappush(self.timers,(time.monotonic()+call.interval,next(self.sequence),call))
    def run(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Event loop must run on the owner thread')
        while not self.stopping:
            self.drain()
            if self.stopping:break
            wait=min(.05,max(0,self.timers[0][0]-time.monotonic())) if self.timers else .05
            try:callback,args=self.pending.get(timeout=wait)
            except queue.Empty:continue
            callback(*args)
        return 0
    def quit(self):self.dispatch(self._quit)
    def _quit(self):self.stopping=True
