"""Typed Win32 bindings. No process injection or foreground switching."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import os

user = C.WinDLL("user32", use_last_error=True)
kernel = C.WinDLL("kernel32", use_last_error=True)
ULONG_PTR = C.c_size_t
LRESULT = C.c_ssize_t
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, W.WPARAM, W.LPARAM)
WNDENUMPROC = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
MARKER = 0x47414D45


class KBD(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEHOOK(C.Structure):
    _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", W.DWORD), ("data", INPUTUNION)]


class GUITHREADINFO(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND),
                ("hwndFocus", W.HWND), ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND),
                ("hwndMoveSize", W.HWND), ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]


def bind(dll, name, args, restype):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, restype
    return fn


bind(user, "EnumWindows", [WNDENUMPROC, W.LPARAM], W.BOOL)
bind(user, "EnumChildWindows", [W.HWND, WNDENUMPROC, W.LPARAM], W.BOOL)
bind(user, "IsWindow", [W.HWND], W.BOOL)
bind(user, "IsWindowVisible", [W.HWND], W.BOOL)
bind(user, "IsIconic", [W.HWND], W.BOOL)
bind(user, "IsChild", [W.HWND, W.HWND], W.BOOL)
bind(user, "GetAncestor", [W.HWND, W.UINT], W.HWND)
bind(user, "GetForegroundWindow", [], W.HWND)
bind(user, "WindowFromPoint", [W.POINT], W.HWND)
bind(user, "GetWindowThreadProcessId", [W.HWND, C.POINTER(W.DWORD)], W.DWORD)
bind(user, "GetWindowTextLengthW", [W.HWND], C.c_int)
bind(user, "GetWindowTextW", [W.HWND, W.LPWSTR, C.c_int], C.c_int)
bind(user, "GetClassNameW", [W.HWND, W.LPWSTR, C.c_int], C.c_int)
bind(user, "GetGUIThreadInfo", [W.DWORD, C.POINTER(GUITHREADINFO)], W.BOOL)
bind(user, "PostMessageW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL)
bind(user, "SendMessageTimeoutW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM,
     W.UINT, W.UINT, C.POINTER(ULONG_PTR)], LRESULT)
bind(user, "PostThreadMessageW", [W.DWORD, W.UINT, W.WPARAM, W.LPARAM], W.BOOL)
bind(user, "GetMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], C.c_int)
bind(user, "PeekMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT], W.BOOL)
bind(user, "TranslateMessage", [C.POINTER(W.MSG)], W.BOOL)
bind(user, "DispatchMessageW", [C.POINTER(W.MSG)], LRESULT)
bind(user, "RegisterHotKey", [W.HWND, C.c_int, W.UINT, W.UINT], W.BOOL)
bind(user, "UnregisterHotKey", [W.HWND, C.c_int], W.BOOL)
bind(user, "SetWindowsHookExW", [C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD], W.HANDLE)
bind(user, "UnhookWindowsHookEx", [W.HANDLE], W.BOOL)
bind(user, "CallNextHookEx", [W.HANDLE, C.c_int, W.WPARAM, W.LPARAM], LRESULT)
bind(user, "SendInput", [W.UINT, C.POINTER(INPUT), C.c_int], W.UINT)
bind(user, "MapVirtualKeyW", [W.UINT, W.UINT], W.UINT)
bind(user, "GetCursorPos", [C.POINTER(W.POINT)], W.BOOL)
bind(user, "ScreenToClient", [W.HWND, C.POINTER(W.POINT)], W.BOOL)
bind(user, "ClientToScreen", [W.HWND, C.POINTER(W.POINT)], W.BOOL)
bind(user, "GetClientRect", [W.HWND, C.POINTER(W.RECT)], W.BOOL)
bind(user, "GetSystemMetrics", [C.c_int], C.c_int)
bind(user, "GetAsyncKeyState", [C.c_int], C.c_short)
bind(kernel, "GetCurrentThreadId", [], W.DWORD)
bind(kernel, "GetModuleHandleW", [W.LPCWSTR], W.HMODULE)
bind(kernel, "OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)
bind(kernel, "CloseHandle", [W.HANDLE], W.BOOL)
bind(kernel, "QueryFullProcessImageNameW", [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL)
bind(kernel, "GetProcessTimes", [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL)


def dpi_awareness():
    try:
        bind(user, "SetProcessDpiAwarenessContext", [C.c_void_p], W.BOOL)(C.c_void_p(-4))
    except AttributeError:
        user.SetProcessDPIAware()


def set_app_id(app_id):
    shell = C.WinDLL("shell32", use_last_error=True)
    bind(shell, "SetCurrentProcessExplicitAppUserModelID", [W.LPCWSTR], W.LONG)(app_id)


def text(hwnd):
    buf = C.create_unicode_buffer(min(user.GetWindowTextLengthW(hwnd) + 1, 4096))
    user.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def class_name(hwnd):
    buf = C.create_unicode_buffer(256)
    user.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def process_info(pid):
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return "无法读取进程", None
    try:
        size = W.DWORD(32768)
        buf = C.create_unicode_buffer(size.value)
        kernel.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size))
        times = [W.FILETIME() for _ in range(4)]
        ok = kernel.GetProcessTimes(handle, *(C.byref(t) for t in times))
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime if ok else None
        return os.path.basename(buf.value) or str(pid), created
    finally:
        kernel.CloseHandle(handle)


@dataclass(frozen=True)
class Target:
    hwnd: int
    pid: int
    created: int
    name: str
    title: str
    receiver: int

    @classmethod
    def capture(cls, hwnd):
        hwnd = user.GetAncestor(hwnd, 2) or hwnd
        pid = W.DWORD()
        tid = user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if not tid or pid.value == os.getpid():
            raise ValueError("请选择其他程序的窗口")
        name, created = process_info(pid.value)
        if created is None:
            raise ValueError("无法读取目标进程身份，可能是权限不足")
        info = GUITHREADINFO(cbSize=C.sizeof(GUITHREADINFO))
        user.GetGUIThreadInfo(tid, C.byref(info))
        focus = info.hwndFocus
        receiver = focus if focus and (focus == hwnd or user.IsChild(hwnd, focus)) else hwnd
        return cls(int(hwnd), pid.value, created, name, text(hwnd), int(receiver))

    def valid(self):
        if not user.IsWindow(self.hwnd) or not user.IsWindow(self.receiver):
            return False
        for hwnd in (self.hwnd, self.receiver):
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            if pid.value != self.pid:
                return False
        return process_info(self.pid)[1] == self.created

    def label(self):
        return f"{self.name}  ·  PID {self.pid}  ·  {self.title}"


def windows():
    result = []

    @WNDENUMPROC
    def callback(hwnd, _):
        if user.IsWindowVisible(hwnd) and text(hwnd):
            try:
                result.append(Target.capture(hwnd))
            except ValueError:
                pass
        return True

    user.EnumWindows(callback, 0)
    return sorted(result, key=lambda w: (w.name.lower(), w.title))


def children(hwnd):
    result = [(hwnd, "主窗口")]

    @WNDENUMPROC
    def callback(child, _):
        if len(result) < 100:
            result.append((int(child), f"{class_name(child)}  {text(child)[:45]}"))
        return True

    user.EnumChildWindows(hwnd, callback, 0)
    return result


def cursor():
    pt = W.POINT()
    if not user.GetCursorPos(C.byref(pt)):
        raise C.WinError(C.get_last_error())
    return pt.x, pt.y


def is_own_window(hwnd):
    pid = W.DWORD()
    win_thread = user.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return bool(win_thread and pid.value == os.getpid())


def convert_point(hwnd, x, y, to_screen):
    pt = W.POINT(x, y)
    fn = user.ClientToScreen if to_screen else user.ScreenToClient
    if not fn(hwnd, C.byref(pt)):
        raise OSError("无法转换目标窗口坐标")
    return pt.x, pt.y


def client_size(hwnd):
    rect = W.RECT()
    if not user.GetClientRect(hwnd, C.byref(rect)):
        raise OSError("无法读取窗口尺寸")
    return [rect.right, rect.bottom]


def desktop():
    return [user.GetSystemMetrics(i) for i in (76, 77, 78, 79)]


class DesktopInput:
    def __init__(self):
        self.pressed_keys = {}
        self.pressed_buttons = set()

    def send(self, item):
        if user.SendInput(1, C.byref(item), C.sizeof(INPUT)) != 1:
            raise OSError("系统未接受模拟输入，请检查目标权限和桌面状态")

    def key(self, vk, down, scan=0, extended=False):
        flags = (0 if down else 2) | (1 if extended else 0)
        item = INPUT(type=1)
        item.ki = KEYBDINPUT(0 if scan else vk, scan, flags | (8 if scan else 0), 0, MARKER)
        self.send(item)
        if down:
            self.pressed_keys[vk] = (scan, extended)
        else:
            self.pressed_keys.pop(vk, None)

    def move(self, x, y):
        left, top, width, height = desktop()
        if not left <= x < left + width or not top <= y < top + height:
            raise ValueError("鼠标坐标超出当前屏幕范围")
        item = INPUT(type=0)
        item.mi = MOUSEINPUT(round((x-left)*65535/max(width-1, 1)),
                             round((y-top)*65535/max(height-1, 1)), 0, 0xC001, 0, MARKER)
        self.send(item)

    def button(self, name, down):
        flags = {"left": (2, 4), "right": (8, 16), "middle": (32, 64),
                 "x1": (128, 256), "x2": (128, 256)}[name][not down]
        item = INPUT(type=0)
        item.mi = MOUSEINPUT(0, 0, {"x1": 1, "x2": 2}.get(name, 0), flags, 0, MARKER)
        self.send(item)
        if down:
            self.pressed_buttons.add(name)
        else:
            self.pressed_buttons.discard(name)

    def wheel(self, delta, horizontal=False):
        item = INPUT(type=0)
        item.mi = MOUSEINPUT(0, 0, delta & 0xFFFFFFFF, 0x1000 if horizontal else 0x800, 0, MARKER)
        self.send(item)

    def release(self):
        errors = []
        for vk, (scan, extended) in list(self.pressed_keys.items())[::-1]:
            try:
                self.key(vk, False, scan, extended)
            except OSError as exc:
                errors.append(str(exc))
        for name in list(self.pressed_buttons):
            try:
                self.button(name, False)
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            raise OSError("释放输入失败：" + errors[0])


class BackgroundInput:
    def __init__(self, target):
        self.target, self.pressed = target, []

    def text_receiver(self):
        def editable(hwnd):
            name = class_name(hwnd).lower()
            return name == "edit" or name.startswith("richedit")
        receiver = self.target.receiver
        if editable(receiver):
            return receiver
        # Only auto-select a unique edit child of the selected receiver.
        matches = [hwnd for hwnd, _ in children(receiver)[1:] if editable(hwnd)]
        return matches[0] if len(matches) == 1 else None

    def command(self, hwnd, message, wp=0, lp=0):
        if not self.target.valid():
            raise OSError("绑定窗口已关闭或身份已改变，请重新绑定")
        result = ULONG_PTR()
        if not user.SendMessageTimeoutW(hwnd, message, wp, lp, 0x22, 1000, C.byref(result)):
            raise OSError("后台编辑命令失败：目标无响应或权限不足")

    def chord(self, keys):
        keys = tuple(keys)
        receiver = self.text_receiver()
        # Posted modifier messages do NOT update GetKeyState in the target.
        # Edit/RichEdit commands implement editing without physical Ctrl input.
        commands = {(17, 86): (0x302, 0, 0), (17, 67): (0x301, 0, 0),
                    (17, 88): (0x300, 0, 0), (17, 65): (0xB1, 0, -1),
                    (17, 90): (0x304, 0, 0), (16, 45): (0x302, 0, 0),
                    (17, 45): (0x301, 0, 0), (16, 46): (0x300, 0, 0)}
        if keys in commands:
            if not receiver:
                raise ValueError("此编辑组合键需要 Edit/RichEdit 文本控件；请在接收窗口中选择编辑区。未发送字母键。")
            self.command(receiver, *commands[keys])
            return
        if receiver and keys == (13,):
            self.command(receiver, 0x102, 13)  # WM_CHAR: deterministic newline
            return
        if receiver and len(keys) > 1:
            raise ValueError("该文本控件的后台组合键暂不支持；支持 Ctrl+A/C/X/V/Z、Ctrl+Insert、Shift+Insert/Delete。")
        for vk in keys:
            self.key(vk, True)

    def key(self, vk, down):
        if not self.target.valid():
            raise OSError("绑定窗口已关闭或身份已改变，请重新绑定")
        scan = user.MapVirtualKeyW(vk, 0)
        extended = vk in (33, 34, 35, 36, 37, 38, 39, 40, 45, 46, 91, 92, 111, 144)
        alt = 18 in self.pressed or vk == 18
        msg = (0x104 if down else 0x105) if alt else (0x100 if down else 0x101)
        lp = 1 | ((scan & 255) << 16) | (int(extended) << 24)
        if 18 in self.pressed:
            lp |= 1 << 29
        if not down:
            lp |= (1 << 30) | (1 << 31)
        if not user.PostMessageW(self.target.receiver, msg, vk, lp):
            raise OSError(f"后台消息发送失败（Windows 错误 {C.get_last_error()}），请检查权限")
        if down:
            self.pressed.append(vk)
        elif vk in self.pressed:
            self.pressed.remove(vk)

    def release(self):
        # Never send releases to a recycled window handle / PID.
        if not self.target.valid():
            self.pressed.clear()
            return
        for vk in self.pressed[::-1]:
            self.key(vk, False)
