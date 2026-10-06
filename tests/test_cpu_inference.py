import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from beatrice import cpu_inference
from beatrice.paddle_reader import PaddleKoreanReader
from beatrice.ui_regions import UIRegionDetector


class CpuInferenceTests(unittest.TestCase):
    def test_thread_counts_are_bounded_by_available_cpu(self):
        with patch('beatrice.cpu_inference.os.cpu_count', return_value=2):
            config=cpu_inference.load_config()
        self.assertEqual((config['yoloThreads'],config['ocrThreads']),(2,2))

    def test_invalid_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir()
            file=root/'config/cpu-inference.json'
            for change in ({'yoloThreads':True},{'ocrThreads':0},{'ocrMkldnn':'true'}):
                config=dict(yoloThreads=4,ocrThreads=4,ocrMkldnn=True)
                config.update(change);file.write_text(json.dumps(config))
                with patch.object(cpu_inference,'ROOT',root),self.assertRaises(ValueError):
                    cpu_inference.load_config()

    def test_predictor_initialization_does_not_leave_library_thread_override(self):
        pool={'threads':12}
        torch=SimpleNamespace(get_num_threads=lambda:pool['threads'],
                              set_num_threads=lambda n:pool.update(threads=n))
        model=Mock(names={0:'test'})
        def predict(*args,**kwargs):
            pool['threads']=8  # The library's initial CPU setup changes the pool.
            return [SimpleNamespace(boxes=[])]
        model.predict.side_effect=predict
        detector=UIRegionDetector(dict(classes=['test'],confidence=.7,imageSize=32),model=model)
        detector.cpu_threads=4
        with patch.dict('sys.modules',{'torch':torch}):
            result=detector.locate(np.zeros((32,32,3),dtype=np.uint8))
        self.assertEqual(result['test']['status'],'missing')
        self.assertEqual(pool['threads'],4)

    def test_initialization_failure_uses_standard_cpu_model(self):
        standard=Mock()
        with patch.object(PaddleKoreanReader,'_create_model',side_effect=[RuntimeError('oneDNN unavailable'),standard]), \
                self.assertWarnsRegex(RuntimeWarning,'기본 CPU'):
            reader=PaddleKoreanReader(cpu_threads=4,enable_mkldnn=True)
        self.assertIs(reader.model,standard)
        self.assertFalse(reader.enable_mkldnn)

    def test_partial_accelerated_failure_retries_entire_input_once(self):
        reader=PaddleKoreanReader.__new__(PaddleKoreanReader)
        reader.enable_mkldnn=True
        accelerated=Mock();standard=Mock();reader.model=accelerated
        def broken_results():
            yield {'rec_text':'partial','rec_score':.9}
            raise RuntimeError('unsupported primitive')
        accelerated.predict.return_value=broken_results()
        standard.predict.return_value=[{'rec_text':'A','rec_score':.9},{'rec_text':'B','rec_score':.99}]
        images=[np.zeros((8,12),dtype=np.uint8)]*2
        with patch.object(reader,'_create_model',return_value=standard), \
                self.assertWarnsRegex(RuntimeWarning,'기본 CPU'):
            result=reader.recognize_many(images)
        self.assertEqual([v[0][1] for v in result],['A','B'])
        self.assertFalse(reader.enable_mkldnn)
        self.assertEqual(len(standard.predict.call_args.args[0]),2)
        standard.predict.side_effect=RuntimeError('standard CPU failed')
        with self.assertRaisesRegex(RuntimeError,'standard CPU failed'):
            reader.recognize_many(images)
