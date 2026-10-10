"""Exercise completion -> engine scheduler -> real Drive using an isolated temporary DB."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from beatrice.google_auth import AuthError, TokenStore, drive_access_token
from beatrice.google_drive import DriveClient, DriveError, API
from beatrice.account_service import GoogleAccount
from beatrice.drive_service import PersonalDrive
from beatrice.storage import Store


def main():
    data = Path(os.environ.get('BEATRICE_DATA_DIR',
        str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'BeatricePC')))
    session = TokenStore(data).load()
    token = drive_access_token(ROOT, session, threading.Event())
    created = []

    class TestDrive(DriveClient):
        def __init__(self, token, cancel, **kwargs):
            super().__init__(token, cancel, namespace='integration-test', **kwargs)

        def upload(self, rows):
            metadata = super().upload(rows)
            created.append(metadata)
            return metadata

    client = DriveClient(token, threading.Event(), namespace='integration-test')
    try:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'test.sqlite3')
            login = GoogleAccount(ROOT, directory)
            login.session = session
            panel = PersonalDrive(ROOT, directory, login, store)
            rows = [dict(characterName='자동연결테스트', characterKey='name:자동연결테스트',
                         dungeonName='테스트던전', difficulty='노말', gate=i,
                         state='완료' if i == 1 else '진행 전', timeBasis='live_capture') for i in (1, 2)]
            try:
                with patch('beatrice.drive_service.DriveClient', TestDrive):
                    previous_cloud = None
                    for complete_gate in (1, 2):
                        rows[complete_gate - 1]['state'] = '완료'
                        store.save_states('name:자동연결테스트', '테스트던전', rows)
                        deadline = time.monotonic() + 90
                        while store.drive_pending(session['account']['sub']) or panel.busy:
                            panel.poll()
                            panel.check_auto_upload()
                            if time.monotonic() > deadline:
                                raise DriveError('자동 저장 테스트 제한 시간 초과: ' + panel.message)
                            time.sleep(.05)
                        if len(created) != complete_gate:
                            raise DriveError('완료 변경당 자동 업로드 횟수가 일치하지 않습니다.')
                        cloud = client.download()['records']
                        if cloud[complete_gate - 1]['state'] != '완료':
                            raise DriveError('Drive의 최신 완료 상태가 일치하지 않습니다.')
                        if any(not r.get('recordID') or not r.get('updatedAt') for r in cloud):
                            raise DriveError('Drive에 recordID 또는 updatedAt이 없습니다.')
                        if previous_cloud:
                            if cloud[0]['recordID'] != previous_cloud[0]['recordID']:
                                raise DriveError('기존 관문의 recordID가 달라졌습니다.')
                            if cloud[0]['updatedAt'] != previous_cloud[0]['updatedAt']:
                                raise DriveError('변경 없는 기록의 시각이 달라졌습니다.')
                        previous_cloud = cloud
                        print(f'PASS: {complete_gate}관문 완료 -> 자동 업로드 -> 최신 JSON 내용 확인', flush=True)
                    store.save_states('name:자동연결테스트', '테스트던전', rows)
                    if store.drive_pending(session['account']['sub']):
                        raise DriveError('같은 완료를 다시 관측하면 안 됩니다.')
                    print('PASS: recordID 유지 / 변경된 기록만 updatedAt 갱신 / 동일 완료 중복 전송 없음', flush=True)
            finally:
                panel.shutdown()
                login.shutdown()
                while not panel.settled:
                    panel.poll(); time.sleep(.05)
                store.close()
    finally:
        for metadata in created:
            client.request(API + '/' + quote(metadata['id'], safe=''), method='DELETE')
        print(f'테스트 파일 {len(created)}개 삭제. 실제 게임 기록과 운영 Drive 백업은 변경하지 않았습니다.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (AuthError, DriveError, OSError, ValueError) as exc:
        print(str(exc), flush=True)
        sys.exit(1)
