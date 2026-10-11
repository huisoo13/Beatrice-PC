import hashlib
import io
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from beatrice.catalog_service import CatalogService
from beatrice.drive import DriveCancelledError
from beatrice.public_assets import PublicAssetCache, MAX_IMAGE_BYTES
from beatrice.public_content import ContentError, PublicContentClient, FOLDER_MIME

SETTINGS = dict(rootFolderID='root', jsonFolderName='JSON', fileName='ContentJSON.json',
                emblemFileName='EmblemJSON.json', imagesFolderName='Images', refreshSeconds=3600)
CONTENT = {'던전': {'하드': {'1관문': {'gold': 100, 'fee': 0, 'bound_percentage': 0}}}}

class FakeAssets:
    def __init__(self):
        self.bodies = {'catalog': json.dumps(CONTENT).encode(),
                       'emblem': json.dumps({'워로드': '/classes/warlord.svg'}).encode(),
                       'gold': b'\x89PNG\r\n\x1a\nimage-data'}
        self.downloads = []
        self.corrupt = False
        self.nested = False
        self.missing = False
        self.duplicate = False
        self.size = None
        self.on_download = None

    def metadata(self, identity, name, mime):
        body = self.bodies[identity]
        return dict(id=identity, name=name, mimeType=mime,
                    md5Checksum=hashlib.md5(body).hexdigest(), size=str(len(body)))

    def __call__(self, request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)
        if 'alt' in query:
            identity = urlsplit(request.full_url).path.rsplit('/', 1)[-1]
            self.downloads.append(identity)
            if self.on_download: self.on_download()
            return io.BytesIO(b'corrupt' if self.corrupt else self.bodies[identity])
        folder = query['q'][0].split("'")[1]
        if folder == 'root':
            items = [dict(id='json', name='JSON', mimeType=FOLDER_MIME)]
            if not self.missing: items.append(dict(id='images', name='Images', mimeType=FOLDER_MIME))
        elif folder == 'json':
            items = [self.metadata('catalog', 'ContentJSON.json', 'application/json'),
                     self.metadata('emblem', 'EmblemJSON.json', 'application/json')]
        elif folder == 'images' and self.nested:
            items = [dict(id='nested', name='gold', mimeType=FOLDER_MIME)]
        else:
            image = self.metadata('gold', 'gold.png', 'image/png')
            if self.size is not None: image['size'] = str(self.size)
            items = [image]
            if self.duplicate: items.append(dict(image, id='another'))
        return io.BytesIO(json.dumps({'files': items}).encode())

class PublicAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fake = FakeAssets()
        self.cancel = threading.Event()
        self.client = PublicContentClient('fake-key', SETTINGS, self.cancel, opener=self.fake)
        self.cache = PublicAssetCache(self.temp.name, SETTINGS)

    def initial(self):
        bundle = self.cache.prepare(self.client)
        self.cache.save(bundle)
        return bundle

    def test_download_store_and_offline_reload(self):
        bundle = self.initial()
        self.assertEqual(bundle['downloadedFiles'], 2)
        self.assertEqual(self.cache.load(), bundle)
        self.assertEqual(bundle['emblem']['content'], {'워로드': '/classes/warlord.svg'})
        for item in [bundle['emblem']] + bundle['images']:
            self.assertTrue(self.cache.file_path(item).is_file())
        self.assertEqual(set(self.fake.downloads), {'emblem', 'gold'})

    def test_unchanged_files_skip_download_and_changed_image_preserves_old_version(self):
        first = self.initial()
        self.fake.downloads.clear()
        self.assertEqual(self.cache.prepare(self.client)['downloadedFiles'], 0)
        self.assertEqual(self.fake.downloads, [])
        self.fake.bodies['gold'] += b'changed'
        second = self.cache.prepare(self.client)
        self.assertEqual(self.fake.downloads, ['gold'])
        self.assertEqual(second['downloadedFiles'], 1)
        self.assertNotEqual(self.cache.file_path(first['images'][0]), self.cache.file_path(second['images'][0]))
        self.assertEqual(self.cache.load(), first)
        self.cache.save(second)
        self.assertEqual(self.cache.load(), second)
        self.assertTrue(self.cache.file_path(first['images'][0]).exists())

    def test_local_corruption_and_missing_file_are_repaired(self):
        bundle = self.initial()
        self.cache.file_path(bundle['images'][0]).write_bytes(b'bad')
        self.cache.file_path(bundle['emblem']).unlink()
        with self.assertRaises(ContentError): self.cache.load()
        repaired = self.cache.prepare(self.client)
        self.assertEqual(repaired['downloadedFiles'], 2)
        self.cache.save(repaired)
        self.assertEqual(self.cache.load(), repaired)

    def test_failed_refresh_and_failed_index_write_keep_last_good_bundle(self):
        first = self.initial()
        self.fake.bodies['gold'] += b'changed'
        self.fake.corrupt = True
        with self.assertRaises(ContentError): self.cache.prepare(self.client)
        self.assertEqual(self.cache.load(), first)
        self.fake.corrupt = False
        second = self.cache.prepare(self.client)
        with patch.object(Path, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.cache.save(second)
        self.assertEqual(self.cache.load(), first)
        self.assertEqual(list(Path(self.temp.name).rglob('*.tmp')), [])

    def test_cancellation_does_not_publish_new_bundle(self):
        first = self.initial()
        self.fake.bodies['gold'] += b'new'
        self.fake.on_download = self.cancel.set
        with self.assertRaises((DriveCancelledError, ContentError)): self.cache.prepare(self.client)
        self.assertEqual(self.cache.load(), first)

    def test_nested_images_and_duplicate_names(self):
        self.fake.nested = True
        bundle = self.initial()
        self.assertEqual(bundle['images'][0]['name'], 'gold/gold.png')
        self.fake.duplicate = True
        with self.assertRaises(ContentError): self.cache.prepare(self.client)

    def test_missing_folder_oversize_and_invalid_emblem_are_rejected(self):
        self.fake.missing = True
        with self.assertRaises(ContentError): self.cache.prepare(self.client)
        self.fake.missing = False
        self.fake.size = MAX_IMAGE_BYTES + 1
        with self.assertRaises(ContentError): self.cache.prepare(self.client)
        self.fake.size = None
        self.fake.bodies['emblem'] = b'{"job":12}'
        with self.assertRaises(ContentError): self.cache.prepare(self.client)

    def test_source_mismatch_and_untrusted_file_id_do_not_escape_cache(self):
        bundle = self.initial()
        with self.assertRaises(ContentError):
            PublicAssetCache(self.temp.name, dict(SETTINGS, rootFolderID='other')).load()
        item = dict(bundle['images'][0], metadata=dict(bundle['images'][0]['metadata'], id='../outside'))
        with self.assertRaises(ContentError): self.cache.file_path(item)

    def test_service_startup_refresh_publishes_assets_and_bad_asset_refresh_keeps_catalog(self):
        with patch('beatrice.catalog_service.load_settings', return_value=SETTINGS):
            service = CatalogService(self.temp.name, self.temp.name)
        def refresh():
            with patch('beatrice.catalog_service.load_api_key', return_value='fake-key'), \
                    patch('beatrice.catalog_service.PublicContentClient', return_value=self.client):
                service.refresh()
                deadline = time.monotonic() + 2
                while service.pending and time.monotonic() < deadline:
                    service.poll()
                    time.sleep(.005)
            self.assertIsNone(service.pending)
        refresh()
        self.assertTrue(service.startup_finished)
        self.assertEqual(service.assets['emblem']['content'], {'워로드': '/classes/warlord.svg'})
        before = service.assets
        self.fake.missing = True
        refresh()
        self.assertEqual(service.cached['content'], CONTENT)
        self.assertEqual(service.assets, before)
        self.assertIn('마지막 정상 문양', service.message)
        self.assertEqual(service.asset_cache.load(), before)

    def test_service_cancelled_result_cannot_publish_asset_index(self):
        bundle = self.initial()
        with patch('beatrice.catalog_service.load_settings', return_value=SETTINGS):
            service = CatalogService(self.temp.name, self.temp.name)
        replies = queue.Queue()
        replies.put((dict(content=CONTENT, _assetBundle=bundle), None))
        cancel = threading.Event(); cancel.set()
        service.pending = cancel, replies
        with patch.object(service.asset_cache, 'save') as save:
            service.poll()
            save.assert_not_called()

if __name__ == '__main__': unittest.main()

class PublicImageLookupTests(unittest.TestCase):
    setUp = PublicAssetTests.setUp
    initial = PublicAssetTests.initial
    def test_exact_image_lookup_reuses_verified_cache_without_download(self):
        bundle = self.initial()
        self.fake.downloads.clear()
        expected = str(self.cache.file_path(bundle['images'][0]).resolve())
        self.assertEqual(self.cache.image_path('gold.png', bundle), expected)
        self.assertEqual(self.cache.image_path('gold.png'), expected)
        self.assertEqual(self.fake.downloads, [])

    def test_unknown_ambiguous_corrupt_and_missing_images_have_no_path(self):
        import copy
        bundle = self.initial()
        self.assertIsNone(self.cache.image_path('unknown.png', bundle))
        duplicate = copy.deepcopy(bundle)
        duplicate['images'].append(duplicate['images'][0])
        self.assertIsNone(self.cache.image_path('gold.png', duplicate))
        path = self.cache.file_path(bundle['images'][0])
        path.write_bytes(b'corrupt')
        self.assertIsNone(self.cache.image_path('gold.png', bundle))
        path.unlink()
        self.assertIsNone(self.cache.image_path('gold.png', bundle))

    def test_wrong_bundle_source_is_not_used(self):
        import copy
        bundle = copy.deepcopy(self.initial())
        bundle['source']['rootFolderID'] = 'wrong-folder'
        self.assertIsNone(self.cache.image_path('gold.png', bundle))

    def test_service_resolves_currency_names_via_public_cache_api(self):
        with patch('beatrice.catalog_service.load_settings', return_value=SETTINGS):
            service = CatalogService(self.temp.name, self.temp.name)
        self.assertEqual(service.currency_images(), dict(gold=None, boundGold=None))
        service.assets = self.initial()
        with patch.object(service.asset_cache, 'image_path', side_effect=['gold-path', 'bound-path']) as lookup:
            self.assertEqual(service.currency_images(), dict(gold='gold-path', boundGold='bound-path'))
            self.assertEqual([args.args[0] for args in lookup.call_args_list], ['gold.unbound.png', 'gold.bound.png'])