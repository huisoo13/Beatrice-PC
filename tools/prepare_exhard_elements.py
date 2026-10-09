"""Create reviewed EX Hard single gate labels; all positions are training annotations."""
import argparse,copy,hashlib,json,shutil
from pathlib import Path
import cv2
from PIL import Image,ImageDraw
from beatrice.ui_regions import UIRegionDetector
from tools.train_dungeon_panel import prepare
ROOT=Path(__file__).resolve().parents[1]
TRAIN=[3499,3723,4047,4300,4605,4944,5372,5558,5661,5717,5748,5765]
WANTED=[3570,3900,4200,4500,4800,5200,5750,5754,5756,5760,5770,5779]
def main():
 p=argparse.ArgumentParser();p.add_argument('session',type=Path);p.add_argument('--reinforced',action='store_true');args=p.parse_args();session=args.session
 train=TRAIN+[3548,3580,3599,3631,3669] if args.reinforced else TRAIN
 suffix='exhard-reinforced-1008' if args.reinforced else 'exhard-1008'
 output=ROOT/'outputs/exhard-review-1008';output.mkdir(parents=True,exist_ok=True)
 raw=ROOT/'data/raw/exhard-gate-panel-1008';raw.mkdir(parents=True,exist_ok=True)
 config=json.loads((ROOT/'config/dungeon-elements.json').read_text(encoding='utf-8'));detector=UIRegionDetector(config)
 doc=copy.deepcopy(json.loads((ROOT/'data/annotations/dungeon-elements-tower-1006.json').read_text(encoding='utf-8')))
 available=sorted(int(f.stem.split('-')[1]) for f in session.glob('event-*.json'))
 evaluate=list(dict.fromkeys(min((n for n in available if n not in train),key=lambda n:abs(n-v)) for v in WANTED))
 rows=[];canvas=Image.new('RGB',(720,265*((len(train)+1)//2)),'white');draw=ImageDraw.Draw(canvas)
 for i,seq in enumerate(train+evaluate):
  name=f'event-{seq:08d}';report=json.loads((session/(name+'.json')).read_text(encoding='utf-8'))
  if (report['dungeon'].get('difficulty') or {}).get('text')!='EX 하드':raise ValueError(name)
  for extension in ['.jpg','.json']:shutil.copy2(session/(name+extension),raw/(name+extension))
  frame=cv2.imread(str(raw/(name+'.jpg')));l,t,r,b=report['dungeon']['raidBounds'];crop=frame[t:b,l:r];found=detector.locate(crop)
  icons=[(kind,item) for kind in ['gate_in_progress','gate_completed'] for item in found[kind]['candidates']]
  if len(icons)!=1:raise ValueError('Manual icon review needed: '+name)
  kind,item=icons[0]
  full=[{'class':'gate_panel','xyxy':[135,113,225,202]}]
  full += [{'class':category,'xyxy':report['dungeon']['ocr'][field]['region']} for field,category in [('dungeonName','dungeon_name'),('difficulty','difficulty')]]
  full.append({'class':kind,'xyxy':[item['xyxy'][0]+l,item['xyxy'][1]+t,item['xyxy'][2]+l,item['xyxy'][3]+t]})
  boxes=[{'class':box['class'],'xyxy':[box['xyxy'][0]-l,box['xyxy'][1]-t,box['xyxy'][2]-l,box['xyxy'][3]-t]} for box in full]
  target=raw/(name+'-panel.png');cv2.imwrite(str(target),crop)
  row=dict(path='../raw/exhard-gate-panel-1008/'+target.name,split='train',sessionId=session.name,boxes=boxes,sourceParent='../raw/exhard-gate-panel-1008/'+name+'.jpg',sourceDetection={'class':'dungeon_panel','xyxy':[l,t,r,b]},observedAt=report['observedAt'],sha256=hashlib.sha256(target.read_bytes()).hexdigest())
  if seq in train:doc['images'].append(row)
  rows.append(dict(row,usage='train' if seq in train else 'same_session_untrained_replay'))
  if i<len(train):
   preview=Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB));annot=ImageDraw.Draw(preview)
   for box in boxes:annot.rectangle(box['xyxy'],outline='red' if box['class']=='gate_panel' else 'lime',width=2)
   x=i%2*360;y=i//2*265;canvas.paste(preview,(x,y+25));draw.text((x,y),f'{seq} {kind}',fill='black')
 canvas.save(output/'review-labels.png')
 doc['annotationMethod']='72 reviewed element images plus reviewed EX Hard single gate panels; icon proposals visually checked'
 doc['evaluationPurpose']='training_reconstruction_and_same_session_untrained_replay_not_independent'
 path=ROOT/('data/annotations/dungeon-elements-'+suffix+'.json');path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
 (raw/'review.json').write_text(json.dumps({'images':rows},ensure_ascii=False,indent=2),encoding='utf-8')
 dataset=ROOT/('data/datasets/dungeon-elements-'+suffix);prepare(path,dataset,doc['classes'],True)
 print(json.dumps(dict(train=len(doc['images']),newTrain=len(train),evaluate=len(evaluate),dataset=str(dataset))))
if __name__=='__main__':main()
