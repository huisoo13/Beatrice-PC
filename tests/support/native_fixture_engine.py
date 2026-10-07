"""Isolated pipe test fixture. Never imports models or contacts game/Drive."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from datetime import datetime, timezone
from PySide6.QtCore import QThread
from beatrice import desktop
from beatrice.game_window import Client
from beatrice.native_bridge import main
from beatrice.storage import Store

desktop.DATA = Path(os.environ['BEATRICE_DATA_DIR'])
desktop.ROOT = desktop.DATA  # No real config/API key can be read by this fixture.


class FixtureWorker(desktop.Worker):
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
    desktop.DATA.mkdir(parents=True, exist_ok=True)
    store = Store(desktop.DATA / 'records.sqlite3')
    store.save_completions('name:샘플 캐릭터', '카멘', [dict(characterName='샘플 캐릭터', dungeonName='카멘',
        difficulty='하드', gate=1, state='완료', observedAt=datetime.now(timezone.utc).isoformat())], 2)
    store.close()
    sys.exit(main(FixtureWorker))
