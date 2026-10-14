"""Preserve previous labels and add reviewed non-selection popup negatives."""
import argparse
import json
import shutil
from pathlib import Path
from PIL import Image, ImageEnhance
from train_dungeon_panel import prepare

ROOT=Path(__file__).resolve().parents[1]


def build(output):
    base=ROOT/'data/annotations'
    doc=json.loads((base/'login-dim-1006.json').read_text(encoding='utf-8'))
    raw=ROOT/'data/raw/character-false-positive-1014';raw.mkdir(parents=True,exist_ok=True)
    session=Path('C:/Users/Huisoo/AppData/Local/BeatricePC/completion-diagnostics/20261014T084740Z-4d82e109')
    for name,event in (('stronghold',208),('bracelet',2109)):
        source=raw/(name+'-source.jpg');meta=raw/(name+'-source.json')
        if not source.exists():shutil.copy2(session/f'event-{event:08d}.jpg',source)
        if not meta.exists():shutil.copy2(session/f'event-{event:08d}.json',meta)
        detections=json.loads(meta.read_text(encoding='utf-8'))['character']['detections']
        bounds=[None,*[detections[k]['xyxy'] for k in ('selected_character_card','game_start_button')]]
        original=Image.open(source).convert('RGB')
        for crop,box in enumerate(bounds):
            image=original if box is None else original.crop(box)
            for scale in (1,.75,1.25):
                for dim in (1,.75,.5,.35):
                    frame=ImageEnhance.Brightness(image).enhance(dim)
                    frame=frame.resize((round(frame.width*scale),round(frame.height*scale)))
                    path=raw/f'{name}-{crop}-{scale}-{dim}.png';frame.save(path)
                    doc['images'].append(dict(path='../raw/'+raw.name+'/'+path.name,split='train',
                        sessionId='false-selection-1014',synthetic=crop!=0 or scale!=1 or dim!=1,boxes=[]))
    doc['annotationMethod']+='; reviewed stronghold and bracelet popup hard negatives, full frames and model-detected crops'
    reviewed={'../raw/login-contexts-1001/row-02.png':'후이수',
              '../raw/login-dim-1006/full-011-7.png':'힐레우스',
              '../raw/login-dim-1006/full-015-3.png':'테베체'}
    for item in doc['images']:
        if item['path'] in reviewed:item['ocrExpected']={'selected_character_name':reviewed[item['path']]}
    doc['evaluationPurpose']='training_reconstruction_and_same_session_replay_not_independent'
    manifest=base/'character-false-positive-1014.json'
    manifest.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
    return prepare(manifest,output,doc['classes'],True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    print(build(parser.parse_args().output))
