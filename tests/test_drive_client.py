"""Contract tests for the reusable transport, without credentials or network."""
import io
import json
import threading
import unittest
from email.parser import BytesParser
from email.policy import default
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from beatrice.drive import (GoogleDriveClient, DriveError, DriveAuthError,
    DrivePermissionError, DriveNotFoundError, DriveRateLimitError,
    DriveNetworkError, DriveResponseError, DriveCancelledError)
from beatrice.drive.client import API, _NoRedirect
from beatrice.google_drive import DriveError as LegacyDriveError

class DriveClientTests(unittest.TestCase):
    def test_credentials_are_exclusive_and_public_client_cannot_write(self):
        for options in ({}, {'access_token': 'secret', 'api_key': 'key'}, {'api_key': ''}):
            with self.assertRaises(ValueError): GoogleDriveClient(**options)
        calls = []
        client = GoogleDriveClient(api_key='public-key', opener=lambda *a, **k: calls.append(a))
        with self.assertRaises(DrivePermissionError): client.files.create({}, b'image')
        self.assertEqual(calls, [])
        self.assertIs(LegacyDriveError, DriveError)

    def test_delete_uses_exact_id_empty_response_and_private_credentials(self):
        calls=[]
        def opener(request, timeout):
            calls.append(request)
            return io.BytesIO(b'')
        client=GoogleDriveClient(access_token='private-token',opener=opener)
        client.files.delete('pc-file')
        self.assertEqual(calls[0].method,'DELETE')
        self.assertEqual(calls[0].full_url,API+'/pc-file')
        self.assertIsNone(calls[0].data)
        with self.assertRaises(ValueError):client.files.delete('../bad')
        with self.assertRaises(DrivePermissionError):GoogleDriveClient(api_key='key',opener=opener).files.delete('pc-file')
        self.assertEqual(len(calls),1)

    def test_public_and_private_requests_keep_credentials_separate(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            return io.BytesIO(b'{}')
        GoogleDriveClient(api_key='public-key', opener=opener).files.get('file')
        GoogleDriveClient(access_token='private-token', opener=opener).files.get('file')
        self.assertEqual(parse_qs(urlsplit(calls[0].full_url).query)['key'], ['public-key'])
        self.assertNotIn('Authorization', calls[0].headers)
        self.assertEqual(calls[1].headers['Authorization'], 'Bearer private-token')
        self.assertNotIn('key', parse_qs(urlsplit(calls[1].full_url).query))

    def test_binary_download_limits_and_cancel_after_read(self):
        cancel = threading.Event()
        class Response(io.BytesIO):
            def read(self, size):
                body = super().read(size)
                cancel.set()
                return body
        client = GoogleDriveClient(api_key='key', max_bytes=2, opener=lambda *a, **k: io.BytesIO(b'\x89PNG'))
        with self.assertRaises(DriveResponseError): client.files.download('image')
        self.assertEqual(client.files.download('image', max_bytes=4), b'\x89PNG')
        client = GoogleDriveClient(api_key='key', cancel=cancel, opener=lambda *a, **k: Response(b'data'))
        with self.assertRaises(DriveCancelledError): client.files.download('image')

    def test_cancel_before_request_and_invalid_paths_never_contact_server(self):
        calls = []
        client = GoogleDriveClient(access_token='token', opener=lambda *a, **k: calls.append(a))
        for path in ('https://evil.test', '//evil.test', '/../', '/%2e%2e', '/file?key=x', '/file#x', '/a/b'):
            with self.assertRaises(ValueError): client.request(path)
        for url in ('http://www.googleapis.com/drive/v3/files', 'https://evil.test/drive/v3/files',
                    'https://www.googleapis.com/drive/v3/files-other', API + '#fragment'):
            with self.assertRaises(ValueError): client.request_url(url)
        client.cancel.set()
        with self.assertRaises(DriveCancelledError): client.files.get('file')
        self.assertEqual(calls, [])
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test'))

    def test_pagination_empty_pages_cycles_and_malformed_metadata(self):
        calls = []
        replies = iter([{'files': [], 'nextPageToken': 'next'}, {'files': [{'id': 'file', 'name': 'image'}]}])
        def opener(request, timeout):
            calls.append(request)
            return io.BytesIO(json.dumps(next(replies)).encode())
        client = GoogleDriveClient(api_key='key', opener=opener)
        self.assertEqual(client.folders.children('root'), [{'id': 'file', 'name': 'image'}])
        self.assertEqual(parse_qs(urlsplit(calls[1].full_url).query)['pageToken'], ['next'])
        for response in ({'files': [], 'nextPageToken': 'cycle'}, {'files': [{}]}, {'files': 'bad'}):
            client.opener = lambda *a, **k: io.BytesIO(json.dumps(response).encode())
            with self.assertRaises(DriveResponseError): list(client.files.iter_files())

    def test_google_errors_are_typed_redacted_and_never_retried(self):
        cases = [(401, None, DriveAuthError), (403, 'forbidden', DrivePermissionError),
                 (403, 'userRateLimitExceeded', DriveRateLimitError), (429, None, DriveRateLimitError),
                 (404, 'notFound', DriveNotFoundError), (500, None, DriveResponseError),
                 (403, 'secret-value', DrivePermissionError)]
        for status, reason, expected in cases:
            with self.subTest(status=status, reason=reason):
                calls = []
                def opener(request, timeout):
                    calls.append(request)
                    body = json.dumps({'error': {'message': 'secret-value', 'errors': [{'reason': reason}]}}).encode()
                    raise HTTPError('https://api/?key=secret-value', status, 'secret-value',
                                    {'Retry-After': '12'}, io.BytesIO(body))
                client = GoogleDriveClient(access_token='secret-value', opener=opener)
                with self.assertRaises(expected) as caught: client.files.create({}, b'data')
                self.assertEqual(len(calls), 1)
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(caught.exception.retry_after, 12)
                self.assertNotIn('secret-value', str(caught.exception))
                self.assertNotIn('secret-value', repr(caught.exception.__dict__))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_network_and_invalid_json_errors_do_not_leak_urls(self):
        def fail(*a, **k): raise URLError('https://api/?key=secret-value')
        client = GoogleDriveClient(api_key='secret-value', opener=fail)
        with self.assertRaises(DriveNetworkError) as caught: client.files.get('file')
        self.assertNotIn('secret-value', str(caught.exception))
        for body in (b'not json', b'[]', b'null', b'\xff', b'{"files":[],"files":[]}', b'{"size":NaN}'):
            client.opener = lambda *a, **k: io.BytesIO(body)
            with self.assertRaises(DriveResponseError): client.files.get('file')

    def test_multipart_create_update_preserve_binary_and_use_correct_endpoint(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            message = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + request.headers['Content-type'] + '\r\n\r\n').encode() + request.data)
            parts = list(message.iter_parts())
            self.assertEqual(json.loads(parts[0].get_payload(decode=True))['name'], 'image.png')
            self.assertEqual(parts[1].get_content_type(), 'image/png')
            self.assertEqual(parts[1].get_payload(decode=True), b'\x89PNG\x00\xff')
            return io.BytesIO(b'{"id":"image"}')
        client = GoogleDriveClient(access_token='token', opener=opener)
        client.files.create({'name': 'image.png'}, b'\x89PNG\x00\xff', mime_type='image/png')
        client.files.update('image', {'name': 'image.png'}, b'\x89PNG\x00\xff', mime_type='image/png')
        self.assertEqual([r.method for r in calls], ['POST', 'PATCH'])
        self.assertEqual(urlsplit(calls[1].full_url).path, '/upload/drive/v3/files/image')
        self.assertEqual(parse_qs(urlsplit(calls[0].full_url).query)['uploadType'], ['multipart'])

    def test_empty_account_without_files_field_can_create_first_pc_file(self):
        from beatrice.google_drive import DriveClient
        replies = iter([b'{}', b'{"id":"pc","mimeType":"application/json"}', b'[]'])
        calls = []
        def opener(request, timeout):
            calls.append(request)
            return io.BytesIO(next(replies))
        client = DriveClient('token', threading.Event(), opener=opener)
        self.assertEqual(client.upload([])['id'], 'pc')
        self.assertEqual([request.method for request in calls], ['GET', 'POST', 'GET'])

    def test_legacy_delete_uses_same_authenticated_official_transport(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            return io.BytesIO(b'')
        client = GoogleDriveClient(access_token='token', opener=opener)
        self.assertEqual(client.request_url(API + '/test-file', method='DELETE'), b'')
        self.assertEqual(calls[0].method, 'DELETE')

if __name__ == '__main__': unittest.main()
