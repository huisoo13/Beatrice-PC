"""Real Drive roundtrip in a separate test namespace; never reads/replaces game records."""
import argparse
import os
import secrets
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from beatrice.google_auth import AuthError, TokenStore, authenticate, drive_access_token
from beatrice.google_drive import DriveClient, DriveError, API, PROPERTY
from beatrice.drive_data import validate_records, encode_records
from beatrice.drive import DriveNotFoundError
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
    # Capture the ID before verification so later failures still clean up the file.
    metadata = client.api.files.create(
        dict(name='beatrice-records-integration-test-' + secrets.token_hex(16) + '.json',
             mimeType='application/json', parents=['appDataFolder'],
             appProperties={PROPERTY: 'integration-test', 'schemaVersion': '3'}),
        encode_records(rows), mime_type='application/json',
        fields='id,name,createdTime,modifiedTime,mimeType,appProperties')
    try:
        listing = client.latest()
        if not listing or listing['id'] != metadata['id']:
            raise DriveError('테스트 파일 조회 결과가 일치하지 않습니다.')
        if client.read(listing) != validate_records(rows):
            raise DriveError('테스트 데이터가 일치하지 않습니다.')
        print('PASS: 실제 Drive JSON 생성 / 앱 전용 폴더 조회 / 다운로드 내용 일치', flush=True)
        changed = rows + [dict(rows[0], gate=2)]
        updated = client.api.files.update(metadata['id'], {'name': metadata['name']},
            encode_records(changed), mime_type='application/json',
            fields='id,name,createdTime,modifiedTime,mimeType,appProperties')
        if updated['id'] != metadata['id'] or client.read(updated) != validate_records(changed):
            raise DriveError('동일 파일 수정 후 ID 또는 다운로드 내용이 일치하지 않습니다.')
        print('PASS: 동일 테스트 파일 PATCH / 파일 ID 유지 / 수정 내용 재다운로드 검증', flush=True)
    finally:
        # Only the unique file this invocation just created is deleted.
        client.request(API + '/' + quote(metadata['id'], safe=''), method='DELETE')
        try:
            client.api.files.get(metadata['id'])
        except DriveNotFoundError:
            print('PASS: 테스트 파일 삭제 후 404 확인. 실제 게임 기록은 변경하지 않았습니다.', flush=True)
        else:
            raise DriveError('테스트 파일 삭제를 확인하지 못했습니다.')


if __name__ == '__main__':
    try:
        main()
    except (AuthError, DriveError, OSError, ValueError) as exc:
        print(str(exc), flush=True)
        sys.exit(1)
