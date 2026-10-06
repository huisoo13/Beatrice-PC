import unittest
from beatrice.character import CharacterTracker

class InitialLoginTests(unittest.TestCase):
    def setUp(self):
        self.tracker=CharacterTracker(max_gap=5);self.t=0
    def feed(self,**obs):
        self.t+=1
        return self.tracker.update(self.t,obs)
    def select(self,name='후이수'):
        for _ in range(3):result=self.feed(characterSelection=True,selectedName=dict(text=name,confidence=.99))
        return result
    def test_initial_login_requires_real_loading_then_three_absent_frames(self):
        self.feed(serverSelection=True);result=self.select()
        self.assertFalse(result['recordingAllowed'])
        for _ in range(4):self.assertFalse(self.feed(loginLoadingAbsent=True)['recordingAllowed'])
        self.feed(loginLoading=True)
        for _ in range(2):self.assertFalse(self.feed(loginLoadingAbsent=True)['recordingAllowed'])
        result=self.feed(loginLoadingAbsent=True)
        self.assertEqual(result['currentName'],'후이수');self.assertTrue(result['recordingAllowed'])
        self.assertEqual(result['actions'],[dict(type='confirmed',name='후이수')])
    def test_loading_or_selection_ambiguity_resets_exit_count(self):
        self.select();self.feed(loginLoading=True)
        for obs in ({},{'selectionUncertain':True,'loginLoadingAbsent':True},{'loginLoading':True}):
            self.feed(loginLoadingAbsent=True);self.feed(**obs)
            self.assertFalse(self.feed(loginLoadingAbsent=True)['recordingAllowed'])
        self.feed(loginLoadingAbsent=True)
        self.assertTrue(self.feed(loginLoadingAbsent=True)['recordingAllowed'])
    def test_cancel_to_selection_and_change_target(self):
        self.select();self.feed(loginLoading=True)
        self.select('테베체')
        for _ in range(3):self.assertFalse(self.feed(loginLoadingAbsent=True)['recordingAllowed'])
        self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertEqual(result['currentName'],'테베체')
    def test_server_return_clears_old_character(self):
        for _ in range(3):self.feed(currentName=dict(text='후이수',confidence=.99))
        result=self.feed(serverSelection=True)
        self.assertFalse(result['recordingAllowed']);self.assertIsNone(result['currentName'])
        self.assertEqual(result['actions'],[dict(type='suspend')])
    def test_menu_fallback_after_missing_loading(self):
        self.select()
        for _ in range(3):result=self.feed(normalMenu=True,currentName=dict(text='테베체',confidence=.99))
        self.assertTrue(result['recordingAllowed']);self.assertEqual(result['currentName'],'테베체')
    def test_map_loading_does_not_change_confirmed_character(self):
        for _ in range(3):self.feed(currentName=dict(text='후이수',confidence=.99))
        result=self.feed(loginLoading=True)
        self.assertEqual(result['status'],'confirmed');self.assertTrue(result['recordingAllowed'])
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertEqual(result['currentName'],'후이수')
    def test_unknown_target_never_guessed(self):
        self.feed(characterSelection=True);self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertFalse(result['recordingAllowed'])
    def test_changed_card_without_name_discards_previous_target(self):
        for _ in range(3):
            self.feed(characterSelection=True,selectedCard=[10,20,110,60],selectedName=dict(text='후이수',confidence=.99))
        result=self.feed(characterSelection=True,selectedCard=[120,20,220,60])
        self.assertIsNone(result['pendingName']);self.assertIsNone(result['previewName'])
        self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertIsNone(result['currentName']);self.assertFalse(result['recordingAllowed'])
    def test_same_card_jitter_and_hidden_name_preserves_target(self):
        for _ in range(3):
            self.feed(characterSelection=True,selectedCard=[10,20,110,60],selectedName=dict(text='후이수',confidence=.99))
        result=self.feed(characterSelection=True,selectedCard=[12,18,108,62])
        self.assertEqual(result['pendingName'],'후이수')
        self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertEqual(result['currentName'],'후이수')
    def test_new_card_requires_its_own_confirmations(self):
        for _ in range(3):
            self.feed(characterSelection=True,selectedCard=[10,20,110,60],selectedName=dict(text='후이수',confidence=.99))
        for i in range(3):
            result=self.feed(characterSelection=True,selectedCard=[120,20,220,60],selectedName=dict(text='힐레우스',confidence=.99))
            self.assertEqual(result['pendingName'],'힐레우스' if i==2 else None)
        self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertEqual(result['currentName'],'힐레우스')
    def test_password_overlay_does_not_erase_stable_selection(self):
        self.select()
        for _ in range(5):self.feed(characterSelection=True)
        self.feed(characterSelection=True,selectedName=dict(text='후이수',confidence=.99))
        self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertEqual(result['currentName'],'후이수')
        self.assertTrue(result['recordingAllowed'])
    def test_selected_card_and_contained_name_do_not_require_start_button(self):
        import numpy as np
        from unittest.mock import Mock
        from beatrice.initial_login import observe_login
        def detected(box):return dict(status='detected',xyxy=box)
        regions={'selected_character_card':detected([10,10,100,60]),
                 'selected_character_name':detected([20,25,70,40]),
                 'game_start_button':detected([30,75,100,90])}
        vision=Mock();vision.read_name.return_value=dict(accepted=dict(text='후이수',confidence=.99))
        frame=np.zeros((100,150,3),dtype=np.uint8)
        self.assertEqual(observe_login(frame,regions,vision)['selectedName']['text'],'후이수')
        regions['selected_character_name']=detected([105,25,140,40]);vision.reset_mock()
        self.assertIsNone(observe_login(frame,regions,vision)['selectedName']);vision.read_name.assert_not_called()
        del regions['game_start_button']
        self.assertFalse(observe_login(frame,regions,vision)['characterSelection'])
        regions['selected_character_name']=detected([20,25,70,40])
        self.assertEqual(observe_login(frame,regions,vision)['selectedName']['text'],'후이수')
        regions['game_menu']=detected([0,0,150,100]);vision.reset_mock()
        self.assertFalse(observe_login(frame,regions,vision)['characterSelection'])
        vision.read_name.assert_not_called();del regions['game_menu']
        del regions['selected_character_card'];vision.reset_mock()
        self.assertFalse(observe_login(frame,regions,vision)['characterSelection'])
        vision.read_name.assert_not_called()
    def test_long_absence_and_server_return_discard_target(self):
        self.select();self.t+=181
        self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertFalse(result['recordingAllowed'])
        self.select();self.feed(serverSelection=True);self.feed(loginLoading=True)
        for _ in range(3):result=self.feed(loginLoadingAbsent=True)
        self.assertFalse(result['recordingAllowed'])
    def test_single_button_cannot_suppress_dungeon_detection(self):
        import numpy as np
        from unittest.mock import Mock
        from beatrice.ui_regions import UIRegionDetector
        detector=UIRegionDetector.__new__(UIRegionDetector)
        detector.character_detector=Mock();detector.dungeon_detector=Mock()
        detector.dungeon_detector.config={'classes':['dungeon_panel']}
        detector.dungeon_detector.locate.return_value={}
        button=dict(status='detected',xyxy=[0,70,100,90])
        detector.character_detector.locate.return_value={'game_start_button':button}
        frame=np.zeros((100,150,3),dtype=np.uint8)
        detector.locate(frame);detector.dungeon_detector.locate.assert_called_once()
        detector.dungeon_detector.locate.reset_mock()
        detector.character_detector.locate.return_value={
            'selected_character_card':dict(status='detected',xyxy=[10,10,100,60]),
            'selected_character_name':dict(status='detected',xyxy=[20,25,70,40])}
        result=detector.locate(frame)
        detector.dungeon_detector.locate.assert_not_called()
        self.assertEqual(result['dungeon_panel']['reason'],'character_ui_visible')
    def test_same_model_rechecks_detected_card_and_maps_name_to_screen(self):
        import numpy as np
        from unittest.mock import Mock
        from beatrice.ui_regions import UIRegionDetector
        detector=UIRegionDetector.__new__(UIRegionDetector)
        detector.model=object();detector.config={'classes':['selected_character_card','selected_character_name']}
        for x,y in ((10,20),(170,140)):
            detector._locate=Mock(side_effect=[
                {'selected_character_card':dict(status='detected',xyxy=[x,y,x+100,y+40])},
                {'selected_character_name':dict(status='detected',candidates=[dict(xyxy=[20,10,80,25],confidence=.99)])}])
            result=detector.locate(np.zeros((300,400,3),dtype=np.uint8))
            self.assertEqual(detector._locate.call_args.args[0].shape,(40,100,3))
            self.assertEqual(result['selected_character_name']['xyxy'],[x+20,y+10,x+80,y+25])

    def test_card_retry_failure_preserves_only_contained_full_frame_name(self):
        import numpy as np
        from unittest.mock import Mock
        from beatrice.ui_regions import UIRegionDetector
        detector=UIRegionDetector.__new__(UIRegionDetector)
        detector.model=object();detector.config={'classes':['selected_character_card','selected_character_name']}
        for box,expected in (([30,30,80,45],'detected'),([150,30,180,45],'missing')):
            item=dict(status='detected',xyxy=box,confidence=.9)
            missing={'selected_character_name':dict(status='missing',candidates=[])}
            detector._locate=Mock(side_effect=[{'selected_character_card':dict(status='detected',xyxy=[10,20,110,60]),
                                               'selected_character_name':item},missing,missing])
            result=detector.locate(np.zeros((100,200,3),dtype=np.uint8))
            self.assertEqual(result['selected_character_name']['status'],expected)

    def test_dimmed_detected_name_is_read_but_empty_dark_crop_is_not(self):
        import cv2,numpy as np
        from unittest.mock import Mock
        from beatrice.character_vision import CharacterVision
        reader=Mock();reader.recognize.return_value=[(None,'Tester',.99)]
        vision=CharacterVision(reader=reader)
        frame=np.zeros((100,240,3),dtype=np.uint8)
        cv2.putText(frame,'Tester',(35,55),cv2.FONT_HERSHEY_SIMPLEX,.9,(85,85,85),2)
        result=vision.read_name(frame,[30,30,150,60])
        self.assertEqual(result['accepted']['text'],'Tester')
        self.assertEqual(reader.recognize.call_count,2)
        reader.reset_mock()
        result=vision.read_name(np.zeros_like(frame),[30,30,150,60])
        self.assertEqual(result['status'],'no_text_pixels');reader.recognize.assert_not_called()

    def test_missing_animated_marker_is_not_loading_exit_in_same_scene(self):
        import numpy as np
        from unittest.mock import Mock
        from beatrice.character_vision import CharacterVision
        from beatrice.initial_login import CLASSES
        vision=CharacterVision(reader=Mock())
        regions={k:dict(status='missing',candidates=[]) for k in
                 CLASSES+['game_menu','switch_dialog','loading_indicator']}
        regions['loading_progress']=dict(status='detected',xyxy=[20,70,40,85])
        loading=np.full((100,160,3),(30,50,100),dtype=np.uint8)
        self.assertTrue(vision.analyze_detected(loading,regions)['loginLoading'])
        regions['loading_progress']=dict(status='missing',candidates=[])
        for _ in range(5):
            self.assertFalse(vision.analyze_detected(loading,regions)['loginLoadingAbsent'])
        changed_tip=loading.copy();changed_tip[10:20,10:120]=220
        self.assertFalse(vision.analyze_detected(changed_tip,regions)['loginLoadingAbsent'])
        self.assertFalse(vision.analyze_detected(np.zeros_like(loading),regions)['loginLoadingAbsent'])
        world=np.full_like(loading,200)
        self.assertTrue(vision.analyze_detected(world,regions)['loginLoadingAbsent'])

if __name__=='__main__':unittest.main()
