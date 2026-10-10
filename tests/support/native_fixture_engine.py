"""Isolated pipe test fixture. Never imports models or contacts game/Drive."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datetime import datetime, timezone
from beatrice import engine_worker as engine
from beatrice.game_window import Client
from beatrice.native_bridge import main
from beatrice.storage import Store
from beatrice.weekly import open_week

engine.DATA = Path(os.environ['BEATRICE_DATA_DIR'])
engine.ROOT = engine.DATA  # No real config/API key can be read by this fixture.


class FixtureWorker(engine.Worker):
    def run(self):
        # Native/C library prints must land in runtime.log, never in JSON lines.
        os.write(1, b'fixture library stdout\n')
        os.write(2, b'fixture library stderr\n')
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            get_handle = ctypes.windll.kernel32.GetStdHandle
            get_handle.argtypes = [wintypes.DWORD]; get_handle.restype = wintypes.HANDLE
            write_file = ctypes.windll.kernel32.WriteFile
            write_file.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            written = wintypes.DWORD()
            message = b'fixture Win32 stdout\n'
            write_file(get_handle(-11 & 0xffffffff), message, len(message), ctypes.byref(written), None)
        self.progress.emit('1 / 3 · 샘플 초기화')
        client = Client(100, 200, 'LOST ARK 샘플')
        self.select(1, client)
        self.ready.emit([client])
        generation = -1
        while not self.stop_event.wait(.02):
            requested, client = self.requested()
            if requested != generation:
                generation = requested
                self.settled.emit(generation)
            if client:
                self.observation.emit(dict(generation=generation,
                    identity=dict(currentName='샘플 캐릭터', recordingAllowed=True),
                    dungeon=dict(dungeonName='카멘', difficulty='하드', contextStatus='ocr_verified', currentRaidPanel=True),
                    result=dict(stableStates=['완료', '진행중']), recordingStatus='샘플 분석 중'))


if __name__ == '__main__':
    engine.DATA.mkdir(parents=True, exist_ok=True)
    store = open_week(engine.DATA)
    store.save_completions('name:샘플 캐릭터', '카멘', [dict(characterName='샘플 캐릭터', dungeonName='카멘',
        difficulty='하드', gate=1, state='완료', observedAt=datetime.now(timezone.utc).isoformat())], 2)
    store.close()
    if os.environ.get('BEATRICE_FIXTURE_DRIVE') == '1':
        import time
        from beatrice import account_service, drive_service
        from beatrice.google_auth import DRIVE_SCOPE
        from beatrice.drive_data import validate_records
        account_service.authenticate = lambda *args: dict(account={'sub':'fixture','email':'fixture@example.com'},scopes=[DRIVE_SCOPE],refresh_token='fixture-secret')
        # Fixture-only persistence and transport; neither production auth nor HTTP is called.
        account_service.TokenStore.load = lambda self: None
        account_service.TokenStore.save = lambda self,value: None
        drive_service.drive_access_token = lambda *args: 'fixture-access'
        class FixtureDrive:
            def __init__(self,token,cancel,**kwargs): self.cancel=cancel
            def upload(self,records):
                time.sleep(.05)
                return dict(id='fixture-file')
            def download(self):
                time.sleep(.05)
                return dict(metadata={'createdTime':'2026-10-08T00:00:00Z'}, records=validate_records([
                    dict(characterName='원격 캐릭터',dungeonName='카멘',difficulty='하드',gate=2,state='완료')]))
        drive_service.DriveClient=FixtureDrive
    sys.exit(main(FixtureWorker))
