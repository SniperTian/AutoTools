"""Windows notification-area icon with its own native message loop."""
import ctypes as C
from ctypes import wintypes as W
import queue
import threading

from .win32 import bind, kernel, LRESULT

u = C.WinDLL("user32", use_last_error=True)
shell = C.WinDLL("shell32", use_last_error=True)
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASS(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HANDLE),
                ("hCursor", W.HANDLE), ("hbrBackground", W.HANDLE),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]


class GUID(C.Structure):
    _fields_ = [("data1", W.DWORD), ("data2", W.WORD), ("data3", W.WORD), ("data4", C.c_ubyte * 8)]


class NOTIFYICONDATA(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT),
                ("uFlags", W.UINT), ("uCallbackMessage", W.UINT), ("hIcon", W.HANDLE),
                ("szTip", W.WCHAR * 128), ("dwState", W.DWORD), ("dwStateMask", W.DWORD),
                ("szInfo", W.WCHAR * 256), ("uVersion", W.UINT), ("szInfoTitle", W.WCHAR * 64),
                ("dwInfoFlags", W.DWORD), ("guidItem", GUID), ("hBalloonIcon", W.HANDLE)]


bind(shell, "Shell_NotifyIconW", [W.DWORD, C.POINTER(NOTIFYICONDATA)], W.BOOL)
bind(u, "RegisterClassW", [C.POINTER(WNDCLASS)], W.ATOM)
bind(u, "UnregisterClassW", [W.LPCWSTR, W.HINSTANCE], W.BOOL)
bind(u, "CreateWindowExW", [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int,
                           C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p], W.HWND)
bind(u, "DefWindowProcW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM], LRESULT)
bind(u, "DestroyWindow", [W.HWND], W.BOOL)
bind(u, "LoadImageW", [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT], W.HANDLE)
bind(u, "DestroyIcon", [W.HANDLE], W.BOOL)
bind(u, "RegisterWindowMessageW", [W.LPCWSTR], W.UINT)
bind(u, "PostMessageW", [W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL)
bind(u, "GetMessageW", [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], C.c_int)
bind(u, "TranslateMessage", [C.POINTER(W.MSG)], W.BOOL)
bind(u, "DispatchMessageW", [C.POINTER(W.MSG)], LRESULT)
bind(u, "PostQuitMessage", [C.c_int], None)
bind(u, "CreatePopupMenu", [], W.HMENU)
bind(u, "AppendMenuW", [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR], W.BOOL)
bind(u, "DestroyMenu", [W.HMENU], W.BOOL)
bind(u, "SetForegroundWindow", [W.HWND], W.BOOL)
bind(u, "GetCursorPos", [C.POINTER(W.POINT)], W.BOOL)
bind(u, "TrackPopupMenu", [W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, C.c_void_p], W.UINT)


class TrayIcon:
    CALLBACK = 0x8002
    COMMAND = 0x8003

    def __init__(self, icon_path, emit):
        self.icon_path = str(icon_path)
        self.emit = emit
        self.visible = False
        self.hwnd = None
        self.hicon = None
        self.error = None
        self.ready = threading.Event()
        self.commands = queue.Queue()
        self.thread = None

    def _data(self):
        data = NOTIFYICONDATA(cbSize=C.sizeof(NOTIFYICONDATA), hWnd=self.hwnd,
                              uID=1, uFlags=1 | 2 | 4 | 0x80,
                              uCallbackMessage=self.CALLBACK, hIcon=self.hicon)
        data.szTip = "AutoTools · 双击显示窗口 / 右键打开菜单"
        return data

    def _show(self):
        if self.visible:
            return
        data = self._data()
        if not shell.Shell_NotifyIconW(0, C.byref(data)):
            raise OSError(f"无法创建托盘图标（Windows 错误 {C.get_last_error()}），已保留任务栏窗口")
        self.visible = True
        data.uVersion = 4
        shell.Shell_NotifyIconW(4, C.byref(data))

    def _hide(self):
        if self.visible:
            data = self._data()
            shell.Shell_NotifyIconW(2, C.byref(data))
            self.visible = False

    def _menu(self):
        menu = u.CreatePopupMenu()
        if not menu:
            return
        try:
            for command, label in ((1, "显示 AutoTools"), (2, "全部停止"), (0, None), (3, "退出")):
                u.AppendMenuW(menu, 0x800 if label is None else 0, command, label)
            point = W.POINT()
            if not u.GetCursorPos(C.byref(point)):
                return
            u.SetForegroundWindow(self.hwnd)
            command = u.TrackPopupMenu(menu, 0x100 | 2, point.x, point.y, 0, self.hwnd, None)
            if command in (1, 2, 3):
                self.emit("tray", {1: "restore", 2: "stop", 3: "exit"}[command])
            u.PostMessageW(self.hwnd, 0, 0, 0)
        finally:
            u.DestroyMenu(menu)

    def _proc(self, hwnd, message, wp, lp):
        try:
            if message == self.CALLBACK:
                event = lp & 0xFFFF
                if event in (0x203, 0x400, 0x401):
                    self.emit("tray", "restore")
                elif event in (0x7B, 0x205):
                    self._menu()
                return 0
            if message == self.taskbar_created:
                if self.visible:
                    self.visible = False
                    self._show()
                return 0
            if message == self.COMMAND:
                while not self.commands.empty():
                    action, reply = self.commands.get_nowait()
                    try:
                        (self._show if action == "show" else self._hide)()
                        reply.put(None)
                    except Exception as exc:
                        reply.put(exc)
                return 0
            if message == 0x10:
                self._hide()
                u.DestroyWindow(hwnd)
                return 0
            if message == 2:
                u.PostQuitMessage(0)
                return 0
        except Exception as exc:
            self.emit("tray_error", str(exc))
            return 0
        return u.DefWindowProcW(hwnd, message, wp, lp)

    def _run(self):
        name = f"AutoToolsTray_{id(self)}"
        module = kernel.GetModuleHandleW(None)
        registered = False
        try:
            self.taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
            self.callback = WNDPROC(self._proc)
            cls = WNDCLASS(lpfnWndProc=self.callback, hInstance=module, lpszClassName=name)
            if not u.RegisterClassW(C.byref(cls)):
                raise C.WinError(C.get_last_error())
            registered = True
            self.hwnd = u.CreateWindowExW(0, name, "AutoTools Tray", 0, 0, 0, 0, 0, None, None, module, None)
            if not self.hwnd:
                raise C.WinError(C.get_last_error())
            self.hicon = u.LoadImageW(None, self.icon_path, 1, 32, 32, 0x10)
            if not self.hicon:
                raise OSError("无法读取 AutoTools 托盘图标")
            self.ready.set()
            message = W.MSG()
            while u.GetMessageW(C.byref(message), None, 0, 0) > 0:
                u.TranslateMessage(C.byref(message)); u.DispatchMessageW(C.byref(message))
        except Exception as exc:
            self.error = exc
        finally:
            self.ready.set()
            self._hide()
            if self.hwnd:
                u.DestroyWindow(self.hwnd)
                self.hwnd = None
            if self.hicon:
                u.DestroyIcon(self.hicon)
                self.hicon = None
            if registered:
                u.UnregisterClassW(name, module)

    def _request(self, action):
        if self.thread is None:
            if action == "hide":
                return
            self.thread = threading.Thread(target=self._run, name="autotools-tray", daemon=True)
            self.thread.start()
        if not self.ready.wait(2) or self.error is not None or not self.hwnd:
            raise OSError(str(self.error or "托盘服务未启动"))
        reply = queue.Queue(maxsize=1)
        self.commands.put((action, reply))
        if not u.PostMessageW(self.hwnd, self.COMMAND, 0, 0):
            raise OSError("无法访问托盘服务")
        try:
            error = reply.get(timeout=2)
        except queue.Empty:
            raise OSError("托盘服务响应超时，窗口保持可见") from None
        if error:
            raise error

    def show(self):
        self._request("show")

    def hide(self):
        self._request("hide")

    def close(self):
        if self.hwnd:
            u.PostMessageW(self.hwnd, 0x10, 0, 0)
        if self.thread:
            self.thread.join(2)
