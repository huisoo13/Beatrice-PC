import unittest
import tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from beatrice.storage import Store
from beatrice.live import LiveCoordinator

class LiveTests(unittest.TestCase):
    def test_pending_promotion_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'test.db');live=LiveCoordinator(store)
            now=datetime(2026,9,17,tzinfo=timezone.utc)
            context=dict(dungeonName='어둠군단장 카멘',difficulty='하드',contextStatus='ocr_verified')
            def feed(i,state,char=None):
                return live.update(now+timedelta(seconds=i),char or {},[dict(xyxy=[40,130,60,160],state=state,confidence=.99)],context)
            for i in range(6):feed(i,'진행중')
            for i in range(6,9):feed(i,'완료')
            self.assertEqual(len(store.pending_records()),1);self.assertEqual(store.records(),[])
            for i in range(9,12):feed(i,'완료',dict(currentName=dict(text='테베체',confidence=.99),normalMenu=True))
            self.assertEqual(len(store.records()),1)
            self.assertEqual(store.records()[0]['characterName'],'테베체')
            self.assertEqual(store.records()[0]['timeBasis'],'live_capture')
            for i in range(12,18):feed(i,'완료')
            self.assertEqual(len(store.records()),1)
            store.clear_all()
            for table in ('events','outbox','sessions','pending_events','pending_segments'):
                self.assertEqual(store.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
            store.close()
    def test_new_character_does_not_claim_previous_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'test.db');live=LiveCoordinator(store)
            now=datetime(2026,9,17,tzinfo=timezone.utc)
            context=dict(dungeonName='어둠군단장 카멘',difficulty='하드',contextStatus='ocr_verified')
            for i in range(9):
                boxes=[dict(xyxy=[40,130,60,160],state='진행중' if i<6 else '완료',confidence=.99)]
                live.update(now+timedelta(seconds=i),{},boxes,context)
            live.update(now+timedelta(seconds=9),dict(switchDialog=True),[],{})
            for i in range(10,13):live.update(now+timedelta(seconds=i),dict(currentName=dict(text='다른캐릭터',confidence=.99),normalMenu=True),[],{})
            self.assertEqual(store.records(),[])
            self.assertIsNone(store.pending_records()[0]['resolvedEventID']);store.close()
    def test_layout_anchors(self):
        import numpy as np
        from beatrice.layout import normalize
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        frame[50,50]=255;frame[400,650]=255
        left=normalize(frame);center=normalize(frame,centered=True)
        self.assertTrue((left[100,100]==255).all())
        self.assertTrue((center[800,1740]==255).all())

if __name__=='__main__':unittest.main()
