import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from beatrice.google_auth import AuthError
from beatrice.lostark_api import LostArkApiKey


class LostArkApiKeyTests(unittest.TestCase):
    def test_real_dpapi_roundtrip_and_replacement(self):
        if os.name != 'nt': self.skipTest('Windows DPAPI')
        with tempfile.TemporaryDirectory() as directory:
            store = LostArkApiKey(directory)
            self.assertFalse(store.view()['configured'])
            self.assertTrue(store.save('  dummy-test-key-one  '))
            self.assertNotIn(b'dummy-test-key-one', store.path.read_bytes())
            restored = LostArkApiKey(directory)
            self.assertTrue(restored.view()['configured'])
            self.assertEqual(restored.load(), 'dummy-test-key-one')
            self.assertNotIn('dummy-test-key-one', str(restored.view()))
            self.assertTrue(restored.save('dummy-test-key-two'))
            self.assertEqual(LostArkApiKey(directory).load(), 'dummy-test-key-two')
            self.assertFalse(store.path.with_suffix('.tmp').exists())

    def test_invalid_input_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LostArkApiKey(directory)
            for value in [None, '', ' ', 'key\nother', 'key\x00', 'x'*16385]:
                self.assertFalse(store.save(value))
            self.assertFalse(store.path.exists())

    def test_encrypt_failure_no_plaintext_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LostArkApiKey(directory)
            with patch('beatrice.lostark_api.dpapi', side_effect=AuthError('dummy-secret')):
                self.assertFalse(store.save('dummy-secret'))
            self.assertNotIn('dummy-secret', str(store.view()))
            self.assertFalse(store.path.exists())

    def test_failed_replace_preserves_existing_key(self):
        if os.name != 'nt': self.skipTest('Windows DPAPI')
        with tempfile.TemporaryDirectory() as directory:
            store = LostArkApiKey(directory)
            self.assertTrue(store.save('old-dummy'))
            with patch.object(Path,'replace',side_effect=OSError('new-dummy')):
                self.assertFalse(store.save('new-dummy'))
            self.assertEqual(store.load(), 'old-dummy')
            self.assertTrue(store.view()['configured'])
            self.assertNotIn('new-dummy', str(store.view()))
            self.assertFalse(store.path.with_suffix('.tmp').exists())

    def test_corrupt_storage_is_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'lostark-api-key.bin').write_bytes(b'not-a-dpapi-blob')
            store = LostArkApiKey(directory)
            self.assertFalse(store.view()['configured'])
            self.assertIn('다시 입력', store.view()['message'])

    def test_clear_removes_only_api_credential_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LostArkApiKey(directory)
            store.path.write_bytes(b'encrypted-test')
            store.path.with_suffix('.tmp').write_bytes(b'encrypted-temporary')
            other = Path(directory)/'google-session.bin'
            other.write_bytes(b'other-credential')
            self.assertTrue(store.clear())
            self.assertFalse(store.path.exists())
            self.assertFalse(store.path.with_suffix('.tmp').exists())
            self.assertFalse(store.view()['configured'])
            self.assertEqual(other.read_bytes(), b'other-credential')
            self.assertTrue(store.clear())

    def test_clear_failure_preserves_configured_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LostArkApiKey(directory)
            store.path.write_bytes(b'encrypted-test')
            store.configured = True
            with patch.object(Path,'unlink',side_effect=PermissionError('private-secret')):
                self.assertFalse(store.clear())
            self.assertTrue(store.view()['configured'])
            self.assertTrue(store.path.exists())
            self.assertNotIn('private-secret', str(store.view()))
