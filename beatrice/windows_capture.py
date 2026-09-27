"""Windows 게임 창의 클라이언트 영역만 캡처합니다."""
import sys
import ctypes as C
from ctypes import wintypes as W
import re
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
    u.MonitorFromWindow.argtypes=[W.HWND,W.DWORD];u.MonitorFromWindow.restype=W.HMONITOR
    for name in ('IsWindowVisible','IsIconic','IsWindow'):
        getattr(u,name).argtypes=[W.HWND]
    u.GetWindowTextLengthW.argtypes=[W.HWND]
    u.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
    u.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
    u.ClientToScreen.argtypes=[W.HWND,C.POINTER(W.POINT)]
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


def windows():
    return [(client.hwnd,client.title) for client in find_clients()]


class WindowCapture:
    def __init__(self,hwnd): self.hwnd=hwnd;self.camera=None;self.monitor=None
    def close(self):
        if self.camera is not None:self.camera.release();self.camera=None
    def grab(self):
        u=api()
        if not u.IsWindow(self.hwnd): raise RuntimeError('게임 창이 종료됐습니다. 다시 선택해주세요.')
        if u.IsIconic(self.hwnd) or u.GetForegroundWindow()!=self.hwnd:
            return None,'게임 창이 활성화되기를 기다리는 중'
        monitor=u.MonitorFromWindow(self.hwnd,2)
        if self.camera is None or monitor!=self.monitor:
            self.close()
            import dxcam
            for device,output in re.findall(r'Device\[(\d+)\] Output\[(\d+)\]',dxcam.output_info()):
                camera=dxcam.create(device_idx=int(device),output_idx=int(output),output_color='BGR',backend='dxgi')
                if int(getattr(camera._output.hmonitor,'value',camera._output.hmonitor))==int(monitor):
                    self.camera=camera;self.monitor=monitor;break
                camera.release()
            if self.camera is None:raise RuntimeError('게임 창의 모니터를 찾지 못했습니다.')
        rect=W.RECT();point=W.POINT(0,0)
        if not u.GetClientRect(self.hwnd,C.byref(rect)) or not u.ClientToScreen(self.hwnd,C.byref(point)):
            return None,'게임 창 위치 확인 중'
        desktop=self.camera._output.desc.DesktopCoordinates
        x=point.x-desktop.left;y=point.y-desktop.top
        width=rect.right;height=rect.bottom
        image=self.camera.grab(new_frame_only=False)
        if image is None:return None,'캡처 프레임 대기 중'
        if width<=0 or height<=0 or x<0 or y<0 or x+width>image.shape[1] or y+height>image.shape[0]:
            return None,'게임 창 전체를 하나의 모니터 안으로 옮겨주세요.'
        return image[y:y+height,x:x+width].copy(),''
