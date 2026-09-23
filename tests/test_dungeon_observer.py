import unittest
from unittest.mock import Mock,patch
import numpy as np
from beatrice.dungeon_observer import DungeonObserver


class DungeonObserverTests(unittest.TestCase):
    def setUp(self):
        self.frame=np.zeros((1440,3440,3),dtype=np.uint8)
        self.regions={k:dict(status='detected',xyxy=v) for k,v in (
            ('dungeon_panel',[0,36,360,240]),('gate_panel',[32,112,320,200]))}
        self.missing={k:dict(status='missing') for k in self.regions}
        self.ocr=Mock();self.ocr.analyze_detected.side_effect=self.read
        self.name='새 던전';self.mode='매칭 모드';self.visible=True
        self.observer=DungeonObserver(self.ocr,Mock())
        self.gate_patch=patch('beatrice.dungeon_observer.predict_panel_gates',return_value=[dict(state='진행중',confidence=.99)])
        self.gates=self.gate_patch.start();self.addCleanup(self.gate_patch.stop)

    def read(self,frame,location,gates):
        valid=location['status']=='detected' and self.visible
        return dict(dungeonVisible=valid,dungeonName=dict(text=self.name,confidence=.99) if valid else None,
            difficulty=dict(text=self.mode,confidence=.99) if valid else None,panelDetection=location)

    def test_reuse_reads_current_frame_but_does_not_extend_deadline(self):
        self.observer.analyze(self.frame,self.regions,0)
        for t in (1,2,3):
            obs,gates=self.observer.analyze(self.frame,self.missing,t)
            self.assertEqual(obs['regionSource'],'verified_previous_region')
            self.assertTrue(obs['dungeonVisible']);self.assertTrue(gates)
        obs,gates=self.observer.analyze(self.frame,self.missing,3.01)
        self.assertFalse(obs['dungeonVisible']);self.assertEqual(gates,[])
        self.assertEqual(self.gates.call_count,4)

    def test_different_dungeon_or_mode_invalidates_cached_region(self):
        for field in ('name','mode'):
            self.observer.analyze(self.frame,self.regions,0)
            setattr(self,field,'다른 값')
            obs,gates=self.observer.analyze(self.frame,self.missing,1)
            self.assertEqual(obs['diagnosticStatus'],'reuse_rejected')
            self.assertIsNone(obs['dungeonName']);self.assertEqual(gates,[])
            self.assertIsNone(self.observer.cached)

    def test_black_frame_or_unreadable_text_clears_cache(self):
        self.observer.analyze(self.frame,self.regions,0);self.visible=False
        obs,gates=self.observer.analyze(self.frame,self.missing,1)
        self.assertEqual(gates,[]);self.assertIsNone(self.observer.cached)

    def test_menu_capture_loss_shape_change_and_ambiguity_clear_cache(self):
        for cause in ('menu','capture','shape','ambiguous'):
            self.observer.analyze(self.frame,self.regions,0)
            frame=self.frame;regions=self.missing
            if cause=='capture':self.observer.reset()
            if cause=='shape':frame=self.frame[:1000]
            if cause=='ambiguous':regions=dict(self.missing,dungeon_panel=dict(status='ambiguous'))
            obs,gates=self.observer.analyze(frame,regions,1,blocked=cause=='menu')
            self.assertEqual(gates,[],cause);self.assertIsNone(self.observer.cached,cause)

    def test_new_but_invalid_detection_does_not_fall_back_to_old_region(self):
        self.observer.analyze(self.frame,self.regions,0);self.visible=False
        obs,gates=self.observer.analyze(self.frame,self.regions,1)
        self.assertEqual(obs['diagnosticStatus'],'text_unverified');self.assertIsNone(self.observer.cached)

    def test_gate_only_drop_requires_matching_panel_position(self):
        self.observer.analyze(self.frame,self.regions,0)
        partial=dict(self.regions,gate_panel=dict(status='missing'))
        obs,gates=self.observer.analyze(self.frame,partial,1)
        self.assertTrue(gates);self.assertEqual(obs['regionSource'],'verified_previous_region')
        partial['dungeon_panel']=dict(status='detected',xyxy=[500,36,860,240])
        obs,gates=self.observer.analyze(self.frame,partial,2)
        self.assertEqual(gates,[]);self.assertIsNone(self.observer.cached)

    def test_fresh_matching_panel_renews_only_with_whole_gate_array(self):
        self.observer.analyze(self.frame,self.regions,0)
        partial=dict(self.regions,gate_panel=dict(status='missing'))
        for t in (2,4,6):
            obs,gates=self.observer.analyze(self.frame,partial,t)
            self.assertTrue(gates);self.assertEqual(self.observer.verified_at,t)
        self.gates.return_value=[]
        self.observer.analyze(self.frame,partial,8)
        self.assertEqual(self.observer.verified_at,6)
        obs,gates=self.observer.analyze(self.frame,self.missing,9.01)
        self.assertEqual(gates,[]);self.assertIsNone(self.observer.cached)

    def test_short_region_drop_preserves_real_completion_and_saves_once(self):
        from datetime import datetime,timedelta,timezone
        from beatrice.storage import Store
        from beatrice.live import LiveCoordinator
        from beatrice.dungeon import DungeonTracker
        store=Store(':memory:');self.addCleanup(store.close)
        live=LiveCoordinator(store);tracker=DungeonTracker(max_gap=5)
        now=datetime(2026,9,23,tzinfo=timezone.utc)
        for i in range(-3,0):
            live.update(now+timedelta(seconds=i),dict(normalMenu=True,currentName=dict(text='테스트',confidence=.99)),[],{})
        for i in range(15):
            self.gates.return_value=[dict(state='진행중' if i<8 else '완료',confidence=.99,xyxy=[60,130,100,180])]
            obs,gates=self.observer.analyze(self.frame,self.missing if i in (8,9) else self.regions,i)
            context=tracker.update(i,obs)
            live.update(now+timedelta(seconds=i),{},gates,context)
        events=store.state_records()
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['gate'],1)
        self.assertEqual(events[0]['characterName'],'테스트')
        self.assertEqual(events[0]['dungeonName'],'새 던전')


if __name__=='__main__':unittest.main()
