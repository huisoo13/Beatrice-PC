import unittest
from unittest.mock import Mock
import numpy as np
from beatrice.ui_regions import UIRegionDetector,load_config,dungeon_location
from beatrice.character_vision import CharacterVision
from beatrice.character import CharacterTracker


def detected(coords):return dict(status='detected',xyxy=coords,confidence=.99)


class UIRegionTests(unittest.TestCase):
    def test_class_threshold_does_not_lower_other_detection_thresholds(self):
        config=dict(classes=['current_name_line','target_name_line'],confidence=.7,imageSize=1280,classConfidence={'target_name_line':.65})
        model=Mock();model.names={0:'current_name_line',1:'target_name_line'}
        model.predict.return_value=[Mock(boxes=[Mock(cls=[i],conf=[.68],xyxy=np.array([[10,20,100,40]])) for i in (0,1)])]
        regions=UIRegionDetector(config,model=model).locate(np.zeros((100,200,3),dtype=np.uint8))
        self.assertEqual(regions['current_name_line']['status'],'missing')
        self.assertEqual(regions['target_name_line']['status'],'detected')

    def test_element_yolo_receives_only_detected_parent_and_returns_original_coordinates(self):
        detector=UIRegionDetector.__new__(UIRegionDetector)
        detector.model=object()
        detector.element_detector=Mock();detector.element_detector.config={'classes':['dungeon_name']}
        detector.element_detector.locate.return_value={'dungeon_name':dict(status='detected',candidates=[dict(xyxy=[10,20,250,50],confidence=.99)])}
        frame=np.zeros((1080,1920,3),dtype=np.uint8)
        for parent in ([720,350,1120,580],[100,600,500,830]):
            detector._locate=Mock(return_value=dict(dungeon_panel=detected(parent)))
            regions=detector.locate(frame)
            self.assertEqual(detector.element_detector.locate.call_args.args[0].shape,(230,400,3))
            self.assertEqual(regions['dungeon_name']['xyxy'],[parent[0]+10,parent[1]+20,parent[0]+250,parent[1]+50])
        detector.element_detector.reset_mock();detector._locate.return_value={'dungeon_panel':{'status':'missing'}}
        self.assertEqual(detector.locate(frame)['dungeon_name']['status'],'missing')
        detector.element_detector.locate.assert_not_called()

    def test_overlapping_text_predictions_merge_but_separate_lines_stay_ambiguous(self):
        from beatrice.ui_regions import merge_text_duplicates
        values=[dict(xyxy=[73,94,279,111],confidence=.99),dict(xyxy=[58,98,291,124],confidence=.97),
                dict(xyxy=[60,150,290,180],confidence=.95)]
        result=merge_text_duplicates(values)
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['xyxy'],[58,94,291,124])
        self.assertEqual(values[0]['xyxy'],[73,94,279,111])
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
        self.vision.read_name=Mock(return_value=dict(accepted=dict(text='현재캐릭터',confidence=.99),raw=[],status='accepted'))
        for t in (0,.5,1):
            result=self.vision.analyze_detected(self.frame,self.regions,seconds=t)
            self.assertIsNotNone(result['currentName'])
        self.assertEqual(self.vision.read_name.call_count,3)
        result=self.vision.analyze_detected(self.frame,self.regions,seconds=1.5,confirmed_name='현재캐릭터')
        self.assertIsNone(result['currentName'])
        self.assertEqual(self.vision.read_name.call_count,3)
        self.vision.analyze_detected(self.frame,self.regions,seconds=3,confirmed_name='현재캐릭터')
        self.assertEqual(self.vision.read_name.call_count,4)
        self.regions['switch_dialog']=detected([800,400,1300,700])
        self.vision.analyze_detected(self.frame,self.regions,seconds=3.1,confirmed_name='현재캐릭터')
        self.regions['switch_dialog']=dict(status='missing')
        self.vision.analyze_detected(self.frame,self.regions,seconds=3.2,confirmed_name='현재캐릭터')
        self.assertEqual(self.vision.read_name.call_count,5)

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

    def test_missing_loading_detection_never_reads_window_corner(self):
        self.vision.analyze_detected(self.frame,self.regions)
        self.vision.read_loading_crop.assert_not_called()
        self.assertFalse(hasattr(self.vision,'read_loading'))

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

    def test_direct_text_requires_matching_parent(self):
        self.regions.update(dungeon_panel=detected([200,100,600,400]),
            dungeon_name=detected([240,130,550,160]),difficulty=detected([280,180,500,210]))
        result=dungeon_location(self.regions,self.frame.shape)
        self.assertEqual(result['status'],'detected')
        self.assertEqual(result['regions']['dungeonName'],[240,130,550,160])
        self.regions['dungeon_name']=detected([2200,130,2550,160])
        self.assertNotEqual(dungeon_location(self.regions,self.frame.shape)['status'],'detected')

    def test_wrong_model_cannot_enable_integrated_mode(self):
        model=Mock();model.names={0:'current_name',1:'target_name',2:'switch_dialog'}
        with self.assertRaises(ValueError):UIRegionDetector(model=model)

    def test_menu_without_name_box_does_not_guess_portrait_coordinates(self):
        self.regions['current_name_line']=dict(status='missing')
        out=self.vision.analyze_detected(self.frame,self.regions)
        self.assertIsNone(out['currentName'])
        self.vision.read_name.assert_not_called()

if __name__=='__main__':unittest.main()
