"""Read-only process snapshots, immediately on startup and then every second."""
import ctypes as C
from ctypes import wintypes as W
import sys
import threading


def lostark_pids():
    if sys.platform!='win32':return frozenset()
    class Entry(C.Structure):
        _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),
                  ('th32DefaultHeapID',C.c_size_t),('th32ModuleID',W.DWORD),
                  ('cntThreads',W.DWORD),('th32ParentProcessID',W.DWORD),
                  ('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
    kernel.CloseHandle.argtypes=[W.HANDLE]
    for name in ('Process32FirstW','Process32NextW'):
        getattr(kernel,name).argtypes=[W.HANDLE,C.POINTER(Entry)]
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)  # TH32CS_SNAPPROCESS only
    if snapshot==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
    try:
        entry=Entry();entry.dwSize=C.sizeof(entry);result=set()
        found=kernel.Process32FirstW(snapshot,C.byref(entry))
        while found:
            if entry.szExeFile.casefold()=='lostark.exe':result.add(entry.th32ProcessID)
            found=kernel.Process32NextW(snapshot,C.byref(entry))
        if C.get_last_error()!=18:raise C.WinError(C.get_last_error())  # ERROR_NO_MORE_FILES
        return frozenset(result)
    finally:kernel.CloseHandle(snapshot)


class ProcessWatch(threading.Thread):
    def __init__(self,on_state,snapshot=lostark_pids,interval=1.0):
        super().__init__(name='LOSTARK process polling')
        if interval<=0:raise ValueError('interval must be positive')
        self.on_state=on_state;self.snapshot=snapshot;self.interval=interval
        self.stop_event=threading.Event();self.ready=threading.Event()
        self.pids=frozenset();self.error=''
    def run(self):
        previous=None
        try:
            while not self.stop_event.is_set():
                try:
                    pids=frozenset(self.snapshot());error=''
                except Exception as exc:
                    pids=frozenset();error=f'프로세스 확인 실패: {exc} · 자동 재시도 중'
                if self.stop_event.is_set():break
                self.pids=pids;self.error=error
                state=(pids,error)
                if state!=previous:
                    self.on_state(pids,error);previous=state
                self.ready.set()
                if self.stop_event.wait(self.interval):break
        finally:self.ready.set()
