from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
from beatrice.dungeon import validate_readings,DungeonTracker,DungeonOCR
from beatrice.session import RecordingSession
from beatrice.deferred_session import DeferredRecordingSession
from beatrice.storage import Store


class DungeonTests(unittest.TestCase):
    def test_direct_text_failure_does_not_retry_other_panel_positions(self):
        from unittest.mock import Mock
        location=dict(status='detected',xyxy=[400,400,800,610],regions={
            'dungeonName':[410,430,790,460],'difficulty':[450,465,700,490]})
        ocr=DungeonOCR(reader=Mock())
        ocr.read_regions=Mock(return_value=dict(dungeonName=None,difficulty=None,ocr={}))
        result=ocr.analyze_detected(None,location,[],allow_without_gates=True)
        self.assertFalse(result['dungeonVisible'])
        ocr.read_regions.assert_called_once_with(None,location['regions'])

    def test_gateless_header_splits_mode_without_requiring_space_after_bracket(self):
        import numpy as np
        from unittest.mock import Mock
        ocr=DungeonOCR(reader=Mock())
        for text in ('[하드]맹렬한 업화','하드] 맹렬한 업화'):
            ocr.read_regions=Mock(return_value=dict(dungeonName=dict(text=text,confidence=.98),ocr={}))
            result=ocr.analyze_gateless(np.zeros((1440,3440,3),dtype=np.uint8),[0,45,405,125])
            self.assertEqual(result['dungeonName']['text'],'맹렬한 업화')
            self.assertEqual(result['difficulty']['text'],'하드')
            region=ocr.read_regions.call_args.args[1]['dungeonName']
            self.assertLessEqual(region[3],125)  # 도전 과제/목표 영역을 읽지 않음
        ocr.read_regions=Mock(return_value=dict(dungeonName=dict(text='도전 과제',confidence=.98),ocr={}))
        self.assertFalse(ocr.analyze_gateless(np.zeros((1440,3440,3),dtype=np.uint8),[0,45,405,125])['dungeonVisible'])

    def test_gateless_accepts_new_bracketed_mode_without_a_dictionary(self):
        from unittest.mock import Mock
        ocr=DungeonOCR(reader=Mock())
        ocr.read_regions=Mock(return_value=dict(dungeonName=dict(text='[새 단계]새 콘텐츠',confidence=.98),ocr={}))
        result=ocr.analyze_gateless(None,[0,0,100,50])
        self.assertEqual(result['difficulty']['text'],'새 단계')
        self.assertEqual(result['dungeonName']['text'],'새 콘텐츠')

    def test_mode_line_excludes_title_fragment_and_divider(self):
        import numpy as np
        from beatrice.dungeon import trim_difficulty_line
        crop=np.zeros((44,260,3),dtype=np.uint8)
        crop[:3,10:250]=255
        crop[38,10:250]=255
        for x in range(80,180,12):crop[15:33,x:x+8]=200
        line=trim_difficulty_line(crop)
        self.assertIsNotNone(line)
        self.assertLessEqual(line.shape[0],20)
        self.assertEqual(int(line.max()),200)
        dim=trim_difficulty_line((crop*.4).astype(np.uint8))
        self.assertIsNotNone(dim)
        self.assertLessEqual(dim.shape[0],20)

    def test_spacing_variants_agree_without_name_dictionary(self):
        result=validate_readings([
            dict(text='2막: 부유하는 악몽의진혼곡',confidence=.95),
            dict(text='2막: 부유하는 악몽의 진혼곡',confidence=.97),
            dict(text='2막: 부유하는 악몽의 진혼곡',confidence=.96)])
        self.assertEqual(result['text'],'2막: 부유하는 악몽의 진혼곡')

    def test_matching_mode_is_preserved_as_displayed(self):
        from unittest.mock import Mock
        ocr=DungeonOCR(reader=Mock())
        result=ocr.verify_context(self.observation('고통의 마녀, 세르카','[매칭 모드]'))
        self.assertTrue(result['dungeonVisible'])
        self.assertEqual(result['difficulty']['text'],'매칭 모드')
        self.assertEqual(result['dungeonName']['text'],'고통의 마녀, 세르카')

    def test_modes_are_read_without_a_dictionary(self):
        from unittest.mock import Mock
        ocr=DungeonOCR(reader=Mock())
        result=ocr.verify_context(self.observation('구원의 종탑','[3단계]'))
        self.assertTrue(result['dungeonVisible'])
        self.assertEqual(result['difficulty']['text'],'3단계')
        self.assertEqual(result['dungeonName']['text'],'구원의 종탑')
        self.assertTrue(ocr.verify_context(self.observation('다른 던전','새 단계'))['dungeonVisible'])
        low=self.observation('구원의 종탑','3단계');low['difficulty']['confidence']=.4
        self.assertFalse(ocr.verify_context(low)['dungeonVisible'])

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
        result=DungeonOCR(reader=reader).read_regions(panel,{'dungeonName':[25,63,800,87]})
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
        observed=ocr.verify_context(ocr.read_regions(panel,{'dungeonName':[25,63,355,87],'difficulty':[50,90,320,120]}))
        self.assertEqual(observed['engine'],'paddle')
        self.assertEqual(observed['dungeonName']['text'],'어둠군단장 카멘')
        self.assertEqual(observed['difficulty']['text'],'하드')
        self.assertEqual(len(observed['ocr']['dungeonName']['raw']),3)

    def test_no_fuzzy_correction_even_high_confidence(self):
        readings=[dict(text='어둡군단장 카엔',confidence=.99)]*3
        self.assertEqual(validate_readings(readings)['text'],'어둡군단장 카엔')

    def test_punctuation_normalization_and_agreement(self):
        readings=[dict(text='고통의 마녀 세르카',confidence=.9),dict(text='고통의 마녀, 세르카',confidence=.8)]
        self.assertEqual(validate_readings(readings)['text'],'고통의 마녀 세르카')
        self.assertIsNone(validate_readings(readings[:1]))

    def test_three_frames_then_keep_display_without_reusing_for_recording(self):
        tracker=DungeonTracker()
        self.assertIsNone(tracker.update(0,self.observation())['dungeonName'])
        tracker.update(.2,self.observation())
        self.assertEqual(tracker.update(.4,self.observation())['contextStatus'],'ocr_verified')
        failed=tracker.update(.6,self.observation(None))
        self.assertEqual(failed['dungeonName'],'고통의 마녀, 세르카');self.assertEqual(failed['difficulty'],'하드')
        self.assertEqual(failed['contextStatus'],'ocr_held')
        self.assertEqual(tracker.update(.8,self.observation('종막 : 최후의 날'))['dungeonName'],'고통의 마녀, 세르카')

    def test_long_gap_resets_and_out_of_order_rejected(self):
        tracker=DungeonTracker()
        for t in [0,.2,.4]:tracker.update(t,self.observation())
        self.assertEqual(tracker.update(2,self.observation())['dungeonName'],'고통의 마녀, 세르카')
        with self.assertRaises(ValueError):tracker.update(2,self.observation())

    def test_spacing_variation_confirms_without_changing_context_identity(self):
        tracker=DungeonTracker()
        for t,name in [(0,'1막: 대지를 부수는 업화의 궤적'),(.2,'1막:대지를 부수는 업화의 궤적'),
                       (.4,'1막: 대지를부수는 업화의 궤적'),(.6,'1막:대지를 부수는 업화의 궤적')]:
            result=tracker.update(t,self.observation(name))
        self.assertEqual(result['contextStatus'],'ocr_verified')
        self.assertEqual(result['dungeonName'],'1막: 대지를 부수는 업화의 궤적')
        self.assertEqual(tracker.update(.8,self.observation('2막: 대지를 부수는 업화의 궤적'))['contextStatus'],'ocr_held')

    def test_replace_pair_only_after_ten_seconds_and_reset_on_character_change(self):
        tracker=DungeonTracker(max_gap=2)
        for t in (0,.5,1):tracker.update(t,self.observation('이전 던전','하드'))
        for t in range(2,12):
            result=tracker.update(t,self.observation('다음 던전','노말'))
            self.assertEqual((result['dungeonName'],result['difficulty']),('이전 던전','하드'))
            self.assertEqual(result['contextStatus'],'ocr_held')
        result=tracker.update(12,self.observation('다음 던전','노말'))
        self.assertEqual((result['dungeonName'],result['difficulty']),('다음 던전','노말'))
        self.assertEqual(result['contextStatus'],'ocr_verified')
        tracker.reset()
        self.assertIsNone(tracker.update(13,{})['dungeonName'])

    def test_missing_changed_candidate_old_value_and_capture_gap_reset_replacement_timer(self):
        for interruption in ('missing','different','original','gap'):
            with self.subTest(interruption=interruption):
                tracker=DungeonTracker(max_gap=2)
                for t in (0,.5,1):tracker.update(t,self.observation('기존'))
                for t in range(2,10):tracker.update(t,self.observation('후보'))
                if interruption!='gap':
                    tracker.update(10,{} if interruption=='missing' else self.observation('다른 후보' if interruption=='different' else '기존'))
                result=tracker.update(12,self.observation('후보'))
                self.assertEqual(result['dungeonName'],'기존')
                self.assertEqual(result['replacementElapsed'],0)

    def test_held_event_context_does_not_become_verified(self):
        from beatrice.dungeon import event_context
        tracker=DungeonTracker()
        for t in (0,.2,.4):tracker.update(t,self.observation())
        self.assertEqual(event_context(tracker.update(.6,{}))['contextStatus'],'ocr_held')

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
