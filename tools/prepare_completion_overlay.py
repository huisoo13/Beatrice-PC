"""Reviewed offline annotations for the September 29 completion samples.

Coordinates here describe training images only; runtime uses predicted boxes.
Video-adjacent frames are training reconstruction, never independent validation.
"""
import json
import sys
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from train_dungeon_panel import prepare

def main():
    folder=ROOT/'data/raw/completion-videos-0929'
    rows=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))['frames']
    classes=['completion_overlay','completion_text']
    images=[]
    specs={1:(19,21.5,[790,345,1135,632],[839,574,1081,623]),
           2:(34.5,36.5,[805,375,1120,638],[824,471,1098,534]),
           3:(23,25,[815,340,1105,638],[849,575,1075,624]),
           4:(37.5,39,[812,310,1118,636],[839,574,1082,624])}
    for row in rows:
        n=int(row['path'][6:9]);a,b,overlay,text=specs[n];t=row['seconds']
        positive=a<=t<=b
        # Omit partially formed/disappearing overlays from supervised labels.
        if not positive and t!=0:continue
        boxes=[dict(class_=k,xyxy=v) for k,v in zip(classes,[overlay,text])] if positive else []
        images.append(dict(path='../raw/completion-videos-0929/'+row['path'],split='train',
            sessionId=f'video-{n}',boxes=[{'class':x['class_'],'xyxy':x['xyxy']} for x in boxes]))
    # Different gameplay sessions, including the gate-less category.
    specs2=[('20260929-150944-gate1-breakthrough.jpg','val',[875,215,1170,529],[908,465,1145,520]),
            ('20260929-dungeon-clear.jpg','val',[875,215,1170,529],[896,465,1153,520]),
            ('20260929-gateless-dungeon-clear.jpg','train',[873,166,1180,453],[898,338,1153,394])]
    for filename,split,overlay,text in specs2:
        with Image.open(ROOT/'data/raw/gate-breakthrough-0929'/filename) as im:w,h=im.size
        boxes=[{'class':k,'xyxy':[round(v*w/2048) for v in coords]} for k,coords in zip(classes,[overlay,text])]
        images.append(dict(path='../raw/gate-breakthrough-0929/'+filename,split=split,sessionId=filename,boxes=boxes))
    # Preserved ordinary gameplay/quest frames are negatives, not completion labels.
    sources=[('outputs/gate-breakthrough-20260929-151043', 'val'),('outputs/gateless-review-20260929-155522','train')]
    for directory,split in sources:
        candidates=sorted((ROOT/directory).rglob('frame-000.jpg'))
        for p in candidates[:1]:
            images.append(dict(path='../../'+p.relative_to(ROOT).as_posix(),split=split,sessionId=directory,boxes=[]))
    manifest=ROOT/'data/annotations/completion-overlay-0929.json'
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps(dict(classes=classes,images=images,notes='Small supplied sample set; video replay is reconstruction, not general accuracy.'),ensure_ascii=False,indent=2),encoding='utf-8')
    print(prepare(manifest,ROOT/'data/processed/completion-overlay-0929',classes))

if __name__=='__main__':main()
