import copy
import json
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from beatrice.storage import Store
from beatrice.live import LiveCoordinator
from beatrice.dungeon import DungeonTracker,key


class StatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close)
        self.live=LiveCoordinator(self.store);self.time=0
        self.now=datetime(2026,9,23,tzinfo=timezone.utc)

    def feed(self,states,count=4,name='캐릭터',dungeon='던전',mode='하드'):
        for _ in range(count):
            self.time+=1
            boxes=[dict(state=s,confidence=.99,xyxy=[40+i*40,130,65+i*40,170]) for i,s in enumerate(states)]
            result=self.live.update(self.now+timedelta(seconds=self.time),dict(currentName=dict(text=name,confidence=.99)),boxes,
                dict(dungeonName=dungeon,difficulty=mode,contextStatus='ocr_verified'))
        return result

    def test_whole_n_gate_snapshot_updates_in_place_and_backfills(self):
        self.feed(['완료','진행중','진행 전','진행 전','진행 전'])
        first=self.store.state_records();self.assertEqual(len(first),5)
        self.assertEqual([r['state'] for r in first],['완료','진행중','진행 전','진행 전','진행 전'])
        self.feed(['완료','진행 전','진행 전','완료','진행중'])
        rows=self.store.state_records();self.assertEqual(len(rows),5)
        self.assertEqual([r['state'] for r in rows],['완료']*4+['진행중'])
        self.assertEqual(rows[0],first[0])
        self.assertEqual(rows[1]['evidenceType'],'later_gate_completion')
        self.assertIsNone(rows[1]['completedAt'])
        self.assertEqual(rows[3]['evidenceType'],'direct')
        self.assertEqual(self.store.records(),[])  # 새 누적 이벤트는 생성하지 않습니다.

    def test_completed_rows_survive_restart_mode_change_and_regression(self):
        self.feed(['완료','완료','진행중'])
        before=self.store.state_records()
        self.live=LiveCoordinator(self.store)
        self.feed(['진행 전','진행중','진행 전'],count=6,mode='노말')
        rows=self.store.state_records();self.assertEqual(len(rows),3)
        self.assertEqual(rows[:2],before[:2]);self.assertEqual(rows[2]['state'],'진행 전')
        self.store.clear_all();self.live=LiveCoordinator(self.store)
        self.feed(['진행 전','진행중','진행 전'])
        self.assertEqual(self.store.state_records()[0]['state'],'진행 전')

    def test_partial_or_single_changed_frame_does_not_update_snapshot(self):
        self.feed(['진행중','진행 전','진행 전'])
        before=self.store.state_records()
        self.feed(['완료','진행중'],count=4)
        self.assertEqual(self.store.state_records(),before)
        self.feed(['완료','진행중','진행 전'],count=1)
        self.assertEqual(self.store.state_records(),before)

    def test_transaction_rolls_back_all_rows_on_failure(self):
        self.feed(['진행중','진행 전','진행 전'])
        before=self.store.state_records();rows=copy.deepcopy(before)
        for row in rows:row['state']='완료'
        self.store.db.execute("CREATE TEMP TRIGGER fail_gate BEFORE UPDATE ON gate_states WHEN NEW.gate=3 BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.save_states('name:캐릭터',key('던전'),rows)
        self.assertEqual(self.store.state_records(),before)

    def test_unchanged_snapshot_does_not_write_again(self):
        self.feed(['완료','진행중'])
        count=self.store.db.total_changes
        self.feed(['완료','진행중'],count=10)
        self.assertEqual(self.store.db.total_changes,count)

    def test_incomplete_pending_snapshot_cannot_overwrite_known_full_snapshot(self):
        from beatrice.state_session import StateSession
        self.feed(['완료','진행중','진행 전'])
        before=self.store.state_records()
        session=StateSession(self.store);pending_owner=session.owner
        self.store.save_states(pending_owner,key('던전'),
            [dict(before[0],characterKey=None,characterName=None,state='진행중')])
        session.prepare_pending_run('pending',1)
        session.confirm_character('name:캐릭터','캐릭터','pending',1)
        self.assertEqual(self.store.state_records('name:캐릭터'),before)
        self.assertEqual(len(self.store.state_records(pending_owner)),1)

    def test_legacy_later_completion_backfills_without_inventing_direct_time(self):
        self.feed(['진행 전','진행 전','완료'])
        # 옛 완료 이벤트만 변환된 DB에는 앞선 관문의 행이 없을 수 있습니다.
        with self.store.db:self.store.db.execute('DELETE FROM gate_states WHERE gate<3')
        self.live=LiveCoordinator(self.store)
        self.feed(['진행중','진행 전','진행 전'],count=6)
        rows=self.store.state_records()
        self.assertEqual([r['state'] for r in rows],['완료']*3)
        for row in rows[:2]:
            self.assertEqual(row['evidenceType'],'later_gate_completion')
            self.assertIsNone(row['completedAt'])


class DungeonTransitionTests(unittest.TestCase):
    def reading(self,name):return dict(dungeonName=dict(text=name,confidence=.99),difficulty=dict(text='하드',confidence=.99))

    def test_new_pair_after_ui_absence_does_not_wait_ten_seconds(self):
        t=DungeonTracker(max_gap=5)
        for i in range(3):t.update(i,self.reading('A 던전'))
        for i in (3,4):t.update(i,dict(transitionSignal=True))
        for i in (5,6):self.assertEqual(t.update(i,self.reading('B 던전'))['contextStatus'],'ocr_held')
        result=t.update(7,self.reading('B 던전'))
        self.assertEqual(result['dungeonName'],'B 던전');self.assertTrue(result['transitionConfirmed'])

    def test_black_screen_alone_and_same_dungeon_return_do_not_reset(self):
        t=DungeonTracker(max_gap=5)
        for i in range(3):t.update(i,self.reading('A 던전'))
        for i in (3,4):self.assertEqual(t.update(i,dict(transitionSignal=True))['dungeonName'],'A 던전')
        self.assertEqual(t.update(5,self.reading('A 던전'))['contextStatus'],'ocr_verified')
        for i in (6,7,8):
            result=t.update(i,self.reading('B 던전'));self.assertFalse(result['transitionConfirmed'])
            self.assertEqual(result['dungeonName'],'A 던전')


if __name__=='__main__':unittest.main()
