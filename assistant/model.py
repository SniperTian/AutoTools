from __future__ import annotations

import json
import math
import os
from pathlib import Path

VERSION = 1
MAX_EVENTS = 150_000
MAX_DURATION = 86_400

KEYS = {chr(k): k for k in range(65, 91)}
KEYS.update({str(k): 48 + k for k in range(10)})
KEYS.update({f"F{k}": 111 + k for k in range(1, 25)})
KEYS.update({f"NUM{k}": 96 + k for k in range(10)})
KEYS.update({"CTRL": 17, "ALT": 18, "SHIFT": 16, "WIN": 91,
             "SPACE": 32, "ENTER": 13, "TAB": 9, "ESC": 27,
             "BACKSPACE": 8, "DELETE": 46, "INSERT": 45,
             "HOME": 36, "END": 35, "PAGEUP": 33, "PAGEDOWN": 34,
             "LEFT": 37, "UP": 38, "RIGHT": 39, "DOWN": 40,
             "CAPSLOCK": 20, "NUMLOCK": 144, "SCROLLLOCK": 145,
             "MINUS": 189, "EQUAL": 187, "COMMA": 188, "PERIOD": 190,
             "SLASH": 191, "BACKSLASH": 220, "SEMICOLON": 186,
             "QUOTE": 222, "LBRACKET": 219, "RBRACKET": 221, "BACKTICK": 192,
             "NUMADD": 107, "NUMSUBTRACT": 109, "NUMMULTIPLY": 106,
             "NUMDIVIDE": 111, "NUMDECIMAL": 110})
MODIFIERS = {16, 17, 18, 91}
KEY_NAMES = {code: name for name, code in KEYS.items()}
KEY_ALIASES = {"`": "BACKTICK", "GRAVE": "BACKTICK", "QUOTELEFT": "BACKTICK",
               "RETURN": "ENTER", "ESCAPE": "ESC", "CONTROL": "CTRL",
               "PRIOR": "PAGEUP", "NEXT": "PAGEDOWN", "PGUP": "PAGEUP", "PGDN": "PAGEDOWN",
               "-": "MINUS", "=": "EQUAL", ",": "COMMA", ".": "PERIOD",
               "/": "SLASH", "\\": "BACKSLASH", ";": "SEMICOLON", "'": "QUOTE",
               "[": "LBRACKET", "]": "RBRACKET"}
DEFAULT_HOTKEYS = {"click": "F6", "keys": "F7", "record": "F8",
                   "replay": "F9", "bind": "CTRL+ALT+B", "stop": "CTRL+ALT+F10"}


def parse_chord(text):
    if not isinstance(text, str):
        raise ValueError("按键必须是文字")
    parts = [p.strip().upper() for p in text.split("+")]
    parts = [KEY_ALIASES.get(p, p) for p in parts]
    if not parts or any(p not in KEYS for p in parts):
        raise ValueError("无效按键。示例：SPACE、CTRL+Q、SHIFT+F1、NUM1")
    codes = [KEYS[p] for p in parts]
    if len(set(codes)) != len(codes):
        raise ValueError("组合键中不能重复按键")
    if len([k for k in codes if k not in MODIFIERS]) > 1:
        raise ValueError("组合键支持多个修饰键与一个主键")
    codes.sort(key=lambda k: k not in MODIFIERS)
    return codes


def normalize_chord(text):
    return "+".join(KEY_NAMES[k] for k in parse_chord(text))


def chord_from_vk(vk, held):
    """Physical virtual-key codes do not depend on Tk keysyms or text input."""
    mods = [KEY_NAMES[k] for k in (17, 18, 16, 91) if k in held]
    if vk in MODIFIERS:
        return "+".join(mods) + "+", False
    if vk not in KEY_NAMES:
        raise ValueError("该按键暂不支持，请换一个按键")
    return "+".join(mods + [KEY_NAMES[vk]]), True


def enabled_actions(page, active=None):
    if active:
        return {"stop", active}
    return {"stop"} | {0: {"click"}, 1: {"keys", "bind"},
                       2: {"record", "replay"}, 3: set()}.get(page, set())


def hotkey_spec(text):
    codes = parse_chord(text)
    mains = [k for k in codes if k not in MODIFIERS]
    if len(mains) != 1:
        raise ValueError("快捷键必须包含一个非修饰键")
    if mains[0] == 123:
        raise ValueError("F12 为系统调试保留键，请换一个快捷键")
    flags = sum({18: 1, 17: 2, 16: 4, 91: 8}[k] for k in codes if k in MODIFIERS)
    return flags, mains[0]


def number(value, label, minimum=0, maximum=3600):
    if isinstance(value, bool):
        raise ValueError(f"{label}必须为数字")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label}必须为数字") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{label}应在 {minimum} 到 {maximum} 之间")
    return result


def validate_steps(steps):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 1000:
        raise ValueError("按键队列应包含 1 至 1000 个步骤")
    result = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("无效的按键步骤")
        result.append({"key": normalize_chord(step.get("key", "")),
                       "hold": number(step.get("hold"), "按下时长", .01, 3600),
                       "wait": number(step.get("wait"), "释放后等待", 0, 3600)})
    return result


def integer(value, label, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{label}必须为 {lo} 至 {hi} 之间的整数")
    return value


def validate_recording(data):
    if not isinstance(data, dict) or data.get("format") != "game-assistant-recording" or data.get("version") != VERSION:
        raise ValueError("不是支持的录制文件（版本 1）")
    mode = data.get("coordinate_mode")
    if mode not in ("screen", "window"):
        raise ValueError("不支持的坐标模式")
    events = data.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise ValueError(f"录制应包含 1 至 {MAX_EVENTS} 个事件")
    last = 0.0
    validated = []
    held_keys, held_buttons = set(), set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("事件格式错误")
        t = number(event.get("t"), "事件时间", last, MAX_DURATION)
        last = t
        kind = event.get("type")
        out = {"t": t, "type": kind}
        if kind == "key":
            out.update(vk=integer(event.get("vk"), "键码", 1, 255),
                       scan=integer(event.get("scan"), "扫描码", 0, 65535))
            if type(event.get("down")) is not bool or type(event.get("extended")) is not bool:
                raise ValueError("按键事件状态错误")
            out.update(down=event["down"], extended=event["extended"])
            if out["down"]:
                held_keys.add(out["vk"])
            elif out["vk"] not in held_keys:
                raise ValueError("录制包含没有对应按下的键盘释放事件")
            else:
                held_keys.remove(out["vk"])
        elif kind in ("move", "button", "wheel"):
            out.update(x=integer(event.get("x"), "X 坐标", -100000, 100000),
                       y=integer(event.get("y"), "Y 坐标", -100000, 100000))
            if kind == "button":
                if event.get("button") not in ("left", "right", "middle", "x1", "x2") or type(event.get("down")) is not bool:
                    raise ValueError("鼠标按键事件错误")
                out.update(button=event["button"], down=event["down"])
                if out["down"]:
                    held_buttons.add(out["button"])
                elif out["button"] not in held_buttons:
                    raise ValueError("录制包含没有对应按下的鼠标释放事件")
                else:
                    held_buttons.remove(out["button"])
            if kind == "wheel":
                out.update(delta=integer(event.get("delta"), "滚动量", -120000, 120000))
                if type(event.get("horizontal")) is not bool:
                    raise ValueError("滚轮方向错误")
                out["horizontal"] = event["horizontal"]
        else:
            raise ValueError("文件包含不支持的事件")
        validated.append(out)
    duration = number(data.get("duration", last), "录制时长", last, MAX_DURATION)
    if held_keys or held_buttons:
        raise ValueError("录制缺少按键释放事件")
    environment = data.get("environment", {})
    if not isinstance(environment, dict):
        raise ValueError("录制环境信息格式错误")
    for name, length in (("desktop", 4), ("client_size", 2)):
        if name in environment:
            values = environment[name]
            if not isinstance(values, list) or len(values) != length:
                raise ValueError("录制环境尺寸格式错误")
            for value in values:
                integer(value, "环境坐标", -100000, 100000)
            if any(v <= 0 for v in values[-2:]):
                raise ValueError("录制环境尺寸必须大于零")
    return {"format": data["format"], "version": VERSION, "coordinate_mode": mode,
            "duration": duration, "environment": environment, "events": validated}


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("文件超过 32 MB 限制")
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
    os.replace(temp, path)
