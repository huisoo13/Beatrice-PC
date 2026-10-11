"""Join the UI-owned lifetime job before loading numerical libraries."""
import os


def join_owner_job():
    name = os.environ.get('BEATRICE_ENGINE_JOB')
    if os.name != 'nt' or not name:
        return
    import ctypes as C
    from ctypes import wintypes as W
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.OpenJobObjectW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
    kernel.OpenJobObjectW.restype = W.HANDLE
    kernel.GetCurrentProcess.restype = W.HANDLE
    kernel.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)]
    kernel.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    job = kernel.OpenJobObjectW(1 | 4, False, name)  # assign + query
    if not job:
        raise C.WinError(C.get_last_error())
    try:
        process = kernel.GetCurrentProcess()
        attached = W.BOOL()
        if not kernel.IsProcessInJob(process, job, C.byref(attached)):
            raise C.WinError(C.get_last_error())
        if not attached.value and not kernel.AssignProcessToJobObject(job, process):
            # The UI may have attached the redirector while this call raced it.
            if not kernel.IsProcessInJob(process, job, C.byref(attached)) or not attached.value:
                raise C.WinError(C.get_last_error())
    finally:
        kernel.CloseHandle(job)
