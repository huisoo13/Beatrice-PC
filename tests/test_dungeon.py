from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
from beatrice.dungeon import validate_readings,DungeonTracker,DungeonOCR
from beatrice.session import RecordingSession
from beatrice.deferred_session import DeferredRecordingSession
from beatrice.storage import Store


class DungeonTests(unittest.TestCase):
    def observation(self,name='고통의 마녀, 세르카',difficulty='하드'):
        return dict(dungeonName=dict(text=name,confidence=.9) if name else None,
            difficulty=dict(text=difficulty,confidence=.99) if difficulty else None,ocr={'test':True})

    def test_image_adapter_preserves_raw_output_and_engine(self):
        import numpy as np
        class Reader:
            calls=0
            def recognize(self,image):
                self.calls+=1
                text='어둠군단장 카멘' if self.calls<=3 else '[하드]'
                return [(None,text,.99)]
        # 실제 모델 정확도 테스트가 아닌 출력 형식/연결 검증입니다.
        panel=np.full((240,400,3),200,dtype=np.uint8)
        ocr=DungeonOCR(reader=Reader(),engine='paddle')
        observed=ocr.analyze_panel(panel)
        self.assertEqual(observed['engine'],'paddle')
        self.assertEqual(observed['dungeonName']['text'],'어둠군단장 카멘')
        self.assertEqual(observed['difficulty']['text'],'하드')
        self.assertEqual(len(observed['ocr']['dungeonName']['raw']),3)
        with self.assertRaises(ValueError):ocr.analyze_panel(panel[:100])

    def test_no_fuzzy_correction_even_high_confidence(self):
        readings=[dict(text='어둡군단장 카엔',confidence=.99)]*3
        self.assertIsNone(validate_readings(readings,['어둠군단장 카멘']))

    def test_punctuation_normalization_and_agreement(self):
        readings=[dict(text='고통의 마녀 세르카',confidence=.9),dict(text='고통의 마녀, 세르카',confidence=.8)]
        self.assertEqual(validate_readings(readings,['고통의 마녀, 세르카'])['text'],'고통의 마녀, 세르카')
        self.assertIsNone(validate_readings(readings[:1],['고통의 마녀, 세르카']))

    def test_three_frames_and_no_stale_values_after_failure_or_change(self):
        tracker=DungeonTracker()
        self.assertIsNone(tracker.update(0,self.observation())['dungeonName'])
        tracker.update(.2,self.observation())
        self.assertEqual(tracker.update(.4,self.observation())['contextStatus'],'ocr_verified')
        failed=tracker.update(.6,self.observation(None))
        self.assertIsNone(failed['dungeonName']);self.assertEqual(failed['difficulty'],'하드')
        self.assertIsNone(tracker.update(.8,self.observation('종막 : 최후의 날'))['dungeonName'])

    def test_long_gap_resets_and_out_of_order_rejected(self):
        tracker=DungeonTracker()
        for t in [0,.2,.4]:tracker.update(t,self.observation())
        self.assertIsNone(tracker.update(2,self.observation())['dungeonName'])
        with self.assertRaises(ValueError):tracker.update(2,self.observation())

    def test_context_stored_directly_and_preserved_on_pending_promotion(self):
        for deferred in [False,True]:
            with self.subTest(deferred=deferred),tempfile.TemporaryDirectory() as temp:
                store=Store(Path(temp)/'events.sqlite')
                session=(DeferredRecordingSession if deferred else RecordingSession)(store)
                run=dict(session_id='test-run',expected_gates=1,time_basis='synthetic_test',is_test=True)
                if deferred:session.prepare_pending_run(**run)
                else:session.confirm_character('A','A',**run)
                tracker=DungeonTracker();start=datetime(2026,9,17,tzinfo=timezone.utc)
                for i in range(6):
                    context=tracker.update(i*.2,self.observation())
                    session.observe(session.token,start+timedelta(seconds=i*.2),
                        [dict(state='진행중' if i<3 else '완료',confidence=.99,xyxy=[60,130,100,180])],context)
                if deferred:
                    self.assertEqual(store.pending_records()[0]['dungeonName'],'고통의 마녀, 세르카')
                    session.confirm_character('A','A',**run)
                event=store.records()[0]
                self.assertEqual(event['dungeonName'],'고통의 마녀, 세르카')
                self.assertEqual(event['difficulty'],'하드')
                self.assertEqual(event['contextStatus'],'ocr_verified')
                self.assertIn('dungeonObservation',event)
                store.close()

if __name__=='__main__':unittest.main()
