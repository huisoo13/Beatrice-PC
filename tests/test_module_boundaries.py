"""Atomicity, cancellation and retained state across module boundaries."""
import queue
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from beatrice.storage import Store
from beatrice.character import CharacterTracker
from beatrice.dungeon import DungeonTracker
from beatrice.completion_banner import CompletionBanner
from beatrice.catalog_service import CatalogService
from tools.evaluation_geometry import iou

class PersistenceBoundaryTests(unittest.TestCase):
    def test_failed_replacement_preserves_history_and_upload_obligation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'records.sqlite3')
            try:
                row = dict(characterName='캐릭터', dungeonName='던전', difficulty='하드',
                    gate=1, state='완료', observedAt='2026-10-08T00:00:00Z')
                store.save_completions('name:캐릭터', '던전', [row], 1)
                before, revision = store.history_records(), store.drive_revision()
                with patch.object(store, 'import_completion', side_effect=sqlite3.IntegrityError('write failed')):
                    with self.assertRaises(sqlite3.IntegrityError):
                        store.replace_history([dict(before[0], characterKey='name:캐릭터')])
                self.assertEqual(store.history_records(), before)
                self.assertEqual(store.drive_revision(), revision)
                self.assertEqual(store.drive_pending('account'), revision)
            finally:
                store.close()

    def test_failed_assignment_rolls_back_all_pending_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'records.sqlite3')
            try:
                for dungeon in ('던전A', '던전B'):
                    store.save_completions('pending:token', dungeon, [dict(characterName=None,
                        dungeonName=dungeon, difficulty='하드', gate=1, state='완료',
                        observedAt='2026-10-08T00:00:00Z')], 1)
                before = store.state_records()
                save, count = store.save_completions, 0
                def fail_second(*args, **kwargs):
                    nonlocal count
                    count += 1
                    if count == 2: raise sqlite3.IntegrityError('second group failed')
                    return save(*args, **kwargs)
                with patch.object(store, 'save_completions', side_effect=fail_second):
                    with self.assertRaises(sqlite3.IntegrityError):
                        store.assign_pending_character('pending:token', 'name:캐릭터', '캐릭터')
                self.assertEqual(store.state_records(), before)
                self.assertEqual(store.state_records('name:캐릭터'), [])
            finally:
                store.close()

class InterruptionBoundaryTests(unittest.TestCase):
    def test_character_keeps_identity_and_clears_partial_evidence(self):
        tracker = CharacterTracker()
        tracker.current, tracker.blocked, tracker.candidate = '캐릭터', False, '다른캐릭터'
        tracker.count = tracker.login_count = tracker.login_recovery = tracker.recovery_count = 2
        tracker.capture_interrupted()
        self.assertEqual(tracker.current, '캐릭터')
        self.assertFalse(tracker.blocked)
        self.assertIsNone(tracker.candidate)
        self.assertEqual((tracker.count,tracker.login_count,tracker.login_recovery,tracker.recovery_count),(0,0,0,0))

    def test_dungeon_keeps_title_and_clears_partial_evidence(self):
        tracker = DungeonTracker()
        tracker.confirmed = dict(dungeonName='던전', difficulty='하드')
        tracker.counts = {field:2 for field in tracker.counts}
        tracker.replacement, tracker.replacement_since, tracker.last = ('새던전','노말'),10,10
        tracker.capture_interrupted()
        self.assertEqual(tracker.confirmed, dict(dungeonName='던전', difficulty='하드'))
        self.assertTrue(all(value==0 for value in tracker.counts.values()))
        self.assertIsNone(tracker.last)
        self.assertIsNone(tracker.replacement)

    def test_consumed_banner_remains_consumed(self):
        banner = CompletionBanner()
        banner.update(1,True,True,'gate','scene')
        self.assertEqual(banner.update(2,True,True,'gate','scene'),'gate')
        banner.commit();banner.capture_interrupted()
        self.assertIsNone(banner.update(3,True,True,'gate','scene'))
        self.assertIsNone(banner.update(4,True,True,'gate','scene'))
        self.assertTrue(banner.consumed)

class CatalogBoundaryTests(unittest.TestCase):
    def service(self, folder):
        with patch('beatrice.catalog_service.load_settings',return_value={'refreshSeconds':300}):
            with patch('beatrice.catalog_service.ContentCache') as cache:
                cache.return_value.load.return_value = {'checkedAt':'old','content':{'던전':{'하드':{'1관문':{'gold':100,'fee':0,'bound_percentage':0}}}}}
                return CatalogService(folder,folder)

    def test_cancelled_result_cannot_overwrite_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self.service(folder)
            previous = service.cached
            cancel, replies = threading.Event(),queue.Queue()
            service.pending = cancel,replies
            service.stop();replies.put(({'checkedAt':'late','content':{}},None))
            self.assertTrue(cancel.is_set())
            self.assertFalse(service.poll())
            self.assertIs(service.cached,previous)
            service.cache.save.assert_not_called()

    def test_cache_failure_retains_previous_matcher_and_data(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self.service(folder)
            previous, matcher = service.cached,service.matcher
            replies = queue.Queue();replies.put(({'checkedAt':'new','content':{}},None))
            service.pending = threading.Event(),replies
            service.cache.save.side_effect = OSError('disk full')
            self.assertTrue(service.poll())
            self.assertIs(service.cached,previous)
            self.assertIs(service.matcher,matcher)
            self.assertTrue(service.startup_finished)

    def test_manual_deadline_survives_new_service(self):
        with tempfile.TemporaryDirectory() as folder:
            service = self.service(folder)
            with patch('beatrice.catalog_service.time.time',return_value=1000):service.reserve_manual_refresh()
            self.assertEqual(self.service(folder).refresh_available_at,1300)

class EvaluationGeometryTests(unittest.TestCase):
    def test_overlap_disjoint_and_zero_area(self):
        self.assertEqual(iou([0,0,2,2],[0,0,2,2]),1)
        self.assertAlmostEqual(iou([0,0,2,2],[1,1,3,3]),1/7)
        self.assertEqual(iou([0,0,1,1],[2,2,3,3]),0)
        self.assertEqual(iou([0,0,0,0],[0,0,0,0]),0)
