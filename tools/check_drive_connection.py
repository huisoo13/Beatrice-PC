"""Real Drive roundtrip in a separate test namespace; never reads/replaces game records."""
import argparse
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from beatrice.google_auth import AuthError, TokenStore, authenticate, drive_access_token
from beatrice.google_drive import DriveClient, DriveError, API
from beatrice.drive_data import validate_records
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize', action='store_true', help='Open browser to grant Drive access')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('BEATRICE_DATA_DIR',
        str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'BeatricePC'))))
    args = parser.parse_args()
    store = TokenStore(args.data_dir)
    saved = store.load()
    cancel = threading.Event()
    if not saved:
        raise AuthError('먼저 앱에서 Google 로그인해주세요.')
    if args.authorize:
        print('브라우저에서 기존 Google 계정으로 Drive 접근에 동의해주세요.', flush=True)
        saved = authenticate(ROOT, saved, cancel, True)
        store.save(saved)
    token = drive_access_token(ROOT, saved, cancel)
    client = DriveClient(token, cancel, namespace='integration-test')
    rows = [dict(characterName='연결확인용캐릭터', dungeonName='연결확인용던전',
                 difficulty='노말', gate=1, state='완료')]
    metadata = client.upload(rows)
    try:
        listing = client.latest()
        if not listing or listing['id'] != metadata['id']:
            raise DriveError('테스트 파일 조회 결과가 일치하지 않습니다.')
        if client.read(listing) != validate_records(rows):
            raise DriveError('테스트 데이터가 일치하지 않습니다.')
        print('PASS: 실제 Drive JSON 생성 / 앱 전용 폴더 조회 / 다운로드 내용 일치', flush=True)
    finally:
        # Only the unique file this invocation just created is deleted.
        client.request(API + '/' + quote(metadata['id'], safe=''), method='DELETE')
        print('테스트 파일 삭제 완료. 실제 게임 기록은 변경하지 않았습니다.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (AuthError, DriveError, OSError, ValueError) as exc:
        print(str(exc), flush=True)
        sys.exit(1)
