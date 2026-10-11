"""Append-only session evidence, independent of the rolling frame slots."""
import json
import uuid
from datetime import datetime,timezone
from pathlib import Path


class CompletionDiagnostic:
    def __init__(self,directory):
        self.directory=Path(directory)/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
        self.sequence=0;self.previous=None
        self.gold_previous={}

    def record(self,frame,report):
        import cv2
        state=report.get('state',{});result=state.get('result',{})
        decision=result.get('completionDecision',{})
        observation=decision.get('observation',{})
        dungeon=report.get('dungeon',{})
        gold=dungeon.get('goldReward') or {}
        if gold.get('status')=='not_requested':gold=self.gold_previous
        else:self.gold_previous=gold
        def text(value):
            return value.get('text') if isinstance(value,dict) else value
        compact=dict(observedAt=report.get('observedAt'),sequence=self.sequence,
            character=state.get('identity',{}).get('currentName'),
            characterStatus=state.get('identity',{}).get('status'),
            pendingCharacter=state.get('identity',{}).get('pendingName'),
            loginSignals={k:bool(report.get('character',{}).get(k)) for k in
                          ('serverSelection','characterSelection','switchLoading','loginLoading')},
            dungeon=text(dungeon.get('dungeonName')),difficulty=text(dungeon.get('difficulty')),
            gates=[b.get('state') for b in report.get('gates',[])],
            completion=observation,reason=decision.get('reason'),targetGate=decision.get('gate'),
            goldReward={k:gold.get(k) for k in ('status','gate','received')},
            changedRecords=result.get('changedRecords',[]))
        signature=json.dumps({k:compact[k] for k in ('character','characterStatus','pendingCharacter','loginSignals','dungeon','difficulty','gates','reason','targetGate','goldReward')},sort_keys=True,ensure_ascii=False)
        self.directory.mkdir(parents=True,exist_ok=True)
        if signature!=self.previous or compact['changedRecords']:
            filename=f'event-{self.sequence:08d}.jpg'
            ok,encoded=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,92])
            if not ok:raise OSError('완료 진단 이미지 인코딩 실패')
            encoded.tofile(self.directory/filename)
            compact['frameFile']=filename
            (self.directory/f'event-{self.sequence:08d}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        with (self.directory/'observations.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(compact,ensure_ascii=False)+'\n')
        self.previous=signature;self.sequence+=1
