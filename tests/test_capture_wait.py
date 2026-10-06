import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from beatrice.desktop import Worker
from beatrice.dungeon import DungeonTracker
from beatrice.live import LiveCoordinator
from beatrice.storage import Store


class CaptureWaitTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close)
        self.live=LiveCoordinator(self.store)
        self.worker=Worker();self.status=[]
        self.worker.status.connect(lambda generation,reason:self.status.append(reason))
        self.character=Mock();self.observer=Mock();self.tracker=DungeonTracker(max_gap=5)
        self.pause=patch.object(self.worker.stop_event,'wait',return_value=False)
        self.wait=self.pause.start();self.addCleanup(self.pause.stop)
        self.now=datetime(2026,10,6,tzinfo=timezone.utc)
        self.name=dict(currentName=dict(text='테스트',confidence=.99))

    def feed(self,seconds):
        return self.live.update(self.now+timedelta(seconds=seconds),self.name,[],{})

    def handle(self,kind,reason='대기'):
        self.worker.capture_wait(SimpleNamespace(wait_kind=kind),reason,1,
                                 self.character,self.tracker,self.observer,self.live)

    def test_short_wait_preserves_confirmation_and_does_not_publish_pause(self):
        self.feed(0);self.feed(.5)
        self.tracker.counts={field:2 for field in self.tracker.counts}
        self.live.banner.count=2
        self.handle('transient')
        self.assertEqual(self.status,[])
        self.assertEqual(self.live.banner.count,2)
        self.assertTrue(all(value==2 for value in self.tracker.counts.values()))
        self.character.reset_name_cache.assert_not_called()
        self.observer.reset.assert_not_called()
        self.wait.assert_called_once_with(.01)
        self.assertEqual(self.feed(1)['identity']['currentName'],'테스트')

    def test_real_outage_breaks_confirmation_and_notifies_once(self):
        self.feed(0);self.feed(.5)
        self.handle('interrupted','공급 중단');self.handle('interrupted','공급 중단')
        self.assertEqual(self.status,['공급 중단'])
        self.character.reset_name_cache.assert_called_once()
        self.observer.reset.assert_called_once()
        self.assertIsNone(self.feed(1)['identity']['currentName'])
        self.feed(1.5)
        self.assertEqual(self.feed(2)['identity']['currentName'],'테스트')

    def test_confirmed_owner_is_preserved_but_completion_candidate_is_cleared(self):
        for seconds in (0,.5,1):self.feed(seconds)
        self.live.banner.count=2;self.live.banner.consumed=True
        self.handle('interrupted','검은 프레임')
        self.assertEqual(self.live.identity.current,'테스트')
        self.assertEqual(self.live.banner.count,0)
        self.assertTrue(self.live.banner.consumed)
        self.assertEqual(self.store.state_records(),[])
