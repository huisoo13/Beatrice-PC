import unittest
from beatrice.storage import Store
from beatrice.content_match import ContentMatcher


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.store=Store(':memory:');self.addCleanup(self.store.close)
        self.matcher=ContentMatcher({'content':[{'name':'1막: 던전','field_name':'1막: 던전','difficulties':[{'name':'싱글 모드','gates':[{'number':1,'gold':3500,'fee':750,'bound_percentage':.5}]}]}]})
        self.old=self.store.save_completions('name:캐릭터','막던전',[dict(characterName='캐릭터',dungeonName='막: 던전',difficulty='싱글 모드',gate=1,state='완료',observedAt='2026-10-11T05:39:36Z')],2)[0]

    def correct(self, **kwargs):
        return self.store.correct_completion(self.old['recordId'],'1막: 던전',self.matcher,expected_updated_at=kwargs.get('at',self.old['updatedAt']))

    def test_correction_preserves_facts_and_rekeys_checkpoint(self):
        before=self.store.drive_revision();row=self.correct()
        for key in ['recordId','observedAt','createdAt','characterName','gateNumber','expectedGates']:self.assertEqual(row[key],self.old[key])
        self.assertGreater(row['updatedAt'],self.old['updatedAt']);self.assertEqual(row['catalogMatch']['status'],'matched')
        self.assertEqual(self.store.state_records()[0],row);self.assertEqual(self.store.history_records(),[row])
        self.assertEqual(self.store.drive_revision()[1],before[1]+1)

    def test_original_ocr_alias_still_prevents_duplicate_old_runtime_save(self):
        self.old['ocrOriginal']=dict(contentName='막: 던전',difficulty='싱글 모드',gateNumber=1)
        self.store.remember_completion(dict(self.old,updatedAt='2090-01-01T00:00:00Z'))
        self.old=self.store.history_records()[0]
        self.store.catalog=lambda:self.matcher
        row=self.correct()
        self.assertEqual(row['ocrOriginal'],self.old['ocrOriginal'])
        duplicate=self.store.save_completions('name:캐릭터','막던전',[dict(characterName='캐릭터',dungeonName='막: 던전',difficulty='싱글 모드',gate=1,state='완료',observedAt='2026-10-11T05:39:38Z')],2)
        self.assertEqual(duplicate,[])

    def test_stale_update_is_rejected_without_changes(self):
        revision=self.store.drive_revision()
        with self.assertRaises(ValueError):self.correct(at='2000-01-01T00:00:00Z')
        self.assertEqual(self.store.history_records(),[self.old]);self.assertEqual(self.store.drive_revision(),revision)

    def test_existing_weekly_completion_blocks_correction(self):
        other=self.store.save_completions('name:캐릭터','1막던전',[dict(characterName='캐릭터',dungeonName='1막: 던전',difficulty='하드',gate=1,state='완료',observedAt='2026-10-11T06:00:00Z')],2)[0]
        revision=self.store.drive_revision()
        with self.assertRaises(ValueError):self.correct()
        self.assertEqual(len(self.store.history_records()),2);self.assertEqual(self.store.drive_revision(),revision)
