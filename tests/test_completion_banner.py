import copy
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from beatrice.live import LiveCoordinator
from beatrice.storage import Store
from beatrice.completion_banner import CompletionBanner


class CompletionBannerTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close)
        self.live=LiveCoordinator(self.store)
        self.live.identity.current='캐릭터';self.live.identity.blocked=False
        self.at=datetime(2026,9,24,tzinfo=timezone.utc)

    def feed(self,states=('진행중','진행 전'),banner=False,kind='gated',fresh=True,status='ocr_verified',count=1,name='던전'):
        for _ in range(count):
            self.at+=timedelta(seconds=1)
            boxes=[dict(state=s,confidence=.99,xyxy=[40+i*60,130,80+i*60,180]) for i,s in enumerate(states)]
            result=self.live.update(self.at,{},boxes,dict(dungeonName=name,difficulty='하드',
                contextStatus=status,raidBounds=[500,400,900,480],raidKind=kind,currentRaidPanel=fresh,completionOverlay=dict(status='verified',kind='dungeon_clear' if kind=='gateless' else 'gate_breakthrough',gate=None if kind=='gateless' else 1) if banner else {}))
        return result

    def states(self):return [r['gateNumber'] for r in self.store.state_records()]

    def test_banner_requests_fresh_icons_without_saving(self):
        self.feed(count=3)
        result=self.feed(states=(),banner=True,count=2)
        self.assertEqual(self.states(),[])
        self.assertTrue(result['result']['gateRecheckRequested'])
        self.feed(states=('완료','진행중'),count=2)
        self.assertEqual(self.states(),[])
        result=self.feed(states=('완료','진행중'))
        self.assertEqual(self.states(),[1])
        self.assertEqual(self.store.state_records()[0]['gateNumber'],1)
        self.assertFalse(result['result']['gateRecheckPending'])

    def test_single_gate_still_requires_completed_icon(self):
        self.feed(states=('진행중',),count=3)
        self.feed(states=(),banner=True,count=3)
        self.assertEqual(self.states(),[])
        self.feed(states=('완료',),count=3)
        self.assertEqual(self.states(),[1])

    def test_recheck_expires_and_normal_icon_polling_continues(self):
        self.feed(count=3)
        self.feed(states=(),banner=True,count=2)
        self.at+=timedelta(seconds=11)
        result=self.feed(states=(),fresh=False,status='ocr_held')
        self.assertFalse(result['result']['gateRecheckPending'])
        self.assertEqual(self.states(),[])
        self.feed(states=('완료','진행중'),count=3)
        self.assertEqual(self.states(),[1])

    def test_capture_interruption_cancels_recheck(self):
        self.feed(count=3)
        self.feed(states=(),banner=True,count=2)
        self.live.capture_interrupted()
        self.assertIsNone(self.live.gate_recheck)
        self.assertEqual(self.states(),[])

    def test_other_header_cancels_recheck(self):
        self.feed(count=3)
        self.feed(states=(),banner=True,count=2)
        result=self.feed(states=(),name='다른 던전')
        # A current OCR title without icons cannot reuse the old context.
        self.assertFalse(result['result']['gateRecheckPending'])
        self.assertEqual(self.states(),[])

    def test_long_banner_cannot_complete_next_gate_after_icon_advance(self):
        self.feed(count=3)
        self.feed(states=('완료','진행중'),banner=True,count=8)
        self.assertEqual(self.states(),[1])
        count=self.store.db.total_changes
        self.feed(states=('완료','진행중'),banner=True,count=5)
        self.assertEqual(self.store.db.total_changes,count)

    def test_icon_only_and_later_banner_do_not_duplicate_completed_row(self):
        self.feed(count=3)
        self.feed(states=('완료','진행 전'),count=3)
        before=copy.deepcopy(self.store.state_records()[0])
        self.feed(states=('완료','진행 전'),banner=True,count=3)
        self.assertEqual(self.store.state_records()[0],before)

    def test_gateless_uses_banner_and_raid_scope_not_missing_gate_heuristic(self):
        self.feed(states=(),kind='gateless',count=3)
        self.assertEqual(self.states(),[])
        self.feed(states=(),kind='gateless',banner=True,count=2)
        self.assertEqual(self.states(),[0])
        self.assertEqual(self.store.state_records()[0]['gateNumber'],0)
        self.assertEqual(self.store.state_records()[0]['expectedGates'],0)

    def test_cutscene_can_use_confirmed_context(self):
        self.feed(count=3)
        result=self.feed(states=(),banner=True,fresh=False,status='ocr_held',count=2)
        self.assertEqual(self.states(),[])
        self.assertTrue(result['result']['gateRecheckRequested'])

    def test_old_quest_banner_is_not_a_completion_signal(self):
        self.feed(count=3)
        for _ in range(3):
            self.at+=timedelta(seconds=1)
            self.live.update(self.at,{},[],dict(completionBanner=True))
        self.assertEqual(self.states(),[])

    def test_single_frame_banner_does_not_save(self):
        self.feed(count=3)
        self.feed(banner=True)
        self.feed(count=3)
        self.assertEqual(self.states(),[])

    def test_missing_frame_restarts_confirmation_without_retargeting(self):
        banner=CompletionBanner()
        self.assertIsNone(banner.update(0,True,True,'first'))
        self.assertIsNone(banner.update(1,False,True,'first'))
        self.assertIsNone(banner.update(2,True,True,'first'))
        self.assertEqual(banner.update(3,True,True,'first'),'first')
        banner.commit()
        banner.update(4,False,True,'second')
        self.assertIsNone(banner.update(5,True,True,'second'))

    def test_explicit_gate_number_does_not_guess_from_progress(self):
        self.feed(states=('진행중','진행중'),count=3)
        result=self.feed(states=(),banner=True,count=3)
        self.assertEqual(self.states(),[])
        self.assertTrue(result['result']['gateRecheckPending'])

    def test_expired_context_cannot_supply_a_target(self):
        self.feed(count=3)
        self.at+=timedelta(seconds=121)
        self.feed(states=(),banner=True,fresh=False,status='ocr_held',count=3)
        self.assertEqual(self.states(),[])

    def test_fresh_matching_header_recovers_expired_context_without_icons(self):
        self.feed(count=3)
        self.at+=timedelta(seconds=121)
        self.feed(states=(),fresh=False,status='ocr_held')
        self.assertIsNone(self.live.completion_context)
        result=self.feed(states=(),banner=True,count=2)
        self.assertEqual(self.states(),[])
        self.assertTrue(result['result']['gateRecheckRequested'])

    def test_fresh_other_header_cannot_recover_expired_context_without_icons(self):
        self.feed(count=3)
        self.at+=timedelta(seconds=121)
        self.feed(states=(),banner=True,name='다른 던전',count=3)
        self.assertEqual(self.states(),[])

    def test_different_preview_invalidates_context_before_display_changes(self):
        self.feed(count=3)
        for _ in range(3):
            self.at+=timedelta(seconds=1)
            self.live.update(self.at,{},[],dict(dungeonName='던전',difficulty='하드',contextStatus='ocr_held',
                preview=dict(dungeonName='다른 던전',difficulty='하드'),
                completionOverlay=dict(status='verified',kind='dungeon_clear',gate=None)))
        self.assertEqual(self.states(),[])

    def test_generic_clear_does_not_guess_last_gate_or_backfill(self):
        self.feed(states=('진행중','진행 전','진행 전'),count=3)
        for _ in range(2):
            self.at+=timedelta(seconds=1)
            self.live.update(self.at,{},[],dict(completionOverlay=dict(status='verified',kind='dungeon_clear',gate=None)))
        self.assertEqual(self.states(),[])
        self.assertTrue(self.live.gate_recheck)
        self.assertIsNone(self.live.update(self.at+timedelta(seconds=1),{},[],{})['result']['completionDecision']['gate'])

    def test_gate_number_outside_confirmed_array_is_rejected(self):
        self.feed(count=3)
        for _ in range(3):
            self.at+=timedelta(seconds=1)
            self.live.update(self.at,{},[],dict(completionOverlay=dict(status='verified',kind='gate_breakthrough',gate=3)))
        self.assertEqual(self.states(),[])

    def test_unconfirmed_banner_is_discarded_and_new_banner_is_required(self):
        self.live.identity.current=None;self.live.identity.blocked=True
        self.feed(kind='gateless',count=3);self.feed(states=(),kind='gateless',banner=True,count=2)
        self.assertEqual(self.store.state_records(),[])
        for _ in range(3):
            self.at+=timedelta(seconds=1)
            self.live.update(self.at,dict(normalMenu=True,currentName=dict(text='새캐릭터',confidence=.99)),[],{})
        self.assertEqual(self.store.state_records(),[])
        self.feed(kind='gateless',count=3)
        self.feed(states=(),kind='gateless',banner=True,count=2)
        rows=self.store.state_records()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['characterName'],'새캐릭터')
        self.assertEqual(rows[0]['gateNumber'],0)

    def test_banner_failure_rolls_back_and_can_retry(self):
        self.feed(kind='gateless',count=3)
        self.store.db.execute("CREATE TEMP TRIGGER reject_banner BEFORE INSERT ON gate_states BEGIN SELECT RAISE(ABORT,'failure'); END")
        self.feed(states=(),kind='gateless',banner=True)
        with self.assertRaises(sqlite3.IntegrityError):self.feed(states=(),kind='gateless',banner=True)
        self.assertEqual(self.states(),[])
        self.assertFalse(self.live.banner.consumed)
        self.store.db.execute('DROP TRIGGER reject_banner')
        self.feed(states=(),kind='gateless',banner=True)
        self.assertEqual(self.states(),[0])

    def test_gateless_cannot_replace_known_multigate_raid(self):
        self.feed(count=3)
        self.feed(states=(),kind='gateless',banner=True,count=4)
        self.assertEqual(self.states(),[])

    def test_banner_arriving_after_icons_advance_does_not_complete_next_gate(self):
        self.feed(count=3)
        self.feed(states=('완료','진행중'),count=3)
        before=copy.deepcopy(self.store.state_records())
        self.feed(states=('완료','진행중'),banner=True,count=6)
        self.assertEqual(self.store.state_records(),before)

    def test_banner_waits_for_same_current_header_but_cannot_cross_scenes(self):
        for same in (True,False):
            banner=CompletionBanner()
            banner.update(0,True,False,None,scene='A')
            self.assertIsNone(banner.update(1,True,True,'gate',scene='A' if same else 'B'))
            result=banner.update(2,True,True,'gate',scene='A' if same else 'B')
            self.assertEqual(result,'gate' if same else None)

    def test_character_switch_invalidates_visible_banner_target(self):
        self.feed(count=3);self.feed(states=(),banner=True)
        before=self.store.state_records()
        self.at+=timedelta(seconds=1)
        # 실제 UI 분석기의 확인된 캐릭터 전환 신호를 전달합니다.
        self.live.update(self.at,dict(switchDialog=True,targetName=dict(text='다른캐릭터',confidence=.99)),[],{})
        self.at+=timedelta(seconds=1)
        self.live.update(self.at,dict(switchLoading=True),[],{})
        self.feed(states=(),banner=True,count=3)
        self.assertEqual(self.store.state_records(),before)

if __name__=='__main__':unittest.main()
