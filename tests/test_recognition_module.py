"""Framework boundary, stale observations and resource lifecycle regressions."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from beatrice.recognition import RecognitionPipeline,RecognitionEvents,RecognitionService,FrameRecognition
from beatrice.recognition import service as module
from beatrice.storage import Store

ROOT=Path(__file__).resolve().parents[1]


class RecognitionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.pipeline=RecognitionPipeline(ROOT)
        self.pipeline.detector=Mock()
        self.pipeline.detector.locate_character.return_value={'game_menu':{'status':'missing'},'switch_dialog':{'status':'missing'}}
        self.pipeline.detector.locate_dungeon.side_effect=lambda frame,regions:regions
        self.pipeline.character=Mock()
        self.pipeline.character.analyze_detected.return_value={}
        self.pipeline.dungeon_observer=Mock()
        self.pipeline.dungeon_observer.analyze.return_value=({'raidKind':'gated'},[{'state':'완료'}])
        self.pipeline.completion=Mock()
        self.pipeline.completion.analyze.return_value={'status':'verified'}
        self.pipeline.gold_reward=Mock()

    def test_gold_uses_fresh_raw_dungeon_before_context_tracking(self):
        self.pipeline.dungeon_observer.analyze.return_value=({'raidKind':'gated','dungeonVisible':True,'currentRaidPanel':True},[{'state':'완료'}])
        self.pipeline.gold_reward.analyze.return_value={'status':'verified','received':False,'gate':1}
        result=self.pipeline.analyze(object(),12,confirmed_name='캐릭터')
        self.assertIs(result.dungeon['goldReward']['received'],False)
        self.pipeline.gold_reward.analyze.assert_called_once()

    def test_import_does_not_load_ui_or_models(self):
        code="import sys,json; import beatrice.recognition; print(json.dumps([m for m in sys.modules if m.startswith(('PySide6','ultralytics','paddle','cv2'))]))"
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(result.stdout),[])

    def test_context_enables_completion_and_preserves_observations(self):
        frame=object()
        result=self.pipeline.analyze(frame,12,confirmed_name='캐릭터',completion_enabled=True)
        self.assertEqual(result.gates,[{'state':'완료'}])
        self.assertEqual(result.dungeon['completionOverlay'],{'status':'verified'})
        self.pipeline.character.analyze_detected.assert_called_once_with(frame,self.pipeline.detector.locate_character.return_value,seconds=12,confirmed_name='캐릭터')

    def test_menu_blocks_completion_analysis(self):
        self.pipeline.detector.locate_character.return_value['game_menu']['status']='detected'
        self.pipeline.analyze(object(),12,confirmed_name='캐릭터',completion_enabled=True)
        self.pipeline.completion.analyze.assert_not_called()
        self.assertTrue(self.pipeline.dungeon_observer.analyze.call_args.kwargs['blocked'])

    def test_missing_confirmed_context_does_not_run_completion(self):
        self.pipeline.analyze(object(),12)
        self.pipeline.completion.analyze.assert_not_called()
        self.pipeline.detector.locate_dungeon.assert_not_called()
        self.pipeline.dungeon_observer.analyze.assert_not_called()

    def test_selection_changed_before_overlay_discards_frame(self):
        self.assertIsNone(self.pipeline.analyze(object(),12,confirmed_name='캐릭터',completion_enabled=True,still_current=lambda:False))
        self.pipeline.completion.analyze.assert_not_called()

    def test_selection_changed_during_overlay_discards_frame(self):
        current=Mock(side_effect=[True,False])
        self.assertIsNone(self.pipeline.analyze(object(),12,confirmed_name='캐릭터',completion_enabled=True,still_current=current))
        self.pipeline.completion.analyze.assert_called_once()


class RecognitionServiceTests(unittest.TestCase):
    def setup_runtime(self,stack,folder):
        runtime=RecognitionService(ROOT,folder)
        pipeline=Mock(config={'architecture':'split'})
        pipeline.completion.config={}
        stack.enter_context(patch.object(module,'RecognitionPipeline',return_value=pipeline))
        capture=Mock(wait_kind='transient')
        capture.binding_ready=threading.Event();capture.binding_ready.set()
        capture.prepare.return_value=True
        stack.enter_context(patch('beatrice.obs_capture.ObsCapture',return_value=capture))
        watch=Mock(pids=frozenset())
        watch.ready=threading.Event();watch.ready.set();watch.stop_event=threading.Event()
        stack.enter_context(patch.object(module,'ProcessWatch',return_value=watch))
        for name in ('recognition_diagnostic.RecognitionDiagnostic','completion_diagnostic.CompletionDiagnostic'):
            stack.enter_context(patch('beatrice.'+name))
        return runtime,pipeline,capture,watch

    def test_stop_during_obs_preparation_closes_capture_and_store(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            runtime,_,capture,watch=self.setup_runtime(stack,folder)
            store=Mock();stack.enter_context(patch('beatrice.weekly.open_week',return_value=store))
            capture.prepare.side_effect=lambda stop:runtime.stop() or False
            runtime.run()
            capture.close.assert_called_once();store.close.assert_called_once()
            watch.start.assert_not_called()
            self.assertTrue(runtime.stop_event.is_set())

    def test_obs_failure_publishes_error_and_closes_resources(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            runtime,_,capture,watch=self.setup_runtime(stack,folder)
            store=Mock();stack.enter_context(patch('beatrice.weekly.open_week',return_value=store))
            errors=[];runtime.events.failed=errors.append
            capture.prepare.side_effect=RuntimeError('capture failure')
            runtime.run()
            self.assertEqual(len(errors),1)
            self.assertIn('capture failure',errors[0])
            capture.close.assert_called_once();store.close.assert_called_once()
            watch.start.assert_not_called()

    def test_service_without_qt_saves_real_icon_completion_and_stops(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            runtime,pipeline,capture,watch=self.setup_runtime(stack,folder)
            store=Store(':memory:');self.addCleanup(store.close)
            proxy=Mock(wraps=store);proxy.close=Mock();proxy.db=store.db
            stack.enter_context(patch('beatrice.weekly.open_week',return_value=proxy))
            client=SimpleNamespace(pid=1,hwnd=2)
            watch.pids=frozenset([1])
            stack.enter_context(patch.object(module,'find_clients',return_value=[client]))
            stack.enter_context(patch.object(module,'client_active',return_value=True))
            stack.enter_context(patch.object(module,'client_alive',return_value=True))
            at=datetime(2026,10,10,tzinfo=timezone.utc);frame=SimpleNamespace(shape=(200,300,3))
            index=0
            def grab():
                nonlocal index
                capture.observed_at=at+timedelta(seconds=index*.5);index+=1
                return frame,None
            capture.grab.side_effect=grab;capture.frame_info={}
            def analyze(*args,**kwargs):
                state='진행중' if index<=3 else '완료'
                return FrameRecognition(dict(currentName=dict(text='테스트',confidence=.99)),
                    dict(dungeonName=dict(text='단일 관문',confidence=.99),difficulty=dict(text='하드',confidence=.99),dungeonVisible=True,raidKind='gated',currentRaidPanel=True),
                    [dict(state=state,confidence=.99,xyxy=[0,0,20,20])],args[1],args[1])
            pipeline.analyze_character.side_effect=lambda frame,seconds,**kwargs: ({},dict(currentName=dict(text='테스트',confidence=.99)),seconds,seconds)
            pipeline.analyze_dungeon.side_effect=lambda frame,regions,identity,seconds,**kwargs: (analyze(frame,seconds).dungeon,analyze(frame,seconds).gates)
            observations=[];errors=[]
            runtime.events.failed=errors.append
            def receive(state):
                observations.append(state)
                if len(observations)==8:runtime.stop()
            runtime.events.observation=receive
            with patch.object(runtime.stop_event,'wait',return_value=False):runtime.run()
            self.assertEqual(errors,[])
            records=store.state_records()
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['gateNumber'],1)
            self.assertEqual(records[0]['characterName'],'테스트')
            self.assertEqual(observations[-1]['generation'],1)
            self.assertEqual(pipeline.analyze_dungeon.call_count,6)
            capture.close.assert_called_once();proxy.close.assert_called_once();watch.join.assert_called_once()
            self.assertTrue(watch.stop_event.is_set())

    def test_capture_close_failure_still_closes_store_and_watch(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            runtime,_,capture,watch=self.setup_runtime(stack,folder)
            store=Mock();stack.enter_context(patch('beatrice.weekly.open_week',return_value=store))
            runtime.events.ready=lambda clients:runtime.stop()
            capture.close.side_effect=RuntimeError('close failure')
            with self.assertRaisesRegex(RuntimeError,'close failure'):runtime.run()
            store.close.assert_called_once();watch.join.assert_called_once()

if __name__=='__main__':unittest.main()
