"""Headless Google lifecycle regressions: no network or production records."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from beatrice.account_service import GoogleAccount
from beatrice.drive_service import PersonalDrive
from beatrice.drive_data import export_records, validate_records
from beatrice.google_auth import AuthError, DRIVE_SCOPE
from beatrice.storage import Store


def session():
    return dict(account={'sub':'person','email':'test@example.com'},scopes=[DRIVE_SCOPE],refresh_token='fake')


def row(gate=1):
    return dict(characterName='캐릭터',dungeonName='던전',difficulty='하드',gate=gate,state='완료',observedAt='2026-10-08T00:00:00+00:00')


class FakeJob:
    def __init__(self, value=None, error=None):
        self.cancel=threading.Event()
        self.thread=threading.Thread()
        self.value=value;self.error=error
    def result(self):return self.value,self.error


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'records.sqlite3');self.addCleanup(self.store.close)
        self.account=GoogleAccount('.',self.temp.name)
        self.drive=PersonalDrive('.',self.temp.name,self.account,self.store)
        self.addCleanup(self.account.shutdown);self.addCleanup(self.drive.shutdown)

    def seed(self,gate=1):
        self.store.save_completions('name:캐릭터','던전',[row(gate)],2)

    def finish_upload(self,error=None,revision=None):
        self.drive.pending=dict(job=FakeJob({'id':'file'},error),action='upload',account='person',
            revision=revision or self.store.drive_revision(),count=1,omitted=0,automatic=True)
        self.drive.poll()

    def finish_download(self,error=None):
        self.drive.pending=dict(job=FakeJob(dict(records=validate_records([{k:v for k,v in row().items() if k!='observedAt'}]),metadata={'createdTime':'2026-10-08T00:00:00Z'}),error),action='download',account='person')
        self.drive.poll()

    def finish_delete(self,error=None,checkpoint=None):
        self.drive.pending=dict(job=FakeJob(True,error),action='delete',account='person',
            deletion=checkpoint or self.store.drive_deletion_checkpoint())
        self.drive.poll()

    def test_delete_keeps_local_records_and_waits_for_new_completion_across_restart(self):
        self.account.session=session();self.seed()
        before=self.store.history_records()
        self.finish_delete()
        self.assertEqual(self.store.history_records(),before)
        self.assertIsNone(self.store.drive_pending('person'))
        self.assertIsNotNone(self.store.drive_pending('other'))
        reopened=Store(Path(self.temp.name)/'records.sqlite3')
        try:self.assertIsNone(reopened.drive_pending('person'))
        finally:reopened.close()
        # Updating a receipt does not count as a newly completed gate.
        self.store.set_gold_reward(before[0]['recordId'],True)
        self.assertIsNone(self.store.drive_pending('person'))
        self.seed(2)
        self.assertIsNotNone(self.store.drive_pending('person'))

    def test_delete_failure_and_account_change_do_not_suppress_pending_upload(self):
        self.account.session=session();self.seed()
        self.finish_delete('offline')
        self.assertIsNotNone(self.store.drive_pending('person'))
        self.account.session['account']['sub']='other';self.finish_delete()
        self.assertIsNotNone(self.store.drive_pending('person'))

    def test_new_completion_during_delete_is_still_pending_and_shutdown_finishes_delete(self):
        self.account.session=session();self.seed()
        checkpoint=self.store.drive_deletion_checkpoint();self.seed(2)
        self.finish_delete(checkpoint=checkpoint)
        self.assertIsNotNone(self.store.drive_pending('person'))
        self.drive.pending=dict(job=FakeJob(True),action='delete',account='person',deletion=self.store.drive_deletion_checkpoint())
        self.drive.shutdown();self.assertFalse(self.drive.pending['job'].cancel.is_set())
        self.drive.poll();self.assertIsNone(self.store.drive_pending('person'))

    def test_delete_job_dispatches_only_backup_delete_and_blocks_overlap(self):
        self.account.session=session();self.seed()
        from unittest.mock import Mock
        client=Mock();client.delete_backup.return_value=True
        with patch('beatrice.drive_service.drive_access_token',return_value='fake'),patch('beatrice.drive_service.DriveClient',return_value=client):
            self.assertTrue(self.drive.begin('delete'))
            self.assertFalse(self.drive.begin('download'))
            self.drive.pending['job'].thread.join(timeout=2)
            self.drive.poll()
        client.delete_backup.assert_called_once_with();client.upload.assert_not_called();client.download.assert_not_called()

    def test_cancelled_login_result_cannot_save(self):
        job=FakeJob(session());self.account.pending=job
        self.account.cancel()
        self.assertTrue(job.cancel.is_set())
        with patch.object(self.account.tokens,'save') as save:
            self.account.poll();save.assert_not_called()
        self.assertIsNone(self.account.session)
        self.account.shutdown();self.account.restore();self.assertIsNone(self.account.pending)

    def test_login_success_persists_on_poll_then_logout_clears(self):
        self.account.pending=FakeJob(session())
        with patch.object(self.account.tokens,'save') as save:
            self.account.poll();save.assert_called_once_with(session())
        self.assertEqual(self.account.view()['email'],'test@example.com')
        self.account.sign_out();self.assertIsNone(self.account.session)

    def test_failed_token_persistence_does_not_publish_session(self):
        self.account.pending=FakeJob(session())
        with patch.object(self.account.tokens,'save',side_effect=AuthError('failed')):self.account.poll()
        self.assertIsNone(self.account.session)
        self.assertIn('안전하게',self.account.message)

    def test_session_restore_runs_once_and_permission_connect_keeps_account(self):
        saved=session()
        with patch.object(self.account.tokens,'load',return_value=saved),patch.object(self.account,'begin') as begin:
            self.account.restore();self.account.restore();begin.assert_called_once_with(False,saved)
        self.account.session=saved;self.assertTrue(self.account.authorized)
        self.account.session['scopes']=[];self.assertFalse(self.account.authorized)

    def test_protocol_view_contains_no_tokens(self):
        self.account.session=session()
        self.assertNotIn('refresh_token',str(self.account.view()))
        self.assertNotIn('fake',str(self.account.view()))

    def test_automatic_upload_coalesces_completion_and_suppresses_repeat(self):
        self.account.session=session();self.seed()
        with patch.object(self.drive,'begin') as begin:
            for now in range(3):
                with patch('beatrice.drive_service.time.monotonic',return_value=now):self.drive.check_auto_upload()
            begin.assert_not_called()
            with patch('beatrice.drive_service.time.monotonic',return_value=3):self.drive.check_auto_upload()
            begin.assert_called_once_with('upload',automatic=True)
        self.finish_upload();self.seed()
        self.assertIsNone(self.store.drive_pending('person'))

    def test_no_login_permission_or_pending_job_does_not_send(self):
        self.seed()
        with patch.object(self.drive,'begin') as begin:
            self.drive.check_auto_upload()
            self.account.session=session();self.account.session['scopes']=[];self.drive.check_auto_upload()
            self.account.session=session();self.drive.preview={'id':'pending'};self.drive.check_auto_upload()
            begin.assert_not_called()
        self.assertIsNotNone(self.store.drive_pending('person'))

    def test_failed_upload_retains_obligation_and_success_acknowledges_only_snapshot(self):
        self.account.session=session();self.seed()
        self.finish_upload('offline')
        self.assertIsNotNone(self.store.drive_pending('person'));self.assertIn('재시도',self.drive.message)
        revision=self.store.drive_revision();self.seed(2);self.finish_upload(revision=revision)
        self.assertIsNotNone(self.store.drive_pending('person'))
        self.finish_upload();self.assertIsNone(self.store.drive_pending('person'))

    def test_empty_upload_and_missing_permission_never_start_network(self):
        with patch('beatrice.drive_service.Job') as job:
            self.assertFalse(self.drive.begin('upload'))
            self.account.session=session();self.assertFalse(self.drive.begin('upload'));job.assert_not_called()
        self.assertIn('빈 기록',self.drive.message)

    def test_preview_cancel_and_network_error_preserve_local_rows(self):
        self.account.session=session();self.seed(2)
        self.finish_download();preview=self.drive.preview_view()
        self.assertEqual(preview['completedCount'],1)
        self.assertFalse(self.drive.resolve('stale',True))
        self.assertTrue(self.drive.resolve(preview['previewId'],False))
        self.assertEqual(self.store.state_records()[0]['gateNumber'],2)
        self.finish_download('offline');self.assertIsNone(self.drive.preview)
        self.assertEqual(self.store.state_records()[0]['gateNumber'],2)

    def test_restore_replaces_snapshot_and_backs_up_previous_db(self):
        self.account.session=session();self.seed(2);self.finish_download()
        preview_id=self.drive.preview['id'];self.assertTrue(self.drive.resolve(preview_id,True))
        self.assertEqual(self.store.state_records()[0]['gateNumber'],1)
        self.assertEqual(export_records(self.store)[0][0]['characterName'],'캐릭터')
        self.assertTrue(list((Path(self.temp.name)/'drive-backups').glob('*.sqlite3')))
        self.assertIsNone(self.store.drive_pending('person'))

    def test_wrong_account_and_backup_failure_never_apply(self):
        self.account.session=session();self.seed(2);self.finish_download()
        self.account.session['account']['sub']='other';self.drive.resolve(self.drive.preview['id'],True)
        self.assertEqual(self.store.state_records()[0]['gateNumber'],2)
        self.account.session=session();self.finish_download()
        with patch('beatrice.drive_service.restore_records',side_effect=OSError('backup failure')):
            self.drive.resolve(self.drive.preview['id'],True)
        self.assertEqual(self.store.state_records()[0]['gateNumber'],2)

    def test_shutdown_finishes_upload_and_ignores_download_result(self):
        self.account.session=session();self.seed()
        self.drive.pending=dict(job=FakeJob({'id':'file'}),action='upload',account='person',revision=self.store.drive_revision(),count=1,omitted=0,automatic=True)
        self.drive.shutdown();self.assertFalse(self.drive.pending['job'].cancel.is_set());self.drive.poll()
        self.assertIsNone(self.store.drive_pending('person'));self.assertTrue(self.drive.settled)
        self.finish_download();self.assertIsNone(self.drive.preview)


if __name__=='__main__':unittest.main()
