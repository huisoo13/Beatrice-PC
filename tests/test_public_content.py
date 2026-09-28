import hashlib
import io
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from beatrice.public_content import (ContentCache, ContentError, PublicContentClient,
    FOLDER_MIME, MAX_BYTES, load_api_key, parse_json, validate_content)

SETTINGS = dict(rootFolderID='root', jsonFolderName='JSON', fileName='ContentJSON.json', refreshSeconds=3600)
CONTENT = {'던전': {'하드': {'1관문': {'gold': 10000, 'fee': 3200, 'bound_percentage': .5}}}}


class FakePublicDrive:
    def __init__(self):
        self.body = json.dumps(CONTENT, ensure_ascii=False).encode('utf-8')
        self.calls = []
        self.duplicate = False
        self.bad_checksum = False

    def __call__(self, request, timeout):
        self.calls.append(request)
        query = parse_qs(urlsplit(request.full_url).query)
        assert query['key'] == ['test-api-key']
        assert 'Authorization' not in request.headers
        assert request.get_method() == 'GET'
        if 'alt' in query:
            return io.BytesIO(self.body)
        if "'root' in parents" in query['q'][0]:
            files = [dict(id='json-folder', name='JSON', mimeType=FOLDER_MIME)]
            if self.duplicate:
                files.append(dict(files[0], id='another'))
        else:
            files = [dict(id='content', name='ContentJSON.json', mimeType='application/json',
                          md5Checksum='0' * 32 if self.bad_checksum else hashlib.md5(self.body).hexdigest())]
        return io.BytesIO(json.dumps(dict(files=files)).encode())


class PublicContentTests(unittest.TestCase):
    def client(self, opener=None):
        return PublicContentClient('test-api-key', SETTINGS, threading.Event(), opener=opener or FakePublicDrive())

    def test_discovers_root_json_and_content_without_oauth(self):
        fake = FakePublicDrive()
        result = self.client(fake).refresh()
        self.assertEqual(result['content'], CONTENT)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(result['metadata']['id'], 'content')
        self.assertNotIn('test-api-key', json.dumps(result))

    def test_unchanged_file_skips_download_and_changed_file_downloads(self):
        fake = FakePublicDrive()
        client = self.client(fake)
        first = client.refresh()
        client.refresh(first)
        self.assertEqual(len(fake.calls), 5)
        new = json.loads(fake.body)
        new['던전']['하드']['1관문']['gold'] = 20000
        fake.body = json.dumps(new).encode()
        self.assertEqual(client.refresh(first)['content'], new)
        self.assertEqual(len(fake.calls), 8)

    def test_duplicate_folder_and_changed_during_download_rejected(self):
        fake = FakePublicDrive()
        fake.duplicate = True
        with self.assertRaises(ContentError):
            self.client(fake).refresh()
        fake.duplicate = False
        fake.bad_checksum = True
        with self.assertRaises(ContentError):
            self.client(fake).refresh()

    def test_pagination_follows_empty_pages_and_rejects_cycles(self):
        responses = iter([{'files': [], 'nextPageToken': 'next'}, {'files': [{'id': 'one', 'name': 'JSON'}]}])
        opener = lambda *a, **k: io.BytesIO(json.dumps(next(responses)).encode())
        self.assertEqual(self.client(opener).children('root')[0]['id'], 'one')
        with self.assertRaises(ContentError):
            self.client(lambda *a, **k: io.BytesIO(b'{"files":[],"nextPageToken":"next"}')).children('root')

    def test_errors_never_contain_key_or_request_url(self):
        for error in (HTTPError('https://api/?key=secret-value', 403, 'secret-value', {}, None),
                      URLError('https://api/?key=secret-value')):
            def fail(*args, **kwargs):
                raise error
            with self.assertRaises(ContentError) as caught:
                self.client(fail).refresh()
            self.assertNotIn('secret-value', str(caught.exception))
            self.assertNotIn('https://', str(caught.exception))

    def test_invalid_json_and_schema_are_rejected(self):
        for body in (b'<html>not json</html>', b'{"x":1,"x":2}', b'{"x":NaN}', b'x' * (MAX_BYTES + 1)):
            with self.assertRaises(ContentError):
                parse_json(body)
        for invalid in ([], {}, {'던전': {}}, {'던전': {'하드': {'2관문': {}}}}):
            with self.assertRaises(ContentError):
                validate_content(invalid)
        for field, value in (('gold', True), ('gold', -1), ('fee', 2.5), ('bound_percentage', 1.1), ('bound_percentage', float('nan'))):
            content = json.loads(json.dumps(CONTENT))
            content['던전']['하드']['1관문'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ContentError):
                validate_content(content)

    def test_cancelled_request_never_contacts_drive(self):
        fake = FakePublicDrive()
        client = self.client(fake)
        client.cancel.set()
        with self.assertRaises(ContentError):
            client.refresh()
        self.assertEqual(fake.calls, [])

    def test_cache_roundtrip_atomic_failure_and_source_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = ContentCache(directory, SETTINGS)
            self.assertIsNone(cache.load())
            data = self.client().refresh()
            cache.save(data)
            self.assertEqual(cache.load(), data)
            self.assertNotIn('test-api-key', cache.path.read_text(encoding='utf-8'))
            with patch.object(Path, 'replace', side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    cache.save(data)
            self.assertEqual(cache.load(), data)
            self.assertFalse(cache.path.with_suffix('.tmp').exists())
            with self.assertRaises(ContentError):
                ContentCache(directory, dict(SETTINGS, rootFolderID='other')).load()

    def test_key_from_file_and_invalid_key_error_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'BEATRICE_DRIVE_API_KEY_FILE': str(Path(directory) / 'key')}):
            path = Path(directory) / 'key'
            path.write_text('A' * 39)
            self.assertEqual(load_api_key('.'), 'A' * 39)
            path.write_text('secret?bad')
            with self.assertRaises(ContentError) as caught:
                load_api_key('.')
            self.assertNotIn('secret?bad', str(caught.exception))


class PublicContentUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from beatrice.public_content_ui import PublicContentPanel
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.result = PublicContentClient('test-api-key', SETTINGS, threading.Event(), opener=FakePublicDrive()).refresh()
        ContentCache(self.temp.name, SETTINGS).save(self.result)
        with patch('beatrice.public_content_ui.load_settings', return_value=SETTINGS):
            self.panel = PublicContentPanel('.', self.temp.name)
        self.addCleanup(self.panel.shutdown)

    def finish(self, result, error):
        replies = queue.Queue()
        replies.put((result, error))
        self.panel.pending = threading.Event(), replies
        self.panel.tick()

    def test_offline_preserves_cache_and_viewer(self):
        self.finish(None, 'offline')
        self.assertEqual(self.panel.cached, self.result)
        self.assertIn('마지막 정상', self.panel.label.text())
        self.assertTrue(self.panel.view_button.isEnabled())

    def test_success_and_shutdown_ignores_late_result(self):
        self.finish(self.result, None)
        self.assertIn('최신 확인', self.panel.label.text())
        self.panel.shutdown()
        with patch.object(self.panel.cache, 'save') as save:
            self.finish(self.result, None)
            save.assert_not_called()

    def test_missing_api_key_keeps_existing_content(self):
        with patch('beatrice.public_content_ui.load_api_key', side_effect=ContentError('key missing')):
            self.panel.refresh()
        self.assertIsNone(self.panel.pending)
        self.assertEqual(self.panel.cached, self.result)


if __name__ == '__main__':
    unittest.main()
