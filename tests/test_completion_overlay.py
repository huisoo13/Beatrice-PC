import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock
import numpy as np
from beatrice.completion_overlay import CompletionOverlayDetector,parse_completion
from beatrice.completion_diagnostic import CompletionDiagnostic


class CompletionOverlayTests(unittest.TestCase):
    def test_exact_semantics_and_confidence(self):
        self.assertEqual(parse_completion(' 12관문 돌파 ',.99),dict(kind='gate_breakthrough',gate=12))
        self.assertEqual(parse_completion('던전 클리어',.99),dict(kind='dungeon_clear',gate=None))
        for text,score in [('퀘스트 완료',.99),('던전 클리어',.7),('0관문 돌파',.99),('1관문 돌파 보상',.99),('던전 클리어',float('nan'))]:
            self.assertIsNone(parse_completion(text,score))

    def test_only_detected_contained_text_is_read_at_arbitrary_position(self):
        reader=Mock();reader.recognize.return_value=[(None,'3관문 돌파',.99)]
        detector=Mock()
        def box(v):return dict(status='detected',xyxy=v)
        detector.locate.return_value=dict(completion_overlay=box([10,20,90,90]),completion_text=box([20,40,80,60]))
        frame=np.zeros((200,300,3),dtype=np.uint8);frame[40:60,20:80]=127
        pipeline=CompletionOverlayDetector(reader,{},detector)
        result=pipeline.analyze(frame)
        self.assertEqual(result['gate'],3)
        self.assertTrue(np.all(reader.recognize.call_args.args[0]==127))
        detector.locate.return_value['completion_text']=box([120,40,180,60]);reader.reset_mock()
        self.assertEqual(pipeline.analyze(frame)['status'],'text_unverified')
        reader.recognize.assert_not_called()

    def test_persistent_evidence_survives_more_than_rolling_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            diagnostic=CompletionDiagnostic(folder)
            frame=np.zeros((20,30,3),dtype=np.uint8)
            for i in range(185):
                diagnostic.record(frame,dict(observedAt=str(i),gates=[],state=dict(result=dict(
                    completionDecision=dict(reason='saved' if i==1 else 'missing',gate=1)))))
            records=[json.loads(line) for line in (diagnostic.directory/'observations.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(records),185)
            self.assertEqual(records[1]['reason'],'saved')
            self.assertTrue((diagnostic.directory/records[1]['frameFile']).exists())

if __name__=='__main__':unittest.main()
