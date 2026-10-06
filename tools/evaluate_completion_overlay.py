"""Replay full supplied videos; does not access the live records database."""
import argparse,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--weights',required=True);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'outputs/ultralytics-config'))
    import cv2,numpy as np,torch
    torch.set_num_threads(2)
    from beatrice.paddle_reader import PaddleKoreanReader
    from beatrice.completion_overlay import CompletionOverlayDetector
    cfg=json.loads((ROOT/'config/completion-overlay.json').read_text(encoding='utf-8'));cfg['weights']=args.weights
    detector=CompletionOverlayDetector(PaddleKoreanReader(),cfg)
    rows=[]
    for number in range(1,5):
        cap=cv2.VideoCapture(str(Path('C:/Users/Huisoo/Videos/Lost Ark')/f'SAMPLE_{number:03d}.mp4'))
        fps=cap.get(cv2.CAP_PROP_FPS);length=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));matches=[]
        for index in range(0,length,15):
            cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,frame=cap.read()
            if not ok:raise ValueError('video read failed')
            start=time.perf_counter();result=detector.analyze(frame)
            rows.append(dict(source=f'SAMPLE_{number:03d}',frame=index,seconds=index/fps,milliseconds=round((time.perf_counter()-start)*1000),result=result))
            if result['status']=='verified':matches.append((index/fps,result['kind'],result['gate']))
        cap.release();print(number,matches,flush=True)
    manifest=json.loads((ROOT/'data/annotations/completion-overlay-0929.json').read_text(encoding='utf-8'))
    for row in manifest['images']:
        if 'gate-breakthrough-0929' not in row['path']:continue
        frame=cv2.imdecode(np.fromfile(ROOT/'data/annotations'/row['path'],dtype=np.uint8),cv2.IMREAD_COLOR)
        for transformed in (False,True):
            if transformed:
                h,w=frame.shape[:2];small=cv2.resize(frame,None,fx=.7,fy=.7)
                canvas=np.zeros((h+100,w+200,3),np.uint8);canvas[85:85+small.shape[0],135:135+small.shape[1]]=small;frame=canvas
            result=detector.analyze(frame)
            rows.append(dict(source=row['path'],transformed=transformed,result=result))
            print(row['path'],transformed,result['status'],result.get('kind'),result.get('gate'),result.get('raw'),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(purpose='supplied_video_reconstruction_and_other_session_checks_not_general_accuracy',rows=rows),ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
