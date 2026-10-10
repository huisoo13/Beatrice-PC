import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from beatrice.content_match import ContentMatcher, FileContentMatcher, record_detail
from beatrice.public_content import ContentCache
from beatrice.storage import Store
from beatrice.dungeon import key
from beatrice.drive_data import export_records, encode_records, decode_records
from beatrice.live import LiveCoordinator


NAME = '4막: 파멸의 성채'
TYPO = '4막 : 파멸의 성체'
VALUES = dict(gold=10000, fee=3200, bound_percentage=.5)
CACHED = dict(metadata=dict(id='content', version='2', md5Checksum='a'*32),
              content={NAME: {'싱글 모드': {'1관문': VALUES, '2관문': VALUES}}})


def row(name=TYPO, mode='싱글모드', gate=1):
    return dict(characterName='캐릭터', dungeonName=name, difficulty=mode, gate=gate,
                state='완료', observedAt='2026-09-28T01:00:00+00:00', timeBasis='live_capture')


class ContentMatchTests(unittest.TestCase):
    def setUp(self):
        self.matcher = ContentMatcher(CACHED)
        self.store = Store(':memory:', catalog=lambda: self.matcher)
        self.addCleanup(self.store.close)

    def save(self, record):
        return self.store.save_completions('name:캐릭터', key(record['dungeonName']), [record], 2)

    def test_normalized_and_unique_typo_map_all_three_keys(self):
        for name in (NAME, '4막 파멸의 성채', TYPO):
            value = self.matcher.record(row(name))
            self.assertEqual((value['dungeonName'], value['difficulty'], value['gateName']),
                             (NAME, '싱글 모드', '1관문'))
            self.assertEqual(value['ocrOriginal']['dungeonName'], name)
            self.assertEqual(value['catalogMatch']['version']['version'], '2')

    def test_name_conversion_is_independent_of_reward_match(self):
        multiple = copy.deepcopy(CACHED)
        multiple['content']['4막: 파멸의 성쵸'] = multiple['content'][NAME]
        matcher = ContentMatcher(multiple)
        self.assertEqual(matcher.record(row())['catalogMatch']['status'], 'ambiguous')
        cases = [row('1막: 파멸의 성채'), row(mode='알수없음'), row(gate=3), row('미등록 던전')]
        for source in cases:
            result = self.matcher.record(source)
            self.assertEqual(result['catalogMatch']['status'], 'unmatched')
            expected_name = NAME if source['dungeonName'] == TYPO else source['dungeonName']
            self.assertEqual(result['dungeonName'], expected_name)
            for field in ('difficulty','gate'):
                self.assertEqual(result[field],source[field])
        self.assertEqual(ContentMatcher().record(row())['dungeonName'], TYPO)

    def test_exact_priority_and_normalized_duplicate_is_ambiguous(self):
        multiple = copy.deepcopy(CACHED)
        multiple['content']['4막: 파멸의 성쵸'] = multiple['content'][NAME]
        self.assertEqual(ContentMatcher(multiple).record(row(NAME))['catalogMatch']['status'], 'matched')
        multiple['content']['4막 파멸의 성채'] = multiple['content'][NAME]
        self.assertEqual(ContentMatcher(multiple).record(row(NAME))['catalogMatch']['status'], 'ambiguous')

    def test_db_canonical_identity_dedup_lock_and_drive_contract(self):
        first = self.save(row())[0]
        self.assertEqual(first['dungeonName'], NAME)
        self.assertEqual(self.save(row(NAME)), [])
        self.assertEqual(self.save(row('4막 파멸의 성채')), [])
        self.assertEqual(self.store.state_records(), [first])
        self.assertEqual(len(self.store.state_records('name:캐릭터', key(TYPO))), 1)
        exported, _ = export_records(self.store)
        self.assertEqual(decode_records(encode_records(exported))[0]['dungeonName'], NAME)
        self.assertEqual(exported[0]['gate'], 1)

    def test_offline_save_then_catalog_download_does_not_duplicate_or_rewrite(self):
        self.matcher = ContentMatcher()
        first = self.save(row())[0]
        self.matcher = ContentMatcher(CACHED)
        self.assertEqual(self.save(row(NAME)), [])
        self.assertEqual(self.store.state_records(), [first])
        self.assertEqual(record_detail(first,CACHED)['status'], 'unmatched')

    def test_pending_promotion_backfill_and_banner_use_matching(self):
        live = LiveCoordinator(self.store)
        now = datetime(2026,9,28,tzinfo=timezone.utc)
        context = dict(dungeonName=TYPO,difficulty='싱글모드',contextStatus='ocr_verified')
        boxes = [dict(state='완료', confidence=.99,xyxy=[i*40,0,i*40+20,20]) for i in range(2)]
        for i in range(7):live.update(now+timedelta(seconds=i),{},boxes,context)
        self.assertEqual(len(self.store.state_records()),2)
        for i in range(7,11):
            live.update(now+timedelta(seconds=i),dict(currentName=dict(text='캐릭터',confidence=.99)),boxes,context)
        rows = self.store.state_records()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['characterName']=='캐릭터' and r['dungeonName']==NAME for r in rows))
        self.assertEqual(live.session.complete_banner(now+timedelta(seconds=12),context,2),[])
        self.assertEqual(self.store.state_records(),rows)

    def test_detail_current_snapshot_and_unmatched_not_rematched(self):
        saved = self.matcher.record(row())
        current = copy.deepcopy(CACHED)
        current['content'][NAME]['싱글 모드']['1관문']['gold']=20000
        self.assertEqual(record_detail(saved,current)['values']['gold'],20000)
        self.assertEqual(record_detail(saved)['values']['gold'],10000)
        self.assertEqual(record_detail(ContentMatcher().record(row()),current)['status'],'unmatched')
        self.assertEqual(record_detail(row(NAME,'싱글 모드'),current)['status'],'matched')
        self.assertEqual(record_detail(row(),current)['status'],'unmatched')

    def test_gateless_never_attaches_first_gate_of_multigate_raid(self):
        self.assertEqual(self.matcher.record(dict(row(),completionScope='raid'))['catalogMatch']['status'],'unmatched')
        single=copy.deepcopy(CACHED)
        del single['content'][NAME]['싱글 모드']['2관문']
        self.assertEqual(ContentMatcher(single).record(dict(row(),completionScope='raid'))['catalogMatch']['status'],'matched')

    def test_legacy_detail_normalizes_spaces_punctuation_without_rewriting_record(self):
        original=row('4막파멸의성채','[싱글 모드]')
        before=copy.deepcopy(original)
        self.assertEqual(record_detail(original,CACHED)['status'],'matched')
        self.assertEqual(original,before)
        multiple=copy.deepcopy(CACHED)
        multiple['content']['4막 파멸의 성채']=multiple['content'][NAME]
        self.assertEqual(record_detail(original,multiple)['status'],'ambiguous')
        self.assertEqual(record_detail(row(),CACHED)['status'],'unmatched')

    def test_banner_first_completion_is_canonical_and_progress_not_persisted(self):
        from beatrice.state_session import StateSession
        session=StateSession(self.store)
        session.confirm_character('name:캐릭터','캐릭터','run',2)
        session.tracker.stable=('진행중','진행 전')
        result=session.complete_banner(datetime.now(timezone.utc),
                                       dict(dungeonName=TYPO,difficulty='싱글모드'),1)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['dungeonName'],NAME)
        self.assertEqual(result[0]['evidenceType'],'completion_banner')
        self.assertEqual(len(self.store.state_records()),1)

    def test_unknown_dungeon_and_ambiguous_names_preserve_ocr(self):
        for source in (row(mode='없는 난이도'),row('미등록 던전')):
            self.store.clear_all()
            saved=self.save(source)[0]
            self.assertEqual(saved['catalogMatch']['status'],'unmatched')
            self.assertEqual(saved['dungeonName'], NAME if source['dungeonName'] == TYPO else source['dungeonName'])
            self.assertEqual(saved['difficulty'],source['difficulty'])
        self.store.clear_all()
        multiple=copy.deepcopy(CACHED)
        multiple['content']['4막: 파멸의 성쵸']=multiple['content'][NAME]
        self.matcher=ContentMatcher(multiple)
        saved=self.save(row())[0]
        self.assertEqual(saved['catalogMatch']['status'],'ambiguous')
        self.assertEqual(saved['dungeonName'],TYPO)

    def test_file_cache_refresh_and_corruption_preserve_last_good(self):
        settings=dict(rootFolderID='root',fileName='ContentJSON.json',jsonFolderName='JSON',refreshSeconds=3600)
        with tempfile.TemporaryDirectory() as temp, patch('beatrice.content_match.load_settings',return_value=settings):
            provider=FileContentMatcher('.',temp)
            self.assertEqual(provider().content,{})
            cache=ContentCache(temp,settings)
            cached=dict(CACHED,rootFolderID='root',fileName='ContentJSON.json')
            cache.save(cached)
            self.assertEqual(provider().record(row())['catalogMatch']['status'],'matched')
            cache.path.write_text('broken',encoding='utf8')
            self.assertEqual(provider().record(row())['catalogMatch']['status'],'matched')



if __name__ == "__main__": unittest.main()
