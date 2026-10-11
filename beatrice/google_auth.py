"""Desktop OAuth: system browser, loopback callback, PKCE and Windows DPAPI.

No credentials or callback URLs are logged.
"""
import base64
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import webbrowser

TOKEN_URL = 'https://oauth2.googleapis.com/token'
USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.appdata'
SCOPES = 'openid email profile ' + DRIVE_SCOPE


class AuthError(Exception):
    pass


def load_client(root):
    override = os.environ.get('BEATRICE_GOOGLE_CLIENT_FILE')
    files = [Path(override)] if override else sorted(Path(root).glob('client_secret_*.json'))
    if len(files) != 1:
        raise AuthError('앱 폴더에 데스크톱용 client_secret_*.json 파일 하나를 넣어주세요.')
    try:
        client = json.loads(files[0].read_text(encoding='utf-8-sig'))['installed']
        if not all(isinstance(client.get(k), str) and client[k] for k in ('client_id', 'client_secret')):
            raise ValueError()
        return {k: client[k] for k in ('client_id', 'client_secret')}
    except (OSError, ValueError, KeyError, TypeError):
        raise AuthError('Google 설정 파일을 읽을 수 없습니다. 데스크톱용 JSON을 확인해주세요.') from None


def dpapi(data, decrypt=False):
    """Encrypt for the current Windows user, with no UI or plaintext fallback."""
    if os.name != 'nt':
        raise AuthError('로그인 정보 보관은 Windows에서 지원합니다.')

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise AuthError('Windows에서 로그인 정보를 보호하거나 읽지 못했습니다. 다시 로그인해주세요.')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class TokenStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'google-session.bin'

    def load(self):
        if not self.path.exists():
            return None
        try:
            value = json.loads(dpapi(self.path.read_bytes(), decrypt=True))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (OSError, ValueError):
            raise AuthError('저장된 로그인 정보를 읽을 수 없습니다. 다시 로그인해주세요.') from None

    def save(self, value):
        encrypted = dpapi(json.dumps(value).encode('utf-8'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        try:
            temporary.write_bytes(encrypted)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)


def request_json(url, form=None, access_token=None):
    headers = {'Accept': 'application/json'}
    if access_token:
        headers['Authorization'] = 'Bearer ' + access_token
    body = urlencode(form).encode('ascii') if form is not None else None
    try:
        with urlopen(Request(url, data=body, headers=headers), timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise AuthError('Google 인증이 만료되었거나 거부되었습니다. 다시 로그인해주세요.') from None
        raise AuthError('Google 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.') from None
    except (URLError, OSError, ValueError):
        raise AuthError('인터넷 연결을 확인한 뒤 다시 시도해주세요.') from None


def callback_result(path, state):
    parts = urlsplit(path)
    if parts.path != '/':
        return None
    query = parse_qs(parts.query)
    if len(query.get('state', [])) != 1 or not secrets.compare_digest(query['state'][0], state):
        return None
    if 'error' in query:
        raise AuthError('Google 로그인이 취소되었거나 권한이 거부되었습니다.')
    if len(query.get('code', [])) != 1:
        raise AuthError('Google 로그인 응답이 올바르지 않습니다. 다시 시도해주세요.')
    return query['code'][0]


def authorize(client, cancel, timeout=180, opener=None, login_hint=None):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                code = callback_result(self.path, state)
                if code is None:
                    self.send_error(400)
                    return
                result['code'] = code
                message = '이 탭을 닫고 Beatrice 앱으로 돌아가세요. 로그인 결과는 앱에 표시됩니다.'
            except AuthError as exc:
                result['error'] = exc
                message = str(exc)
            # Browser-opened tabs may refuse window.close(); retain a quiet fallback.
            closing = ('<script>window.close();setTimeout(function(){'
                       'document.getElementById("message").hidden=false;},500);</script>') if 'code' in result else ''
            hidden = ' hidden' if closing else ''
            body = ('<!doctype html><meta charset="utf-8"><title>Beatrice</title>'
                    '<p id="message"' + hidden + '>' + message + '</p>' + closing).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(body)

    class Server(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(1)
            return connection, address

        def handle_error(self, request, address):
            pass  # Never print OAuth callback contents or request exceptions.

    with Server(('127.0.0.1', 0), Handler) as server:
        server.timeout = .2
        redirect = f'http://127.0.0.1:{server.server_port}/'
        parameters = dict(
            client_id=client['client_id'], redirect_uri=redirect, response_type='code',
            scope=SCOPES, state=state, code_challenge=challenge, code_challenge_method='S256',
            access_type='offline', prompt='consent select_account')
        if login_hint:
            parameters['login_hint'] = login_hint
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(parameters)
        if not (opener or webbrowser.open)(url):
            raise AuthError('브라우저를 열지 못했습니다. 기본 브라우저 설정을 확인해주세요.')
        deadline = time.monotonic() + timeout
        while not result and not cancel.is_set() and time.monotonic() < deadline:
            server.handle_request()
    if cancel.is_set():
        raise AuthError('로그인을 취소했습니다.')
    if not result:
        raise AuthError('로그인 대기 시간이 지났습니다. 다시 시도해주세요.')
    if 'error' in result:
        raise result['error']
    return request_json(TOKEN_URL, dict(client, code=result['code'], code_verifier=verifier,
                                       redirect_uri=redirect, grant_type='authorization_code'))


def authenticate(root, saved, cancel, interactive):
    client = load_client(root)
    if interactive:
        tokens = authorize(client, cancel, login_hint=(saved or {}).get('account', {}).get('email'))
    else:
        if not saved:
            return None
        if saved.get('client_id') != client['client_id'] or not saved.get('refresh_token'):
            raise AuthError('Google 로그인이 필요합니다.')
        tokens = request_json(TOKEN_URL, dict(client, refresh_token=saved['refresh_token'], grant_type='refresh_token'))
        tokens.setdefault('refresh_token', saved['refresh_token'])
    if cancel.is_set():
        raise AuthError('로그인을 취소했습니다.')
    if not tokens.get('access_token') or not tokens.get('refresh_token'):
        raise AuthError('로그인 유지 권한을 받지 못했습니다. 다시 로그인해주세요.')
    account = request_json(USERINFO_URL, access_token=tokens['access_token'])
    if not account.get('sub') or not account.get('email') or account.get('email_verified') is not True:
        raise AuthError('Google 계정 정보를 확인하지 못했습니다.')
    if saved and account['sub'] != saved.get('account', {}).get('sub'):
        raise AuthError('저장된 Google 계정이 일치하지 않습니다. 다시 로그인해주세요.')
    return dict(client_id=client['client_id'], refresh_token=tokens['refresh_token'],
                scopes=tokens.get('scope', SCOPES if interactive else ' '.join((saved or {}).get('scopes', []))).split(),
                account={k: account.get(k, '') if isinstance(account.get(k, ''),str) else ''
                         for k in ('sub', 'email', 'name', 'picture')})


def drive_access_token(root, saved, cancel):
    """Refresh in memory; the caller never prints or persists the access token."""
    client = load_client(root)
    if not saved or saved.get('client_id') != client['client_id'] or not saved.get('refresh_token'):
        raise AuthError('Google 로그인이 필요합니다.')
    if cancel.is_set():
        raise AuthError('작업을 취소했습니다.')
    tokens = request_json(TOKEN_URL, dict(client, refresh_token=saved['refresh_token'], grant_type='refresh_token'))
    scopes = tokens.get('scope', ' '.join(saved.get('scopes', []))).split()
    if DRIVE_SCOPE not in scopes:
        raise AuthError('Drive 권한 연결 버튼을 눌러 앱 전용 데이터 접근에 동의해주세요.')
    if not tokens.get('access_token'):
        raise AuthError('Google 인증을 확인하지 못했습니다. 다시 로그인해주세요.')
    return tokens['access_token']
