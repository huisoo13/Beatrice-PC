from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
from beatrice.dungeon import validate_readings,DungeonTracker,DungeonOCR
from beatrice.session import RecordingSession
from beatrice.deferred_session import DeferredRecordingSession
from beatrice.storage import Store


class DungeonTests(unittest.TestCase):
    def test_spacing_variants_agree_without_name_dictionary(self):
        result=validate_readings([
            dict(text='2막: 부유하는 악몽의진혼곡',confidence=.95),
            dict(text='2막: 부유하는 악몽의 진혼곡',confidence=.97),
            dict(text='2막: 부유하는 악몽의 진혼곡',confidence=.96)])
        self.assertEqual(result['text'],'2막: 부유하는 악몽의 진혼곡')
    def test_live_requires_gate_hud_and_difficulty_before_display(self):
        import numpy as np
        from unittest.mock import Mock
        frame=np.zeros((1440,3440,3),dtype=np.uint8)
        reader=Mock()
        ocr=DungeonOCR(reader=reader)
        result=ocr.analyze(frame,gate_boxes=[])
        reader.recognize.assert_not_called()
        self.assertIsNone(result['dungeonName'])
        boxes=[dict(state='진행중',confidence=.99,xyxy=[60,130,100,180])]
        ocr.analyze_panel=Mock(return_value=self.observation('일반 화면 텍스트','퀘스트 목록'))
        result=ocr.analyze(frame,gate_boxes=boxes)
        self.assertIsNone(result['dungeonName'])
        self.assertIsNone(result['difficulty'])
        ocr.analyze_panel.return_value=self.observation('이름이 긴 새로운 던전입니다','하드')
        self.assertTrue(ocr.analyze(frame,gate_boxes=boxes)['dungeonVisible'])
        self.assertEqual(ocr.analyze_panel.call_args.args[0].shape,(240,800,3))
        ocr.analyze_panel.return_value=self.observation('2막 : 부유하는 악몽의 진혼곡','싱글 모드')
        boxes.append(dict(state='진행중',confidence=.3,xyxy=[60,130,100,180]))
        result=ocr.analyze(frame,gate_boxes=boxes)
        self.assertTrue(result['dungeonVisible'])
        self.assertEqual(result['difficulty']['text'],'싱글 모드')

    def test_title_keeps_words_separated_by_spaces(self):
        import numpy as np
        from beatrice.character_vision import trim_name_line
        crop=np.zeros((24,800,3),dtype=np.uint8)
        for left,right in ((30,60),(76,150),(167,230),(246,310)):
            crop[3:21,left:right]=255
        trimmed=trim_name_line(crop,max_gap=24)
        self.assertGreaterEqual(trimmed.shape[1],280)

    def test_dungeon_name_crop_includes_text_beyond_old_width(self):
        import numpy as np
        from unittest.mock import Mock
        panel=np.zeros((240,800,3),dtype=np.uint8)
        for x in range(30,650,15):panel[66:84,x:x+10]=255
        reader=Mock()
        reader.recognize.return_value=[(None,'긴 던전 이름',.99)]
        result=DungeonOCR(reader=reader).analyze_panel(panel)
        self.assertGreater(reader.recognize.call_args_list[0].args[0].shape[1],355)
        self.assertEqual(result['dungeonName']['text'],'긴 던전 이름')

    def test_unseen_text_preview_confirmation_and_event_context(self):
        from beatrice.dungeon import event_context
        name='새로운 던전 : 별빛의 성역'
        reading=validate_readings([dict(text=name,confidence=.97)]*2)
        self.assertEqual(reading['text'],name)
        tracker=DungeonTracker()
        observation=self.observation(name,'익스트림')
        first=tracker.update(0,observation)
        self.assertEqual(first['preview']['dungeonName'],name)
        self.assertIsNone(first['dungeonName'])
        tracker.update(.2,observation)
        context=event_context(tracker.update(.4,observation))
        self.assertEqual(context['dungeonName'],name)
        self.assertEqual(context['difficulty'],'익스트림')
        self.assertEqual(context['contextStatus'],'ocr_verified')
        self.assertIsNone(validate_readings([dict(text='[]',confidence=.99)]*2))
        self.assertIsNone(validate_readings([dict(text=name,confidence=.3)]*2))
        self.assertIsNone(validate_readings([dict(text=name,confidence=.99),dict(text='다른 이름',confidence=.99)]))

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
                    context=tracker.update(i*.2,self.observation('미등록 던전 : 새벽의 성'))
                    session.observe(session.token,start+timedelta(seconds=i*.2),
                        [dict(state='진행중' if i<3 else '완료',confidence=.99,xyxy=[60,130,100,180])],context)
                if deferred:
                    self.assertEqual(store.pending_records()[0]['dungeonName'],'미등록 던전 : 새벽의 성')
                    session.confirm_character('A','A',**run)
                event=store.records()[0]
                self.assertEqual(event['dungeonName'],'미등록 던전 : 새벽의 성')
                self.assertEqual(event['difficulty'],'하드')
                self.assertEqual(event['contextStatus'],'ocr_verified')
                self.assertIn('dungeonObservation',event)
                store.close()

if __name__=='__main__':unittest.main()
