import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from beatrice.__main__ import main
from beatrice.game_window import Client


class CaptureCliTests(unittest.TestCase):
    def run_command(self, arguments, clients, adapter=None):
        with patch('sys.argv', ['beatrice', *arguments]), patch('sys.platform', 'win32'), \
                patch('beatrice.game_window.find_clients', return_value=clients), \
                patch('beatrice.obs_capture.ObsCapture', return_value=adapter) as factory, \
                contextlib.redirect_stdout(io.StringIO()):
            result = main()
        return result, factory

    def test_multiple_windows_require_explicit_selection(self):
        with self.assertRaisesRegex(RuntimeError, '--pid'):
            self.run_command(['capture'], [Client(1, 2, 'A'), Client(3, 4, 'B')])

    def test_selected_game_frame_and_metadata_are_saved_and_engine_closed(self):
        adapter = Mock()
        adapter.grab.return_value = (np.ones((3, 4, 3), dtype=np.uint8), '')
        adapter.observed_at = None
        adapter.frame_info = {'source': 'embedded_obs', 'sequence': 2}
        clients = [Client(1, 2, 'A'), Client(3, 4, 'B')]
        with tempfile.TemporaryDirectory() as directory:
            result, factory = self.run_command(
                ['capture', '--pid', '4', '--directory', directory], clients, adapter)
            self.assertEqual(result, 0)
            self.assertEqual(factory.call_args.args[0], clients[1])
            image, = Path(directory).glob('*.png')
            metadata = json.loads(image.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual((metadata['source'], metadata['pid'], metadata['captureScope']),
                             ('embedded_obs', 4, 'game'))
            self.assertEqual((metadata['width'], metadata['height']), (4, 3))
        adapter.close.assert_called_once()

    def test_timeout_preserves_capture_reason_and_closes_engine(self):
        adapter = Mock()
        adapter.grab.return_value = (None, '게임 접근 거부')
        with patch('beatrice.__main__.time.monotonic', side_effect=[0, 0, 16]), \
                patch('beatrice.__main__.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '게임 접근 거부'):
                self.run_command(['capture'], [Client(1, 2, 'A')], adapter)
        adapter.close.assert_called_once()

    def test_capture_failure_closes_engine(self):
        adapter = Mock()
        adapter.grab.side_effect = RuntimeError('게임 창 종료')
        with self.assertRaisesRegex(RuntimeError, '게임 창 종료'):
            self.run_command(['capture'], [Client(1, 2, 'A')], adapter)
        adapter.close.assert_called_once()
