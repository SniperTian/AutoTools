from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import queue
import threading
import time
from . import win32 as win
from .model import MAX_EVENTS, MAX_DURATION, hotkey_spec, chord_from_vk


def generic(vk):
    return {160: 16, 161: 16, 162: 17, 163: 17, 164: 18, 165: 18, 92: 91}.get(vk, vk)


class InputService:
    """Dedicated Windows message loop for system hotkeys and low-level hooks."""
    def __init__(self, emit):
        self.emit = emit
        self.thread_id = None
        self.commands = queue.Queue()
        self.ready = threading.Event()
        self.registered = {}
        self.specs = {}
        self.physical_down = {}
        self.suppressed = set()
        self.capture_token = None
        self.capture_held = set()
        self.capture_swallowed = set()
        self.capture_done = False
        self.lock = threading.RLock()
        self.recording = False
        self.events = []
        self.record_keys = {}
        self.record_buttons = set()
        self.start_time = 0
        self.mode = "screen"
        self.target = None
        self.last_move = 0
        self.last_point = (0, 0)
        self.hooks_ok = False
        self.thread = threading.Thread(target=self._run, name="input-listener", daemon=True)
        self.thread.start()

    def configure(self, hotkeys):
        specs = {name: hotkey_spec(key) for name, key in hotkeys.items()}
        if len(set(specs.values())) != len(specs):
            raise ValueError("功能快捷键不能重复")
        self.commands.put(specs)
        if self.ready.wait(2) and self.thread_id:
            win.user.PostThreadMessageW(self.thread_id, 0x8001, 0, 0)
        else:
            raise OSError("系统输入监听服务未启动")

    def _configure(self, specs):
        for ident in self.registered:
            win.user.UnregisterHotKey(None, ident)
        self.registered.clear()
        self.specs.clear()
        failures = []
        for ident, (name, (mods, vk)) in enumerate(specs.items(), 1):
            if win.user.RegisterHotKey(None, ident, mods | 0x4000, vk):
                self.registered[ident] = name
                self.specs[name] = (mods, vk)
            else:
                failures.append(name)
        self.emit("hotkeys", failures)

    def start_capture(self, token):
        with self.lock:
            if not self.hooks_ok:
                raise OSError("系统键盘监听不可用，无法捕获按键")
            self.capture_token = token
            self.capture_done = False
            self.capture_held = {k for k in (16, 17, 18, 91)
                                 if win.user.GetAsyncKeyState(k) & 0x8000}

    def end_capture(self):
        with self.lock:
            self.capture_token = None
            self.capture_held.clear()

    def _capture_key(self, vk, down):
        with self.lock:
            # Swallow the entire captured press, including repeat and release,
            # even when the GUI has already left capture mode.
            if vk in self.capture_swallowed:
                if not down:
                    self.capture_swallowed.discard(vk)
                    self.capture_held.discard(generic(vk))
                    self.physical_down.pop(vk, None)
                return True
            if self.capture_token is None or not win.is_own_window(win.user.GetForegroundWindow()):
                return False
            if not down:
                self.capture_held.discard(generic(vk))
                return False
            self.capture_swallowed.add(vk)
            if self.capture_done:
                return True
            self.capture_held.add(generic(vk))
            try:
                text, complete = chord_from_vk(generic(vk), self.capture_held)
                self.capture_done = complete
                self.emit("captured_key", (self.capture_token, text, complete))
            except ValueError as exc:
                self.emit("capture_error", (self.capture_token, str(exc)))
            return True

    def begin(self, mode="screen", target=None):
        with self.lock:
            if not self.hooks_ok:
                raise OSError("键鼠监听钩子不可用，不能录制")
            if self.recording:
                raise ValueError("正在录制")
            if mode == "window" and (target is None or not target.valid()):
                raise ValueError("窗口相对坐标需要先绑定目标窗口")
            self.events = []
            self.record_keys.clear()
            self.record_buttons.clear()
            self.mode, self.target = mode, target
            self.environment = {"desktop": win.desktop()}
            if target:
                self.environment["client_size"] = win.client_size(target.hwnd)
            self.start_time = time.monotonic()
            self.last_move = 0
            self.last_point = (0, 0)
            self.recording = True

    def finish(self):
        with self.lock:
            self.recording = False
            duration = min(time.monotonic() - self.start_time, MAX_DURATION)
            for vk, (scan, extended) in list(self.record_keys.items()):
                self.events.append({"type": "key", "t": duration, "vk": vk, "scan": scan,
                                    "extended": extended, "down": False})
            x, y = self.last_point
            for button in self.record_buttons:
                self.events.append({"type": "button", "t": duration, "x": x, "y": y,
                                    "button": button, "down": False})
            self.record_keys.clear()
            self.record_buttons.clear()
            return {"format": "game-assistant-recording", "version": 1,
                    "coordinate_mode": self.mode, "duration": duration,
                    "environment": self.environment, "events": list(self.events)}

    def stats(self):
        with self.lock:
            return len(self.events), max(0, time.monotonic() - self.start_time)

    def _append(self, event):
        if len(self.events) >= MAX_EVENTS - 300 or event["t"] > MAX_DURATION - 1:
            self.recording = False
            self.emit("record_limit", "已达到录制上限，录制已停止")
            return
        self.events.append(event)

    def _key(self, code, wp, lp):
        try:
            if code >= 0:
                info = C.cast(lp, C.POINTER(win.KBD)).contents
                if info.dwExtraInfo != win.MARKER and self._capture_key(int(info.vkCode), wp in (0x100, 0x104)):
                    return 1
                if not info.flags & 0x10 and info.dwExtraInfo != win.MARKER:
                    down = wp in (0x100, 0x104)
                    vk = int(info.vkCode)
                    now = time.monotonic()
                    if down:
                        self.physical_down.setdefault(vk, now)
                    active = {generic(k) for k in self.physical_down}
                    mods = sum(flag for key, flag in ((18, 1), (17, 2), (16, 4), (91, 8)) if key in active)
                    is_control = down and any((mods, generic(vk)) == spec for spec in self.specs.values())
                    with self.lock:
                        if is_control:
                            control = {k for k in self.physical_down if generic(k) in (16, 17, 18, 91) or k == vk}
                            self.suppressed.update(control)
                            if self.recording:
                                # Remove only the currently held control chord, not earlier uses of it.
                                self.events = [e for e in self.events if not (
                                    e["type"] == "key" and e["vk"] in control and
                                    e["t"] >= self.physical_down[e["vk"]] - self.start_time - .000001)]
                                for key in control:
                                    self.record_keys.pop(key, None)
                        elif self.recording and vk not in self.suppressed and (
                                not win.is_own_window(win.user.GetForegroundWindow()) or
                                (not down and vk in self.record_keys)):
                            if down or vk in self.record_keys:
                                event = {"type": "key", "t": now-self.start_time, "vk": vk,
                                         "scan": int(info.scanCode), "extended": bool(info.flags & 1), "down": down}
                                self._append(event)
                                if down:
                                    self.record_keys[vk] = (int(info.scanCode), bool(info.flags & 1))
                                else:
                                    self.record_keys.pop(vk, None)
                    if not down:
                        self.physical_down.pop(vk, None)
                        self.suppressed.discard(vk)
        except Exception as exc:
            self.recording = False
            self.emit("hook_error", str(exc))
        return win.user.CallNextHookEx(None, code, wp, lp)

    def _mouse(self, code, wp, lp):
        try:
            if code >= 0 and self.recording:
                info = C.cast(lp, C.POINTER(win.MOUSEHOOK)).contents
                if not info.flags & 1 and info.dwExtraInfo != win.MARKER:
                    with self.lock:
                        if not self.recording:
                            return win.user.CallNextHookEx(None, code, wp, lp)
                        now = time.monotonic()
                        x, y = info.pt.x, info.pt.y
                        # UI control clicks must not become macro actions. Keep releases
                        # of a drag begun outside our UI to preserve a balanced recording.
                        if win.is_own_window(win.user.WindowFromPoint(info.pt)):
                            if wp not in (0x202, 0x205, 0x208, 0x20C) or not self.record_buttons:
                                return win.user.CallNextHookEx(None, code, wp, lp)
                        if self.mode == "window":
                            if not self.target.valid() or win.user.IsIconic(self.target.hwnd):
                                self.recording = False
                                self.emit("record_limit", "录制目标关闭或最小化，已停止录制")
                                return win.user.CallNextHookEx(None, code, wp, lp)
                            x, y = win.convert_point(self.target.hwnd, x, y, False)
                        event = {"t": now-self.start_time, "x": x, "y": y}
                        self.last_point = (x, y)
                        buttons = {0x201: ("left", True), 0x202: ("left", False),
                                   0x204: ("right", True), 0x205: ("right", False),
                                   0x207: ("middle", True), 0x208: ("middle", False)}
                        if wp in (0x20B, 0x20C):
                            buttons[wp] = ("x1" if info.mouseData >> 16 == 1 else "x2", wp == 0x20B)
                        if wp == 0x200:
                            if now-self.last_move < .008:
                                return win.user.CallNextHookEx(None, code, wp, lp)
                            self.last_move = now
                            event["type"] = "move"
                        elif wp in buttons:
                            button, down = buttons[wp]
                            if not down and button not in self.record_buttons:
                                return win.user.CallNextHookEx(None, code, wp, lp)
                            event.update(type="button", button=button, down=down)
                            if down:
                                self.record_buttons.add(button)
                            else:
                                self.record_buttons.discard(button)
                        elif wp in (0x20A, 0x20E):
                            event.update(type="wheel", delta=C.c_short(info.mouseData >> 16).value, horizontal=wp == 0x20E)
                        else:
                            return win.user.CallNextHookEx(None, code, wp, lp)
                        self._append(event)
        except Exception as exc:
            self.recording = False
            self.emit("hook_error", str(exc))
        return win.user.CallNextHookEx(None, code, wp, lp)

    def _run(self):
        self.thread_id = win.kernel.GetCurrentThreadId()
        msg = W.MSG()
        win.user.PeekMessageW(C.byref(msg), None, 0, 0, 0)
        self.key_callback = win.HOOKPROC(self._key)
        self.mouse_callback = win.HOOKPROC(self._mouse)
        module = win.kernel.GetModuleHandleW(None)
        keyboard = win.user.SetWindowsHookExW(13, self.key_callback, module, 0)
        mouse = win.user.SetWindowsHookExW(14, self.mouse_callback, module, 0)
        self.hooks_ok = bool(keyboard and mouse)
        self.ready.set()
        if not self.hooks_ok:
            self.emit("hook_error", "无法安装键鼠录制钩子")
        try:
            while win.user.GetMessageW(C.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x8001:
                    while not self.commands.empty():
                        self._configure(self.commands.get_nowait())
                elif msg.message == 0x312:
                    name = self.registered.get(msg.wParam)
                    if name:
                        # Capture foreground identity before the GUI receives the event.
                        hwnd = win.user.GetForegroundWindow() if name == "bind" else None
                        self.emit("hotkey", (name, hwnd))
                else:
                    win.user.TranslateMessage(C.byref(msg))
                    win.user.DispatchMessageW(C.byref(msg))
        finally:
            for ident in self.registered:
                win.user.UnregisterHotKey(None, ident)
            for hook in (keyboard, mouse):
                if hook:
                    win.user.UnhookWindowsHookEx(hook)

    def close(self):
        if self.thread_id:
            win.user.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
