import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit, urlencode
from urllib.request import urlopen

from beatrice.google_auth import (AuthError, TokenStore, authenticate, authorize,
                                  callback_result, load_client, SCOPES)


class GoogleAuthTests(unittest.TestCase):
    def test_client_rejects_web_and_ambiguous_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / 'client_secret_test.json'
            path.write_text(json.dumps({'web': {'client_id': 'test'}}))
            with self.assertRaises(AuthError):
                load_client(directory)
            path.write_text(json.dumps({'installed': {'client_id': 'test', 'client_secret': 'secret'}}))
            self.assertEqual(load_client(directory)['client_id'], 'test')
            (Path(directory) / 'client_secret_second.json').write_text('{}')
            with self.assertRaises(AuthError):
                load_client(directory)

    def test_callback_requires_state_and_handles_denial(self):
        self.assertIsNone(callback_result('/?code=stolen&state=wrong', 'expected'))
        self.assertIsNone(callback_result('/favicon.ico?state=expected', 'expected'))
        self.assertIsNone(callback_result('/?state=expected&state=expected&code=x', 'expected'))
        with self.assertRaises(AuthError):
            callback_result('/?state=expected&error=access_denied', 'expected')
        self.assertEqual(callback_result('/?state=expected&code=valid', 'expected'), 'valid')

    def test_loopback_pkce_and_exchange(self):
        from base64 import urlsafe_b64encode
        from hashlib import sha256
        queries = []
        callbacks = []

        def opener(url):
            query = parse_qs(urlsplit(url).query)
            queries.append(query)
            def callback():
                with urlopen(query['redirect_uri'][0] + '?' + urlencode(
                        dict(state=query['state'][0], code='test-code')), timeout=5) as response:
                    callbacks.append(response.status)
            thread = threading.Thread(target=callback)
            thread.start()
            self.addCleanup(thread.join, 5)
            return True

        with patch('beatrice.google_auth.request_json', return_value={'access_token': 'fake'}) as request:
            result = authorize({'client_id': 'client', 'client_secret': 'secret'}, threading.Event(), opener=opener)
        self.assertEqual(result['access_token'], 'fake')
        form = request.call_args.args[1]
        expected = urlsafe_b64encode(sha256(form['code_verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(queries[0]['code_challenge'], [expected])
        self.assertEqual(queries[0]['scope'], [SCOPES])
        self.assertEqual(form['code'], 'test-code')
        self.assertEqual(form['redirect_uri'], queries[0]['redirect_uri'][0])

    def test_cancel_and_timeout_do_not_exchange(self):
        cancel = threading.Event()
        cancel.set()
        with patch('beatrice.google_auth.request_json') as request:
            with self.assertRaises(AuthError):
                authorize({'client_id': 'client'}, cancel, opener=lambda url: True)
            with self.assertRaises(AuthError):
                authorize({'client_id': 'client'}, threading.Event(), timeout=0, opener=lambda url: True)
            request.assert_not_called()

    def test_dedicated_browser_completion_closes_only_after_valid_callback(self):
        from unittest.mock import Mock
        browser=Mock(managed=True,completion_title='Beatrice-login-test-marker')
        pages=[];threads=[]
        def open_browser(url):
            query=parse_qs(urlsplit(url).query)
            def callback():
                with urlopen(query['redirect_uri'][0]+'?'+urlencode(dict(state=query['state'][0],code='test-code')),timeout=5) as response:
                    pages.append(response.read().decode())
            thread=threading.Thread(target=callback);threads.append(thread);thread.start()
            return True
        browser.open.side_effect=open_browser
        with patch('beatrice.google_auth.OAuthBrowser',return_value=browser),patch('beatrice.google_auth.request_json',return_value={'access_token':'fake'}):
            self.assertEqual(authorize({'client_id':'client'},threading.Event()),{'access_token':'fake'})
        for thread in threads:thread.join(timeout=5)
        browser.close_completed.assert_called_once_with()
        self.assertIn('<title>Beatrice-login-test-marker</title>',pages[0])
        self.assertNotIn('window.close()',pages[0])
        self.assertNotIn('test-code',pages[0])

    def test_cancelled_dedicated_login_cannot_close_unidentified_browser(self):
        from unittest.mock import Mock
        browser=Mock();browser.open.return_value=True
        cancel=threading.Event();cancel.set()
        with patch('beatrice.google_auth.OAuthBrowser',return_value=browser),patch('beatrice.google_auth.request_json') as request:
            with self.assertRaises(AuthError):authorize({'client_id':'client'},cancel)
        browser.close_completed.assert_not_called();request.assert_not_called()

    def test_refresh_keeps_refresh_token_and_checks_account(self):
        saved = dict(client_id='client', refresh_token='refresh', account={'sub': 'person'})
        with patch('beatrice.google_auth.load_client', return_value={'client_id': 'client', 'client_secret': 'secret'}), \
                patch('beatrice.google_auth.request_json', side_effect=[
                    {'access_token': 'new'}, {'sub': 'person', 'email': 'test@example.com', 'email_verified': True}]):
            result = authenticate('.', saved, threading.Event(), False)
        self.assertEqual(result['refresh_token'], 'refresh')
        self.assertNotIn('access_token', result)
        with patch('beatrice.google_auth.load_client', return_value={'client_id': 'other'}):
            with self.assertRaises(AuthError):
                authenticate('.', saved, threading.Event(), False)

    def test_profile_name_and_picture_survive_authentication_without_tokens_in_view(self):
        from beatrice.account_service import GoogleAccount
        saved=dict(client_id='client',refresh_token='refresh',account={'sub':'person'})
        profile=dict(sub='person',email='test@example.com',email_verified=True,name='사용자',picture='https://lh3.googleusercontent.com/profile')
        with patch('beatrice.google_auth.load_client',return_value={'client_id':'client'}), \
                patch('beatrice.google_auth.request_json',side_effect=[{'access_token':'new'},profile]):
            result=authenticate('.',saved,threading.Event(),False)
        with tempfile.TemporaryDirectory() as folder:
            account=GoogleAccount(Path('.'),Path(folder));account.session=result
            view=account.view()
            self.assertEqual(view['name'],'사용자')
            self.assertEqual(view['picture'],profile['picture'])
            self.assertNotIn('refresh_token',view)
            self.assertNotIn('access_token',view)
            account.session=dict(account={'email':'old@example.com'})
            self.assertEqual(account.view()['name'],'')
            self.assertEqual(account.view()['picture'],'')

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_credentials_are_encrypted_and_clearable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TokenStore(directory)
            self.assertIsNone(store.load())
            value = {'refresh_token': 'sensitive-test-value', 'account': {'sub': 'test'}}
            store.save(value)
            self.assertNotIn(b'sensitive-test-value', store.path.read_bytes())
            self.assertEqual(store.load(), value)
            store.clear()
            self.assertIsNone(store.load())



if __name__ == "__main__": unittest.main()
