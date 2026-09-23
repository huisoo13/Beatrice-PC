import unittest
from unittest.mock import Mock
import numpy as np
from beatrice.ui_regions import UIRegionDetector,load_config,dungeon_location
from beatrice.character_vision import CharacterVision
from beatrice.character import CharacterTracker


def detected(coords):return dict(status='detected',xyxy=coords,confidence=.99)


class UIRegionTests(unittest.TestCase):
    def test_split_models_skip_dungeon_when_character_ui_is_present(self):
        detector=UIRegionDetector.__new__(UIRegionDetector)
        detector.character_detector=Mock();detector.dungeon_detector=Mock()
        detector.dungeon_detector.config={'classes':['dungeon_panel','gate_panel']}
        character={k:dict(status='missing',candidates=[]) for k in ('game_menu','current_name_line','switch_dialog','target_name_line','loading_indicator')}
        detector.character_detector.locate.return_value=character
        detector.dungeon_detector.locate.return_value={'dungeon_panel':detected([0,36,360,240]),'gate_panel':detected([32,112,352,224])}
        detector.locate(self.frame)
        detector.dungeon_detector.locate.assert_called_once()
        detector.dungeon_detector.locate.reset_mock()
        character['game_menu']=detected([780,320,2820,1050])
        result=detector.locate(self.frame)
        detector.dungeon_detector.locate.assert_not_called()
        self.assertEqual(result['dungeon_panel']['status'],'missing')

    def test_name_cache_never_counts_as_fresh_confirmation_and_clears_on_dialog(self):
        self.vision.read_menu_name=Mock(return_value=dict(accepted=dict(text='현재캐릭터',confidence=.99),raw=[],status='accepted'))
        for t in (0,.5,1):
            result=self.vision.analyze_detected(self.frame,self.regions,seconds=t)
            self.assertIsNotNone(result['currentName'])
        self.assertEqual(self.vision.read_menu_name.call_count,3)
        result=self.vision.analyze_detected(self.frame,self.regions,seconds=1.5,confirmed_name='현재캐릭터')
        self.assertIsNone(result['currentName'])
        self.assertEqual(self.vision.read_menu_name.call_count,3)
        self.vision.analyze_detected(self.frame,self.regions,seconds=3,confirmed_name='현재캐릭터')
        self.assertEqual(self.vision.read_menu_name.call_count,4)
        self.regions['switch_dialog']=detected([800,400,1300,700])
        self.vision.analyze_detected(self.frame,self.regions,seconds=3.1,confirmed_name='현재캐릭터')
        self.regions['switch_dialog']=dict(status='missing')
        self.vision.analyze_detected(self.frame,self.regions,seconds=3.2,confirmed_name='현재캐릭터')
        self.assertEqual(self.vision.read_menu_name.call_count,5)

    def test_duplicate_boxes_merge_but_separate_regions_remain(self):
        from beatrice.ui_regions import suppress_duplicates
        boxes=[dict(xyxy=[800,896,1160,932],confidence=.98),
               dict(xyxy=[820,903,1165,935],confidence=.91),
               dict(xyxy=[1800,896,2160,932],confidence=.9)]
        self.assertEqual(suppress_duplicates(boxes),[boxes[0],boxes[2]])
    def setUp(self):
        self.frame=np.zeros((1440,3440,3),dtype=np.uint8)
        self.regions={name:dict(status='missing') for name in load_config()['classes']}
        self.regions.update(game_menu=detected([300,200,1800,1100]),
                            current_name_line=detected([350,800,700,840]))
        self.vision=CharacterVision.__new__(CharacterVision)
        self.vision.read_name=Mock(return_value=dict(accepted=dict(text='현재캐릭터',confidence=.99),status='accepted'))
        self.vision.read_loading_crop=Mock(return_value=dict(visible=True,iconVisible=True,raw=[]))
        self.vision.read_loading=Mock(return_value=dict(visible=False,iconVisible=False,raw=[]))

    def test_full_frame_model_called_once_for_all_classes(self):
        model=Mock();model.names=dict(enumerate(load_config()['classes']))
        model.predict.return_value=[Mock(boxes=[Mock(cls=[1],conf=[.99],xyxy=np.array([[350,800,700,840]]))])]
        result=UIRegionDetector(model=model).locate(self.frame)
        model.predict.assert_called_once()
        self.assertIs(model.predict.call_args.args[0],self.frame)
        self.assertEqual(result['current_name_line']['status'],'detected')
        self.assertEqual(result['switch_dialog']['status'],'missing')

    def test_current_name_uses_detected_original_region(self):
        out=self.vision.analyze_detected(self.frame,self.regions)
        self.assertTrue(out['normalMenu'])
        self.assertEqual(out['currentName']['text'],'현재캐릭터')
        self.assertEqual(self.vision.read_name.call_args.args[1],[350,800,700,840])
        self.assertTrue(self.vision.read_name.call_args.kwargs['includes_level'])

    def test_foreign_name_and_ambiguous_popup_are_not_read_as_current(self):
        self.regions['current_name_line']=detected([2000,800,2300,840])
        self.assertIsNone(self.vision.analyze_detected(self.frame,self.regions)['currentName'])
        self.regions['current_name_line']=detected([350,800,700,840])
        self.regions['switch_dialog']=dict(status='ambiguous')
        out=self.vision.analyze_detected(self.frame,self.regions)
        self.assertFalse(out['normalMenu']);self.assertIsNone(out['currentName'])
        self.vision.read_name.assert_not_called()

    def test_target_requires_popup_containment(self):
        self.regions['switch_dialog']=detected([800,400,1300,700])
        self.regions['target_name_line']=detected([900,490,1200,530])
        out=self.vision.analyze_detected(self.frame,self.regions)
        self.assertTrue(out['switchDialog']);self.assertIsNotNone(out['targetName'])
        self.assertIsNone(out['currentName'])
        self.regions['target_name_line']=detected([2000,490,2300,530])
        self.assertIsNone(self.vision.analyze_detected(self.frame,self.regions)['targetName'])

    def test_popup_loading_new_character_sequence(self):
        tracker=CharacterTracker()
        for t in (0,.2,.4):tracker.update(t,self.vision.analyze_detected(self.frame,self.regions))
        self.regions['switch_dialog']=detected([800,400,1300,700])
        result=tracker.update(.6,self.vision.analyze_detected(self.frame,self.regions))
        self.assertTrue(result['recordingAllowed'])
        self.regions['switch_dialog']=dict(status='missing')
        self.regions['loading_indicator']=detected([2500,1100,2950,1270])
        out=self.vision.analyze_detected(self.frame,self.regions)
        self.assertIsNone(out['currentName'])
        result=tracker.update(.8,out)
        self.assertFalse(result['recordingAllowed']);self.assertEqual(result['actions'],[dict(type='suspend')])
        self.assertEqual(self.vision.read_loading_crop.call_args.args[0].shape,(170,450,3))
        self.regions['loading_indicator']=dict(status='missing')
        self.vision.read_name.return_value=dict(accepted=dict(text='새캐릭터',confidence=.99),status='accepted')
        for t in (1,1.2,1.4):result=tracker.update(t,self.vision.analyze_detected(self.frame,self.regions))
        self.assertTrue(result['recordingAllowed']);self.assertEqual(result['currentName'],'새캐릭터')

    def test_gate_panel_requires_matching_dungeon_parent(self):
        self.regions['dungeon_panel']=detected([200,100,600,400])
        self.regions['gate_panel']=detected([220,250,580,350])
        result=dungeon_location(self.regions,self.frame.shape)
        self.assertEqual(result['status'],'detected')
        self.assertEqual(result['regions']['gates'],[220,250,580,350])
        self.regions['gate_panel']=detected([2200,250,2580,350])
        self.assertNotEqual(dungeon_location(self.regions,self.frame.shape)['status'],'detected')

    def test_wrong_model_cannot_enable_integrated_mode(self):
        model=Mock();model.names={0:'current_name',1:'target_name',2:'switch_dialog'}
        with self.assertRaises(ValueError):UIRegionDetector(model=model)

    def test_gold_portrait_decoration_does_not_merge_level_text_rows(self):
        import cv2
        frame=np.zeros((1440,3440,3),dtype=np.uint8)
        cv2.line(frame,(650,830),(720,925),(30,190,220),4)
        cv2.putText(frame,'Lv.70',(850,919),cv2.FONT_HERSHEY_SIMPLEX,.7,(30,190,220),2)
        vision=CharacterVision.__new__(CharacterVision)
        def read(image,box,includes_level=False):
            valid=box[1]<=904 and box[3]>=920 and box[3]-box[1]<40
            return dict(accepted=dict(text='힐레우스',confidence=.99) if valid else None,raw=[],status='test')
        vision.read_name=Mock(side_effect=read)
        result=vision.read_menu_name(frame,[780,320,2820,1050])
        self.assertEqual(result['accepted']['text'],'힐레우스')

    def test_menu_recovery_does_not_replace_dungeon_results(self):
        def model(boxes):
            value=Mock();value.names=dict(enumerate(load_config()['classes']))
            value.predict.return_value=[Mock(boxes=[Mock(cls=[kind],conf=[.99],xyxy=np.array([coords])) for kind,coords in boxes])]
            return value
        primary=model([(5,[10,40,360,240])])
        recovery=model([(0,[780,320,2820,1050]),(1,[780,893,1210,932]),(5,[20,50,370,250])])
        detector=UIRegionDetector(model=primary,recovery_model=recovery)
        result=detector.locate(self.frame)
        self.assertEqual(result['game_menu']['source'],'menu_recovery_yolo')
        self.assertEqual(result['dungeon_panel']['xyxy'],[10,40,360,240])
        primary.predict.return_value=[Mock(boxes=[Mock(cls=[0],conf=[.99],xyxy=np.array([[780,320,2820,1050]]))])]
        recovery.predict.reset_mock()
        detector.locate(self.frame)
        recovery.predict.assert_not_called()


if __name__=='__main__':unittest.main()
