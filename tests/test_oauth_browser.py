"""Window ownership tests use fake browsers and never access Google credentials."""
import unittest
from unittest.mock import Mock
from beatrice.oauth_browser import OAuthBrowser


class FakeWindows:
    def __init__(self):
        self.rows={10:(100,'browser.exe','existing','Chrome_WidgetWin_1')}
        self.closed=[]
    def handles(self):return set(self.rows)
    def identity(self, hwnd):return self.rows.get(hwnd)
    def close(self, hwnd, identity, marker):
        if self.rows.get(hwnd)!=identity:return False
        self.closed.append(hwnd);self.rows.pop(hwnd)
        return True


class OAuthBrowserTests(unittest.TestCase):
    def browser(self, launch=None):
        windows=FakeWindows()
        browser=OAuthBrowser(executable='browser.exe',windows=windows,launch=launch or Mock(),fallback=Mock(return_value=True))
        return browser,windows

    def test_new_window_flag_and_only_exact_completion_window_closes(self):
        browser,windows=self.browser()
        browser.open('https://accounts.google.com/o/oauth2/v2/auth?state=test')
        self.assertEqual(browser.launch.call_args.args[0][:2],['browser.exe','--new-window'])
        windows.rows[20]=(100,'browser.exe',browser.completion_title+' - Browser','Chrome_WidgetWin_1')
        windows.rows[30]=(100,'browser.exe','unrelated new window','Chrome_WidgetWin_1')
        self.assertTrue(browser.close_completed(timeout=0))
        self.assertEqual(windows.closed,[20]);self.assertEqual(set(windows.rows),{10,30})

    def test_preexisting_window_is_never_closed_even_with_matching_title(self):
        browser,windows=self.browser();browser.open('url')
        windows.rows[10]=(100,'browser.exe',browser.completion_title,'Chrome_WidgetWin_1')
        self.assertFalse(browser.close_completed(timeout=0));self.assertEqual(windows.closed,[])

    def test_wrong_executable_or_class_or_marker_never_closes(self):
        for path,title,kind in [('other.exe',None,'Chrome_WidgetWin_1'),('browser.exe','other','Chrome_WidgetWin_1'),('browser.exe',None,'other')]:
            browser,windows=self.browser();browser.open('url')
            windows.rows[20]=(200,path,title or browser.completion_title,kind)
            self.assertFalse(browser.close_completed(timeout=0));self.assertEqual(windows.closed,[])

    def test_ambiguous_completion_windows_remain_open(self):
        browser,windows=self.browser();browser.open('url')
        for hwnd in (20,30):windows.rows[hwnd]=(100,'browser.exe',browser.completion_title,'Chrome_WidgetWin_1')
        self.assertFalse(browser.close_completed(timeout=0));self.assertEqual(windows.closed,[])

    def test_failed_launch_falls_back_without_native_window_cleanup(self):
        browser,windows=self.browser(Mock(side_effect=OSError()))
        self.assertTrue(browser.open('url'));browser.fallback.assert_called_once_with('url')
        self.assertEqual(browser.completion_title,'Beatrice')
        self.assertFalse(browser.close_completed(timeout=0));self.assertEqual(windows.closed,[])


if __name__=='__main__':unittest.main()
