import unittest
from unittest.mock import Mock
import numpy as np
from beatrice.storage import Store
from beatrice.completion_record import validate
from beatrice.gold_reward import GoldRewardDetector
from beatrice.gold_reward_session import GoldRewardSession
from beatrice.native_presentation import record_view


class GoldRewardTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close)
        self.row=self.store.save_completions('name:캐릭터','던전',[dict(characterName='캐릭터',dungeonName='던전',difficulty='싱글 모드',gate=1,state='완료',observedAt='2026-10-11T05:39:36Z')],2)[0]
        self.session=GoldRewardSession(self.store);self.session.register([self.row],10)
        self.dungeon=dict(dungeonName='던전',difficulty='싱글 모드',contextStatus='ocr_verified',currentRaidPanel=True,goldReward=dict(status='verified',gate=1,received=False))
        self.boxes=[dict(state='완료',confidence=.9),dict(state='진행중',confidence=.9)]

    def observe(self,at,**changes):
        return self.session.observe(at,'캐릭터',dict(self.dungeon,**changes),self.boxes)

    def test_receipt_requires_two_fresh_frames_and_preserves_completion(self):
        revision=self.store.drive_revision()[1]
        self.assertEqual(self.observe(11),[]);self.assertEqual(self.observe(11),[])
        updated=self.observe(12)[0]
        self.assertIs(updated['goldReward'],False)
        for field in ('recordId','observedAt','createdAt','contentName','gateNumber'):self.assertEqual(updated[field],self.row[field])
        self.assertEqual(self.store.state_records()[0],updated)
        self.assertEqual(self.store.drive_revision()[1],revision+1)
        self.assertIs(record_view(updated)['detail']['goldReward'],False)

    def test_conflicting_known_result_rejected_and_same_result_noop(self):
        self.store.set_gold_reward(self.row['recordId'],True);revision=self.store.drive_revision()
        self.store.set_gold_reward(self.row['recordId'],True)
        with self.assertRaises(ValueError):self.store.set_gold_reward(self.row['recordId'],False)
        self.assertEqual(self.store.drive_revision(),revision)

    def test_unregistered_prior_weekly_record_never_associated(self):
        self.session.reset();self.assertEqual(self.observe(11),[]);self.assertEqual(self.observe(12),[])
        self.assertNotIn('goldReward',self.store.history_records()[0])

    def test_wrong_gate_or_content_and_unverified_title_rejected(self):
        for changes in (dict(dungeonName='다른 던전'),dict(difficulty='하드'),dict(contextStatus='ocr_held'),dict(goldReward=dict(status='verified',gate=2,received=True)),dict(goldReward=dict(status='missing'))):
            self.assertEqual(self.observe(11,**changes),[]);self.assertEqual(self.observe(12,**changes),[])
        self.assertNotIn('goldReward',self.store.history_records()[0])

    def test_known_receipt_is_not_registered_again(self):
        row=self.store.set_gold_reward(self.row['recordId'],True)
        self.session.reset();self.session.register([row],10)
        self.assertEqual(self.observe(11),[]);self.assertEqual(self.observe(12),[])
        self.assertIs(self.store.history_records()[0]['goldReward'],True)

    def test_reversed_or_interrupted_observation_needs_fresh_pair(self):
        self.observe(11)
        self.assertEqual(self.observe(12,goldReward=dict(status='verified',gate=1,received=True)),[])
        self.assertEqual(self.observe(13),[])
        self.session.reset();self.session.register([self.row],14)
        self.assertEqual(self.observe(15),[])
        self.assertEqual(len(self.observe(16)),1)

    def test_expired_pending_and_character_change_cannot_attach(self):
        self.assertEqual(self.observe(131),[])
        self.session.register([self.row],140)
        self.session.observe(141,'다른 캐릭터',self.dungeon,self.boxes)
        self.assertEqual(self.observe(142),[]);self.assertEqual(self.observe(143),[])

    def test_throttled_frame_is_not_an_observation(self):
        self.assertEqual(self.observe(11),[])
        self.assertEqual(self.observe(11.5,goldReward=dict(status='not_requested')),[])
        self.assertEqual(len(self.observe(12)),1)

    def test_final_reward_updates_only_last_completed_gate(self):
        row=self.store.save_completions('name:캐릭터','던전',[dict(characterName='캐릭터',dungeonName='던전',difficulty='싱글 모드',gate=2,state='완료',observedAt='2026-10-11T05:40:36Z')],2)[0]
        self.session.register([row],10)
        self.boxes[1]['state']='완료'
        reward=dict(status='verified',scope='final',gate=None,received=False)
        self.assertEqual(self.observe(11,goldReward=reward),[])
        updated=self.observe(12,goldReward=reward)
        self.assertEqual([r['recordId'] for r in updated],[row['recordId']])
        self.assertIs(updated[0]['goldReward'],False)
        first=next(r for r in self.store.history_records() if r['gateNumber']==1)
        self.assertNotIn('goldReward',first)

    def test_final_reward_cannot_guess_last_gate_from_incomplete_icons(self):
        reward=dict(status='verified',scope='final',gate=None,received=False)
        self.assertEqual(self.observe(11,goldReward=reward),[])
        self.assertEqual(self.observe(12,goldReward=reward),[])
        self.assertNotIn('goldReward',self.store.history_records()[0])

    def test_final_reward_rejects_truncated_gate_array(self):
        self.boxes=self.boxes[:1]
        reward=dict(status='verified',scope='final',gate=None,received=False)
        self.assertEqual(self.observe(11,goldReward=reward),[])
        self.assertEqual(self.observe(12,goldReward=reward),[])
        self.assertNotIn('goldReward',self.store.history_records()[0])

    def test_unknown_compatibility_and_invalid_flags(self):
        validate(self.row);validate(dict(self.row,goldReward=None))
        for invalid in (0,1,'false',{},[]):
            with self.assertRaises(ValueError):validate(dict(self.row,goldReward=invalid))

    def test_drive_roundtrip_keeps_receipt_and_restore(self):
        from beatrice.drive_data import encode_records,decode_records
        row=self.store.set_gold_reward(self.row['recordId'],False)
        decoded=decode_records(encode_records([row]))
        self.assertEqual(decoded,[row])
        other=Store(':memory:');self.addCleanup(other.close)
        other.replace_history(decoded)
        self.assertIs(other.history_records()[0]['goldReward'],False)

    def test_live_connects_receipt_without_creating_another_completion_event(self):
        from beatrice.live import LiveCoordinator
        from datetime import datetime,timedelta,timezone
        store=Store(':memory:');self.addCleanup(store.close);live=LiveCoordinator(store)
        now=datetime(2026,10,11,tzinfo=timezone.utc)
        char=dict(currentName=dict(text='캐릭터',confidence=.99))
        boxes=[dict(state='완료',confidence=.99,xyxy=[1,1,20,20]),dict(state='진행중',confidence=.99,xyxy=[25,1,40,20])]
        updates=[];events=[]
        for i in range(12):
            state=live.update(now+timedelta(seconds=i),char,boxes,self.dungeon)
            updates.extend(state['result'].get('goldRewardUpdates',[]));events.extend(state['result'].get('events',[]))
        self.assertEqual(len(updates),1);self.assertEqual(len(events),1)
        self.assertEqual(len(store.history_records()),1);self.assertIs(store.history_records()[0]['goldReward'],False)

    def test_diagnostic_throttle_does_not_save_same_reward_image_again(self):
        from beatrice.completion_diagnostic import CompletionDiagnostic
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            diagnostic=CompletionDiagnostic(folder);frame=np.zeros((20,30,3),dtype=np.uint8)
            for status in ('verified','not_requested','verified'):
                diagnostic.record(frame,dict(dungeon=dict(goldReward=dict(status=status,gate=1,received=False))))
            self.assertEqual(len(list(diagnostic.directory.glob('*.jpg'))),1)


def region(box):return dict(status='detected',xyxy=box,confidence=.95)


class GoldDetectorTests(unittest.TestCase):
    def run_detector(self,elements,text='1관문 돌파'):
        detector=Mock();detector.locate.side_effect=[{'reward_panel':region([0,0,100,100])},elements]
        reader=Mock();reader.recognize.return_value=[(None,text,.99)]
        return GoldRewardDetector(reader,{},detector).analyze(np.zeros((100,100,3),dtype=np.uint8),10)

    def test_explicit_absent_with_gate_title_verifies_false(self):
        result=self.run_detector({'reward_gate_title':region([1,1,90,20]),'gold_reward_absent':region([1,30,90,80])})
        self.assertEqual((result['status'],result['gate'],result['received']),('verified',1,False))

    def test_missing_gold_alone_or_conflicting_classes_is_unknown(self):
        title={'reward_gate_title':region([1,1,90,20])}
        for elements in (title,dict(title,gold_reward_present=region([1,30,90,80]),gold_reward_absent=region([1,30,90,80]))):
            self.assertEqual(self.run_detector(elements)['status'],'unverified')

    def test_trade_gold_and_wrong_title_do_not_verify(self):
        elements={'reward_gate_title':region([1,1,90,20]),'gold_reward_present':region([1,30,90,80])}
        for title in ('던전 클리어','골드','9관문 돌파','던전 종료 예정','거래 던전 종료'):
            self.assertEqual(self.run_detector(elements,title)['status'],'unverified')

    def test_dungeon_end_verifies_receipt_without_guessing_gate(self):
        for title in ('던전 종료',"'던전 종료'",'던전 종료"','“던전 종료”'):
            result=self.run_detector({'reward_gate_title':region([1,1,90,20]),'gold_reward_absent':region([1,30,90,80])},title)
            self.assertEqual((result['status'],result['scope'],result['gate'],result['received']),('verified','final',None,False))
