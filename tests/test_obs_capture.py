import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from beatrice.obs_capture import ObsCapture,HEADER,OFFSET,CAPACITY,read_frame,runtime_path
from beatrice.game_window import Client

def frame(sequence=2,width=8,height=8,value=100,received=None):
    stride=width*4
    return bytearray(HEADER.pack(sequence,123,time.monotonic() if received is None else received,
                                 width,height,stride,1)+bytes(OFFSET-HEADER.size)
                     +bytes([value])*(stride*height))

class FrameProtocolTests(unittest.TestCase):
    def test_each_publication_is_read_once(self):
        memory=frame()
        self.assertEqual(read_frame(memory,0)[0],2)
        self.assertIsNone(read_frame(memory,2))
    def test_in_progress_or_unready_frame_is_ignored(self):
        self.assertIsNone(read_frame(frame(sequence=3),0))
        memory=frame();memory[:HEADER.size]=HEADER.pack(2,123,1,8,8,32,0)
        self.assertIsNone(read_frame(memory,0))
    def test_invalid_dimensions_are_rejected_before_reading_pixels(self):
        memory=frame();memory[:HEADER.size]=HEADER.pack(2,123,1,8192,8192,32768,1)
        with self.assertRaises(RuntimeError):read_frame(memory,0)
    def test_republication_during_copy_is_ignored(self):
        memory=frame()
        class Changing:
            def __getitem__(self,key):
                result=memory[key]
                if key.start==OFFSET:memory[:8]=(4).to_bytes(8,'little')
                return result
        self.assertIsNone(read_frame(Changing(),0))
    def test_runtime_does_not_resolve_installed_obs(self):
        with tempfile.TemporaryDirectory() as folder,patch('beatrice.obs_capture.ROOT',Path(folder)):
            with self.assertRaises(RuntimeError):runtime_path()
            owned=Path(folder)/'obs-runtime';owned.mkdir();(owned/'manifest.json').write_text('{}')
            self.assertEqual(runtime_path(),owned.resolve())

class ObsCaptureTests(unittest.TestCase):
    def setUp(self):
        self.capture=ObsCapture(Client(123,456,'LOSTARK'),Path('.'))
        self.capture.process=SimpleNamespace(poll=lambda:None)
        self.native_api=SimpleNamespace(IsIconic=lambda hwnd:True,GetForegroundWindow=lambda:999)
        self.alive=patch('beatrice.game_window.client_alive',return_value=True);self.alive.start()
        self.api=patch('beatrice.game_window.api',return_value=self.native_api);self.api.start()
        self.addCleanup(self.alive.stop);self.addCleanup(self.api.stop)
    def test_minimized_and_unfocused_changed_frame_can_be_analyzed(self):
        self.capture.memory=frame()
        image,reason=self.capture.grab()
        self.assertEqual(image.shape,(8,8,3));self.assertEqual(reason,'')
        self.assertTrue(self.capture.frame_info['minimized'])
        self.assertFalse(self.capture.frame_info['foreground'])
        self.assertEqual(self.capture.frame_info['source'],'embedded_obs')
        self.assertIsNone(self.capture.grab()[0])
    def test_black_frame_is_rejected(self):
        self.capture.memory=frame(value=0)
        self.assertIn('검은',self.capture.grab()[1])
    def test_stale_frame_is_rejected(self):
        self.capture.memory=frame(received=time.monotonic()-3)
        self.assertIn('지연',self.capture.grab()[1])
    def test_frozen_compositor_output_pauses_until_pixels_change(self):
        self.native_api.IsIconic=lambda hwnd:False
        self.capture.memory=frame()
        self.assertIsNotNone(self.capture.grab()[0])
        self.capture.changed_at=time.monotonic()-3
        self.capture.memory=frame(sequence=4)
        self.assertIn('화면 변화 없음',self.capture.grab()[1])
        self.capture.memory=frame(sequence=6,value=150)
        self.assertIsNotNone(self.capture.grab()[0])
    def test_minimized_identical_pixels_are_paused_immediately(self):
        self.capture.memory=frame()
        self.capture.grab()
        self.capture.memory=frame(sequence=4)
        self.assertIn('최소화',self.capture.grab()[1])
        self.capture.memory=frame(sequence=6,value=150)
        self.assertIsNotNone(self.capture.grab()[0])
    def test_missing_engine_produces_wait_reason_and_retries_later(self):
        self.capture.process=None
        with patch.object(self.capture,'_start',side_effect=RuntimeError('missing engine')) as start:
            self.assertEqual(self.capture.grab(),(None,'missing engine'))
            self.capture.grab();self.assertEqual(start.call_count,1)
    def test_game_exit_rejects_even_a_queued_frame(self):
        self.alive.stop()
        with patch('beatrice.game_window.client_alive',return_value=False):
            self.capture.memory=frame()
            with self.assertRaises(RuntimeError):self.capture.grab()

    def test_duplicate_publication_is_a_short_wait_then_a_real_outage(self):
        self.native_api.IsIconic=lambda hwnd:False
        self.capture.memory=frame(received=10)
        with patch('beatrice.obs_capture.time.monotonic',return_value=10):self.capture.grab()
        with patch('beatrice.obs_capture.time.monotonic',return_value=10.5):
            self.assertIsNone(self.capture.grab()[0])
        self.assertEqual(self.capture.wait_kind,'transient')
        with patch('beatrice.obs_capture.time.monotonic',return_value=12.1):
            self.assertIn('공급 중단',self.capture.grab()[1])
        self.assertEqual(self.capture.wait_kind,'interrupted')
        self.capture.memory=frame(sequence=4,value=150,received=12.2)
        with patch('beatrice.obs_capture.time.monotonic',return_value=12.2):
            self.assertIsNotNone(self.capture.grab()[0])
        self.assertEqual(self.capture.wait_kind,'ready')
        self.assertEqual(self.capture.frame_info['readWaits']['already_read'],2)

    def test_copy_retry_has_grace_after_long_analysis(self):
        self.capture.memory=frame(received=10)
        with patch('beatrice.obs_capture.time.monotonic',return_value=10):self.capture.grab()
        with patch('beatrice.obs_capture.time.monotonic',return_value=14):self.capture.grab()
        self.assertEqual(self.capture.wait_kind,'transient')
        self.capture.memory=frame(sequence=4,value=150,received=14.01)
        with patch('beatrice.obs_capture.time.monotonic',return_value=14.01):
            self.assertIsNotNone(self.capture.grab()[0])

    def test_black_or_frozen_wait_reason_survives_a_copy_miss(self):
        self.capture.memory=frame(value=0)
        reason=self.capture.grab()[1]
        self.assertEqual(self.capture.grab()[1],reason)
        self.assertEqual(self.capture.wait_kind,'interrupted')

    def test_writer_busy_is_retried_without_reusing_old_frame(self):
        self.native_api.IsIconic=lambda hwnd:False
        self.capture.memory=frame();self.capture.grab()
        self.capture.memory=frame(sequence=3,value=150)
        self.assertIsNone(self.capture.grab()[0])
        self.assertEqual(self.capture.wait_kind,'transient')
        self.capture.memory=frame(sequence=4,value=150)
        self.assertIsNotNone(self.capture.grab()[0])
        self.assertEqual(self.capture.frame_info['readWaits']['writer_busy'],1)

    def test_copy_race_is_retried_and_only_completed_publication_is_delivered(self):
        self.native_api.IsIconic=lambda hwnd:False
        self.capture.memory=frame();self.capture.grab()
        memory=frame(sequence=4)
        class ChangingOnce:
            changed=False
            def __getitem__(self,key):
                result=memory[key]
                if key.start==OFFSET and not self.changed:
                    self.changed=True
                    memory[:]=frame(sequence=6,value=150)
                return result
        self.capture.memory=ChangingOnce()
        self.assertIsNone(self.capture.grab()[0])
        self.assertEqual(self.capture.wait_kind,'transient')
        image,_=self.capture.grab()
        self.assertEqual(int(image[0,0,0]),150)
        self.assertEqual(self.capture.frame_info['sequence'],6)
        self.assertEqual(self.capture.frame_info['readWaits']['copy_race'],1)

if __name__=='__main__':unittest.main()
