"""Test the app's own OBS engine; no installed OBS and no record DB writes."""
import argparse
import json
import time
from pathlib import Path
from beatrice.obs_capture import ObsCapture
from beatrice.game_window import find_clients

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=12)
    args=parser.parse_args()
    clients=find_clients()
    if len(clients)!=1:raise RuntimeError('검증은 실행 중인 게임 창이 하나일 때 진행해주세요.')
    output=Path('outputs/embedded-obs-probe');output.mkdir(parents=True,exist_ok=True)
    capture=ObsCapture(clients[0],output);valid=0
    try:
        import cv2
        started=time.monotonic()
        with (output/'frames.jsonl').open('w',encoding='utf-8') as log:
            while time.monotonic()-started<args.seconds:
                frame,reason=capture.grab()
                row=dict(seconds=round(time.monotonic()-started,2),frame=frame is not None,reason=reason)
                if frame is not None:
                    valid+=1;row.update(capture.frame_info);row['shape']=list(frame.shape)
                    if valid==1:cv2.imwrite(str(output/'first-frame.jpg'),frame)
                log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
                time.sleep(.5)
    finally:capture.close()
    print(json.dumps(dict(validFrames=valid,log=str(output/'frames.jsonl'))))
    if not valid:raise SystemExit(1)

if __name__=='__main__':main()
