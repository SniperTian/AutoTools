"""Launch with the game_assistant Conda environment (Python 3.12, Windows x64)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import queue
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from assistant import win32 as win
from assistant.tray import TrayIcon
from assistant.engine import Runner
from assistant.hooks import InputService, generic
from assistant.model import (DEFAULT_HOTKEYS, KEYS, hotkey_spec, normalize_chord, number,
                             read_json, validate_recording, validate_steps, write_json, enabled_actions)

BG = "#10141e"
SIDE = "#141a26"
CARD = "#1b2332"
FIELD = "#111925"
TEXT = "#e7edf8"
MUTED = "#97a6be"
ACCENT = "#779dff"
GREEN = "#71d6b0"
RED = "#ff8796"
NAMES = {"click": "鼠标连点", "keys": "键盘队列", "record": "操作录制",
         "replay": "录制回放", "bind": "绑定窗口", "stop": "全部停止"}
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"


class App:
    def __init__(self, root):
        self.root = root
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.root.title("AutoTools")
        if (ASSETS / "autotools.ico").exists():
            self.root.iconbitmap(default=str(ASSETS / "autotools.ico"))
        self.root.geometry(f"{round(1160*self.scale)}x{round(800*self.scale)}")
        self.root.minsize(round(1020*self.scale), round(740*self.scale))
        self.root.configure(bg=BG)
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#354d7e")
        self.events = queue.Queue()
        self.tray = TrayIcon(ASSETS / "autotools.ico", self.emit)
        self.tray_hidden = False
        self.restore_state = "normal"
        self.runner = Runner(self.emit)
        self.service = InputService(self.emit)
        self.target = None
        self.window_list = []
        self.receivers = []
        self.hotkeys = dict(DEFAULT_HOTKEYS)
        self.steps = [{"key": "1", "hold": .05, "wait": 1.0}, {"key": "CTRL+Q", "hold": .05, "wait": .5}]
        self.recording = None
        self.dirty_recording = False
        self.active = None
        self.current_page = 0
        self.capture = None
        self.capture_serial = 0
        self.pending_record = False
        self.started = 0
        self.hotkey_failures = []
        self.controls = []
        self.page_buttons = []
        self.log_lines = []
        self.closing = False
        self.config = {}
        self.load_config()
        self.minimize_to_tray = tk.BooleanVar(value=bool(self.config.get("minimize_to_tray", False)))
        self.style()
        self.build_shell()
        self.build_click()
        self.build_keys()
        self.build_record()
        self.build_settings()
        self.restore_fields()
        self.show_page(0)
        self.refresh_windows()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Unmap>", self.on_unmap, add="+")
        self.root.bind("<Configure>", self.on_configure, add="+")
        self.root.after(40, self.poll)

    def emit(self, kind, data):
        self.events.put((kind, data))

    def style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, padding=(0, 5))
        s.map("Card.TCheckbutton", background=[("active", CARD)], foreground=[("active", TEXT)])
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("TButton", background="#2a354b", foreground=TEXT, borderwidth=0,
                    padding=(14, 9), focusthickness=0)
        s.map("TButton", background=[("active", "#374865"), ("disabled", "#202a3b")],
              foreground=[("disabled", "#61718c")])
        s.configure("Primary.TButton", background=ACCENT, foreground="#10182a", font=("Microsoft YaHei UI", 10, "bold"))
        s.map("Primary.TButton", background=[("active", "#a0baff"), ("disabled", "#303e59")])
        s.configure("Danger.TButton", background="#3e2838", foreground=RED)
        s.map("Danger.TButton", background=[("active", "#5b3245")])
        s.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, bordercolor="#35425b", padding=8,
                    insertcolor=TEXT)
        s.map("TEntry", fieldbackground=[("disabled", "#222a39")], foreground=[("disabled", MUTED)])
        s.configure("TCombobox", fieldbackground=FIELD, background="#2b3851", foreground=TEXT,
                    arrowcolor=MUTED, padding=7, bordercolor="#35425b")
        s.map("TCombobox", fieldbackground=[("readonly", FIELD), ("disabled", "#222a39")],
              foreground=[("readonly", TEXT), ("disabled", MUTED)], selectbackground=[("readonly", FIELD)],
              selectforeground=[("readonly", TEXT)])
        s.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT, borderwidth=0,
                    rowheight=round(36*self.scale), font=("Microsoft YaHei UI", 10))
        s.configure("Treeview.Heading", background="#263249", foreground=MUTED, padding=8,
                    font=("Microsoft YaHei UI", 9), relief="flat")
        s.map("Treeview", background=[("selected", "#334f80")], foreground=[("selected", "#ffffff")])
        s.configure("Vertical.TScrollbar", background="#35435d", troughcolor=FIELD, borderwidth=0, arrowcolor=MUTED)

    def label(self, parent, text="", size=10, color=TEXT, bold=False, bg=None, **kw):
        if "wraplength" in kw:
            kw["wraplength"] = round(kw["wraplength"] * self.scale)
        return tk.Label(parent, text=text, bg=bg or parent.cget("bg"), fg=color,
                        font=("Microsoft YaHei UI", size, "bold" if bold else "normal"), **kw)

    def button(self, parent, text, command, primary=False, editable=False, danger=False):
        style = "Primary.TButton" if primary else "Danger.TButton" if danger else "TButton"
        button = ttk.Button(parent, text=text, command=lambda: self.safe(command), style=style)
        if editable:
            self.controls.append((button, "normal"))
        return button

    def entry(self, parent, variable, width=12):
        widget = ttk.Entry(parent, textvariable=variable, width=width)
        self.controls.append((widget, "normal"))
        return widget

    def combo(self, parent, variable, values, width=18):
        widget = ttk.Combobox(parent, textvariable=variable, values=values, width=width, state="readonly")
        self.controls.append((widget, "readonly"))
        return widget

    def safe(self, action):
        try:
            action()
        except Exception as exc:
            self.log(str(exc))
            messagebox.showerror("无法完成操作", str(exc), parent=self.root)

    def build_shell(self):
        side = tk.Frame(self.root, bg=SIDE, width=round(202*self.scale))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=SIDE)
        brand.pack(anchor="w", padx=18, pady=(30, 8))
        if (ASSETS / "autotools.png").exists():
            self.brand_icon = tk.PhotoImage(file=str(ASSETS / "autotools.png")).subsample(max(1, round(256/(30*self.scale))))
            tk.Label(brand, image=self.brand_icon, bg=SIDE).pack(side="left", padx=(0, 8))
        self.label(brand, "AutoTools", 18, bold=True).pack(side="left")
        self.label(side, "WINDOWS AUTOMATION", 8, ACCENT).pack(anchor="w", padx=22)
        self.label(side, "让重复操作更简单", 10, MUTED).pack(anchor="w", padx=27, pady=(8, 34))
        for i, title in enumerate(("鼠标连点", "键盘队列", "操作录制", "偏好设置")):
            b = tk.Button(side, text=f"{i+1:02}    {title}", anchor="w", padx=22, pady=15,
                          relief="flat", bd=0, bg=SIDE, fg=MUTED, activebackground="#25324a",
                          activeforeground=TEXT, cursor="hand2", command=lambda n=i: self.show_page(n))
            b.pack(fill="x", padx=12, pady=4)
            self.page_buttons.append(b)
        self.label(side, "WINDOWS · PYTHON 3.12\n本地运行 / 无需联网", 9, MUTED, justify="left").pack(side="bottom", anchor="w", padx=26, pady=28)
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        footer = tk.Frame(main, bg=SIDE, height=round(78*self.scale))
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        self.button(footer, "全部停止", self.stop_all, danger=True).pack(side="right", padx=22, pady=17)
        self.footer_status = self.label(footer, "●  就绪", 11, GREEN)
        self.footer_status.pack(side="left", padx=26)
        self.footer_time = self.label(footer, "", 9, MUTED)
        self.footer_time.pack(side="left", padx=8)
        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill="both", expand=True, padx=28, pady=(25, 18))
        self.pages = [tk.Frame(self.content, bg=BG) for _ in range(4)]

    def header(self, page, eyebrow, title, subtitle):
        self.label(page, eyebrow, 9, ACCENT, True).pack(anchor="w")
        self.label(page, title, 24, bold=True).pack(anchor="w", pady=(5, 6))
        self.label(page, subtitle, 10, MUTED).pack(anchor="w", pady=(0, 22))

    def card(self, page, title, subtitle=None, expand=False):
        outer = tk.Frame(page, bg=CARD, highlightbackground="#2b374e", highlightthickness=1)
        outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 14))
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=20, pady=17)
        self.label(inner, title, 12, bold=True).pack(anchor="w", pady=(0, 10))
        if subtitle:
            self.label(inner, subtitle, 9, MUTED, justify="left", anchor="w").pack(anchor="w", pady=(0, 12))
        return inner

    def form_field(self, parent, column, title, variable, values=None, width=15):
        frame = tk.Frame(parent, bg=parent.cget("bg"))
        frame.grid(row=0, column=column, sticky="w", padx=(0, 24))
        self.label(frame, title, 9, MUTED).pack(anchor="w", pady=(0, 8))
        (self.combo(frame, variable, values, width) if values else self.entry(frame, variable, width)).pack(anchor="w")
        return frame

    def show_page(self, index):
        self.cancel_capture()
        self.current_page = index
        for i, page in enumerate(self.pages):
            page.pack_forget()
            self.page_buttons[i].configure(bg="#263650" if i == index else SIDE, fg=TEXT if i == index else MUTED)
        self.pages[index].pack(fill="both", expand=True)
        self.sync_hotkeys()

    def sync_hotkeys(self):
        enabled = enabled_actions(self.current_page, self.active)
        self.service.configure({name: chord for name, chord in self.hotkeys.items() if name in enabled})

    def arm_capture(self, widget, variable, status, hotkey=False):
        self.cancel_capture()
        self.capture_serial += 1
        widget.focus_set()
        self.service.start_capture(self.capture_serial)
        self.capture = {"token": self.capture_serial, "widget": widget, "variable": variable,
                        "status": status, "hotkey": hotkey}
        status.configure(text="等待按键… 支持 F6 / ` / Home / 组合键")

    def cancel_capture(self, widget=None):
        if self.capture is not None and (widget is None or self.capture["widget"] == widget):
            state = self.capture
            self.capture = None
            self.service.end_capture()
            if state["status"].winfo_exists():
                state["status"].configure(text="捕获已取消；点击按键框可重新捕获")

    def receive_capture(self, data):
        token, chord, complete = data
        state = self.capture
        if state is None or state["token"] != token:
            return
        if not complete:
            state["status"].configure(text=f"{chord} … 请继续按下主键")
            return
        if state["hotkey"]:
            try:
                hotkey_spec(chord)
            except ValueError as exc:
                state["status"].configure(text=str(exc))
                self.service.start_capture(token)
                return
        state["variable"].set(chord)
        state["status"].configure(text=f"已捕获 {chord}" + (" · 点击“应用快捷键”保存" if state["hotkey"] else ""))
        self.service.end_capture()
        self.capture = None

    def build_click(self):
        page = self.pages[0]
        self.header(page, "01 / AUTO CLICKER", "鼠标连点", "设置点击节奏，交给 AutoTools 重复执行。")
        self.click_button = tk.StringVar(value="左键")
        self.click_mode = tk.StringVar(value="单击")
        self.click_interval = tk.StringVar(value="0.100")
        self.click_position = tk.StringVar(value="跟随当前鼠标")
        self.click_x = tk.StringVar(value="0")
        self.click_y = tk.StringVar(value="0")
        self.click_loops = tk.StringVar(value="0")
        self.click_delay = tk.StringVar(value="3")
        card = self.card(page, "点击方式", "间隔从一次完整单击 / 双击结束后开始计算。")
        row = tk.Frame(card, bg=CARD); row.pack(fill="x")
        self.form_field(row, 0, "鼠标按键", self.click_button, ["左键", "右键", "中键"])
        self.form_field(row, 1, "动作", self.click_mode, ["单击", "双击"])
        self.form_field(row, 2, "每次间隔（秒）", self.click_interval)
        card = self.card(page, "位置与循环")
        row = tk.Frame(card, bg=CARD); row.pack(fill="x")
        self.position_fields = [
            self.form_field(row, 0, "点击位置", self.click_position, ["跟随当前鼠标", "固定屏幕坐标"]),
            self.form_field(row, 1, "X 坐标", self.click_x, width=12),
            self.form_field(row, 2, "Y 坐标", self.click_y, width=12)]
        self.pick_button = self.button(row, "3 秒后取点", self.capture_point, editable=True)
        self.pick_button.grid(row=0, column=3, sticky="s")
        row = tk.Frame(card, bg=CARD); row.pack(fill="x", pady=(18, 0))
        self.form_field(row, 0, "执行次数（0 = 无限）", self.click_loops)
        self.form_field(row, 1, "启动倒计时（秒）", self.click_delay)
        self.label(card, "双击内部间隔为 0.06 秒；停止时会自动释放已按下的鼠标键。", 9, MUTED).pack(anchor="w", pady=(15, 0))
        actions = tk.Frame(page, bg=BG); actions.pack(fill="x", pady=(4, 0))
        self.click_start = self.button(actions, "开始连点", self.toggle_click, primary=True)
        self.click_start.pack(side="left")
        self.click_hint = self.label(actions, "", 10, MUTED); self.click_hint.pack(side="left", padx=18)
        self.label(page, "提示：点击作用于真实鼠标指针所在位置，使用快捷键停止更方便。", 9, MUTED).pack(anchor="w", pady=18)

    def build_keys(self):
        page = self.pages[1]
        self.header(page, "02 / BACKGROUND KEYS", "键盘队列", "绑定窗口，按顺序循环发送后台按键。")
        card = self.card(page, "目标进程 / 窗口")
        row = tk.Frame(card, bg=CARD); row.pack(fill="x")
        self.window_var = tk.StringVar()
        self.window_combo = self.combo(row, self.window_var, [], 55)
        self.window_combo.pack(side="left", fill="x", expand=True)
        self.window_combo.bind("<<ComboboxSelected>>", lambda _: self.safe(self.select_window))
        self.button(row, "刷新", self.refresh_windows, editable=True).pack(side="left", padx=(10, 0))
        row = tk.Frame(card, bg=CARD); row.pack(fill="x", pady=(10, 0))
        self.label(row, "接收窗口", 9, MUTED).pack(side="left", padx=(0, 10))
        self.receiver_var = tk.StringVar()
        self.receiver_combo = self.combo(row, self.receiver_var, [], 38)
        self.receiver_combo.pack(side="left", fill="x", expand=True)
        self.receiver_combo.bind("<<ComboboxSelected>>", lambda _: self.safe(self.select_receiver))
        self.bind_hint = self.label(card, "", 9, MUTED); self.bind_hint.pack(anchor="w", pady=(10, 0))
        card = self.card(page, "按键序列", expand=True)
        self.key_tree = self.tree(card, ("序号", "按键 / 组合键", "按下（秒）", "释放后等待（秒）"), (55, 230, 120, 150), 4)
        self.key_tree.bind("<Double-1>", lambda _: self.safe(lambda: self.edit_step(True)) if not self.active else None)
        row = tk.Frame(card, bg=CARD); row.pack(fill="x", pady=(12, 0))
        for title, command in (("＋ 添加", lambda: self.edit_step(False)), ("编辑", lambda: self.edit_step(True)),
                               ("删除", self.delete_step), ("复制", self.copy_step),
                               ("↑", lambda: self.move_step(-1)), ("↓", lambda: self.move_step(1))):
            self.button(row, title, command, editable=True).pack(side="left", padx=(0, 6))
        self.button(row, "导入", self.load_queue, editable=True).pack(side="right")
        self.button(row, "导出", self.save_queue, editable=True).pack(side="right", padx=6)
        self.key_loops = tk.StringVar(value="0")
        row = tk.Frame(page, bg=BG); row.pack(fill="x")
        self.key_start = self.button(row, "开始后台执行", self.toggle_keys, primary=True)
        self.key_start.pack(side="left")
        self.label(row, "轮数（0 = 无限）", 9, MUTED).pack(side="left", padx=(18, 8))
        self.entry(row, self.key_loops, 6).pack(side="left")
        self.key_hint = self.label(row, "", 9, MUTED); self.key_hint.pack(side="right")
        self.label(page, "后台 / 最小化均发送窗口消息，不抢焦点。发送成功不代表游戏响应；组合键支持取决于目标。",
                   9, "#d3b581", wraplength=830, justify="left").pack(anchor="w", pady=(12, 0))
        self.refresh_steps()

    def tree(self, parent, headings, widths, height):
        frame = tk.Frame(parent, bg=FIELD); frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=list(range(len(headings))), show="headings", height=height, selectmode="browse")
        for i, (name, width) in enumerate(zip(headings, widths)):
            tree.heading(i, text=name, anchor="center")
            tree.column(i, width=round(width*self.scale), minwidth=round(45*self.scale),
                        anchor="center", stretch=i != 0)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y"); tree.pack(fill="both", expand=True)
        return tree

    def build_record(self):
        page = self.pages[2]
        self.header(page, "03 / MACRO RECORDER", "操作录制", "记录键盘与鼠标，让一套操作可以再次执行。")
        self.record_mode = tk.StringVar(value="屏幕坐标")
        self.replay_loops = tk.StringVar(value="1")
        self.replay_speed = tk.StringVar(value="1.0")
        self.replay_gap = tk.StringVar(value="1.0")
        self.record_delay = tk.StringVar(value="3")
        card = self.card(page, "录制与回放设置")
        row = tk.Frame(card, bg=CARD); row.pack(fill="x")
        self.form_field(row, 0, "坐标模式", self.record_mode, ["屏幕坐标", "窗口相对坐标"], 17)
        self.form_field(row, 1, "循环次数（0 = 无限）", self.replay_loops, width=13)
        self.form_field(row, 2, "回放速度", self.replay_speed, ["0.5", "1.0", "2.0"], 9)
        row = tk.Frame(card, bg=CARD); row.pack(fill="x", pady=(12, 0))
        self.form_field(row, 0, "每轮等待（秒）", self.replay_gap, width=17)
        self.form_field(row, 1, "录制 / 回放倒计时（秒）", self.record_delay, width=13)
        self.label(row, "窗口模式复用键盘页绑定的目标。\n回放操作需要目标在前台。", 9, MUTED, justify="left").grid(row=0, column=2, sticky="w")
        card = self.card(page, "事件预览", expand=True)
        self.record_info = self.label(card, "尚无录制 · 点击开始录制，或加载本地文件", 9, MUTED)
        self.record_info.pack(anchor="w", pady=(0, 8))
        self.record_tree = self.tree(card, ("时间（秒）", "类型", "内容"), (100, 100, 430), 4)
        row = tk.Frame(page, bg=BG); row.pack(fill="x")
        self.record_start = self.button(row, "开始录制", self.toggle_record, primary=True)
        self.record_start.pack(side="left")
        self.replay_start = self.button(row, "回放", self.toggle_replay)
        self.replay_start.pack(side="left", padx=8)
        self.button(row, "加载文件", self.load_record, editable=True).pack(side="right")
        self.button(row, "保存文件", self.save_record, editable=True).pack(side="right", padx=8)
        self.record_hint = self.label(page, "", 9, MUTED); self.record_hint.pack(anchor="w", pady=(12, 0))

    def build_settings(self):
        page = self.pages[3]
        self.header(page, "04 / PREFERENCES", "偏好设置", "统一管理全局快捷键与运行状态。")
        viewport = tk.Frame(page, bg=BG)
        viewport.pack(fill="both", expand=True)
        self.settings_canvas = tk.Canvas(viewport, bg=BG, highlightthickness=0, height=400)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.settings_canvas.yview)
        self.settings_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.settings_canvas.pack(side="left", fill="both", expand=True)
        page = tk.Frame(self.settings_canvas, bg=BG)
        self.settings_body = page
        content = self.settings_canvas.create_window(0, 0, anchor="nw", window=page)
        page.bind("<Configure>", lambda event: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>", lambda event: self.settings_canvas.itemconfigure(content, width=event.width))
        self.root.bind_all("<MouseWheel>", self.on_settings_wheel, add="+")
        card = self.card(page, "工具快捷键", "点击按键框后直接按键，支持 F6、反引号 `、Home 和组合键；捕获时不会启动工具。")
        grid = tk.Frame(card, bg=CARD); grid.pack(fill="x")
        self.hotkey_vars = {}
        self.hotkey_entries = {}
        for idx, (key, title) in enumerate(NAMES.items()):
            row, col = divmod(idx, 2)
            self.label(grid, title, 10, MUTED).grid(row=row, column=col*2, sticky="w", padx=(0, 15), pady=5)
            variable = tk.StringVar(value=self.hotkeys[key])
            self.hotkey_vars[key] = variable
            entry = ttk.Entry(grid, textvariable=variable, width=21, state="readonly")
            entry.grid(row=row, column=col*2+1, sticky="w", padx=(0, 26), pady=5)
            self.controls.append((entry, "readonly"))
            self.hotkey_entries[key] = entry

            def arm(event, widget=entry, var=variable):
                if not self.active:
                    self.safe(lambda: self.arm_capture(widget, var, self.capture_hint, hotkey=True))
                return "break"

            entry.bind("<Button-1>", arm)
            entry.bind("<FocusIn>", lambda event, widget=entry, var=variable:
                       self.safe(lambda: self.arm_capture(widget, var, self.capture_hint, hotkey=True))
                       if not self.active and self.capture is None else None)
            entry.bind("<FocusOut>", lambda event: self.cancel_capture(event.widget))
        self.capture_hint = self.label(card, "点击上方按键框开始捕获；修改后需点击应用。", 9, MUTED)
        self.capture_hint.pack(anchor="w", pady=(10, 0))
        row = tk.Frame(card, bg=CARD); row.pack(fill="x", pady=(12, 0))
        self.button(row, "应用快捷键", self.apply_hotkeys, primary=True, editable=True).pack(side="left")
        self.button(row, "恢复默认", self.default_hotkeys, editable=True).pack(side="left", padx=8)
        self.hotkey_status = self.label(row, "正在注册…", 9, MUTED); self.hotkey_status.pack(side="left", padx=8)
        card = self.card(page, "窗口与托盘")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        row.columnconfigure(1, weight=1)
        size = round(26 * self.scale)
        self.tray_check_images = []
        for selected in (False, True):
            icon = tk.PhotoImage(master=self.root, width=size, height=size)
            icon.put(ACCENT if selected else MUTED, to=(1, 1, size-1, size-1))
            icon.put(ACCENT if selected else FIELD, to=(3, 3, size-3, size-3))
            if selected:
                # Draw a real check mark, independent of font/theme glyphs.
                points = ((.23, .50), (.43, .70), (.78, .30))
                for a, b in zip(points, points[1:]):
                    for n in range(size * 2):
                        t = n / (size * 2 - 1)
                        x = round(size * (a[0] + (b[0]-a[0])*t))
                        y = round(size * (a[1] + (b[1]-a[1])*t))
                        r = max(1, round(self.scale))
                        icon.put(FIELD, to=(x-r, y-r, x+r+1, y+r+1))
            self.tray_check_images.append(icon)
        self.tray_check = tk.Checkbutton(row, text="  最小化到系统托盘", variable=self.minimize_to_tray,
            image=self.tray_check_images[0], selectimage=self.tray_check_images[1], compound="left",
            indicatoron=False, bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=TEXT,
            selectcolor=CARD, relief="flat", overrelief="flat", bd=0, padx=4, pady=8,
            highlightthickness=1, highlightbackground=CARD, highlightcolor=ACCENT, takefocus=True,
            command=lambda: self.safe(self.apply_tray_preference))
        self.tray_check.grid(row=0, column=0, sticky="nw", padx=(0, 20))
        self.tray_help = self.label(row, "开启：最小化后隐藏到托盘；关闭：最小化到任务栏。\n双击托盘图标恢复，右键可停止或退出；窗口 × 仍为退出。",
                                   9, MUTED, justify="left", wraplength=520)
        self.tray_help.grid(row=0, column=1, sticky="nw", pady=8)
        row.bind("<Configure>", lambda e: self.tray_help.configure(
            wraplength=max(180, e.width-self.tray_check.winfo_reqwidth()-24)))
        card = self.card(page, "运行日志", expand=True)
        self.log_widget = tk.Text(card, bg=FIELD, fg=MUTED, relief="flat", bd=0, height=6,
                                  wrap="word", font=("Microsoft YaHei UI", 9), padx=12, pady=10, state="disabled")
        self.log_widget.pack(fill="both", expand=True)
        self.label(page, "只启用当前工具页的启动快捷键；停止当前任务和紧急停止始终有效。\n配置保存在程序 data 文件夹。后台消息是否被游戏接受取决于游戏的输入机制。",
                   9, MUTED, justify="left", wraplength=820).pack(anchor="w", pady=(2, 0))

    def on_settings_wheel(self, event):
        if self.current_page != 3 or isinstance(event.widget, tk.Text):
            return
        widget = event.widget
        while widget is not None:
            if widget in (self.settings_body, self.settings_canvas):
                if event.delta:
                    amount = max(1, abs(event.delta) // 120)
                    self.settings_canvas.yview_scroll(-amount if event.delta > 0 else amount, "units")
                return "break"
            widget = getattr(widget, "master", None)

    def load_config(self):
        try:
            path = BASE / "data" / "settings.json"
            if path.exists():
                self.config = read_json(path)
                if not isinstance(self.config, dict):
                    raise ValueError("配置应为对象")
                self.steps = validate_steps(self.config.get("steps", self.steps))
                hotkeys = self.config.get("hotkeys", self.hotkeys)
                if set(hotkeys) != set(DEFAULT_HOTKEYS):
                    raise ValueError("快捷键配置不完整")
                specs = [hotkey_spec(v) for v in hotkeys.values()]
                if len(set(specs)) != len(specs):
                    raise ValueError("快捷键重复")
                self.hotkeys = hotkeys
        except Exception as exc:
            self.config = {}
            self.emit("log", f"配置无法加载，使用默认值：{exc}")

    def fields(self):
        return ("click_button", "click_mode", "click_interval", "click_position", "click_x", "click_y",
                "click_loops", "click_delay", "key_loops", "record_mode", "replay_loops", "replay_speed",
                "replay_gap", "record_delay")

    def restore_fields(self):
        saved = self.config.get("fields", {})
        if isinstance(saved, dict):
            for name in self.fields():
                if name in saved and isinstance(saved[name], str):
                    getattr(self, name).set(saved[name])
        self.update_hints()

    def save_config(self):
        write_json(BASE / "data" / "settings.json", {"hotkeys": self.hotkeys, "steps": self.steps,
                   "minimize_to_tray": self.minimize_to_tray.get(),
                   "fields": {name: getattr(self, name).get() for name in self.fields()}})

    def apply_tray_preference(self):
        if not self.minimize_to_tray.get() and self.tray_hidden:
            self.restore_window()
        self.save_config()

    def on_configure(self, event):
        if event.widget == self.root:
            state = self.root.state()
            if state in ("normal", "zoomed"):
                self.restore_state = state

    def on_unmap(self, event):
        if event.widget == self.root and not self.closing:
            self.root.after_idle(self.handle_minimize)

    def handle_minimize(self):
        if self.closing or self.tray_hidden or not self.minimize_to_tray.get() or self.root.state() != "iconic":
            return
        self.cancel_capture()
        try:
            # Keep the normal taskbar window if icon creation fails.
            self.tray.show()
        except Exception as exc:
            self.log(f"托盘不可用，保留任务栏窗口：{exc}")
            return
        self.tray_hidden = True
        self.root.withdraw()

    def restore_window(self):
        # Restore first so a failed tray deletion can never hide the only UI.
        self.root.deiconify()
        self.root.state(self.restore_state)
        self.root.lift()
        self.tray_hidden = False
        try:
            self.tray.hide()
        except Exception as exc:
            self.log(f"清理托盘图标失败：{exc}")

    def on_tray_action(self, action):
        if action == "restore":
            self.restore_window()
        elif action == "stop":
            self.stop_all()
        elif action == "exit":
            self.restore_window()
            self.close()

    def update_hints(self):
        self.click_hint.configure(text=f"{self.hotkeys['click']}  启动 / 停止")
        self.key_hint.configure(text=f"{self.hotkeys['keys']}  启动 / 停止")
        self.bind_hint.configure(text=f"切换到目标窗口后按 {self.hotkeys['bind']} 快速绑定，也可使用上方下拉列表。")
        self.record_hint.configure(text=f"{self.hotkeys['record']}  录制 / 停止     {self.hotkeys['replay']}  回放 / 停止     控制快捷键不录入")

    def apply_hotkeys(self):
        self.cancel_capture()
        proposed = {key: normalize_chord(var.get()) for key, var in self.hotkey_vars.items()}
        specs = [hotkey_spec(v) for v in proposed.values()]
        if len(set(specs)) != len(specs):
            raise ValueError("快捷键存在重复")
        self.hotkeys = proposed
        for name, chord in proposed.items():
            self.hotkey_vars[name].set(chord)
        self.sync_hotkeys()
        self.update_hints()
        self.save_config()

    def default_hotkeys(self):
        for key, value in DEFAULT_HOTKEYS.items():
            self.hotkey_vars[key].set(value)
        self.apply_hotkeys()

    def refresh_windows(self):
        self.window_list = win.windows()
        self.window_combo.configure(values=[w.label() for w in self.window_list])
        if self.target:
            self.window_var.set(self.target.label())
        elif self.window_list:
            self.window_var.set("请选择目标窗口，或使用绑定快捷键")
        else:
            self.window_var.set("未找到可绑定窗口，请打开目标程序后刷新")

    def select_window(self):
        index = self.window_combo.current()
        if index >= 0:
            self.bind_target(win.Target.capture(self.window_list[index].hwnd))

    def bind_target(self, target):
        if self.active:
            raise ValueError("请先停止当前任务再更换绑定窗口")
        self.target = target
        self.window_var.set(target.label())
        self.receivers = win.children(target.hwnd)
        self.receiver_combo.configure(values=[f"{name}  ·  0x{hwnd:X}" for hwnd, name in self.receivers])
        idx = next((i for i, pair in enumerate(self.receivers) if pair[0] == target.receiver), 0)
        self.receiver_combo.current(idx)
        self.select_receiver()
        self.footer_status.configure(text=f"●  已绑定 PID {target.pid}", fg=GREEN)
        self.log(f"绑定：{target.label()}")

    def select_receiver(self):
        index = self.receiver_combo.current()
        if self.target and index >= 0:
            self.target = replace(self.target, receiver=self.receivers[index][0])

    def get_target(self):
        if not self.target or not self.target.valid():
            raise ValueError("请先在键盘队列页绑定有效窗口；进程重启后需要重新绑定")
        return self.target

    def refresh_steps(self, select=None):
        self.key_tree.delete(*self.key_tree.get_children())
        for idx, step in enumerate(self.steps):
            self.key_tree.insert("", "end", iid=str(idx), values=(f"{idx+1:02}", step["key"], step["hold"], step["wait"]))
        if select is not None and 0 <= select < len(self.steps):
            self.key_tree.selection_set(str(select)); self.key_tree.see(str(select))

    def selected_step(self):
        selection = self.key_tree.selection()
        if not selection:
            raise ValueError("请先选中一个步骤")
        return int(selection[0])

    def edit_step(self, edit):
        if self.active:
            return
        index = self.selected_step() if edit else None
        step = self.steps[index] if edit else {"key": "SPACE", "hold": .05, "wait": 1}
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑按键步骤" if edit else "添加按键步骤")
        dialog.configure(bg=CARD)
        dialog.geometry(f"{round(470*self.scale)}x{round(370*self.scale)}")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        body = tk.Frame(dialog, bg=CARD); body.pack(fill="both", expand=True, padx=24, pady=22)
        self.label(body, "按键步骤", 17, bold=True).pack(anchor="w", pady=(0, 12))
        key = tk.StringVar(value=step["key"])
        hold = tk.StringVar(value=str(step["hold"]))
        wait = tk.StringVar(value=str(step["wait"]))
        self.label(body, "按键 / 组合键", 9, MUTED).pack(anchor="w")
        entry = ttk.Entry(body, textvariable=key); entry.pack(fill="x", pady=(6, 8))
        capture = self.button(body, "点击捕获，然后按下组合键", lambda: self.arm_capture(capture, key, capture))
        capture.pack(fill="x")
        capture.bind("<FocusOut>", lambda event: self.cancel_capture(capture))
        dialog.bind("<Destroy>", lambda event: self.cancel_capture(capture) if event.widget == dialog else None)
        row = tk.Frame(body, bg=CARD); row.pack(fill="x", pady=15)
        for col, (title, var) in enumerate((("按下时长（秒）", hold), ("释放后等待（秒）", wait))):
            f = tk.Frame(row, bg=CARD); f.grid(row=0, column=col, padx=(0, 18))
            self.label(f, title, 9, MUTED).pack(anchor="w", pady=(0, 5))
            ttk.Entry(f, textvariable=var, width=20).pack()

        def save():
            try:
                value = validate_steps([{"key": key.get(), "hold": hold.get(), "wait": wait.get()}])[0]
                if edit:
                    self.steps[index] = value
                else:
                    self.steps.append(value)
                self.refresh_steps(index if edit else len(self.steps)-1)
                self.save_config()
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("步骤无效", str(exc), parent=dialog)

        self.button(body, "保存步骤", save, primary=True).pack(anchor="e")
        entry.focus_set()

    def delete_step(self):
        idx = self.selected_step(); del self.steps[idx]; self.refresh_steps(min(idx, len(self.steps)-1))

    def copy_step(self):
        idx = self.selected_step(); self.steps.insert(idx+1, dict(self.steps[idx])); self.refresh_steps(idx+1)

    def move_step(self, delta):
        idx = self.selected_step(); other = idx+delta
        if 0 <= other < len(self.steps):
            self.steps[idx], self.steps[other] = self.steps[other], self.steps[idx]
            self.refresh_steps(other)

    def save_queue(self):
        steps = validate_steps(self.steps)
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json", filetypes=[("按键队列", "*.json")], initialfile="按键队列.json")
        if path:
            write_json(path, {"format": "game-assistant-queue", "version": 1, "steps": steps})
            self.log("按键队列已保存")

    def load_queue(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("按键队列", "*.json")])
        if path:
            data = read_json(path)
            if not isinstance(data, dict) or data.get("format") != "game-assistant-queue" or data.get("version") != 1:
                raise ValueError("不是支持的按键队列文件")
            self.steps = validate_steps(data.get("steps")); self.refresh_steps(); self.save_config()

    def loops(self, variable):
        val = number(variable.get(), "循环次数", 0, 1_000_000)
        if val != int(val):
            raise ValueError("循环次数必须为整数")
        return int(val)

    def prepare(self, kind):
        if self.active or self.runner.busy:
            raise ValueError("请先停止当前任务；同一时间运行一个工具")
        if "stop" in self.hotkey_failures:
            raise ValueError("紧急停止快捷键注册失败，请在设置页更换快捷键")
        self.save_config()
        self.active = kind
        self.cancel_capture()
        self.sync_hotkeys()
        self.started = time.monotonic()
        for control, _ in self.controls:
            control.configure(state="disabled")
        self.footer_status.configure(text=f"●  {NAMES[kind]}准备中", fg=ACCENT)
        self.click_start.configure(text="停止连点" if kind == "click" else "开始连点", state="normal" if kind == "click" else "disabled")
        self.key_start.configure(text="停止执行" if kind == "keys" else "开始后台执行", state="normal" if kind == "keys" else "disabled")
        self.record_start.configure(text="停止录制" if kind == "record" else "开始录制", state="normal" if kind == "record" else "disabled")
        self.replay_start.configure(text="停止回放" if kind == "replay" else "回放", state="normal" if kind == "replay" else "disabled")
        self.log(f"开始：{NAMES[kind]}")

    def idle(self, error=None):
        self.active = None
        self.sync_hotkeys()
        self.pending_record = False
        for control, state in self.controls:
            control.configure(state=state)
        for button, title in ((self.click_start, "开始连点"), (self.key_start, "开始后台执行"),
                              (self.record_start, "开始录制"), (self.replay_start, "回放")):
            button.configure(text=title, state="normal")
        self.footer_status.configure(text="●  " + ("已停止 · 请查看日志" if error else "就绪"), fg=RED if error else GREEN)
        self.footer_time.configure(text="")
        self.log(error or "任务已停止 / 完成")

    def toggle_click(self):
        if self.active == "click":
            self.stop_all(); return
        interval = number(self.click_interval.get(), "点击间隔", .001, 3600)
        delay = number(self.click_delay.get(), "启动倒计时", 0, 60)
        loops = self.loops(self.click_loops)
        point = None
        if self.click_position.get() == "固定屏幕坐标":
            point = (int(self.click_x.get()), int(self.click_y.get()))
        button = {"左键": "left", "右键": "right", "中键": "middle"}[self.click_button.get()]
        self.prepare("click")
        self.runner.click(button, self.click_mode.get() == "双击", interval, loops, point, delay)

    def toggle_keys(self):
        if self.active == "keys":
            self.stop_all(); return
        target = self.get_target()
        steps = validate_steps(self.steps)
        loops = self.loops(self.key_loops)
        self.prepare("keys")
        self.runner.keys(target, steps, loops)

    def confirm_replace_recording(self):
        return not self.dirty_recording or messagebox.askyesno("尚未保存", "当前录制尚未保存，是否放弃并继续？", parent=self.root)

    def toggle_record(self):
        if self.active == "record":
            self.stop_all(); return
        if self.active:
            raise ValueError("请先停止当前任务")
        if not self.confirm_replace_recording():
            return
        delay = number(self.record_delay.get(), "倒计时", 0, 60)
        mode = "window" if self.record_mode.get() == "窗口相对坐标" else "screen"
        target = self.get_target() if mode == "window" else None
        if not self.service.hooks_ok:
            raise ValueError("键鼠监听不可用，无法录制")
        self.prepare("record")
        self.pending_record = True
        deadline = time.monotonic() + delay

        def tick():
            if not self.pending_record or self.closing:
                return
            if time.monotonic() < deadline:
                self.footer_status.configure(text=f"●  录制倒计时 · {max(1, int(deadline-time.monotonic()+.99))} 秒")
                self.root.after(50, tick)
                return
            try:
                if target and (win.user.GetForegroundWindow() != target.hwnd or win.user.IsIconic(target.hwnd)):
                    raise ValueError("请在倒计时内切换到绑定窗口后重新录制")
                self.service.begin(mode, target)
                self.pending_record = False
                self.footer_status.configure(text="●  正在录制", fg=RED)
            except Exception as exc:
                self.idle(str(exc))
        tick()

    def toggle_replay(self):
        if self.active == "replay":
            self.stop_all(); return
        if not self.recording:
            raise ValueError("请先录制操作或加载录制文件")
        recording = validate_recording(self.recording)
        # Externally edited recordings must not synthesize our global control chords.
        down = set()
        for event in recording["events"]:
            if event["type"] == "key":
                vk = generic(event["vk"])
                if event["down"]:
                    down.add(vk)
                    mods = sum(flag for key, flag in ((18, 1), (17, 2), (16, 4), (91, 8)) if key in down)
                    if (mods, vk) in [hotkey_spec(v) for v in self.hotkeys.values()]:
                        raise ValueError("录制包含当前控制快捷键，请修改快捷键或重新录制")
                else:
                    down.discard(vk)
        target = self.get_target() if recording["coordinate_mode"] == "window" else None
        loops = self.loops(self.replay_loops)
        speed = number(self.replay_speed.get(), "速度", .1, 4)
        gap = number(self.replay_gap.get(), "轮间等待", 0, 3600)
        delay = number(self.record_delay.get(), "倒计时", 0, 60)
        self.prepare("replay")
        self.runner.replay(recording, loops, speed, gap, delay, target)

    def finish_recording(self):
        self.recording = self.service.finish()
        self.dirty_recording = bool(self.recording["events"])
        self.preview_recording()
        self.idle()

    def stop_all(self):
        if self.active == "record":
            if self.pending_record:
                self.pending_record = False
                self.idle()
            else:
                self.finish_recording()
        elif self.runner.busy:
            self.runner.stop()
            self.footer_status.configure(text="●  正在停止并释放输入…", fg=MUTED)

    def capture_point(self):
        self.footer_status.configure(text="●  请把鼠标移到目标位置 · 3 秒后取点", fg=ACCENT)

        def capture():
            if not self.active:
                x, y = win.cursor()
                self.click_x.set(str(x)); self.click_y.set(str(y))
                self.click_position.set("固定屏幕坐标")
                self.footer_status.configure(text=f"●  已取点 ({x}, {y})", fg=GREEN)
        self.root.after(3000, capture)

    def preview_recording(self):
        self.record_tree.delete(*self.record_tree.get_children())
        if not self.recording:
            return
        names = {v: k for k, v in KEYS.items()}
        events = self.recording["events"]
        # Show the first 500 events without filling the UI with a large mouse trace.
        for event in events[:500]:
            kind = event["type"]
            if kind == "key":
                desc = f"{names.get(event['vk'], 'VK '+str(event['vk']))}  {'按下' if event['down'] else '释放'}"
            elif kind == "button":
                desc = f"{event['button']}  {'按下' if event['down'] else '释放'}  ({event['x']}, {event['y']})"
            elif kind == "wheel":
                desc = f"{'水平' if event['horizontal'] else '垂直'}滚动 {event['delta']}"
            else:
                desc = f"({event['x']}, {event['y']})"
            self.record_tree.insert("", "end", values=(f"{event['t']:.3f}", {"key": "键盘", "button": "鼠标按键", "move": "移动", "wheel": "滚轮"}[kind], desc))
        mode = "屏幕坐标" if self.recording["coordinate_mode"] == "screen" else "窗口相对坐标"
        self.record_mode.set(mode)
        self.record_info.configure(text=f"{len(events)} 个事件 · {self.recording['duration']:.2f} 秒 · {mode} · 预览前 500 条" + (" · 未保存" if self.dirty_recording else ""))

    def save_record(self):
        if not self.recording:
            raise ValueError("暂无录制可保存")
        data = validate_recording(self.recording)
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json", filetypes=[("录制文件", "*.json")], initialfile="操作录制.json")
        if path:
            write_json(path, data)
            self.dirty_recording = False
            self.preview_recording()
            self.log("录制文件已保存")

    def load_record(self):
        if not self.confirm_replace_recording():
            return
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("录制文件", "*.json")])
        if path:
            self.recording = validate_recording(read_json(path))
            self.dirty_recording = False
            self.preview_recording()
            self.log("录制已加载；窗口相对模式需要重新确认当前绑定目标")

    def log(self, text):
        self.log_lines.append(f"{time.strftime('%H:%M:%S')}   {text}")
        self.log_lines = self.log_lines[-150:]
        if hasattr(self, "log_widget"):
            self.log_widget.configure(state="normal")
            self.log_widget.delete("1.0", "end")
            self.log_widget.insert("end", "\n".join(self.log_lines))
            self.log_widget.see("end")
            self.log_widget.configure(state="disabled")

    def on_hotkey(self, data):
        name, hwnd = data
        if self.capture is not None:
            return
        if name == "stop":
            self.stop_all(); return
        if self.root.grab_current() is not None:
            return
        if name not in enabled_actions(self.current_page, self.active):
            return
        if name == "bind":
            target = win.Target.capture(hwnd)
            self.bind_target(target)
            messagebox.showinfo("窗口绑定成功", f"进程：{target.name}\nPID：{target.pid}\n窗口：{target.title}\n\n已绑定，可执行后台按键队列。", parent=self.root)
        else:
            {"click": self.toggle_click, "keys": self.toggle_keys, "record": self.toggle_record, "replay": self.toggle_replay}[name]()

    def poll(self):
        if self.closing:
            return
        for _ in range(250):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "hotkey":
                    self.on_hotkey(data)
                elif kind == "tray":
                    self.on_tray_action(data)
                elif kind == "tray_error":
                    self.log("托盘错误：" + data)
                    if self.tray_hidden:
                        self.restore_window()
                elif kind == "captured_key":
                    self.receive_capture(data)
                elif kind == "capture_error":
                    if self.capture is not None and self.capture["token"] == data[0]:
                        self.capture["status"].configure(text=data[1])
                elif kind == "hotkeys":
                    self.hotkey_failures = data
                    self.hotkey_status.configure(text="注册失败：" + "、".join(NAMES[k] for k in data) if data else "当前页快捷键已启用", fg=RED if data else GREEN)
                    self.log(self.hotkey_status.cget("text"))
                    if data:
                        self.footer_status.configure(text="●  快捷键冲突，请在设置页修改", fg=RED)
                elif kind == "finished":
                    self.idle(data["error"])
                elif kind == "progress":
                    self.footer_status.configure(text="●  " + data)
                elif kind == "step":
                    if self.key_tree.exists(str(data)):
                        self.key_tree.selection_set(str(data)); self.key_tree.see(str(data))
                elif kind == "record_limit":
                    if self.active == "record":
                        self.finish_recording()
                    self.log(data)
                elif kind == "hook_error":
                    if self.active == "record":
                        self.finish_recording()
                    self.log("录制监听错误：" + data)
                elif kind == "log":
                    self.log(data)
            except Exception as exc:
                self.log(str(exc))
                self.footer_status.configure(text="●  操作失败 · 请查看设置页日志", fg=RED)
        if self.active:
            elapsed = time.monotonic() - self.started
            self.footer_time.configure(text=f"{int(elapsed)//60:02}:{int(elapsed)%60:02}")
        if self.active == "record" and not self.pending_record:
            count, elapsed = self.service.stats()
            self.record_info.configure(text=f"正在录制 · {elapsed:.1f} 秒 · {count} 个事件")
            if self.service.mode == "window" and (not self.service.target.valid() or win.user.GetForegroundWindow() != self.service.target.hwnd):
                self.finish_recording()
                self.log("录制目标失焦或关闭，录制已停止")
        self.root.after(40, self.poll)

    def close(self):
        self.cancel_capture()
        self.stop_all()
        if self.runner.busy:
            self.root.after(50, self.close)
            return
        if not self.confirm_replace_recording():
            return
        try:
            self.save_config()
        except OSError as exc:
            messagebox.showwarning("配置未保存", str(exc), parent=self.root)
        self.closing = True
        self.service.close()
        self.tray.close()
        self.root.destroy()


def main():
    if sys.platform != "win32":
        raise SystemExit("本程序仅支持 Windows")
    win.dpi_awareness()
    win.set_app_id("AutoTools.Desktop")
    root = tk.Tk()
    if len(sys.argv) == 3 and sys.argv[1] == "--startup-check":
        # Exercise frozen Python, Tk DLLs, bundled Tcl scripts and icons without
        # global hotkeys, clipboard access, or changing the user's preferences.
        root.withdraw()
        root.iconbitmap(default=str(ASSETS / "autotools.ico"))
        icon = tk.PhotoImage(file=str(ASSETS / "autotools.png"))
        ttk.Button(root, text="AutoTools").pack()
        root.update_idletasks()
        write_json(Path(sys.argv[2]), {"ok": True, "frozen": bool(getattr(sys, "frozen", False)),
                   "python": sys.version, "tk": root.tk.call("info", "patchlevel"), "icon_width": icon.width()})
        root.destroy()
        return
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
