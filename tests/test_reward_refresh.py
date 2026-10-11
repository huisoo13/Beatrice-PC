"""Rewards use field_name; saved display names are not recognition aliases."""
import copy
import sqlite3
import unittest
from beatrice.completion_record import new_record
from beatrice.content_match import ContentMatcher,record_detail
from beatrice.storage import Store
from beatrice.drive_data import export_records,encode_records,decode_records

DATA=[dict(name='지평의 성당',field_name='구원의 종탑',difficulties=[dict(name='3단계',gates=[
    dict(number=1,gold=20000,fee=6400,bound_percentage=1),
    dict(number=2,gold=30000,fee=9600,bound_percentage=1)])])]
CACHED=dict(content=DATA,metadata=dict(id='public',version='16',md5Checksum='a'*32))


def record(source='구원의 종탑',name='지평의 성당',gate=1):
    row=new_record(dict(characterName='캐릭터',dungeonName=name,difficulty='3단계',gate=gate,state='완료',
        observedAt='2026-10-11T00:00:00.000Z'),2)
    row.update(ocrOriginal=dict(contentName=source,difficulty='3단계',gateNumber=gate),catalogMatch=dict(status='unmatched'))
    return row


class RewardRefreshTests(unittest.TestCase):
    def setUp(self):
        self.matcher=ContentMatcher(CACHED)
        self.store=Store(':memory:');self.addCleanup(self.store.close)

    def test_field_name_matches_canonical_record_and_preserves_all_completion_facts(self):
        original=record();before=copy.deepcopy(original)
        matched=self.matcher.refresh_record_match(original)
        self.assertEqual(original,before)
        for field in ('recordId','observedAt','createdAt','updatedAt','ocrOriginal','expectedGates'):
            self.assertEqual(matched[field],original[field])
        self.assertEqual(matched['catalogMatch']['status'],'matched')
        self.assertEqual(matched['catalogMatch']['fieldName'],'구원의 종탑')
        self.assertEqual(matched['catalogMatch']['contentName'],'지평의 성당')
        self.assertEqual(matched['catalogMatch']['gateNumber'],1)
        self.assertEqual(matched['catalogMatch']['values'],dict(gold=20000,fee=6400,bound_percentage=1))
        self.assertEqual(self.matcher.saved_reward(matched['catalogMatch']),matched['catalogMatch']['values'])

    def test_display_name_alone_cannot_substitute_for_field_name(self):
        original=record(source='지평의 성당')
        self.assertEqual(self.matcher.refresh_record_match(original),original)
        original.pop('ocrOriginal')
        self.assertEqual(self.matcher.refresh_record_match(original),original)

    def test_new_json_record_api_uses_original_field_name_and_returns_new_fields(self):
        original=record();original.pop('catalogMatch')
        matched=self.matcher.record(original)
        self.assertEqual(matched['catalogMatch']['status'],'matched')
        self.assertEqual(matched['catalogMatch']['gateNumber'],1)
        self.assertEqual(matched['ocrOriginal'],original['ocrOriginal'])
        self.assertNotIn('dungeonName',matched)
        self.assertNotIn('gateName',matched['catalogMatch'])
        wrong=record(source='지평의 성당');wrong.pop('catalogMatch')
        self.assertEqual(self.matcher.record(wrong)['catalogMatch']['status'],'unmatched')

    def test_exact_only_ambiguous_field_or_wrong_difficulty_does_not_attach_rewards(self):
        for source in ('구원의 종탕','미등록 장소'):
            original=record(source=source)
            self.assertEqual(self.matcher.refresh_record_match(original),original)
        data=copy.deepcopy(DATA);data.append(dict(data[0],name='동일 화면 이름의 다른 콘텐츠'))
        original=record()
        self.assertEqual(ContentMatcher(dict(content=data)).refresh_record_match(original),original)
        original['difficulty']='없는 단계'
        self.assertEqual(self.matcher.refresh_record_match(original),original)

    def test_refresh_updates_checkpoint_history_and_drive_once(self):
        originals=[record(gate=i) for i in (1,2)]
        self.store.replace_history(originals)
        before=self.store.drive_revision()
        changed=self.store.refresh_catalog_matches(self.matcher)
        self.assertEqual(len(changed),2)
        self.assertEqual(self.store.drive_revision(),(before[0],before[1]+1))
        for old in originals:
            saved=next(row for row in self.store.history_records() if row['recordId']==old['recordId'])
            self.assertEqual(saved['observedAt'],old['observedAt'])
            self.assertEqual(saved['createdAt'],old['createdAt'])
            self.assertGreater(saved['updatedAt'],old['updatedAt'])
            self.assertEqual(record_detail(saved,matcher=self.matcher)['status'],'matched')
        self.assertEqual(self.store.state_records(),sorted(changed,key=lambda row:row['gateNumber']))
        exported=export_records(self.store)[0]
        self.assertEqual(decode_records(encode_records(exported)),exported)
        revision=self.store.drive_revision()
        self.assertEqual(self.store.refresh_catalog_matches(self.matcher),[])
        self.assertEqual(self.store.drive_revision(),revision)

    def test_refresh_failure_rolls_back_all_rewards_and_drive_obligation(self):
        self.store.replace_history([record(gate=i) for i in (1,2)])
        before=self.store.history_records();revision=self.store.drive_revision()
        self.store.db.execute("CREATE TRIGGER fail_reward BEFORE UPDATE ON completion_history WHEN json_extract(NEW.payload,'$.gateNumber')=2 BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.refresh_catalog_matches(self.matcher)
        self.assertEqual(self.store.history_records(),before)
        self.assertEqual(self.store.drive_revision(),revision)
        self.assertTrue(all(row['catalogMatch']['status']=='unmatched' for row in self.store.state_records()))

    def test_existing_matched_reward_is_preserved_and_unknown_total_is_not_inferred(self):
        original=record();original['expectedGates']=0
        matched=self.matcher.refresh_record_match(original)
        self.assertEqual(matched['expectedGates'],0)
        updated=copy.deepcopy(CACHED);updated['content'][0]['difficulties'][0]['gates'][0]['gold']=100
        self.assertEqual(ContentMatcher(updated).refresh_record_match(matched),matched)


if __name__=='__main__':unittest.main()
