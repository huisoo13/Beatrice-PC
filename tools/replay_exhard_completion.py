"""Replay preserved EX Hard gameplay with real YOLO/OCR into an isolated memory DB."""
import argparse,json,shutil
from datetime import datetime
from pathlib import Path
import cv2,numpy as np
from beatrice.ui_regions import UIRegionDetector
from beatrice.dungeon import DungeonOCR,DungeonTracker
from beatrice.dungeon_observer import DungeonObserver
from beatrice.completion_overlay import CompletionOverlayDetector
from beatrice.live import LiveCoordinator
from beatrice.storage import Store
ROOT=Path(__file__).resolve().parents[1]
SEQUENCES=[5662,5665,5676,5683,5685,5686,5717,5720,5723,5728,5729,5736,5738,5739,5740,5750,5754,5756,5760,5770,5779]
def main():
 p=argparse.ArgumentParser();p.add_argument('--weights',required=True);p.add_argument('--session',required=True,type=Path);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
 raw=ROOT/'data/raw/exhard-gate-panel-1008';raw.mkdir(parents=True,exist_ok=True)
 cfg=json.loads((ROOT/'config/dungeon-elements.json').read_text(encoding='utf-8'));cfg['weights']=args.weights
 parent=UIRegionDetector(json.loads((ROOT/'config/dungeon-regions.json').read_text(encoding='utf-8')));parent.element_detector=UIRegionDetector(cfg)
 ocr=DungeonOCR();observer=DungeonObserver(ocr);tracker=DungeonTracker(max_gap=5)
 completion=CompletionOverlayDetector(ocr.reader,json.loads((ROOT/'config/completion-overlay.json').read_text(encoding='utf-8')))
 store=Store(':memory:');live=LiveCoordinator(store);rows=[]
 try:
  seed=json.loads((args.session/f'event-{SEQUENCES[0]:08d}.json').read_text(encoding='utf-8'))
  live.identity.current=seed['state']['identity']['currentName'];live.identity.blocked=False
  for seq in SEQUENCES:
   name=f'event-{seq:08d}'
   for suffix in ['.jpg','.json']:shutil.copy2(args.session/(name+suffix),raw/(name+suffix))
   doc=json.loads((raw/(name+'.json')).read_text(encoding='utf-8'));at=datetime.fromisoformat(doc['observedAt'])
   frame=cv2.imdecode(np.fromfile(raw/(name+'.jpg'),dtype=np.uint8),cv2.IMREAD_COLOR)
   regions=parent.locate(frame);observation,gates=observer.analyze(frame,regions,at.timestamp())
   if live.completion_context is not None:observation['completionOverlay']=completion.analyze(frame)
   context=tracker.update(at.timestamp(),observation);result=live.update(at,{},gates,context)
   rows.append(dict(sequence=seq,observedAt=at.isoformat(),observation=observation,gates=gates,state=result))
  records=store.state_records();report=dict(purpose='same_session_preserved_gameplay_real_models_memory_database',rows=rows,records=records)
  args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  print(dict(frames=len(rows),records=[{k:r.get(k) for k in ['dungeonName','difficulty','gate','state','evidenceType']} for r in records]))
  if len(records)!=1 or records[0]['gate']!=1 or records[0]['state']!='완료':raise SystemExit('EX Hard completion was not saved')
 finally:store.close()
if __name__=='__main__':main()
