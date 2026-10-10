import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from beatrice.emblem_cache import EmblemCache, CDN_BASE_URL, MAX_SVG_BYTES
from beatrice.public_assets import PublicAssetCache
from beatrice.public_content import ContentError
from test_public_assets import FakeAssets, SETTINGS, PublicContentClient

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
JOBS = {'워로드': '/classes/warlord.svg', '공통': '/classes/warlord.svg', '바드': '/classes/bard.svg'}

class Response(io.BytesIO):
    def __init__(self, body, headers):
        super().__init__(body)
        self.headers = headers

class FakeCdn:
    def __init__(self):
        self.bodies = {'warlord.svg': SVG, 'bard.svg': SVG}
        self.calls, self.fetched = [], []
        self.errors = {}
        self.etag = '"version-1"'
        self.on_read = None
        self.content_type = 'image/svg+xml'

    def __call__(self, request, timeout):
        self.calls.append(request)
        name = request.full_url.rsplit('/', 1)[-1]
        error = self.errors.get(name)
        if isinstance(error, Exception): raise error
        if error: raise HTTPError(request.full_url, error, 'failed', {}, io.BytesIO())
        if self.etag and request.get_header('If-none-match') == self.etag:
            raise HTTPError(request.full_url, 304, 'unchanged', {}, io.BytesIO())
        if not self.etag and request.get_header('If-modified-since') == 'Mon, 14 Sep 2026 06:40:25 GMT':
            raise HTTPError(request.full_url, 304, 'unchanged', {}, io.BytesIO())
        self.fetched.append(name)
        response = Response(self.bodies[name], {'Content-Type': self.content_type,
            'ETag': self.etag, 'Last-Modified': 'Mon, 14 Sep 2026 06:40:25 GMT'})
        if self.on_read:
            read = response.read
            def cancel_read(size):
                self.on_read()
                return read(size)
            response.read = cancel_read
        return response

class EmblemCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeCdn()
        self.cache = EmblemCache(self.temp.name, opener=self.fake)

    def test_initial_download_deduplicates_paths_and_resolves_profession(self):
        entries, count, errors = self.cache.prepare(JOBS)
        self.assertEqual(count, 2)
        self.assertEqual(errors, {})
        self.assertEqual(entries['워로드']['localPath'], entries['공통']['localPath'])
        self.assertEqual(self.cache.for_job('워로드', entries).read_bytes(), SVG)
        self.assertIsNone(self.cache.for_job('unknown', entries))
        self.assertTrue(all('Authorization' not in call.headers and 'key=' not in call.full_url for call in self.fake.calls))

    def test_etag_304_and_last_modified_reuse_cached_bytes(self):
        entries, _, _ = self.cache.prepare(JOBS)
        self.fake.fetched.clear()
        again, count, errors = self.cache.prepare(JOBS, entries)
        self.assertEqual(again, entries)
        self.assertEqual((count, errors, self.fake.fetched), (0, {}, []))
        self.fake.etag = None
        entries, _, _ = self.cache.prepare({'워로드': JOBS['워로드']})
        _, count, errors = self.cache.prepare({'워로드': JOBS['워로드']}, entries)
        self.assertEqual((count, errors), (0, {}))
        self.assertEqual(self.fake.calls[-1].get_header('If-modified-since'), 'Mon, 14 Sep 2026 06:40:25 GMT')

    def test_changed_content_uses_new_path_and_keeps_previous_bytes(self):
        entries, _, _ = self.cache.prepare(JOBS)
        self.fake.etag = '"version-2"'
        self.fake.bodies['warlord.svg'] = SVG.replace(b'M0 0', b'M1 1')
        again, _, _ = self.cache.prepare(JOBS, entries)
        self.assertNotEqual(again['워로드']['localPath'], entries['워로드']['localPath'])
        self.assertEqual(self.cache.for_job('워로드', entries).read_bytes(), SVG)
        self.assertIn(b'M1 1', self.cache.for_job('워로드', again).read_bytes())

    def test_partial_404_and_offline_keep_available_files_and_report_failure(self):
        self.fake.errors['bard.svg'] = 404
        entries, count, errors = self.cache.prepare(JOBS)
        self.assertEqual(count, 1)
        self.assertEqual(set(errors), {'바드'})
        self.assertNotIn('바드', entries)
        self.cache.validate(JOBS, entries, errors)
        self.fake.errors['warlord.svg'] = URLError('offline')
        again, count, errors = self.cache.prepare(JOBS, entries)
        self.assertEqual(again, entries)
        self.assertEqual(count, 0)
        self.assertEqual(set(errors), set(JOBS))
        self.cache.validate(JOBS, again, errors)

    def test_missing_or_corrupt_file_forces_unconditional_download(self):
        entries, _, _ = self.cache.prepare(JOBS)
        self.cache.for_job('워로드', entries).write_bytes(b'bad')
        self.fake.fetched.clear()
        again, count, errors = self.cache.prepare(JOBS, entries)
        self.assertEqual((count, errors, self.fake.fetched), (1, {}, ['warlord.svg']))
        self.assertEqual(self.cache.for_job('워로드', again).read_bytes(), SVG)

    def test_untrusted_domains_paths_and_cache_paths_are_rejected(self):
        with self.assertRaises(ContentError): EmblemCache(self.temp.name, 'https://evil.test')
        for path in ('https://evil.test/x.svg', '//evil.test/x.svg', '/../x.svg', '/%2e%2e/x.svg', '/a.svg?x=1'):
            with self.assertRaises(ContentError): self.cache.source_url(path)
        entries, _, _ = self.cache.prepare(JOBS)
        entries['워로드']['localPath'] = '../outside.svg'
        self.assertIsNone(self.cache.for_job('워로드', entries))

    def test_invalid_svg_mime_and_oversize_do_not_become_usable_cache(self):
        for body in (b'<html/>', b'<!DOCTYPE svg><svg/>', b'<svg><script/></svg>', b'x' * (MAX_SVG_BYTES + 1)):
            self.fake.bodies['warlord.svg'] = body
            entries, count, errors = self.cache.prepare({'워로드': JOBS['워로드']})
            self.assertEqual((entries, count), ({}, 0))
            self.assertIn('워로드', errors)
        self.fake.content_type = 'text/html'
        entries, _, errors = self.cache.prepare({'워로드': JOBS['워로드']})
        self.assertEqual(entries, {})
        self.assertIn('워로드', errors)

    def test_cancelled_download_does_not_save_or_fallback(self):
        cancel = threading.Event()
        self.fake.on_read = cancel.set
        with self.assertRaises(ContentError): self.cache.prepare(JOBS, cancel=cancel)
        self.assertEqual(list(Path(self.temp.name).rglob('*.svg')), [])
        self.assertEqual(list(Path(self.temp.name).rglob('*.tmp')), [])

    def test_refresh_time_budget_keeps_previous_cache_without_more_requests(self):
        entries, _, _ = self.cache.prepare({'워로드': JOBS['워로드']})
        self.fake.calls.clear()
        with patch('beatrice.emblem_cache.time.monotonic', side_effect=[0, 61]):
            again, count, errors = self.cache.prepare({'워로드': JOBS['워로드']}, entries)
        self.assertEqual(again, entries)
        self.assertEqual(count, 0)
        self.assertIn('워로드', errors)
        self.assertEqual(self.fake.calls, [])

    def test_asset_manifest_roundtrip_repair_and_partial_failure(self):
        settings = dict(SETTINGS, emblemBaseUrl=CDN_BASE_URL)
        cache = PublicAssetCache(self.temp.name, settings)
        cache.emblem_cache = self.cache = EmblemCache(cache.directory, opener=self.fake)
        drive = FakeAssets()
        drive.bodies['emblem'] = json.dumps(JOBS).encode()
        client = PublicContentClient('fake-key', settings, threading.Event(), opener=drive)
        bundle = cache.prepare(client)
        cache.save(bundle)
        self.assertEqual(cache.load(), bundle)
        self.assertEqual(cache.emblem_path('워로드', bundle).read_bytes(), SVG)
        cache.emblem_path('바드', bundle).unlink()
        self.fake.fetched.clear()
        fixed = cache.prepare(client)
        self.assertEqual(fixed['downloadedEmblems'], 1)
        self.assertEqual(self.fake.fetched, ['bard.svg'])
        cache.save(fixed)
        self.fake.errors['bard.svg'] = 404
        partial = cache.prepare(client)
        cache.save(partial)
        self.assertEqual(cache.load(), partial)
        self.assertIn('바드', partial['emblemErrors'])
        self.assertIsNotNone(cache.emblem_path('바드', partial))

if __name__ == '__main__': unittest.main()
