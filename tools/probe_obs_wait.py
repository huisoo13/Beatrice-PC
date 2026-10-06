"""Exercise OBS frame delivery, pause and resume with an app-owned color source."""
import ctypes as C
import json
import mmap
import os
import time
import uuid
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from beatrice.game_window import Client
from beatrice.obs_capture import ObsCapture, CAPACITY, runtime_path
from beatrice.obs_engine import Engine


def main():
    output=Path(__file__).resolve().parents[1]/'outputs/embedded-obs-probe/wait-test.json'
    runtime=runtime_path();os.chdir(runtime/'bin/64bit')
    memory=mmap.mmap(-1,CAPACITY,tagname='Local\\BeatriceOBSWait-'+uuid.uuid4().hex)
    engine=Engine(runtime,memory)
    capture=ObsCapture(Client(0,0,'Internal OBS test'),output.parent)
    capture.memory=memory;capture.process=SimpleNamespace(poll=lambda:None)
    api=SimpleNamespace(IsIconic=lambda hwnd:False,GetForegroundWindow=lambda:0)
    counts={};transitions=[];last_kind=None;last_color_change=0;color=0
    phases=[('stream',1.5),('paused',2.5),('resumed',1.5)]
    try:
        engine.start(dict(width=3440,height=1440,color=0xff336699),3440,1440,test_pattern=True)
        engine.bind('obs_source_update',None,C.c_void_p,C.c_void_p)
        with patch('beatrice.game_window.client_alive',return_value=True),patch('beatrice.game_window.api',return_value=api):
            for phase,duration in phases:
                if phase=='paused':engine.obs.obs_remove_raw_video_callback(engine.callback,None)
                if phase=='resumed':engine.obs.obs_add_raw_video_callback(None,engine.callback,None)
                started=time.monotonic();counts[phase]=Counter()
                while time.monotonic()-started<duration:
                    now=time.monotonic()
                    if phase!='paused' and now-last_color_change>.3:
                        color+=1;last_color_change=now
                        data=engine.obs.obs_data_create_from_json(json.dumps(dict(
                            width=3440,height=1440,color=0xff336699 if color%2 else 0xff99cc33)).encode())
                        engine.obs.obs_source_update(engine.source,data);engine.obs.obs_data_release(data)
                    image,reason=capture.grab()
                    kind=capture.wait_kind
                    counts[phase][kind]+=1
                    if kind!=last_kind:
                        transitions.append(dict(phase=phase,seconds=round(now-started,3),kind=kind,reason=reason))
                        last_kind=kind
                    time.sleep(.01)
        passed=(counts['stream']['ready']>0 and counts['paused']['transient']>0 and
                counts['paused']['interrupted']>0 and counts['resumed']['ready']>0)
        payload=dict(passed=passed,size=[3440,1440],counts=counts,transitions=transitions,
                     readWaits=capture.read_waits,
                     scope='internal libobs source; no game/window manipulation or completion record writes')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(passed=passed,counts=counts,readWaits=capture.read_waits)))
        if not passed:raise RuntimeError('OBS wait transition test failed')
    finally:
        engine.close();memory.close()


if __name__=='__main__':main()
