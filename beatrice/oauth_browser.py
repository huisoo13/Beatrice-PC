"""External OAuth window ownership, independent of tokens and account storage."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import subprocess
import time
import webbrowser


def browser_executable():
    """Prefer the default Chromium browser; otherwise use an installed Edge/Chrome."""
    if os.name != 'nt':return None
    import winreg
    preferred = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
            progid = winreg.QueryValueEx(key, 'ProgId')[0].lower()
        if 'chrome' in progid:preferred = 'chrome.exe'
        elif 'msedge' in progid:preferred = 'msedge.exe'
    except OSError:pass
    names = [preferred] if preferred else ['msedge.exe', 'chrome.exe']
    for name in names:
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\App Paths'+'\\'+name) as key:
                    path = Path(winreg.QueryValueEx(key, None)[0])
                if path.name.lower() == name and path.is_file():return str(path)
            except (OSError, TypeError, ValueError):pass
    return None


class WindowsBrowserWindows:
    """Never terminate a browser process or close a pre-existing HWND."""
    def __init__(self):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
        self.user.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self.user.GetPropW.restype = wintypes.HANDLE
        self.user.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self.user.RemovePropW.restype = wintypes.HANDLE
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    def handles(self):
        found = []
        callback = self.callback_type(lambda hwnd, _: found.append(hwnd) or True)
        self.user.EnumWindows(callback, 0)
        return set(found)

    def identity(self, hwnd):
        title = ctypes.create_unicode_buffer(512)
        kind = ctypes.create_unicode_buffer(128)
        self.user.GetWindowTextW(hwnd, title, len(title))
        self.user.GetClassNameW(hwnd, kind, len(kind))
        pid = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = self.kernel.OpenProcess(0x1000, False, pid.value)
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        try:
            if not process or not self.kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                return None
            return pid.value, path.value, title.value, kind.value
        finally:
            if process:self.kernel.CloseHandle(process)

    def close(self, hwnd, expected, marker):
        # The title is checked again immediately before posting, and the random
        # property prevents a recycled HWND from matching the tracked window.
        if self.identity(hwnd) != expected:return False
        if not self.user.SetPropW(hwnd, marker, 1):return False
        try:
            if self.user.GetPropW(hwnd, marker) != 1 or self.identity(hwnd) != expected:return False
            return bool(self.user.PostMessageW(hwnd, 0x0010, 0, 0))  # WM_CLOSE
        finally:
            self.user.RemovePropW(hwnd, marker)


class OAuthBrowser:
    def __init__(self, executable=None, windows=None, launch=None, fallback=None):
        self.executable = executable if executable is not None else browser_executable()
        self.windows = windows if windows is not None else (WindowsBrowserWindows() if self.executable and os.name == 'nt' else None)
        self.launch = launch or subprocess.Popen
        self.fallback = fallback or webbrowser.open
        self.marker = 'Beatrice-login-' + secrets.token_hex(16)
        self.before = set()
        self.managed = False

    @property
    def completion_title(self):
        return self.marker if self.managed else 'Beatrice'

    def open(self, url):
        if self.executable and self.windows:
            try:
                self.before = self.windows.handles()
                self.launch([self.executable, '--new-window', url], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.managed = True
                return True
            except OSError:pass
        return self.fallback(url)

    def close_completed(self, timeout=2):
        """Only a new browser window displaying this attempt's completion page can close."""
        if not self.managed:return False
        deadline = time.monotonic() + timeout
        while True:
            matches = []
            for hwnd in self.windows.handles() - self.before:
                identity = self.windows.identity(hwnd)
                if not identity:continue
                _, path, title, kind = identity
                if (os.path.normcase(path) == os.path.normcase(self.executable)
                        and (title == self.marker or title.startswith(self.marker+' - '))
                        and kind == 'Chrome_WidgetWin_1'):
                    matches.append((hwnd, identity))
            if len(matches) == 1:
                return self.windows.close(*matches[0], self.marker)
            if len(matches) > 1 or time.monotonic() >= deadline:return False
            time.sleep(.05)
