import unittest,copy
from unittest.mock import Mock
import numpy as np
from beatrice.dungeon_observer import DungeonObserver
from beatrice.ui_regions import detected_gates

def box(coords):return dict(status='detected',xyxy=coords,confidence=.99)

class DungeonObserverTests(unittest.TestCase):
    def setUp(self):
        self.frame=np.zeros((1080,1920,3),dtype=np.uint8)
        self.regions=dict(dungeon_panel=box([600,300,1000,530]),gate_panel=box([630,410,900,490]),
            dungeon_name=box([650,320,950,350]),difficulty=box([700,360,850,390]),
            gate_in_progress=box([660,420,700,480]),gate_not_started=box([800,420,840,480]))
        self.ocr=Mock(engine='paddle');self.ocr.analyze_detected.side_effect=self.read
        self.observer=DungeonObserver(self.ocr)
    def read(self,frame,location,gates,**kwargs):
        valid=location['status']=='detected'
        return dict(dungeonVisible=valid,dungeonName=dict(text='새 던전',confidence=.99) if valid else None,
                    difficulty=dict(text='하드',confidence=.99) if valid else None)
    def test_text_and_icons_use_actual_translated_geometry(self):
        obs,gates=self.observer.analyze(self.frame,self.regions,0)
        self.assertTrue(obs['dungeonVisible'])
        self.assertEqual([g['xyxy'] for g in gates],[[660,420,700,480],[800,420,840,480]])
        self.assertEqual(self.ocr.analyze_detected.call_args.args[1]['regions']['dungeonName'],[650,320,950,350])
    def test_missing_region_never_reuses_previous_coordinates(self):
        self.observer.analyze(self.frame,self.regions,0);self.ocr.reset_mock()
        obs,gates=self.observer.analyze(self.frame,{},1)
        self.assertFalse(obs['dungeonVisible']);self.assertFalse(obs['currentRaidPanel']);self.assertEqual(gates,[])
        self.ocr.analyze_detected.assert_not_called()
    def test_missing_text_never_reads_a_panel_relative_region(self):
        self.regions.pop('dungeon_name')
        obs,gates=self.observer.analyze(self.frame,self.regions,0)
        self.assertFalse(obs['dungeonVisible']);self.assertEqual(gates,[])
    def test_missing_icons_can_verify_text_without_inventing_icons(self):
        self.regions.pop('gate_panel')
        obs,gates=self.observer.analyze(self.frame,self.regions,0)
        self.assertTrue(obs['dungeonVisible']);self.assertTrue(obs['currentRaidPanel']);self.assertEqual(gates,[])
    def test_banner_alone_and_blocked_menu_never_supply_raid_context(self):
        for regions,blocked in (({'quest_complete_banner':box([600,10,1000,100])},False),(self.regions,True)):
            obs,gates=self.observer.analyze(self.frame,regions,0,blocked)
            self.assertFalse(obs['dungeonVisible']);self.assertFalse(obs['currentRaidPanel']);self.assertEqual(gates,[])
    def test_blocked_but_visible_panel_is_display_only_presence(self):
        obs, gates = self.observer.analyze(self.frame, self.regions, 0, True)
        self.assertTrue(obs['raidPanelVisible'])
        self.assertFalse(obs['currentRaidPanel'])
        self.assertEqual(gates, [])

    def test_gateless_requires_direct_title_and_excludes_conflicting_panel(self):
        regions=dict(gateless_raid_panel=box([600,300,1000,400]),gateless_title=box([620,330,970,370]))
        self.ocr.analyze_gateless.return_value=self.read(None,{'status':'detected'},[])
        obs,gates=self.observer.analyze(self.frame,regions,0)
        self.assertTrue(obs['dungeonVisible']);self.assertEqual(obs['raidBounds'],[600,300,1000,400])
        self.ocr.analyze_gateless.assert_called_once_with(self.frame,[620,330,970,370])
        regions['dungeon_panel']=self.regions['dungeon_panel']
        obs,gates=self.observer.analyze(self.frame,regions,1)
        self.assertFalse(obs['currentRaidPanel'])
    def test_multiple_same_state_icons_valid_but_conflicting_overlap_is_not(self):
        regions=copy.deepcopy(self.regions);regions.pop('gate_in_progress')
        regions['gate_not_started']=dict(status='ambiguous',candidates=[box([660,420,700,480]),box([800,420,840,480])])
        self.assertEqual(len(detected_gates(regions)),2)
        regions['gate_completed']=box([660,420,700,480])
        self.assertEqual(detected_gates(regions),[])
    def test_icons_outside_detected_row_are_not_used(self):
        self.regions['gate_in_progress']=box([1500,420,1540,480])
        self.assertEqual(detected_gates(self.regions),[])
    def test_snapshot_completion_survives_resize_without_duplicate(self):
        from beatrice.gates import GateTracker
        tracker=GateTracker('resize',2,max_sample_gap=5,snapshot_mode=True)
        def values(states,scale=1,offset=0):
            return [dict(state=s,confidence=.99,xyxy=[offset+(50+i*70)*scale,400*scale,offset+(90+i*70)*scale,450*scale]) for i,s in enumerate(states)]
        for t in range(3):result=tracker.update(t,values(['진행중','진행 전']))
        for t in range(3,6):result=tracker.update(t,values(['완료','진행중'],.7,700))
        self.assertEqual(result['stableStates'],('완료','진행중'));self.assertEqual(len(result['events']),1)
        for t in range(6,9):result=tracker.update(t,values(['진행 전','진행중'],1.2,300))
        self.assertEqual(result['stableStates'],('완료','진행중'));self.assertEqual(result['events'],[])

if __name__=='__main__':unittest.main()
