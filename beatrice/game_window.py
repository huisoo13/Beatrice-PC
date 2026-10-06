"""OBS가 연결할 Windows 게임 창을 탐색하고 실행 상태를 확인합니다."""
import sys
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import PureWindowsPath


@dataclass(frozen=True)
class Client:
    hwnd: int
    pid: int
    title: str

    @property
    def identity(self):
        return self.hwnd, self.pid


def process_name(pid):
    kernel=C.windll.kernel32
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]
    kernel.OpenProcess.restype=W.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes=[W.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return ''
    try:
        size=W.DWORD(32768);path=C.create_unicode_buffer(size.value)
        if kernel.QueryFullProcessImageNameW(handle,0,path,C.byref(size)):
            return PureWindowsPath(path.value).name.casefold()
        return ''
    finally:kernel.CloseHandle(handle)


def client_alive(client):
    if sys.platform!='win32':return False
    u=api();pid=W.DWORD()
    u.GetWindowThreadProcessId(client.hwnd,C.byref(pid))
    return bool(u.IsWindow(client.hwnd) and pid.value==client.pid)


def client_active(client):
    if not client_alive(client):return False
    u=api()
    return not u.IsIconic(client.hwnd) and u.GetForegroundWindow()==client.hwnd


def api():
    if sys.platform!='win32': raise RuntimeError('실시간 캡처는 Windows에서 실행해주세요.')
    u=C.windll.user32
    u.GetForegroundWindow.restype=W.HWND
    for name in ('IsWindowVisible','IsIconic','IsWindow'):
        getattr(u,name).argtypes=[W.HWND]
    u.GetWindowTextLengthW.argtypes=[W.HWND]
    u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
    u.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
    u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    return u


def find_clients(pids=None):
    if sys.platform!='win32': return []
    u=api();items=[]
    callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    def visit(hwnd,_):
        n=u.GetWindowTextLengthW(hwnd)
        if n and u.IsWindowVisible(hwnd):
            title=C.create_unicode_buffer(n+1);u.GetWindowTextW(hwnd,title,n+1)
            pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,C.byref(pid))
            if (pid.value in pids if pids is not None else process_name(pid.value)=='lostark.exe'):
                items.append(Client(int(hwnd),pid.value,title.value))
        return True
    u.EnumWindows(callback(visit),0)
    return items
