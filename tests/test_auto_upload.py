import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from beatrice.auto_upload import AutoUploadSchedule
from beatrice.drive_data import export_snapshot, restore_records
from beatrice.google_auth import DRIVE_SCOPE
from beatrice.storage import Store


def record(gate=1, state='완료', **kwargs):
    return dict(dict(characterName='자동테스트', characterKey='name:자동테스트',
                     dungeonName='던전', difficulty='하드', gate=gate, state=state,
                     timeBasis='live_capture'), **kwargs)


class CompletionQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'records.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.close())

    def save(self, records):
        return self.store.save_states('name:자동테스트', '던전', records)

    def test_progress_does_not_queue_and_completion_queues_once(self):
        self.save([record(state='진행 전')])
        self.save([record(state='진행중')])
        self.assertIsNone(self.store.drive_pending('account'))
        self.save([record()])
        pending = self.store.drive_pending('account')
        self.save([record()])
        self.assertEqual(self.store.drive_pending('account'), pending)
        self.assertEqual(pending[1], 1)

    def test_pending_survives_restart_and_acknowledgment_is_account_specific(self):
        self.save([record()])
        pending = self.store.drive_pending('account')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.drive_pending('account'), pending)
        self.store.acknowledge_drive('account', *pending)
        self.assertIsNone(self.store.drive_pending('account'))
        self.assertEqual(self.store.drive_pending('another'), pending)
        self.store.close()
        self.store = Store(self.path)
        self.assertIsNone(self.store.drive_pending('account'))

    def test_new_completion_during_upload_remains_pending(self):
        self.save([record(), record(2, '진행 전')])
        rows, _, revision = export_snapshot(self.store)
        self.assertEqual([r['gate'] for r in rows], [1])
        self.save([record(), record(2)])
        self.store.acknowledge_drive('account', *revision)
        pending = self.store.drive_pending('account')
        self.assertEqual(pending[1], revision[1] + 1)

    def test_acknowledgments_cannot_move_backwards(self):
        self.save([record(), record(2, '진행 전')])
        old = self.store.drive_revision()
        self.save([record(), record(2)])
        self.store.acknowledge_drive('account', *self.store.drive_revision())
        self.store.acknowledge_drive('account', *old)
        self.assertIsNone(self.store.drive_pending('account'))

    def test_record_and_upload_queue_roll_back_together(self):
        with self.assertRaises(RuntimeError):
            with self.store.db:
                self.store.save_states('name:자동테스트', '던전', [record()], transactional=False)
                raise RuntimeError('abort')
        self.assertEqual(self.store.state_records(), [])
        self.assertIsNone(self.store.drive_pending('account'))

    def test_unidentified_completion_queues_only_when_name_is_confirmed(self):
        self.store.save_states('pending:test', '던전', [record(characterName=None, characterKey=None)])
        self.assertIsNone(self.store.drive_pending('account'))
        self.save([record()])
        self.assertIsNotNone(self.store.drive_pending('account'))

    def test_test_records_do_not_queue(self):
        for i, extra in enumerate((dict(isTest=True), dict(timeBasis='synthetic_test'), dict(difficulty=None))):
            self.store.save_states(str(i), '던전', [record(**extra)])
        self.assertIsNone(self.store.drive_pending('account'))

    def test_clear_and_restore_discard_pending_without_reupload(self):
        self.save([record()])
        old = self.store.drive_revision()
        rows, _, _ = export_snapshot(self.store)
        restore_records(self.store, rows, Path(self.temp.name) / 'backups')
        self.assertIsNone(self.store.drive_pending('account'))
        self.assertNotEqual(self.store.drive_revision()[0], old[0])
        self.store.acknowledge_drive('account', *old)
        self.assertIsNone(self.store.drive_pending('account'))
        self.store.clear_all()
        self.assertIsNone(self.store.drive_pending('account'))

    def test_adding_queue_to_existing_database_does_not_publish_old_records(self):
        self.save([record()])
        self.store.db.executescript('DROP TABLE drive_changes; DROP TABLE drive_uploads;')
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(len(self.store.state_records()), 1)
        self.assertIsNone(self.store.drive_pending('account'))

    def test_snapshot_revision_matches_rows_during_concurrent_completion(self):
        self.save([record(), record(2, '진행 전')])
        from beatrice.drive_data import export_records
        other = Store(self.path)
        self.addCleanup(other.close)
        def concurrent_export(store):
            other.save_states('name:자동테스트', '던전', [record(), record(2)])
            return export_records(store)
        with patch('beatrice.drive_data.export_records', side_effect=concurrent_export):
            rows, _, revision = export_snapshot(self.store)
        self.assertEqual([r['gate'] for r in rows], [1])
        self.assertEqual(revision[1], 1)
        self.assertEqual(self.store.drive_revision()[1], 2)


class ScheduleTests(unittest.TestCase):
    def test_debounce_and_maximum_wait(self):
        scheduler = AutoUploadSchedule()
        for now in range(15):
            self.assertFalse(scheduler.due(('account', 'epoch', now), now))
        self.assertTrue(scheduler.due(('account', 'epoch', 15), 15))
        scheduler.reset()
        self.assertFalse(scheduler.due(('account', 'epoch', 1), 100))
        self.assertFalse(scheduler.due(('account', 'epoch', 1), 102))
        self.assertTrue(scheduler.due(('account', 'epoch', 1), 103))

    def test_retry_backoff_is_capped_and_new_changes_do_not_bypass_it(self):
        scheduler = AutoUploadSchedule()
        scheduler.due(('account', 'epoch', 1), 0)
        self.assertEqual(scheduler.failed(3), 5)
        self.assertFalse(scheduler.due(('account', 'epoch', 2), 4))
        self.assertTrue(scheduler.due(('account', 'epoch', 2), 8))
        self.assertEqual(scheduler.failed(8), 10)
        for _ in range(15):
            delay = scheduler.failed(20)
        self.assertEqual(delay, 300)
        self.assertFalse(scheduler.due(None, 100))
        self.assertEqual(scheduler.failures, 0)


class AutomaticUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from beatrice.google_login_ui import GoogleLogin
        from beatrice.drive_ui import DrivePanel
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'records.sqlite3')
        self.addCleanup(self.store.close)
        self.login = GoogleLogin('.', self.temp.name)
        self.login.session = dict(account={'sub': 'account', 'email': 'test@example.com'}, scopes=[DRIVE_SCOPE])
        self.panel = DrivePanel('.', self.temp.name, self.login, self.store, lambda: False, lambda: None)
        self.addCleanup(self.panel.shutdown)
        self.addCleanup(self.login.shutdown)

    def complete(self):
        self.store.save_states('name:자동테스트', '던전', [record()])

    def test_auto_upload_starts_after_debounce_even_during_analysis(self):
        self.complete()
        with patch.object(self.panel, 'begin') as begin:
            for now in range(3):
                with patch('beatrice.drive_ui.time.monotonic', return_value=now):
                    self.panel.tick()
            begin.assert_not_called()
            with patch('beatrice.drive_ui.time.monotonic', return_value=3):
                self.panel.tick()
            begin.assert_called_once_with('upload', automatic=True)

    def test_no_login_or_permission_or_busy_does_not_send(self):
        self.complete()
        saved = self.login.session
        with patch.object(self.panel, 'begin') as begin:
            self.login.session = None
            self.panel.tick()
            self.login.session = saved
            self.login.session['scopes'] = []
            self.panel.next_scan = 0
            self.panel.tick()
            self.login.session['scopes'] = [DRIVE_SCOPE]
            self.panel.busy = True
            self.panel.next_scan = 0
            self.panel.tick()
            begin.assert_not_called()
        self.assertIsNotNone(self.store.drive_pending('account'))

    def finish_upload(self, error=None):
        results = queue.Queue()
        results.put(({'id': 'file'}, error))
        self.panel.pending = (threading.Event(), results, 'upload', 1, 0, 'account')
        self.panel.upload_revision = self.store.drive_revision()
        self.panel.busy = True
        self.panel.automatic = True
        self.panel.tick()

    def test_success_clears_pending_failure_does_not(self):
        self.complete()
        self.finish_upload('offline')
        self.assertIsNotNone(self.store.drive_pending('account'))
        self.assertIn('재시도', self.panel.label.text())
        self.finish_upload()
        self.assertIsNone(self.store.drive_pending('account'))
        self.assertIn('자동 저장', self.panel.label.text())


if __name__ == '__main__':
    unittest.main()
