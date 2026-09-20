from __future__ import annotations

import threading
import time
from .model import parse_chord
from .win32 import BackgroundInput, DesktopInput, convert_point, user, desktop, client_size


class Cancelled(Exception):
    pass


class Runner:
    """One task at a time; all waits are interruptible, including long holds."""
    def __init__(self, emit):
        self.emit = emit
        self.cancel = threading.Event()
        self.thread = None
        self.kind = None

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def stop(self):
        self.cancel.set()

    def wait(self, seconds, target=None, foreground=False):
        deadline = time.monotonic() + seconds
        while True:
            if self.cancel.is_set():
                raise Cancelled()
            if target is not None and not target.valid():
                raise OSError("目标进程或窗口已退出，请重新绑定")
            if foreground and (user.IsIconic(target.hwnd) or user.GetForegroundWindow() != target.hwnd):
                raise OSError("回放目标失焦或最小化，已停止。录制回放需要目标处于前台")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.cancel.wait(min(remaining, .05))

    def start(self, kind, action):
        if self.busy:
            raise ValueError("已有任务运行，请先停止")
        self.cancel.clear()
        self.kind = kind

        def work():
            error = None
            try:
                action()
            except Cancelled:
                pass
            except Exception as exc:
                error = str(exc)
            finally:
                self.emit("finished", {"kind": kind, "error": error})

        self.thread = threading.Thread(target=work, name=f"task-{kind}", daemon=True)
        self.thread.start()

    def countdown(self, seconds, target=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.emit("progress", f"准备开始 · {max(1, int(deadline-time.monotonic()+.99))} 秒")
            self.wait(min(1, max(0, deadline-time.monotonic())), target)

    def click(self, button, double, interval, loops, point=None, delay=3):
        def action():
            backend = DesktopInput()
            try:
                self.countdown(delay)
                count = 0
                last_update = 0
                while not loops or count < loops:
                    self.wait(0)
                    if point is not None:
                        backend.move(*point)
                    for n in range(2 if double else 1):
                        backend.button(button, True)
                        self.wait(.015)
                        backend.button(button, False)
                        if double and n == 0:
                            self.wait(.06)
                    count += 1
                    if time.monotonic() - last_update > .1 or count == loops:
                        self.emit("progress", f"已完成 {count} 次{'双击' if double else '单击'}")
                        last_update = time.monotonic()
                    if not loops or count < loops:
                        self.wait(interval)
            finally:
                backend.release()
        self.start("click", action)

    def keys(self, target, steps, loops):
        def action():
            backend = BackgroundInput(target)
            try:
                count = 0
                while not loops or count < loops:
                    for idx, step in enumerate(steps):
                        self.wait(0, target)
                        self.emit("step", idx)
                        self.emit("progress", f"后台发送 · 第 {count+1} 轮 / 第 {idx+1} 步 · {step['key']}")
                        backend.chord(parse_chord(step["key"]))
                        self.wait(step["hold"], target)
                        backend.release()
                        self.wait(step["wait"], target)
                    count += 1
            finally:
                backend.release()
        self.start("keys", action)

    def replay(self, recording, loops, speed, gap, delay, target=None):
        def action():
            backend = DesktopInput()
            mode = recording["coordinate_mode"]
            try:
                self.countdown(delay, target)
                count = 0
                while not loops or count < loops:
                    started = time.monotonic()
                    last_update = 0
                    for idx, event in enumerate(recording["events"]):
                        self.wait(max(0, started + event["t"]/speed - time.monotonic()), target, mode == "window")
                        if mode == "window":
                            if user.IsIconic(target.hwnd) or user.GetForegroundWindow() != target.hwnd:
                                raise OSError("回放目标失焦或最小化，已停止。录制回放需要目标处于前台")
                            expected = recording.get("environment", {}).get("client_size")
                            if expected and client_size(target.hwnd) != expected:
                                raise OSError("目标窗口客户区尺寸已改变，请恢复录制时尺寸")
                        elif desktop() != recording.get("environment", {}).get("desktop", desktop()):
                            raise OSError("显示器布局已改变，请恢复录制时布局")
                        kind = event["type"]
                        if kind == "key":
                            backend.key(event["vk"], event["down"], event["scan"], event["extended"])
                        else:
                            x, y = event["x"], event["y"]
                            if mode == "window":
                                x, y = convert_point(target.hwnd, x, y, True)
                            backend.move(x, y)
                            if kind == "button":
                                backend.button(event["button"], event["down"])
                            elif kind == "wheel":
                                backend.wheel(event["delta"], event["horizontal"])
                        if time.monotonic() - last_update > .1:
                            self.emit("progress", f"回放第 {count+1} 轮 · 事件 {idx+1}/{len(recording['events'])}")
                            last_update = time.monotonic()
                    self.wait(max(0, started + recording["duration"]/speed - time.monotonic()), target, mode == "window")
                    backend.release()
                    count += 1
                    if not loops or count < loops:
                        self.wait(gap, target, mode == "window")
            finally:
                backend.release()
        self.start("replay", action)
