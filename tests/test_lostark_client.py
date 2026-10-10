import io
import json
import os
import tempfile
import unittest
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from beatrice.google_auth import AuthError
from beatrice.lostark import (LostArkClient, LostArkAuthError, LostArkNetworkError,
                             LostArkNotFoundError, LostArkRateLimitError,
                             LostArkResponseError)
from beatrice.lostark.client import _NoRedirect


class Response(io.BytesIO):
    def __init__(self, data=b'{}', *, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = str(value)


class LostArkClientTests(unittest.TestCase):
    def client(self, **kwargs):
        api = LostArkClient('dummy-key', **kwargs)
        api._opener = Mock()
        api._opener.open.return_value = Response()
        return api

    def test_profile_encodes_name_and_authenticates(self):
        api = self.client(timeout=3)
        expected = {'CharacterName': '후이수', 'NewField': {'x': 1}}
        api._opener.open.return_value = Response(json.dumps(expected).encode())
        self.assertEqual(api.characters.profile(' 후이수 '), expected)
        request = api._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://developer-lostark.game.onstove.com/armories/characters/%ED%9B%84%EC%9D%B4%EC%88%98/profiles')
        self.assertEqual(request.get_header('Authorization'), 'bearer dummy-key')
        self.assertEqual(api._opener.open.call_args.kwargs['timeout'], 3)
        self.assertNotIn('dummy-key', repr(api))

    def test_all_character_and_armory_routes(self):
        api = self.client()
        routes = [('characters', 'siblings', '/characters/Name/siblings'),
                  ('armory', 'full', '/armories/characters/Name')]
        for method, suffix in [('equipment','equipment'), ('avatars','avatars'),
                               ('combat_skills','combat-skills'), ('engravings','engravings'),
                               ('cards','cards'), ('gems','gems'), ('colosseums','colosseums'),
                               ('collectibles','collectibles'), ('ark_passive','arkpassive'),
                               ('ark_grid','arkgrid')]:
            routes.append(('armory', method, '/armories/characters/Name/' + suffix))
        for group, method, path in routes:
            with self.subTest(method=method):
                api._opener.open.return_value = Response()
                getattr(getattr(api, group), method)('Name')
                self.assertTrue(api._opener.open.call_args.args[0].full_url.endswith(path))

    def test_null_and_no_content(self):
        api = self.client()
        for response in [Response(b'null'), Response(b'',status=204)]:
            api._opener.open.return_value = response
            self.assertIsNone(api.characters.profile('Name'))

    def test_get_query_and_post_body(self):
        api = self.client()
        api.request('POST','/auctions/items',params={'q':'한 글'},body={'ItemName':'보석'})
        request = api._opener.open.call_args.args[0]
        self.assertEqual(request.get_method(),'POST')
        self.assertEqual(json.loads(request.data),{'ItemName':'보석'})
        self.assertEqual(request.get_header('Content-type'),'application/json')
        self.assertTrue(request.full_url.endswith('?q=%ED%95%9C+%EA%B8%80'))

    def test_invalid_inputs_never_send_requests(self):
        api = self.client()
        for name in [None,'','  ','x\n','x'*101]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                api.characters.profile(name)
        for path in ['https://other.test','//other.test','/a/../b','/a?x=1','/a#x','/a\\b','/한글','/a\n']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                api.request('GET',path)
        with self.assertRaises(ValueError):api.request('DELETE','/news/events')
        with self.assertRaises(ValueError):api.request('GET','/news/events',body={})
        api._opener.open.assert_not_called()

    def test_invalid_client_configuration(self):
        for kwargs in [{}, {'key':'x','key_provider':lambda:'x'}, {'key_provider':1}]:
            with self.subTest(kwargs=list(kwargs)),self.assertRaises(ValueError):LostArkClient(**kwargs)
        for timeout in [0,-1,float('inf'),float('nan'),True,'10']:
            with self.subTest(timeout=timeout),self.assertRaises(ValueError):LostArkClient('x',timeout=timeout)

    def test_key_provider_refreshes_and_bearer_is_normalized(self):
        provider = Mock(side_effect=['Bearer first','second',None])
        api = LostArkClient(key_provider=provider)
        api._opener = Mock(side_effect=None)
        for expected in ['bearer first','bearer second']:
            api._opener.open.return_value = Response()
            api.characters.profile('Name')
            self.assertEqual(api._opener.open.call_args.args[0].get_header('Authorization'),expected)
        with self.assertRaises(LostArkAuthError):api.characters.profile('Name')
        self.assertEqual(api._opener.open.call_count,2)

    def test_bad_key_and_storage_errors_are_sanitized(self):
        for value in [None,'','bearer ','secret\nvalue','has space','비밀']:
            api = LostArkClient(key_provider=lambda:value)
            api._opener = Mock()
            with self.subTest(value=value),self.assertRaises(LostArkAuthError):api.characters.profile('Name')
            api._opener.open.assert_not_called()
        api = LostArkClient(key_provider=Mock(side_effect=AuthError('private-key')))
        with self.assertRaises(LostArkAuthError) as caught:api.characters.profile('Name')
        self.assertNotIn('private-key',str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_http_errors_are_typed_and_do_not_expose_body(self):
        api = self.client()
        for status, error_type in [(401,LostArkAuthError),(403,LostArkAuthError),
                                   (404,LostArkNotFoundError),(500,LostArkResponseError),
                                   (302,LostArkResponseError)]:
            error = HTTPError('https://official.test',status,'private-key',{},io.BytesIO(b'private-key'))
            api._opener.open.side_effect = error
            with self.subTest(status=status),self.assertRaises(error_type) as caught:
                api.characters.profile('Name')
            self.assertEqual(caught.exception.status,status)
            self.assertNotIn('private-key',str(caught.exception))
            self.assertTrue(error.fp.closed)

    def test_network_and_invalid_json(self):
        api = self.client()
        for error in [URLError('private-key'),TimeoutError('private-key'),IncompleteRead(b'private-key')]:
            api._opener.open.side_effect = error
            with self.assertRaises(LostArkNetworkError) as caught:api.characters.profile('Name')
            self.assertNotIn('private-key',str(caught.exception))
        api._opener.open.side_effect = None
        api._opener.open.return_value = Response(b'<html>private-key</html>')
        with self.assertRaises(LostArkResponseError) as caught:api.characters.profile('Name')
        self.assertEqual(caught.exception.status,200)
        self.assertNotIn('private-key',str(caught.exception))

    def test_rate_limit_exhaustion_blocks_until_reset_without_sleep(self):
        api = self.client()
        headers = {'X-RateLimit-Limit':100,'X-RateLimit-Remaining':0,'X-RateLimit-Reset':1060}
        with patch('beatrice.lostark.client.time.time',return_value=1000):
            api._opener.open.return_value = Response(headers=headers)
            api.characters.profile('Name')
            self.assertEqual(api.rate_limit.remaining,0)
            with self.assertRaises(LostArkRateLimitError) as caught:api.characters.profile('Name')
            self.assertEqual(caught.exception.retry_after,60)
            self.assertEqual(api._opener.open.call_count,1)
        with patch('beatrice.lostark.client.time.time',return_value=1061):
            api._opener.open.return_value = Response()
            api.characters.profile('Name')
        self.assertEqual(api._opener.open.call_count,2)

    def test_429_uses_retry_after_and_falls_back_to_one_minute(self):
        for headers,expected in [({'Retry-After':'12'},12),({},60),
                                 ({'X-RateLimit-Reset':'1030'},30),
                                 ({'X-RateLimit-Reset':'bad','Retry-After':'bad'},60)]:
            api = self.client()
            api._opener.open.side_effect = HTTPError('https://official.test',429,'limit',headers,io.BytesIO())
            with self.subTest(headers=headers),patch('beatrice.lostark.client.time.time',return_value=1000):
                with self.assertRaises(LostArkRateLimitError) as caught:api.characters.profile('Name')
                self.assertEqual(caught.exception.retry_after,expected)
                with self.assertRaises(LostArkRateLimitError):api.characters.profile('Name')
                self.assertEqual(api._opener.open.call_count,1)

    def test_invalid_rate_limit_metadata_is_ignored(self):
        api = self.client()
        api._opener.open.return_value = Response(headers={'X-RateLimit-Limit':'bad','X-RateLimit-Remaining':-1})
        api.characters.profile('Name')
        self.assertIsNone(api.rate_limit.limit)
        self.assertIsNone(api.rate_limit.remaining)

    def test_redirects_are_rejected(self):
        self.assertIsNone(_NoRedirect().redirect_request(None,None,302,'',{},'https://other.test'))

    def test_saved_key_directory_precedence_and_no_eager_request(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ,{'BEATRICE_DATA_DIR':directory,'LOCALAPPDATA':'unused'}),patch('beatrice.lostark.client.LostArkApiKey') as store:
                api = LostArkClient.from_saved_key()
                store.assert_not_called()
                api._opener = Mock()
                api._opener.open.return_value = Response()
                store.return_value.load.return_value = 'dummy'
                api.characters.profile('Name')
                store.assert_called_once_with(Path(directory))
                explicit = LostArkClient.from_saved_key(Path(directory)/'explicit')
                explicit._opener = Mock()
                explicit._opener.open.return_value = Response()
                explicit.characters.profile('Name')
                self.assertEqual(store.call_args.args[0],Path(directory)/'explicit')
            with patch.dict(os.environ,{'LOCALAPPDATA':directory}),patch('beatrice.lostark.client.LostArkApiKey') as store:
                os.environ.pop('BEATRICE_DATA_DIR',None)
                store.return_value.load.return_value = 'dummy'
                api = LostArkClient.from_saved_key()
                api._opener = Mock()
                api._opener.open.return_value = Response()
                api.characters.profile('Name')
                store.assert_called_once_with(Path(directory)/'BeatricePC')

    def test_real_saved_key_replacement_and_clear(self):
        if os.name != 'nt':self.skipTest('Windows DPAPI')
        from beatrice.lostark_api import LostArkApiKey
        with tempfile.TemporaryDirectory() as directory:
            store = LostArkApiKey(directory)
            api = LostArkClient.from_saved_key(directory)
            api._opener = Mock()
            for key in ['dummy-one','dummy-two']:
                self.assertTrue(store.save(key))
                api._opener.open.return_value = Response()
                api.characters.profile('Name')
                self.assertEqual(api._opener.open.call_args.args[0].get_header('Authorization'),'bearer '+key)
            self.assertTrue(store.clear())
            with self.assertRaises(LostArkAuthError):api.characters.profile('Name')
            self.assertEqual(api._opener.open.call_count,2)
