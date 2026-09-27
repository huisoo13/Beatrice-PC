import threading
import unittest
from unittest.mock import Mock
from beatrice.process_watch import ProcessWatch


class ProcessWatchTests(unittest.TestCase):
    def run_snapshots(self,values):
        states=[];snapshot=Mock(side_effect=values)
        watch=ProcessWatch(lambda *state:states.append(state),snapshot=snapshot)
        watch.stop_event=Mock()
        watch.stop_event.is_set.return_value=False
        watch.stop_event.wait.side_effect=[False]*(len(values)-1)+[True]
        watch.run()
        self.assertTrue(watch.ready.is_set())
        self.assertEqual(watch.stop_event.wait.call_args_list[0].args,(1.0,))
        return states,snapshot

    def test_immediate_snapshot_then_poll_for_start_and_stop(self):
        states,snapshot=self.run_snapshots([set(),{10},{10},set()])
        self.assertEqual(snapshot.call_count,4)
        self.assertEqual(states,[(frozenset(),''),(frozenset({10}),''),(frozenset(),'')])

    def test_error_is_reported_and_next_poll_recovers(self):
        states,_=self.run_snapshots([{10},OSError('unavailable'),{20}])
        self.assertEqual(states[1][0],frozenset())
        self.assertIn('자동 재시도',states[1][1])
        self.assertEqual(states[-1],(frozenset({20}),''))

    def test_stop_interrupts_wait_and_fresh_watcher_queries_immediately(self):
        first=Mock(return_value={10});second=Mock(return_value={20})
        states=[]
        for snapshot in (first,second):
            watch=ProcessWatch(lambda *state:states.append(state),snapshot=snapshot,interval=60)
            watch.start()
            try:self.assertTrue(watch.ready.wait(2))
            finally:watch.stop_event.set();watch.join(2)
            self.assertFalse(watch.is_alive())
            snapshot.assert_called_once()
        self.assertEqual(states,[(frozenset({10}),''),(frozenset({20}),'')])

    def test_stop_during_snapshot_discards_result(self):
        entered=threading.Event();release=threading.Event();callback=Mock()
        def snapshot():entered.set();release.wait(2);return {10}
        watch=ProcessWatch(callback,snapshot=snapshot);watch.start()
        try:
            self.assertTrue(entered.wait(2));watch.stop_event.set()
        finally:release.set();watch.join(2)
        self.assertFalse(watch.is_alive());callback.assert_not_called()

    def test_already_stopped_does_not_query(self):
        snapshot=Mock();watch=ProcessWatch(Mock(),snapshot=snapshot)
        watch.stop_event.set();watch.run();snapshot.assert_not_called()


if __name__=='__main__':unittest.main()
