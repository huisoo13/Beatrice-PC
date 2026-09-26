import unittest
import tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from beatrice.storage import Store
from beatrice.live import LiveCoordinator

class LiveTests(unittest.TestCase):
    def test_missing_gate_does_not_replace_known_gate_count(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        now=datetime(2026,9,23,tzinfo=timezone.utc)
        context=dict(dungeonName='새 던전',difficulty='매칭 모드',contextStatus='ocr_verified')
        for i in range(20):
            boxes=[dict(xyxy=[40,130,60,160],state='진행중' if i<12 else '완료',confidence=.99),
                   dict(xyxy=[100,130,120,160],state='진행 전',confidence=.99)]
            if 6<=i<=10:boxes=boxes[:1]
            state=live.update(now+timedelta(seconds=i),dict(currentName=dict(text='테스트',confidence=.99)),boxes,context)
            if i>=5:self.assertEqual(live.context[1],2)
            if 6<=i<=10:self.assertIn('관문 수 불일치',state['recordingStatus'])
        self.assertEqual(len(store.state_records()),2)
        self.assertEqual([r['state'] for r in store.state_records()],['완료','진행 전'])

    def test_display_explains_held_context_without_claiming_current_detection(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        context=dict(dungeonName='기존 던전',difficulty='하드',contextStatus='ocr_held',diagnosticStatus='region_missing')
        state=live.update(datetime(2026,9,23,tzinfo=timezone.utc),{},[],context)
        self.assertIn('이전 던전명 유지',state['recordingStatus'])
        self.assertIn('관문 영역 재탐지',state['recordingStatus'])
        self.assertEqual(state['result'],{})

    def test_starting_with_completed_gate_creates_one_state_record(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        now=datetime(2026,9,23,tzinfo=timezone.utc)
        context=dict(dungeonName='새 던전',difficulty='매칭 모드',contextStatus='ocr_verified')
        for i in range(15):
            live.update(now+timedelta(seconds=i),dict(normalMenu=True,currentName=dict(text='테스트',confidence=.99)),
                [dict(xyxy=[40,130,60,160],state='완료',confidence=.99)],context)
        self.assertEqual(len(store.state_records()),1);self.assertEqual(store.state_records()[0]['state'],'완료')

    def test_held_dungeon_does_not_record_gate_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'test.db');live=LiveCoordinator(store)
            now=datetime(2026,9,17,tzinfo=timezone.utc)
            for i in range(12):
                context=dict(dungeonName='기존 던전',difficulty='하드',contextStatus='ocr_verified' if i<6 else 'ocr_held')
                boxes=[dict(xyxy=[40,130,60,160],state='진행중' if i<6 else '완료',confidence=.99)]
                live.update(now+timedelta(seconds=i),dict(currentName=dict(text='테베체',confidence=.99)),boxes,context)
            self.assertEqual(len(store.state_records()),1);self.assertEqual(store.state_records()[0]['state'],'진행중')
            store.close()
    def test_pending_promotion_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'test.db');live=LiveCoordinator(store)
            now=datetime(2026,9,17,tzinfo=timezone.utc)
            context=dict(dungeonName='어둠군단장 카멘',difficulty='하드',contextStatus='ocr_verified')
            def feed(i,state,char=None):
                return live.update(now+timedelta(seconds=i),char or {},[dict(xyxy=[40,130,60,160],state=state,confidence=.99)],context)
            for i in range(6):feed(i,'진행중')
            for i in range(6,9):feed(i,'완료')
            self.assertEqual(len(store.state_records()),1);self.assertIsNone(store.state_records()[0]['characterName'])
            for i in range(9,12):feed(i,'완료',dict(currentName=dict(text='테베체',confidence=.99),normalMenu=True))
            self.assertEqual(len(store.state_records()),1)
            self.assertEqual(store.state_records()[0]['characterName'],'테베체')
            self.assertEqual(store.state_records()[0]['timeBasis'],'live_capture')
            for i in range(12,18):feed(i,'완료')
            self.assertEqual(len(store.state_records()),1)
            store.clear_all()
            for table in ('gate_states','events','outbox','sessions','pending_events','pending_segments'):
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
            live.update(now+timedelta(seconds=9.5),dict(switchLoading=True),[],{})
            for i in range(10,13):live.update(now+timedelta(seconds=i),dict(currentName=dict(text='다른캐릭터',confidence=.99),normalMenu=True),[],{})
            self.assertEqual(len(store.state_records()),1)
            self.assertIsNone(store.state_records()[0]['characterName']);store.close()

if __name__=='__main__':unittest.main()
