from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from beatrice.character import CharacterTracker, CharacterRecordingBridge, valid_name
from beatrice.session import RecordingSession
from beatrice.storage import Store


def observation(name=None,dialog=False,target=None,confidence=.95):
    return dict(currentName=dict(text=name,confidence=confidence) if name else None,
                targetName=dict(text=target,confidence=confidence) if target else None,
                currentRegionVisible=name is not None,switchDialog=dialog)


class CharacterTests(unittest.TestCase):
    def setUp(self):
        self.tracker=CharacterTracker();self.t=-.5

    def feed(self,name=None,dialog=False,target=None,confidence=.95,count=1):
        for _ in range(count):
            self.t+=.5
            result=self.tracker.update(self.t,observation(name,dialog,target,confidence))
        return result

    def test_initial_name_requires_consecutive_readings(self):
        self.assertFalse(self.feed('후이수',count=2)['recordingAllowed'])
        self.assertTrue(self.feed('후이수')['recordingAllowed'])
        self.assertTrue(self.feed()['recordingAllowed'])  # 메뉴를 닫고 플레이

    def test_target_is_not_current_and_cancel_does_not_switch(self):
        self.feed('테베체',count=3)
        result=self.feed('테베체',True,'힐레우스')
        self.assertEqual(result['currentName'],'테베체')
        self.assertFalse(result['recordingAllowed'])
        result=self.feed('테베체',count=6)
        self.assertEqual(result['currentName'],'테베체')
        self.assertFalse(result['recordingAllowed'])  # 취소와 전환 대기를 구분할 근거 부족

    def test_success_requires_current_after_gap(self):
        self.feed('후이수',count=3)
        self.feed('후이수',True,'테베체')
        self.assertFalse(self.feed('테베체',count=3)['recordingAllowed'])
        self.feed(count=3)
        result=self.feed('테베체',count=3)
        self.assertEqual(result['currentName'],'테베체')
        self.assertTrue(result['recordingAllowed'])

    def test_unknown_target_still_blocks(self):
        self.feed('후이수',count=3)
        self.assertFalse(self.feed('후이수',True,None)['recordingAllowed'])
        self.feed(count=2)
        self.assertTrue(self.feed('테베체',count=3)['recordingAllowed'])

    def test_uncertain_reading_and_long_gap_reset_streak(self):
        self.feed('테베체',count=2)
        self.feed('테비체',confidence=.4)
        self.assertFalse(self.feed('테베체')['recordingAllowed'])
        self.t+=2
        self.assertFalse(self.feed('테베체')['recordingAllowed'])
        self.assertTrue(self.feed('테베체',count=2)['recordingAllowed'])

    def test_wrong_timestamp_rejected(self):
        self.feed('후이수')
        with self.assertRaises(ValueError):self.tracker.update(self.t,observation('후이수'))

    def test_bridge_blocks_old_frames_and_preserves_exact_name(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'test.sqlite')
            recording=RecordingSession(store)
            bridge=CharacterRecordingBridge(recording,lambda name:dict(character_key='test:'+name,
                session_id='test-run',expected_gates=1,time_basis='synthetic_test',is_test=True))
            bridge.apply(self.feed('후이수',count=3));old=recording.token
            bridge.apply(self.feed('후이수',True,'테베체'))
            start=datetime(2026,9,16,tzinfo=timezone.utc)
            self.assertEqual(recording.observe(old,start,[])['status'],'character_unconfirmed_or_stale_frame')
            self.feed(count=3)
            bridge.apply(self.feed('테베체',count=3))
            self.assertEqual(recording.character['name'],'테베체')
            for i in range(6):
                box=dict(state='진행중' if i<3 else '완료',confidence=.99,xyxy=[60,130,100,180])
                recording.observe(recording.token,start+timedelta(seconds=i*.2),[box])
            records=store.records()
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['characterName'],'테베체')
            self.assertEqual(records[0]['syncStatus'],'test_only')
            store.close()

if __name__=='__main__':unittest.main()
