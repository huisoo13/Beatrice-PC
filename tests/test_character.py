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
    def test_loading_without_recent_dialog_does_not_suspend(self):
        self.feed('후이수',count=3)
        self.assertTrue(self.feed(loading=True)['recordingAllowed'])
        self.feed('후이수',dialog=True,target='테베체')
        self.t+=10
        result=self.feed(loading=True)
        self.assertTrue(result['recordingAllowed'])
        self.assertIsNone(result['pendingName'])

    def test_cancel_without_readable_name_clears_switch_intent(self):
        self.feed('후이수',count=3)
        self.feed(dialog=True,target='테베체')
        self.feed(menu=True,count=5)
        self.assertTrue(self.feed(loading=True)['recordingAllowed'])

    def test_confirm_menu_gap_before_loading_keeps_switch_intent(self):
        self.feed('후이수',count=3)
        self.feed(dialog=True,target='테베체')
        self.assertTrue(self.feed('후이수',menu=True)['recordingAllowed'])
        result=self.feed(loading=True)
        self.assertFalse(result['recordingAllowed'])
        self.assertEqual(result['actions'],[dict(type='suspend')])

    def test_loading_needs_both_icon_and_text_at_bottom_right(self):
        from unittest.mock import Mock
        import numpy as np
        from beatrice.character_vision import CharacterVision
        vision=CharacterVision.__new__(CharacterVision)
        vision.reader=Mock()
        vision.reader.recognize.return_value=[(None,'잠시만 기다려주세요.',.99)]
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        self.assertFalse(vision.read_loading(frame)['visible'])
        vision.reader.recognize.assert_not_called()
        frame[660:685,1210:1230]=(255,220,0)
        self.assertTrue(vision.read_loading(frame)['visible'])
        vision.reader.recognize.return_value=[(None,'다른 문구',.99)]
        self.assertFalse(vision.read_loading(frame)['visible'])

    def test_map_loading_and_capture_loss_preserve_character(self):
        for signal in ('identityUncertain','loadingScreen'):
            tracker=CharacterTracker()
            for t in (0,.2,.4):tracker.update(t,observation('이전캐릭터'))
            pending=tracker.update(.6,{signal:True})
            self.assertTrue(pending['recordingAllowed'])
            self.assertEqual(pending['actions'],[])
            self.assertEqual(pending['currentName'],'이전캐릭터')
            self.assertTrue(tracker.update(.8,{})['recordingAllowed'])
            self.assertTrue(tracker.update(.85,dict(switchDialog=True))['recordingAllowed'])
            pending=tracker.update(.9,dict(switchLoading=True))
            self.assertFalse(pending['recordingAllowed'])
            self.assertEqual(pending['actions'],[dict(type='suspend')])
            tracker.update(.95,{})
            for t in (1,1.2,1.4):result=tracker.update(t,observation('새캐릭터'))
            self.assertEqual(result['currentName'],'새캐릭터')
            self.assertTrue(result['recordingAllowed'])

    def test_switch_title_detected_even_without_name_or_menu_detection(self):
        from unittest.mock import Mock,patch
        import numpy as np
        from beatrice.character_vision import CharacterVision
        vision=CharacterVision.__new__(CharacterVision)
        vision.model=Mock()
        vision.model.names={0:'current_name',1:'target_name',2:'switch_dialog'}
        vision.model.predict.return_value=[Mock(boxes=[])]
        vision.menu_template=np.zeros((425,880),dtype=np.uint8)
        vision.reader=Mock()
        vision.reader.recognize.return_value=[(None,'다른 캐릭터 바로 접속',.99)]
        frame=np.zeros((1440,3440,3),dtype=np.uint8)
        with patch('cv2.matchTemplate',return_value=np.array([[0.]])),patch(
            'beatrice.character_vision.trim_name_line',return_value=np.zeros((30,200,3),dtype=np.uint8)):
            result=vision.analyze(frame)
        self.assertTrue(result['switchDialog'])
        self.assertFalse(result['normalMenu'])

    def test_level_prefix_removed_without_changing_name(self):
        from beatrice.character_vision import name_from_line
        for length in range(2,13):
            name='가'*length
            for prefix in ('Lv.70 ', 'Lv.70', 'lv 70 ', 'LV . 70 '):
                self.assertEqual(name_from_line(prefix+name,True),name)
        self.assertEqual(name_from_line('Lv.70123기사',True),'123기사')
        self.assertEqual(name_from_line('Lv.70 MyLv70',True),'MyLv70')
        self.assertEqual(name_from_line('Lv70기사',False),'Lv70기사')
        for text in ('Lv.70', 'Lv.70 '+'가'*13, 'Lv.xx 기사', '기사', '기사 Lv.70'):
            self.assertIsNone(name_from_line(text,True))

    def test_long_name_crop_keeps_separated_level_prefix(self):
        import cv2
        import numpy as np
        from unittest.mock import Mock
        from beatrice.character_vision import CharacterVision
        frame=np.zeros((40,600,3),dtype=np.uint8)
        cv2.putText(frame,'Lv.70',(10,28),cv2.FONT_HERSHEY_SIMPLEX,.7,(40,190,220),2)
        # 긴 이름 군집이 레벨 군집보다 커도 레벨을 버리지 않아야 합니다.
        for x in range(105,405,25):cv2.rectangle(frame,(x,9),(x+18,29),(240,240,240),-1)
        vision=CharacterVision.__new__(CharacterVision);vision.reader=Mock()
        vision.reader.recognize.return_value=[(None,'Lv.70 가나다라마바사아자차카타',.99)]
        vision.read_name(frame,[0,0,600,40],includes_level=True)
        self.assertGreater(vision.reader.recognize.call_args_list[0].args[0].shape[1],380)

    def test_ocr_compares_names_after_removing_level_and_preserves_raw(self):
        from unittest.mock import Mock,patch
        import numpy as np
        from beatrice.character_vision import CharacterVision
        vision=CharacterVision.__new__(CharacterVision)
        vision.reader=Mock()
        vision.reader.recognize.side_effect=[[(None,'Lv.70 가나다라마바',.99)],[(None,'lv 70 가나다라마바',.98)]]
        with patch('beatrice.character_vision.trim_name_line',side_effect=lambda crop,**kwargs:crop):
            read=vision.read_name(np.zeros((40,550,3),dtype=np.uint8),[0,0,550,40],includes_level=True)
        self.assertEqual(read['accepted']['text'],'가나다라마바')
        self.assertEqual(read['raw'][0]['text'],'Lv.70 가나다라마바')

    def test_trim_keeps_long_text_run_and_removes_distant_background(self):
        import numpy as np
        from beatrice.character_vision import trim_name_line
        for length in (2,12):
            crop=np.zeros((32,550,3),dtype=np.uint8)
            crop[4:7,10:13]=255  # 고립된 배경 반사
            for i in range(length+4):  # 레벨과 이름을 하나의 줄로 처리
                crop[7:25,100+i*20:115+i*20]=255
            trimmed=trim_name_line(crop)
            self.assertIsNotNone(trimmed)
            self.assertGreaterEqual(trimmed.shape[1],(length+3)*20+15)
            self.assertLess(trimmed.shape[1],550)
        self.assertIsNone(trim_name_line(np.zeros((32,550,3),dtype=np.uint8)))

    def test_name_length_limits(self):
        for length in range(2,13):
            name='가'*length
            self.assertEqual(valid_name(dict(text=name,confidence=.99)),name)
        for length in (1,13,16):
            self.assertIsNone(valid_name(dict(text='가'*length,confidence=.99)))

    def test_short_detections_do_not_limit_name_line_width(self):
        from beatrice.character_vision import name_line_box
        current=name_line_box('current_name',[974,897,1044,925])
        target=name_line_box('target_name',[1680,655,1760,688])
        self.assertLess(current[0],900)  # 레벨과 길어진 이름의 왼쪽까지 포함
        for box in (current,target):
            self.assertGreaterEqual(box[2]-box[0],12*28)
        self.assertEqual(name_line_box('current_name',[974,897,1330,925])[2],1330)

    def test_unseen_name_preview_then_confirm(self):
        name='처음보는캐릭터123'
        result=self.feed(name)
        self.assertEqual(result['previewName'],name)
        self.assertFalse(result['recordingAllowed'])
        result=self.feed(name,count=2)
        self.assertEqual(result['currentName'],name)
        self.assertTrue(result['recordingAllowed'])

    def test_menu_reads_full_name_line_without_yolo_detection(self):
        from unittest.mock import Mock,patch
        import numpy as np
        from beatrice.character_vision import CharacterVision
        vision=CharacterVision.__new__(CharacterVision)
        vision.model=Mock()
        vision.model.names={0:'current_name',1:'target_name',2:'switch_dialog'}
        vision.model.predict.return_value=[Mock(boxes=[])]
        vision.menu_template=np.zeros((425,880),dtype=np.uint8)
        vision.read_name=Mock(return_value=dict(accepted=dict(text='처음보는캐릭터123',confidence=.99)))
        frame=np.zeros((1440,3440,3),dtype=np.uint8)
        with patch('cv2.matchTemplate',return_value=np.array([[.99]])):
            result=vision.analyze(frame)
        self.assertEqual(result['currentName']['text'],'처음보는캐릭터123')
        self.assertEqual(vision.read_name.call_args.args[1],[760,897,1310,925])
        self.assertTrue(vision.read_name.call_args.kwargs['includes_level'])
        vision.read_name.reset_mock()
        with patch('cv2.matchTemplate',return_value=np.array([[.2]])):
            result=vision.analyze(frame)
        self.assertIsNone(result['currentName'])
        vision.read_name.assert_not_called()

    def setUp(self):
        self.tracker=CharacterTracker();self.t=-.5

    def feed(self,name=None,dialog=False,target=None,confidence=.95,count=1,loading=False,menu=False):
        for _ in range(count):
            self.t+=.5
            obs=observation(name,dialog,target,confidence)
            obs.update(switchLoading=loading,normalMenu=menu)
            result=self.tracker.update(self.t,obs)
        return result

    def test_initial_name_requires_consecutive_readings(self):
        self.assertFalse(self.feed('후이수',count=2)['recordingAllowed'])
        self.assertTrue(self.feed('후이수')['recordingAllowed'])
        self.assertTrue(self.feed()['recordingAllowed'])  # 메뉴를 닫고 플레이

    def test_target_is_not_current_and_cancel_does_not_switch(self):
        self.feed('테베체',count=3)
        result=self.feed('테베체',True,'힐레우스')
        self.assertEqual(result['currentName'],'테베체')
        self.assertTrue(result['recordingAllowed'])
        self.assertEqual(result['actions'],[])
        result=self.feed('테베체',count=6,menu=True)
        self.assertEqual(result['currentName'],'테베체')
        self.assertTrue(result['recordingAllowed'])
        self.assertIsNone(result['pendingName'])
        self.assertTrue(self.feed(loading=True)['recordingAllowed'])  # 취소 후 맵 로딩

    def test_success_requires_current_after_gap(self):
        self.feed('후이수',count=3)
        self.feed('후이수',True,'테베체')
        self.assertFalse(self.feed('후이수',loading=True,count=3)['recordingAllowed'])
        self.assertFalse(self.feed('후이수',menu=True,count=3)['recordingAllowed'])
        self.feed(count=3)
        result=self.feed('테베체',count=3)
        self.assertEqual(result['currentName'],'테베체')
        self.assertTrue(result['recordingAllowed'])

    def test_unknown_target_still_blocks(self):
        self.feed('후이수',count=3)
        self.assertTrue(self.feed('후이수',True,None)['recordingAllowed'])
        self.assertFalse(self.feed('후이수',loading=True)['recordingAllowed'])
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
            self.assertEqual(recording.token,old)
            bridge.apply(self.feed('후이수',loading=True))
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
