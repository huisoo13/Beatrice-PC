import unittest
from unittest.mock import Mock

import numpy as np

from beatrice.dungeon import DungeonOCR
from beatrice.paddle_reader import PaddleKoreanReader, recognize_images


class OcrBatchTests(unittest.TestCase):
    def test_reader_preserves_input_order_and_converts_gray(self):
        reader = PaddleKoreanReader.__new__(PaddleKoreanReader)
        reader.model = Mock()
        reader.model.predict.return_value = iter([
            {'rec_text': '긴 이름', 'rec_score': .91},
            {'rec_text': '하드', 'rec_score': .98}])
        inputs = [np.zeros((6, 40), dtype=np.uint8), np.zeros((8, 10, 3), dtype=np.uint8)]
        result = reader.recognize_many(inputs)
        self.assertEqual([values[0][1] for values in result], ['긴 이름', '하드'])
        submitted = reader.model.predict.call_args.args[0]
        self.assertEqual(submitted[0].shape, (6, 40, 3))
        self.assertIs(submitted[1], inputs[1])
        self.assertEqual(reader.model.predict.call_args.kwargs['batch_size'], 1)

    def test_result_count_mismatch_is_rejected(self):
        reader = PaddleKoreanReader.__new__(PaddleKoreanReader)
        reader.model = Mock()
        reader.model.predict.return_value = []
        with self.assertRaisesRegex(RuntimeError, '결과 수'):
            reader.recognize_many([np.zeros((6, 40), dtype=np.uint8)])

    def test_empty_input_does_not_invoke_model(self):
        reader = PaddleKoreanReader.__new__(PaddleKoreanReader)
        reader.model = Mock()
        self.assertEqual(reader.recognize_many([]), [])
        reader.model.predict.assert_not_called()

    def test_single_image_adapter_preserves_empty_and_ambiguous_results(self):
        reader = Mock()
        reader.recognize.side_effect = [[], [(None, 'A', .9), (None, 'B', .9)]]
        images = [np.zeros((5, 8), dtype=np.uint8)] * 2
        self.assertEqual(recognize_images(reader, images),
                         [[], [(None, 'A', .9), (None, 'B', .9)]])

    def test_field_results_do_not_mix_and_disagreement_is_still_rejected(self):
        class Reader:
            def recognize_many(self, images):
                self.count = len(images)
                return [[(None, text, .99)] for text in
                        ['던전 A', '던전 A', '던전 B', '[하드]', '[하드]', '[하드]']]

        reader = Reader()
        panel = np.full((240, 400, 3), 200, dtype=np.uint8)
        result = DungeonOCR(reader).read_regions(panel, {
            'dungeonName': [25, 63, 355, 87], 'difficulty': [50, 90, 320, 120]})
        self.assertEqual(reader.count, 6)
        self.assertIsNone(result['dungeonName'])
        self.assertEqual(result['difficulty']['text'], '하드')
        self.assertEqual([r['variant'] for r in result['ocr']['dungeonName']['raw']],
                         ['gray', 'enlarged', 'inverted'])
