"""Real Edit/clipboard integration on a PRIVATE window station.

Never opens or changes the user's desktop clipboard. Run in a subprocess.
"""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from assistant import win32 as win
from assistant.engine import Runner


def run():
    u, k, bind = win.user, win.kernel, win.bind
    bind(u, "CreateWindowStationW", [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p], W.HANDLE)
    bind(u, "SetProcessWindowStation", [W.HANDLE], W.BOOL)
    bind(u, "CreateDesktopW", [W.LPCWSTR, W.LPCWSTR, C.c_void_p, W.DWORD, W.DWORD, C.c_void_p], W.HANDLE)
    bind(u, "SetThreadDesktop", [W.HANDLE], W.BOOL)
    station = u.CreateWindowStationW(f"AutoToolsTest_{os.getpid()}", 0, 0x37F, None)
    if not station or not u.SetProcessWindowStation(station):
        print("SKIP: Windows denied private clipboard isolation")
        raise SystemExit(77)
    desktop = u.CreateDesktopW("EditTest", None, None, 0, 0x1FF, None)
    assert desktop and u.SetThreadDesktop(desktop), "Cannot isolate desktop"
    bind(u, "CreateWindowExW", [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
         C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p], W.HWND)
    bind(u, "SendMessageW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM], win.LRESULT)
    bind(u, "ShowWindow", [W.HWND, C.c_int], W.BOOL)
    bind(u, "DestroyWindow", [W.HWND], W.BOOL)
    bind(u, "OpenClipboard", [W.HWND], W.BOOL)
    bind(u, "CloseClipboard", [], W.BOOL)
    bind(u, "EmptyClipboard", [], W.BOOL)
    bind(u, "SetClipboardData", [W.UINT, W.HANDLE], W.HANDLE)
    bind(k, "GlobalAlloc", [W.UINT, C.c_size_t], W.HGLOBAL)
    bind(k, "GlobalLock", [W.HGLOBAL], C.c_void_p)
    bind(k, "GlobalUnlock", [W.HGLOBAL], W.BOOL)
    hwnd = u.CreateWindowExW(0, "EDIT", "测试", 0x00CF0004, 0, 0, 320, 200, None, None, k.GetModuleHandleW(None), None)
    assert hwnd
    assert u.OpenClipboard(hwnd)
    try:
        assert u.EmptyClipboard()
        payload = "测试\0".encode("utf-16-le")
        handle = k.GlobalAlloc(2, len(payload))
        pointer = k.GlobalLock(handle)
        assert pointer
        C.memmove(pointer, payload, len(payload))
        k.GlobalUnlock(handle)
        assert u.SetClipboardData(13, handle)
    finally:
        u.CloseClipboard()
    name, created = win.process_info(os.getpid())
    target = win.Target(hwnd, os.getpid(), created, name, "isolated edit", hwnd)
    for minimized in (False, True):
        initial = C.create_unicode_buffer("测试")
        u.SendMessageW(hwnd, 0xC, 0, C.addressof(initial))
        u.SendMessageW(hwnd, 0xB1, 2, 2)
        if minimized:
            u.ShowWindow(hwnd, 7)
            assert u.IsIconic(hwnd)
        foreground = u.GetForegroundWindow()
        events = []
        runner = Runner(lambda kind, value: events.append((kind, value)))
        runner.keys(target, [{"key": "ENTER", "hold": .01, "wait": .01},
                            {"key": "CTRL+V", "hold": .01, "wait": .01}], 3)
        deadline = time.monotonic() + 5
        msg = W.MSG()
        while runner.busy and time.monotonic() < deadline:
            while u.PeekMessageW(C.byref(msg), None, 0, 0, 1):
                u.TranslateMessage(C.byref(msg)); u.DispatchMessageW(C.byref(msg))
            time.sleep(.002)
        assert not runner.busy, "Queue timed out"
        assert [v["error"] for kind, v in events if kind == "finished"] == [None], events
        actual = win.text(hwnd)
        assert actual == "测试\r\n测试\r\n测试\r\n测试", repr(actual)
        assert u.GetForegroundWindow() == foreground
        if minimized:
            assert u.IsIconic(hwnd)
        print(f"PASS actual Edit text, minimized={minimized}: {actual!r}")
    u.DestroyWindow(hwnd)


if __name__ == "__main__":
    run()
