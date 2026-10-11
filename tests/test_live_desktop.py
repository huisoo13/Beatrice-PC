import unittest
import tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from beatrice.storage import Store
from beatrice.live import LiveCoordinator

class LiveTests(unittest.TestCase):
    def test_current_gate_survives_saved_completion_on_reentry(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        now=datetime(2026,9,30,tzinfo=timezone.utc)
        context=dict(dungeonName='카멘',difficulty='하드',contextStatus='ocr_verified',currentRaidPanel=True)
        char=dict(currentName=dict(text='테스트',confidence=.99))
        def feed(i, states):
            boxes=[dict(xyxy=[40+60*j,130,60+60*j,160],state=s,confidence=.99) for j,s in enumerate(states)]
            return live.update(now+timedelta(seconds=i),char,boxes,context)
        for i in range(8): feed(i,['완료','완료'])
        for i in range(8,12): result=feed(i,['완료','진행중'])
        self.assertEqual(result['result']['stableStates'],('완료','완료'))
        self.assertEqual(result['result']['observedStates'],('완료','진행중'))
        self.assertEqual([r['gateNumber'] for r in store.state_records()],[1,2])

    def test_capture_gap_preserves_owner_and_consumed_banner_but_breaks_confirmation(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        now=datetime(2026,9,30,tzinfo=timezone.utc)
        for i in range(3):
            live.update(now+timedelta(seconds=i),dict(currentName=dict(text='테스트',confidence=.99)),[],{})
        live.banner.active=True;live.banner.consumed=True;live.banner.count=1
        live.capture_interrupted()
        self.assertEqual(live.identity.current,'테스트')
        self.assertFalse(live.identity.blocked)
        self.assertTrue(live.banner.consumed)
        self.assertEqual(live.banner.count,0)
        self.assertEqual(store.state_records(),[])

    def test_switch_target_records_without_reopening_menu(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        now=datetime(2026,9,30,tzinfo=timezone.utc)
        def feed(i,char=None,context=None,boxes=None):
            return live.update(now+timedelta(seconds=i),char or {},boxes or [],context or {})
        for i in range(3):feed(i,dict(currentName=dict(text='후이수',confidence=.99)))
        feed(3,dict(switchDialog=True,targetName=dict(text='테베체',confidence=.99)))
        feed(4,dict(switchLoading=True))
        context=dict(dungeonName='새 던전',difficulty='하드',contextStatus='ocr_held')
        boxes=[dict(xyxy=[0,0,20,30],state='완료',confidence=.99)]
        for i in range(5,8):
            self.assertFalse(feed(i,context=context,boxes=boxes)['identity']['recordingAllowed'])
        # 마을 화면: 던전/관문 정보 없이 로딩 종료만으로 이름 확정.
        for i in range(8,11):result=feed(i,dict(loadingAbsent=True))
        self.assertEqual(result['identity']['currentName'],'테베체')
        self.assertTrue(result['identity']['recordingAllowed'])
        context['contextStatus']='ocr_verified'
        for i in range(11,18):result=feed(i,context=context,boxes=boxes)
        self.assertEqual(result['identity']['currentName'],'테베체')
        records=store.state_records()
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['characterName'],'테베체')

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
        self.assertEqual(len(store.state_records()),1)
        self.assertEqual([r['gateNumber'] for r in store.state_records()],[1])

    def test_display_explains_held_context_without_claiming_current_detection(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        context=dict(dungeonName='기존 던전',difficulty='하드',contextStatus='ocr_held',diagnosticStatus='region_missing')
        state=live.update(datetime(2026,9,23,tzinfo=timezone.utc),{},[],context)
        self.assertIn('던전 탐지 중지',state['recordingStatus'])
        self.assertEqual(state['dungeon'],{})
        self.assertFalse(state['result'].get('changedRecords'))
        self.assertNotIn('completionDecision',state['result'])

    def test_starting_with_completed_gate_creates_one_state_record(self):
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        now=datetime(2026,9,23,tzinfo=timezone.utc)
        context=dict(dungeonName='새 던전',difficulty='매칭 모드',contextStatus='ocr_verified')
        for i in range(15):
            live.update(now+timedelta(seconds=i),dict(normalMenu=True,currentName=dict(text='테스트',confidence=.99)),
                [dict(xyxy=[40,130,60,160],state='완료',confidence=.99)],context)
        self.assertEqual(len(store.state_records()),1);self.assertEqual(store.state_records()[0]['gateNumber'],1)

    def test_held_dungeon_does_not_record_gate_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'test.db');live=LiveCoordinator(store)
            now=datetime(2026,9,17,tzinfo=timezone.utc)
            for i in range(12):
                context=dict(dungeonName='기존 던전',difficulty='하드',contextStatus='ocr_verified' if i<6 else 'ocr_held')
                boxes=[dict(xyxy=[40,130,60,160],state='진행중' if i<6 else '완료',confidence=.99)]
                live.update(now+timedelta(seconds=i),dict(currentName=dict(text='테베체',confidence=.99)),boxes,context)
            self.assertEqual(store.state_records(),[])
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
            self.assertEqual(len(store.state_records()),0)
            for i in range(9,14):feed(i,'완료',dict(currentName=dict(text='테베체',confidence=.99),normalMenu=True))
            self.assertEqual(len(store.state_records()),1)
            self.assertEqual(store.state_records()[0]['characterName'],'테베체')
            self.assertEqual(store.state_records()[0]['isTest'],False)
            for i in range(14,20):feed(i,'완료')
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
            self.assertEqual(store.state_records(),[]);store.close()

if __name__=='__main__':unittest.main()
