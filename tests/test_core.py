import copy
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from assistant.model import (parse_chord, normalize_chord, number, hotkey_spec,
                             read_json, write_json, validate_steps, validate_recording)
from assistant.engine import Runner
from assistant.hooks import InputService
from assistant import win32 as win


def recording():
    return {"format": "game-assistant-recording", "version": 1, "coordinate_mode": "screen",
            "duration": .03, "environment": {}, "events": [
                {"type": "key", "t": 0, "vk": 65, "scan": 30, "extended": False, "down": True},
                {"type": "key", "t": .02, "vk": 65, "scan": 30, "extended": False, "down": False}]}


class ModelTests(unittest.TestCase):
    def test_chord_orders_modifiers(self):
        self.assertEqual(parse_chord("q+ctrl+shift"), [17, 16, 81])
        self.assertEqual(normalize_chord(" ctrl + q "), "CTRL+Q")

    def test_invalid_chords(self):
        for value in ("", "A+B", "CTRL+CTRL+A", "CTRL+", "UNKNOWN"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_chord(value)

    def test_hotkey_requires_main_and_rejects_f12(self):
        for value in ("CTRL", "F12"):
            with self.assertRaises(ValueError):
                hotkey_spec(value)
        self.assertEqual(hotkey_spec("CTRL+ALT+B"), (3, 66))

    def test_finite_timing(self):
        for value in (float("nan"), float("inf"), -1, True):
            with self.assertRaises(ValueError):
                number(value, "time")

    def test_queue_validation(self):
        self.assertEqual(validate_steps([{"key": "space", "hold": "0.1", "wait": "0"}])[0]["key"], "SPACE")
        with self.assertRaises(ValueError):
            validate_steps([])
        with self.assertRaises(ValueError):
            validate_steps([{"key": "A", "hold": 0, "wait": 0}])

    def test_json_roundtrip_unicode(self):
        # A normal-permission scratch directory also works in restricted Windows
        # test runners, unlike tempfile's private (0700) directory ACL.
        path = Path(os.environ.get("GA_TEST_TMP", "work")) / ("roundtrip_" + uuid.uuid4().hex)
        path.mkdir(parents=True)
        try:
            file = Path(path) / "录制.json"
            write_json(file, recording())
            self.assertEqual(validate_recording(read_json(file)), recording())
        finally:
            for item in path.iterdir():
                item.unlink()
            path.rmdir()

    def test_bad_recordings(self):
        original = recording()
        for field, value in (("version", 2), ("events", []), ("coordinate_mode", "invalid"), ("environment", [])):
            data = copy.deepcopy(original); data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_recording(data)

    def test_recording_order_and_balance(self):
        data = recording(); data["events"][1]["t"] = -1
        with self.assertRaises(ValueError):
            validate_recording(data)
        data = recording(); data["events"].pop()
        with self.assertRaises(ValueError):
            validate_recording(data)
        data = recording(); data["events"][0]["down"] = False
        with self.assertRaises(ValueError):
            validate_recording(data)


class FakeDesktop:
    instances = []

    def __init__(self):
        self.events = []
        self.released = False
        self.__class__.instances.append(self)

    def key(self, *args): self.events.append(("key", args))
    def button(self, *args): self.events.append(("button", args))
    def move(self, *args): self.events.append(("move", args))
    def wheel(self, *args): self.events.append(("wheel", args))
    def release(self): self.released = True


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.runner = Runner(lambda k, v: self.messages.append((k, v)))
        FakeDesktop.instances.clear()

    def finish(self):
        self.runner.thread.join(3)
        self.assertFalse(self.runner.busy)
        errors = [v["error"] for k, v in self.messages if k == "finished"]
        self.assertEqual(errors, [None])

    @patch("assistant.engine.DesktopInput", FakeDesktop)
    def test_double_click_count(self):
        self.runner.click("middle", True, .001, 2, delay=0)
        self.finish()
        self.assertEqual(len(FakeDesktop.instances[0].events), 8)
        self.assertTrue(FakeDesktop.instances[0].released)

    @patch("assistant.engine.DesktopInput", FakeDesktop)
    def test_stop_interrupts_long_wait(self):
        self.runner.click("left", False, 3600, 0, delay=0)
        time.sleep(.06)
        started = time.monotonic(); self.runner.stop(); self.finish()
        self.assertLess(time.monotonic()-started, .2)
        self.assertTrue(FakeDesktop.instances[0].released)

    @patch("assistant.engine.DesktopInput", FakeDesktop)
    def test_replay_order_and_loops(self):
        self.runner.replay(recording(), 2, 2, 0, 0)
        self.finish()
        self.assertEqual(FakeDesktop.instances[0].events, [
            ("key", (65, True, 30, False)), ("key", (65, False, 30, False))] * 2)

    @patch("assistant.engine.DesktopInput", FakeDesktop)
    def test_exclusive_task(self):
        self.runner.click("left", False, 1, 0, delay=30)
        with self.assertRaises(ValueError):
            self.runner.click("right", False, 1, 1)
        self.runner.stop(); self.finish()

    @patch("assistant.engine.DesktopInput", FakeDesktop)
    def test_window_replay_stops_on_focus_loss(self):
        class Target:
            hwnd = 123
            def valid(self): return True
        data = recording(); data["coordinate_mode"] = "window"
        data["events"][0]["t"] = 10
        with patch("assistant.engine.user.GetForegroundWindow", return_value=456), patch("assistant.engine.user.IsIconic", return_value=False):
            self.runner.replay(data, 1, 1, 0, 0, Target())
            self.runner.thread.join(1)
        self.assertFalse(self.runner.busy)
        self.assertEqual(FakeDesktop.instances[0].events, [])
        self.assertTrue(FakeDesktop.instances[0].released)
        self.assertIn("失焦", self.messages[-1][1]["error"])


class NativeReceiver:
    """A real Win32 test window, not an application controlled by the user."""
    def __init__(self):
        self.events = []
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            raise RuntimeError("Test receiver failed to start")

    def run(self):
        WNDPROC = C.WINFUNCTYPE(win.LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

        class WNDCLASS(C.Structure):
            _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                        ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HANDLE),
                        ("hCursor", W.HANDLE), ("hbrBackground", W.HANDLE),
                        ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]

        win.bind(win.user, "DefWindowProcW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM], win.LRESULT)
        win.bind(win.user, "RegisterClassW", [C.POINTER(WNDCLASS)], W.ATOM)
        win.bind(win.user, "CreateWindowExW", [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                 C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p], W.HWND)
        win.bind(win.user, "ShowWindow", [W.HWND, C.c_int], W.BOOL)
        win.bind(win.user, "DestroyWindow", [W.HWND], W.BOOL)

        @WNDPROC
        def proc(hwnd, msg, wp, lp):
            if msg in (0x100, 0x101, 0x104, 0x105):
                self.events.append((msg, int(wp), int(lp)))
                return 0
            if msg == 0x10:
                win.user.DestroyWindow(hwnd)
                win.user.PostQuitMessage(0)
                return 0
            return win.user.DefWindowProcW(hwnd, msg, wp, lp)

        self.proc = proc
        module = win.kernel.GetModuleHandleW(None)
        cls = WNDCLASS(lpfnWndProc=proc, hInstance=module, lpszClassName=f"GA_Test_{id(self)}")
        if not win.user.RegisterClassW(C.byref(cls)):
            raise C.WinError(C.get_last_error())
        self.hwnd = win.user.CreateWindowExW(0, cls.lpszClassName, "GA background test receiver", 0x00CF0000,
                                             10, 10, 250, 180, None, None, module, None)
        name, created = win.process_info(os.getpid())
        self.target = win.Target(self.hwnd, os.getpid(), created, name, "test", self.hwnd)
        self.ready.set()
        msg = W.MSG()
        while win.user.GetMessageW(C.byref(msg), None, 0, 0) > 0:
            win.user.TranslateMessage(C.byref(msg)); win.user.DispatchMessageW(C.byref(msg))

    def close(self):
        win.user.PostMessageW(self.hwnd, 0x10, 0, 0)
        self.thread.join(2)


class WindowsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.receiver = NativeReceiver()

    def tearDown(self):
        self.receiver.close()

    def test_background_receives_chords_without_focus_change(self):
        foreground = win.user.GetForegroundWindow()
        messages = []
        runner = Runner(lambda k, v: messages.append((k, v)))
        runner.keys(self.receiver.target, [{"key": "CTRL+Q", "hold": .02, "wait": .01}], 2)
        runner.thread.join(3); time.sleep(.03)
        self.assertFalse(runner.busy)
        self.assertEqual([(m, k) for m, k, _ in self.receiver.events], [(0x100, 17), (0x100, 81), (0x101, 81), (0x101, 17)] * 2)
        self.assertEqual(win.user.GetForegroundWindow(), foreground)
        self.assertEqual([v["error"] for k, v in messages if k == "finished"], [None])
        self.assertTrue(self.receiver.events[2][2] & (1 << 31))

    def test_minimized_receives_and_stays_minimized(self):
        win.user.ShowWindow(self.receiver.hwnd, 7)  # SW_SHOWMINNOACTIVE
        self.assertTrue(win.user.IsIconic(self.receiver.hwnd))
        foreground = win.user.GetForegroundWindow()
        backend = win.BackgroundInput(self.receiver.target)
        backend.key(65, True); backend.key(65, False)
        time.sleep(.06)
        self.assertEqual([(m, k) for m, k, _ in self.receiver.events], [(0x100, 65), (0x101, 65)])
        self.assertTrue(win.user.IsIconic(self.receiver.hwnd))
        self.assertEqual(win.user.GetForegroundWindow(), foreground)

    def test_stop_during_long_hold_releases_modifier(self):
        messages = []
        runner = Runner(lambda k, v: messages.append((k, v)))
        runner.keys(self.receiver.target, [{"key": "CTRL+Q", "hold": 3600, "wait": 0}], 0)
        time.sleep(.06); started = time.monotonic(); runner.stop(); runner.thread.join(2); time.sleep(.02)
        self.assertLess(time.monotonic()-started, .25)
        self.assertEqual([(m, k) for m, k, _ in self.receiver.events], [(0x100, 17), (0x100, 81), (0x101, 81), (0x101, 17)])

    def test_closed_target_is_rejected(self):
        self.receiver.close()
        self.assertFalse(self.receiver.target.valid())
        with self.assertRaises(OSError):
            win.BackgroundInput(self.receiver.target).key(65, True)

    def test_pid_creation_mismatch_rejected(self):
        from dataclasses import replace
        target = replace(self.receiver.target, created=self.receiver.target.created + 1)
        self.assertFalse(target.valid())


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.service = InputService(lambda k, v: self.messages.append((k, v)))
        self.assertTrue(self.service.ready.wait(3))
        self.assertTrue(self.service.hooks_ok)
        self.owner_patch = patch("assistant.hooks.win.is_own_window", return_value=False)
        self.owner_patch.start()

    def tearDown(self):
        self.owner_patch.stop()
        self.service.close(); self.service.thread.join(2)

    def key(self, vk, down=True, flags=0):
        data = win.KBD(vk, win.user.MapVirtualKeyW(vk, 0), flags, 0, 0)
        self.service._key(0, 0x100 if down else 0x101, C.addressof(data))

    def test_record_and_synthesize_final_release(self):
        self.service.begin()
        self.key(65)
        data = self.service.finish()
        self.assertEqual([e["down"] for e in data["events"]], [True, False])
        validate_recording(data)

    def test_injected_events_ignored(self):
        self.service.begin()
        self.key(65, True, 0x10); self.key(65, False, 0x10)
        self.assertEqual(self.service.finish()["events"], [])

    def test_control_chord_removed(self):
        self.service.specs = {"stop": (3, 121)}
        self.service.begin()
        self.key(65); self.key(65, False)
        self.key(162); self.key(164); self.key(121)
        self.key(121, False); self.key(164, False); self.key(162, False)
        data = self.service.finish()
        self.assertEqual([e["vk"] for e in data["events"]], [65, 65])
        validate_recording(data)

    def test_unmatched_release_ignored(self):
        self.service.begin(); self.key(65, False)
        self.assertEqual(self.service.finish()["events"], [])

    def test_drag_final_release_uses_last_recorded_position(self):
        self.service.begin()
        down = win.MOUSEHOOK(W.POINT(50, 60), 0, 0, 0, 0)
        move = win.MOUSEHOOK(W.POINT(70, 80), 0, 0, 0, 0)
        self.service._mouse(0, 0x201, C.addressof(down))
        self.service._mouse(0, 0x200, C.addressof(move))
        data = self.service.finish()
        self.assertEqual(data["events"][-1]["type"], "button")
        self.assertFalse(data["events"][-1]["down"])
        self.assertEqual((data["events"][-1]["x"], data["events"][-1]["y"]), (70, 80))
        validate_recording(data)

    def test_own_ui_click_not_recorded(self):
        self.service.begin()
        click = win.MOUSEHOOK(W.POINT(50, 60), 0, 0, 0, 0)
        with patch("assistant.hooks.win.is_own_window", return_value=True):
            self.service._mouse(0, 0x201, C.addressof(click))
            self.service._mouse(0, 0x202, C.addressof(click))
        self.assertEqual(self.service.finish()["events"], [])

    def test_hotkey_registration_conflict_reported(self):
        # Reserve an unusual chord in this thread, then ask the service to register it.
        if not win.user.RegisterHotKey(None, 197, 3 | 0x4000, 134):
            self.skipTest("Test chord already occupied")
        try:
            self.service.configure({"stop": "CTRL+ALT+F23"})
            time.sleep(.08)
            self.assertIn(("hotkeys", ["stop"]), self.messages)
        finally:
            win.user.UnregisterHotKey(None, 197)


class DesktopAbiTests(unittest.TestCase):
    def test_x64_sendinput_structure_and_release_flags(self):
        self.assertEqual(C.sizeof(win.INPUT), 40)
        captured = []

        def send(count, pointer, size):
            item = C.cast(pointer, C.POINTER(win.INPUT)).contents
            captured.append((item.type, item.ki.wScan, item.ki.dwFlags, item.ki.dwExtraInfo))
            return 1

        with patch.object(win.user, "SendInput", side_effect=send):
            backend = win.DesktopInput()
            backend.key(39, True, 77, True)
            backend.release()
        self.assertEqual(captured, [(1, 77, 9, win.MARKER), (1, 77, 11, win.MARKER)])

    def test_sendinput_failure_is_reported(self):
        with patch.object(win.user, "SendInput", return_value=0):
            with self.assertRaises(OSError):
                win.DesktopInput().button("left", True)


if __name__ == "__main__":
    unittest.main()
