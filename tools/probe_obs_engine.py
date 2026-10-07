"""Validate app-local libobs delivery with an internal color source, no game/UI access."""
import ctypes as C
import json
import mmap
import os
import time
import uuid
from pathlib import Path
from beatrice.obs_capture import runtime_path,read_frame,CAPACITY
from beatrice.obs_engine import Engine

def main():
    runtime=runtime_path();os.chdir(runtime/'bin/64bit')
    memory=mmap.mmap(-1,CAPACITY,tagname='Local\\BeatriceOBSTest-'+uuid.uuid4().hex)
    engine=Engine(runtime,memory);rows=[];last=0
    output=Path(__file__).resolve().parents[1]/'outputs/embedded-obs-probe/engine-test.json'
    try:
        engine.start(dict(width=320,height=180,color=0xff336699),320,180,test_pattern=True)
        engine.bind('obs_source_update',None,C.c_void_p,C.c_void_p)
        for color in (0xff336699,0xff99cc33):
            data=engine.obs.obs_data_create_from_json(json.dumps(dict(width=320,height=180,color=color)).encode())
            engine.obs.obs_source_update(engine.source,data);engine.obs.obs_data_release(data)
            time.sleep(.5)
            result=read_frame(memory,last)
            if result is None:raise RuntimeError('Internal OBS source produced no frames')
            last,ticks,received,width,height,stride,pixels=result
            rows.append(dict(sequence=last,ticks=ticks,width=width,height=height,
                             firstPixel=list(pixels[:4]),nonzero=any(pixels)))
        if rows[0]['firstPixel']==rows[1]['firstPixel']:raise RuntimeError('Internal OBS frame did not update')
        engine.detach()
        if read_frame(memory,last) is not None:raise RuntimeError('Detached source retained a ready frame')
        engine.attach(dict(width=640,height=360,color=0xffcc3366),640,360,test_pattern=True)
        time.sleep(.5)
        result=read_frame(memory,last)
        if result is None:raise RuntimeError('Reattached source produced no new frame')
        sequence,ticks,received,width,height,stride,pixels=result
        if (width,height)!=(640,360):raise RuntimeError('Reattached frame dimensions did not change')
        rows.append(dict(sequence=sequence,ticks=ticks,width=width,height=height,
                         firstPixel=list(pixels[:4]),nonzero=any(pixels)))
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(rows,indent=2))
        print(json.dumps(dict(passed=True,frames=rows)))
    finally:engine.close();memory.close()

if __name__=='__main__':main()
