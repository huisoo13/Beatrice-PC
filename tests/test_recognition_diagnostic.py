import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from beatrice.recognition_diagnostic import RecognitionDiagnostic


class RecognitionDiagnosticTests(unittest.TestCase):
    def test_transition_saved_between_periodic_frames_and_storage_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder=RecognitionDiagnostic(directory,capacity=2,interval=1)
            frame=np.zeros((20,30,3),dtype=np.uint8)
            normal=dict(character=dict(switchDialog=False,switchLoading=False))
            self.assertTrue(recorder.record(frame,normal,now=0))
            self.assertFalse(recorder.record(frame,normal,now=.1))
            popup=dict(character=dict(switchDialog=True,switchLoading=False))
            self.assertTrue(recorder.record(frame,popup,now=.2))
            loading=dict(character=dict(switchDialog=False,switchLoading=True))
            self.assertTrue(recorder.record(frame,loading,now=.4))
            files=list(Path(directory).glob('*.json'))
            self.assertEqual(len(files),2)
            reports=[json.loads(p.read_text(encoding='utf-8')) for p in files]
            self.assertEqual(sorted(r['sequence'] for r in reports),[1,2])
            self.assertTrue(all((Path(directory)/r['frameFile']).exists() for r in reports))
            self.assertTrue(all(r['frameSize']==[20,30] for r in reports))
