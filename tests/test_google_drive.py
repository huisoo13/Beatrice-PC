import io
import json
import os
from pathlib import Path
import queue
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from email.parser import BytesParser
from email.policy import default

from beatrice.drive_data import (decode_records, encode_records, export_records,
                                 restore_records, validate_records, MAX_BYTES)
from beatrice.google_auth import AuthError, DRIVE_SCOPE, drive_access_token, authenticate
from beatrice.google_drive import DriveClient, DriveError
from beatrice.storage import Store
from beatrice.completion_record import recognition_record


def row(**kwargs):
    return dict(dict(characterName='테스트', dungeonName='던전', difficulty='하드', gate=1, state='완료'), **kwargs)


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'records.sqlite3')
        self.addCleanup(self.store.close)

    def restore(self, records):
        return restore_records(self.store, records, Path(self.temp.name) / 'backups')

    def test_json_roundtrip_canonical_fields_and_gateless(self):
        rows = [row(gate=0), row(characterName='다른캐릭터')]
        self.restore(rows)
        actual, omitted = export_records(self.store)
        self.assertEqual(actual, validate_records(rows))
        self.assertEqual(decode_records(encode_records(actual)), actual)
        self.assertEqual(omitted, 0)
        self.assertIn('raid', [recognition_record(r)['completionScope'] for r in self.store.state_records()])

    def test_replacement_and_backup_include_previous_wal_records(self):
        self.restore([row()])
        backup = self.restore([row(state='진행 전')])
        old = Store(backup)
        try:
            self.assertEqual(old.state_records()[0]['gateNumber'], 1)
        finally:
            old.close()
        self.assertEqual(self.store.state_records(), [])
        self.restore([row(state='진행 전')])
        self.assertEqual(len(self.store.state_records()), 0)

    def test_failed_insert_rolls_back_deletions(self):
        self.restore([row()])
        self.store.db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON gate_states BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.restore([row(difficulty='노말')])
        self.assertEqual(self.store.state_records()[0]['gateNumber'], 1)

    def test_failed_backup_does_not_change_records(self):
        self.restore([row()])
        path = Path(self.temp.name) / 'not-a-directory'
        path.write_text('test')
        with self.assertRaises(OSError):
            restore_records(self.store, [row(state='진행 전')], path)
        self.assertEqual(self.store.state_records()[0]['gateNumber'], 1)

    def test_invalid_import_leaves_records_intact(self):
        self.restore([row()])
        invalid = [[row(gate=True)], [row(), row(difficulty='노말')],
                   [row(state='알수없음')], [row(extra=1)], [row(characterName='')],
                   [row(gate=0), row()], [row(gate=9)], {'records': [row()]}]
        for records in invalid:
            with self.subTest(records=records), self.assertRaises(ValueError):
                self.restore(records)
        self.assertEqual(self.store.state_records()[0]['gateNumber'], 1)

    def test_mixed_difficulty_per_gate_and_complete_array(self):
        rows = [row(), row(gate=2, difficulty='노말', state='진행중')]
        self.restore(rows)
        self.assertEqual(export_records(self.store)[0], validate_records([rows[0]]))

    def test_sparse_completion_import_does_not_invent_total_gate_count(self):
        self.restore([row(state='진행 전'),row(gate=2),row(gate=3,state='진행중')])
        records=self.store.state_records()
        self.assertEqual([r['gateNumber'] for r in records],[2])
        self.assertEqual(records[0]['expectedGates'],0)
        self.assertEqual(export_records(self.store)[0],validate_records([row(gate=2)]))

    def test_pending_and_test_records_are_not_exported(self):
        self.restore([row()])
        base = recognition_record(self.store.state_records()[0])
        self.store.save_states('pending:test', '기타', [dict(row(characterName=None,dungeonName='기타'))])
        self.store.save_states('test', '테스트', [dict(row(characterName='테스트데이터',dungeonName='테스트'),isTest=True)])
        records, omitted = export_records(self.store)
        self.assertEqual(records, validate_records([row()]))
        self.assertEqual(omitted, 1)

    def test_corrupt_duplicate_keys_and_large_json_rejected(self):
        for body in (b'{', b'\xff', b'[{"gate":1,"gate":2}]', b' ' * (MAX_BYTES + 1)):
            with self.assertRaises(ValueError):
                decode_records(body)


class FakeDrive:
    def __init__(self):
        self.files = {}
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.assert_auth(request)
        if request.method in ('POST', 'PATCH'):
            message = BytesParser(policy=default).parsebytes(
                ('Content-Type: ' + request.headers['Content-type'] + '\r\n\r\n').encode() + request.data)
            parts = list(message.iter_parts())
            metadata = json.loads(parts[0].get_payload(decode=True))
            identity = urlsplit(request.full_url).path.rsplit('/',1)[-1] if request.method == 'PATCH' else str(len(self.files)+1)
            if request.method == 'PATCH':
                metadata = dict(self.files[identity][0], **metadata)
            metadata.update(id=identity, createdTime='2026-09-27T00:00:00Z')
            self.files[metadata['id']] = (metadata, parts[1].get_payload(decode=True))
            return io.BytesIO(json.dumps(metadata).encode())
        query = parse_qs(urlsplit(request.full_url).query)
        if query.get('alt') == ['media']:
            return io.BytesIO(self.files[urlsplit(request.full_url).path.rsplit('/', 1)[-1]][1])
        namespace = 'integration-test' if 'integration-test' in query['q'][0] else 'v1'
        records = [v[0] for v in self.files.values() if v[0]['appProperties']['beatriceRecords'] == namespace]
        if "name = 'PC.json'" in query['q'][0]:
            records = [r for r in records if r['name'] == 'PC.json']
        return io.BytesIO(json.dumps({'files': records[-1:]}).encode())

    @staticmethod
    def assert_auth(request):
        if request.headers.get('Authorization') != 'Bearer fake':
            raise AssertionError('Missing bearer token')


class DriveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)


    def test_empty_intermediate_page_is_followed(self):
        responses = iter([{'files': [], 'nextPageToken': 'next'}, {'files': [{'id': 'found'}]}])
        client = DriveClient('fake', threading.Event(), opener=lambda *a, **k: io.BytesIO(json.dumps(next(responses)).encode()))
        self.assertEqual(client.latest(), {'id': 'found'})

    def test_multiple_uploads_update_pc_only_and_back_up_previous(self):
        fake = FakeDrive()
        client = DriveClient('fake', threading.Event(), opener=fake, backup_directory=self.temp.name)
        first = client.upload([row()])
        second = client.upload([row(state='진행 전')])
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(fake.files), 1)
        self.assertEqual(second['name'], 'PC.json')
        self.assertEqual(client.download()['records'], validate_records([row(state='진행 전')]))
        backups = list(Path(self.temp.name).glob('PC-*.json'))
        self.assertEqual(decode_records(backups[0].read_bytes()), validate_records([row()]))
        self.assertEqual(first['parents'], ['appDataFolder'])
        self.assertEqual(first['appProperties'], {'beatriceRecords': 'v1', 'schemaVersion': '4'})

    def test_ios_and_old_snapshot_files_are_never_replaced(self):
        fake=FakeDrive()
        metadata=dict(id='ios',name='iOS.json',mimeType='application/json',appProperties={'beatriceRecords':'v1','schemaVersion':'2'})
        fake.files['ios']=(metadata,encode_records([row()]))
        client=DriveClient('fake',threading.Event(),opener=fake,backup_directory=self.temp.name)
        first=client.upload([row()]);client.upload([])
        self.assertEqual(fake.files['ios'][1],encode_records([row()]))
        self.assertEqual(client.read(first),[])
        self.assertEqual(len(fake.files),2)

    def test_missing_recovery_directory_prevents_replacement(self):
        fake=FakeDrive()
        client=DriveClient('fake',threading.Event(),opener=fake)
        first=client.upload([row()])
        with self.assertRaises(DriveError):client.upload([])
        self.assertEqual(client.read(first),validate_records([row()]))
        self.assertFalse(any(r.method=='PATCH' for r in fake.requests))

    def test_integration_namespace_not_visible_to_production(self):
        fake = FakeDrive()
        DriveClient('fake', threading.Event(), opener=fake, namespace='integration-test').upload([row()])
        with self.assertRaisesRegex(DriveError, '없습니다'):
            DriveClient('fake', threading.Event(), opener=fake, backup_directory=self.temp.name).download()

    def test_denied_offline_rate_limit_and_oversize(self):
        for error in [HTTPError('url', 403, 'denied', {}, None), HTTPError('url', 429, 'limit', {}, None), URLError('offline')]:
            def fail(*args, **kwargs):
                raise error
            with self.subTest(error=error), self.assertRaises(DriveError):
                DriveClient('fake', threading.Event(), opener=fail).latest()
        client = DriveClient('fake', threading.Event(), opener=lambda *a, **k: io.BytesIO(b'x' * (MAX_BYTES + 1)))
        with self.assertRaises(DriveError):
            client.latest()

    def test_cancel_does_not_send_request(self):
        cancel = threading.Event()
        cancel.set()
        fake = FakeDrive()
        with self.assertRaises(DriveError):
            DriveClient('fake', cancel, opener=fake, backup_directory=self.temp.name).upload([row()])
        self.assertEqual(fake.requests, [])

    def test_failed_upload_keeps_previous_snapshot(self):
        fake = FakeDrive()
        client = DriveClient('fake', threading.Event(), opener=fake, backup_directory=self.temp.name)
        first = client.upload([row()])
        def failing(request, timeout):
            if request.method in ('POST', 'PATCH'):
                raise URLError('offline')
            return fake(request, timeout)
        client.opener = failing
        with self.assertRaises(DriveError):
            client.upload([row(state='진행중')])
        self.assertEqual(client.read(first), validate_records([row()]))

    def test_old_identity_only_token_requires_drive_consent(self):
        saved = dict(client_id='client', refresh_token='refresh', scopes=['openid'])
        with patch('beatrice.google_auth.load_client', return_value={'client_id': 'client'}), \
                patch('beatrice.google_auth.request_json', return_value={'access_token': 'fake', 'scope': 'openid'}):
            with self.assertRaisesRegex(AuthError, 'Drive 권한'):
                drive_access_token('.', saved, threading.Event())

    def test_drive_refresh_and_scope_preserved_on_restore(self):
        saved = dict(client_id='client', refresh_token='refresh', scopes=[DRIVE_SCOPE], account={'sub': 'person'})
        with patch('beatrice.google_auth.load_client', return_value={'client_id': 'client'}), \
                patch('beatrice.google_auth.request_json', return_value={'access_token': 'fake'}):
            self.assertEqual(drive_access_token('.', saved, threading.Event()), 'fake')
        with patch('beatrice.google_auth.load_client', return_value={'client_id': 'client'}), \
                patch('beatrice.google_auth.request_json', side_effect=[{'access_token': 'fake'},
                    {'sub': 'person', 'email': 'test@example.com', 'email_verified': True}]):
            self.assertIn(DRIVE_SCOPE, authenticate('.', saved, threading.Event(), False)['scopes'])

    def test_consent_cannot_switch_account(self):
        saved = dict(account={'sub': 'person', 'email': 'test@example.com'})
        with patch('beatrice.google_auth.load_client', return_value={'client_id': 'client'}), \
                patch('beatrice.google_auth.authorize', return_value={'access_token': 'fake', 'refresh_token': 'refresh'}), \
                patch('beatrice.google_auth.request_json', return_value={'sub': 'other', 'email': 'other@example.com', 'email_verified': True}):
            with self.assertRaises(AuthError):
                authenticate('.', saved, threading.Event(), True)



if __name__ == "__main__": unittest.main()
