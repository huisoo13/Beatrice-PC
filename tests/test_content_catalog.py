import copy
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from beatrice.content_catalog import ContentCatalog, ContentError, validate_content
from beatrice.content_match import ContentMatcher, record_detail, FileContentMatcher
from beatrice.public_content import ContentCache
from beatrice.catalog_service import CatalogService
from beatrice.native_presentation import record_view, observation_view
from beatrice.storage import Store
from beatrice.drive_data import export_records, encode_records, decode_records
from beatrice.dungeon import key

VALUES = dict(gold=20000, fee=6400, bound_percentage=1)
DATA = [dict(name='지평의 성당', field_name='구원의 종탑', difficulties=[
    dict(name='3단계', gates=[dict(number=i, **VALUES) for i in (1, 2)])])]
CACHED = dict(rootFolderID='root', fileName='ContentJSON.json', metadata={'version':'new'}, content=DATA)


def row(name='구원의 종탑', mode='3단계', gate=1):
    return dict(characterName='캐릭터', dungeonName=name, difficulty=mode, gate=gate,
                state='완료', observedAt=datetime.now(timezone.utc).isoformat(), timeBasis='live_capture')

class ContentCatalogTests(unittest.TestCase):
    def test_new_schema_validation_and_reward_rows_preserve_display_name(self):
        self.assertEqual(validate_content(DATA), DATA)
        catalog = ContentCatalog(DATA)
        self.assertEqual(catalog.field_names, {'지평의 성당':'구원의 종탑'})
        self.assertEqual(len(catalog.rows()), 2)
        self.assertEqual(catalog.rows()[0], dict(dungeon='지평의 성당', mode='3단계', gate='1관문', **VALUES))
        original = copy.deepcopy(DATA)
        catalog.rewards['지평의 성당']['3단계']['1관문']['gold'] = 0
        self.assertEqual(DATA, original)

    def test_duplicate_names_invalid_gates_and_invalid_reward_are_rejected(self):
        invalid = [DATA + DATA]
        for field, value in [('name',''), ('field_name',''), ('difficulties',{})]:
            altered = copy.deepcopy(DATA); altered[0][field] = value; invalid.append(altered)
        for field, value in [('number',True), ('number',2), ('gold',True), ('fee',-1), ('bound_percentage',1.5)]:
            altered = copy.deepcopy(DATA); altered[0]['difficulties'][0]['gates'][0][field] = value; invalid.append(altered)
        altered = copy.deepcopy(DATA); altered[0]['difficulties'] *= 2; invalid.append(altered)
        for value in invalid:
            with self.assertRaises(ContentError): validate_content(value)

    def test_ocr_matches_field_name_and_never_display_name_as_an_ocr_alias(self):
        matcher = ContentMatcher(CACHED)
        self.assertEqual(matcher.record(row())['dungeonName'], '지평의 성당')
        self.assertEqual(matcher.record(row('구원의종탑'))['dungeonName'], '지평의 성당')
        canonical_input = matcher.record(row('지평의 성당'))
        self.assertEqual(canonical_input['catalogMatch']['status'], 'unmatched')
        self.assertEqual(canonical_input['dungeonName'], '지평의 성당')
        self.assertEqual(matcher.record(row('미등록 장소'))['dungeonName'], '미등록 장소')

    def test_field_match_converts_name_even_without_mode_or_gate_reward(self):
        matcher = ContentMatcher(CACHED)
        for source in (row(mode='미등록 모드'), row(gate=3)):
            saved = matcher.record(source)
            self.assertEqual(saved['dungeonName'], '지평의 성당')
            self.assertEqual(saved['catalogMatch']['status'], 'unmatched')
            self.assertEqual(saved['difficulty'], source['difficulty'])
            self.assertEqual(saved['ocrOriginal']['dungeonName'], '구원의 종탑')

    def test_ambiguous_field_name_keeps_original_ocr(self):
        data = copy.deepcopy(DATA) + [dict(DATA[0], name='다른 표시명')]
        matcher = ContentMatcher(dict(CACHED, content=data))
        saved = matcher.record(row())
        self.assertEqual(saved['dungeonName'], '구원의 종탑')
        self.assertEqual(saved['catalogMatch']['status'], 'ambiguous')

    def test_saved_name_and_field_name_deduplicate_and_export_new_name(self):
        matcher = ContentMatcher(CACHED)
        with closing(Store(':memory:', catalog=lambda:matcher)) as store:
            first = store.save_completions('name:캐릭터', key('구원의 종탑'), [row()], 2)[0]
            self.assertEqual(first['contentName'], '지평의 성당')
            self.assertEqual(store.save_completions('name:캐릭터', key('지평의 성당'), [row()], 2), [])
            self.assertEqual(store.save_completions('name:캐릭터', key('구원의 종탑'), [row()], 2), [])
            self.assertEqual(store.state_records(), [first])
            exported, _ = export_records(store)
            self.assertEqual(decode_records(encode_records(exported))[0]['contentName'], '지평의 성당')

    def test_offline_old_field_record_still_blocks_new_name_without_rewriting_history(self):
        matcher = ContentMatcher()
        with closing(Store(':memory:', catalog=lambda:matcher)) as store:
            first = store.save_completions('name:캐릭터', key('구원의 종탑'), [row()], 2)[0]
            matcher = ContentMatcher(CACHED)
            self.assertEqual(store.save_completions('name:캐릭터', key('지평의 성당'), [row()], 2), [])
            self.assertEqual(store.history_records(), [first])
            presented = record_view(first, CACHED, matcher=matcher)
            self.assertEqual(presented['dungeon'], '지평의 성당')
            self.assertEqual(presented['detail']['status'], 'unmatched')

    def test_legacy_stored_reward_link_resolves_new_name_and_keeps_record_identity(self):
        old = dict(row(), recordID='same-id', updatedAt='same-time', catalogMatch=dict(
            status='matched', dungeonName='구원의 종탑', difficulty='3단계', gateName='1관문', values=dict(VALUES, gold=1)))
        before = copy.deepcopy(old)
        presented = record_view(old, CACHED)
        self.assertEqual(presented['dungeon'], '지평의 성당')
        self.assertEqual(presented['detail']['values']['gold'], 20000)
        self.assertEqual(presented['detail']['source'], '현재 공용 데이터')
        self.assertEqual(old, before)
        self.assertEqual(record_detail(row(), CACHED)['status'], 'matched')
        self.assertEqual(record_detail(row('지평의 성당'), CACHED)['status'], 'matched')

    def test_new_saved_field_link_survives_later_display_name_change(self):
        saved = ContentMatcher(CACHED).record(row())
        data = copy.deepcopy(DATA); data[0]['name'] = '새 표시명'; data[0]['difficulties'][0]['gates'][0]['gold'] = 25000
        current = dict(CACHED, content=data)
        self.assertEqual(record_detail(saved, current)['values']['gold'], 25000)
        self.assertEqual(record_view(saved, current)['dungeon'], '새 표시명')

    def test_name_change_with_same_field_keeps_weekly_completion_and_original_identity(self):
        matcher = ContentMatcher(CACHED)
        with closing(Store(':memory:', catalog=lambda:matcher)) as store:
            first = store.save_completions('name:캐릭터', key('구원의 종탑'), [row()], 2)[0]
            data = copy.deepcopy(DATA); data[0]['name'] = '새 표시명'
            matcher = ContentMatcher(dict(CACHED, content=data))
            self.assertEqual(store.save_completions('name:캐릭터', key('새 표시명'), [row()], 2), [])
            self.assertEqual(store.history_records(), [first])
            self.assertEqual(store.state_records('name:캐릭터', key('새 표시명')), [first])

    def test_live_footer_uses_name_and_unknown_location_keeps_ocr(self):
        value = dict(identity={}, dungeon=dict(dungeonName='구원의 종탑', difficulty='3단계', contextStatus='ocr_verified'))
        self.assertEqual(observation_view(value, ContentMatcher(CACHED))['dungeon'], '지평의 성당')
        value['dungeon']['dungeonName'] = '미등록 장소'
        self.assertEqual(observation_view(value, ContentMatcher(CACHED))['dungeon'], '미등록 장소')

    def test_old_cache_upgrade_and_invalid_new_cache_retain_previous_matcher(self):
        from unittest.mock import patch
        settings = dict(rootFolderID='root', fileName='ContentJSON.json', jsonFolderName='JSON', refreshSeconds=3600)
        with tempfile.TemporaryDirectory() as directory, patch('beatrice.content_match.load_settings', return_value=settings):
            cache = ContentCache(directory, settings)
            legacy = dict(CACHED, content={'구원의 종탑': {'3단계': {'1관문': VALUES}}})
            cache.save(legacy)
            provider = FileContentMatcher('.', directory)
            self.assertEqual(provider().record(row())['dungeonName'], '구원의 종탑')
            cache.save(CACHED)
            self.assertEqual(provider().record(row())['dungeonName'], '지평의 성당')
            cache.path.write_text('[]', encoding='utf-8')
            self.assertEqual(provider().record(row())['dungeonName'], '지평의 성당')

if __name__ == '__main__': unittest.main()
