"""Associate repeated fresh reward observations only with newly saved completions."""
from .dungeon import key
from .content_match import mode_key


class GoldRewardSession:
    def __init__(self,store):
        self.store=store;self.reset()

    def reset(self):
        self.pending={};self.candidate=None;self.last_at=None;self.count=0

    def register(self,rows,at):
        for row in rows:
            if row.get('goldReward') is None and row.get('gateNumber',0)>0:
                self.pending[row['recordId']]=(row,at)

    def observe(self,at,name,dungeon,boxes):
        self.pending={identifier:item for identifier,item in self.pending.items() if 0<=at-item[1]<=120 and item[0]['characterName']==name}
        observation=dungeon.get('goldReward') or {}
        if observation.get('status')=='not_requested':return []
        def clear():self.candidate=None;self.last_at=None;self.count=0
        if dungeon.get('contextStatus')!='ocr_verified' or not dungeon.get('currentRaidPanel') or observation.get('status')!='verified':clear();return []
        gate=observation.get('gate');received=observation.get('received')
        if observation.get('scope')=='final':
            if not boxes or any(b.get('state')!='완료' or b.get('confidence',0)<.5 for b in boxes):clear();return []
            gate=len(boxes)
        if type(gate) is not int or type(received) is not bool or not 1<=gate<=len(boxes) or boxes[gate-1].get('state')!='완료' or boxes[gate-1].get('confidence',0)<.5:clear();return []
        matches=[]
        for identifier,(row,_) in self.pending.items():
            if observation.get('scope')=='final' and row.get('expectedGates')!=gate:continue
            aliases=[row['contentName'],row.get('ocrOriginal',{}).get('contentName'),row.get('catalogMatch',{}).get('fieldName')]
            if row['gateNumber']==gate and key(dungeon.get('dungeonName') or '') in {key(a) for a in aliases if a} and mode_key(row['difficulty'])==mode_key(dungeon.get('difficulty') or ''):matches.append(identifier)
        if len(matches)!=1:clear();return []
        candidate=(matches[0],received)
        if self.last_at is not None and at<=self.last_at:return []
        self.count=self.count+1 if self.candidate==candidate and self.last_at is not None and at-self.last_at<=3 else 1
        self.candidate=candidate;self.last_at=at
        if self.count<2:return []
        row=self.store.set_gold_reward(*candidate)
        self.pending.pop(candidate[0]);clear()
        return [row]
