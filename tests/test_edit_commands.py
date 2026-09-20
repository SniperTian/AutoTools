from pathlib import Path
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from assistant import win32 as win


class EditCommandsTests(unittest.TestCase):
    def test_real_edit_newline_and_select_all_while_minimized(self):
        # A private test window; no clipboard calls or input injection.
        win.bind(win.user, "CreateWindowExW", [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
            C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p], W.HWND)
        win.bind(win.user, "DestroyWindow", [W.HWND], W.BOOL)
        win.bind(win.user, "ShowWindow", [W.HWND, C.c_int], W.BOOL)
        hwnd = win.user.CreateWindowExW(0, "EDIT", "测试", 0x00CF0004, 0, 0, 300, 180,
                                       None, None, win.kernel.GetModuleHandleW(None), None)
        self.assertTrue(hwnd)
        try:
            name, created = win.process_info(os.getpid())
            backend = win.BackgroundInput(win.Target(hwnd, os.getpid(), created, name, "test", hwnd))
            backend.command(hwnd, 0xB1, 2, 2)
            foreground = win.user.GetForegroundWindow()
            win.user.ShowWindow(hwnd, 7)
            self.assertTrue(win.user.IsIconic(hwnd))
            backend.chord([13])
            self.assertEqual(win.text(hwnd), "测试\r\n")
            backend.chord([17, 65])
            start, end = W.DWORD(), W.DWORD()
            backend.command(hwnd, 0xB0, C.addressof(start), C.addressof(end))
            self.assertEqual((start.value, end.value), (0, 4))
            self.assertEqual(win.user.GetForegroundWindow(), foreground)
            self.assertTrue(win.user.IsIconic(hwnd))
        finally:
            win.user.DestroyWindow(hwnd)

    def test_actual_clipboard_paste_on_isolated_desktop(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("native_edit_probe.py"))],
                                capture_output=True, text=True, timeout=20)
        if result.returncode == 77:
            self.skipTest(result.stdout.strip())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unsupported_paste_never_posts_literal_v(self):
        backend = win.BackgroundInput(Mock())
        with patch.object(backend, "text_receiver", return_value=None), patch.object(backend, "key") as key:
            with self.assertRaises(ValueError):
                backend.chord([17, 86])
            key.assert_not_called()

    def test_paste_sends_command_without_modifier_messages(self):
        backend = win.BackgroundInput(Mock())
        with patch.object(backend, "text_receiver", return_value=123), patch.object(backend, "command") as command, patch.object(backend, "key") as key:
            backend.chord([17, 86])
            command.assert_called_once_with(123, 0x302, 0, 0)
            key.assert_not_called()

    def test_timeout_reports_failure(self):
        backend = win.BackgroundInput(Mock())
        with patch.object(win.user, "SendMessageTimeoutW", return_value=0):
            with self.assertRaises(OSError):
                backend.command(123, 0x302)
