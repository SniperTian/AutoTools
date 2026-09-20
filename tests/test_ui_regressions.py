import ctypes as C
from pathlib import Path
import threading
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import App
from assistant import win32 as win
from assistant.hooks import InputService
from assistant.model import chord_from_vk, enabled_actions, hotkey_spec, normalize_chord


class KeyNamesTests(unittest.TestCase):
    def test_punctuation_and_home_aliases(self):
        for text, expected in (("`", "BACKTICK"), ("grave", "BACKTICK"),
                               ("home", "HOME"), ("Ctrl+`", "CTRL+BACKTICK"),
                               ("Prior", "PAGEUP"), (".", "PERIOD")):
            with self.subTest(text=text):
                self.assertEqual(normalize_chord(text), expected)
        self.assertEqual(hotkey_spec("`"), (0, 192))
        self.assertEqual(hotkey_spec("home"), (0, 36))

    def test_vk_capture_function_and_navigation_keys(self):
        for vk, name in ((117, "F6"), (192, "BACKTICK"), (36, "HOME"), (35, "END"),
                         (33, "PAGEUP"), (34, "PAGEDOWN"), (45, "INSERT"), (46, "DELETE")):
            with self.subTest(vk=vk):
                self.assertEqual(chord_from_vk(vk, set()), (name, True))
        self.assertEqual(chord_from_vk(36, {17, 16}), ("CTRL+SHIFT+HOME", True))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        # Exercise the real hook callback without installing another global hook.
        self.events = []
        self.service = InputService.__new__(InputService)
        s = self.service
        s.emit = lambda k, v: self.events.append((k, v))
        s.lock = threading.RLock()
        s.hooks_ok = True
        s.recording = False
        s.capture_token = None
        s.capture_held = set()
        s.capture_swallowed = set()
        s.capture_done = False
        s.physical_down = {}
        s.suppressed = set()
        s.specs = {"stop": (0, 117)}
        self.owner = patch("assistant.hooks.win.is_own_window", return_value=True)
        self.owner.start()
        self.async_state = patch.object(win.user, "GetAsyncKeyState", return_value=0)
        self.async_state.start()
        s.start_capture(1)

    def tearDown(self):
        self.async_state.stop(); self.owner.stop()

    def key(self, vk, down=True):
        item = win.KBD(vk, 0, 0, 0, 0)
        return self.service._key(0, 0x100 if down else 0x101, C.addressof(item))

    def test_registered_f6_is_captured_and_swallowed(self):
        self.assertEqual(self.key(117), 1)
        self.assertEqual(self.events, [("captured_key", (1, "F6", True))])
        self.assertFalse(self.service.recording)

    def test_special_keys_capture_and_repeat_filter(self):
        for token, vk, name in ((2, 192, "BACKTICK"), (3, 36, "HOME")):
            self.service.start_capture(token)
            self.assertEqual(self.key(vk), 1)
            self.assertEqual(self.key(vk), 1)
            self.service.end_capture()
            self.assertEqual(self.key(vk, False), 1)
            self.assertEqual(self.events[-1], ("captured_key", (token, name, True)))
        self.assertEqual(len(self.events), 2)

    def test_modifiers_then_main_and_release(self):
        self.key(162); self.key(160); self.key(36)
        self.assertEqual(self.events[-1], ("captured_key", (1, "CTRL+SHIFT+HOME", True)))
        self.service.end_capture()
        self.assertEqual(self.key(36, False), 1)
        self.assertEqual(self.key(160, False), 1)
        self.assertEqual(self.key(162, False), 1)
        self.assertEqual(self.service.capture_swallowed, set())

    def test_capture_does_not_intercept_other_apps(self):
        with patch("assistant.hooks.win.is_own_window", return_value=False):
            self.assertFalse(self.service._capture_key(36, True))
        self.assertEqual(self.events, [])

    def test_old_release_does_not_capture_in_new_field(self):
        self.key(117)
        self.service.end_capture(); self.service.start_capture(2)
        self.key(117, False)
        self.assertEqual(len(self.events), 1)
        self.key(36)
        self.assertEqual(self.events[-1], ("captured_key", (2, "HOME", True)))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.app = App.__new__(App)
        self.app.root = Mock()
        self.app.root.grab_current.return_value = None
        self.app.active = None
        self.app.capture = None
        self.app.current_page = 0
        self.app.stop_all = Mock()
        self.app.toggle_click = Mock()
        self.app.toggle_keys = Mock()
        self.app.toggle_record = Mock()
        self.app.toggle_replay = Mock()
        self.app.bind_target = Mock()

    def test_all_page_start_combinations(self):
        actions = {"click": self.app.toggle_click, "keys": self.app.toggle_keys,
                   "record": self.app.toggle_record, "replay": self.app.toggle_replay}
        for page in range(4):
            for name, callback in actions.items():
                with self.subTest(page=page, action=name):
                    callback.reset_mock(); self.app.current_page = page
                    self.app.on_hotkey((name, None))
                    self.assertEqual(callback.call_count, int(name in enabled_actions(page)))

    def test_stop_existing_task_after_switching_page(self):
        self.app.active = "keys"; self.app.current_page = 0
        self.app.on_hotkey(("keys", None))
        self.app.toggle_keys.assert_called_once()
        self.app.on_hotkey(("click", None))
        self.app.toggle_click.assert_not_called()
        self.app.on_hotkey(("stop", None))
        self.app.stop_all.assert_called_once()

    def test_capturing_does_not_dispatch_control_shortcuts(self):
        self.app.capture = {"token": 1}
        self.app.on_hotkey(("click", None)); self.app.on_hotkey(("stop", None))
        self.app.toggle_click.assert_not_called(); self.app.stop_all.assert_not_called()

    def test_binding_popup_success_only_on_keyboard_page(self):
        target = SimpleNamespace(name="test.exe", pid=123, title="测试窗口")
        with patch("app.win.Target.capture", return_value=target) as capture, patch("app.messagebox.showinfo") as popup:
            self.app.on_hotkey(("bind", 42))
            capture.assert_not_called(); popup.assert_not_called()
            self.app.current_page = 1
            self.app.on_hotkey(("bind", 42))
            self.app.bind_target.assert_called_once_with(target)
            popup.assert_called_once()
            self.assertEqual(popup.call_args.args[0], "窗口绑定成功")
            self.assertIn("123", popup.call_args.args[1])

    def test_failed_binding_does_not_show_success(self):
        self.app.current_page = 1
        with patch("app.win.Target.capture", side_effect=ValueError("closed")), patch("app.messagebox.showinfo") as popup:
            with self.assertRaises(ValueError):
                self.app.on_hotkey(("bind", 42))
            popup.assert_not_called()


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.service_patch = patch("app.InputService")
        self.service_patch.start()
        self.window_patch = patch("app.win.windows", return_value=[])
        self.window_patch.start()
        self.config_patch = patch.object(App, "load_config")
        self.config_patch.start()
        self.root = tk.Tk(); self.root.withdraw()
        self.app = App(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        self.app.closing = True
        self.root.destroy()
        self.config_patch.stop(); self.window_patch.stop(); self.service_patch.stop()

    def test_column_header_and_body_anchor_match_after_resize(self):
        for size in ("1020x740", "1500x1000"):
            self.root.geometry(size); self.root.update_idletasks()
            for col in self.app.key_tree["columns"]:
                self.assertEqual(str(self.app.key_tree.heading(col, "anchor")),
                                 str(self.app.key_tree.column(col, "anchor")))

    def test_title_and_coordinate_layout(self):
        self.assertEqual(self.root.title(), "AutoTools")
        fields = self.app.position_fields
        self.assertEqual([int(f.grid_info()["row"]) for f in fields], [0, 0, 0])
        self.assertEqual([int(f.grid_info()["column"]) for f in fields], [0, 1, 2])
        self.assertEqual(fields[1].winfo_reqheight(), fields[2].winfo_reqheight())
        self.assertEqual(int(self.app.pick_button.grid_info()["column"]), 3)
        self.assertEqual(int(self.app.pick_button.grid_info()["row"]), 0)
        self.assertEqual(self.app.pick_button.master, fields[2].master)

    def test_tray_preference_is_saved(self):
        self.assertFalse(self.app.minimize_to_tray.get())
        self.assertGreaterEqual(self.app.tray_check_images[0].width(), 26)
        self.assertEqual(self.app.tray_check.master, self.app.tray_help.master)
        self.assertEqual(int(self.app.tray_help.grid_info()["column"]), 1)
        self.app.minimize_to_tray.set(False)
        with patch("app.write_json") as save:
            self.app.apply_tray_preference()
            self.assertFalse(save.call_args.args[1]["minimize_to_tray"])

    def test_registration_changes_with_selected_page(self):
        for page, expected in ((0, {"click", "stop"}), (1, {"keys", "bind", "stop"}),
                               (2, {"record", "replay", "stop"}), (3, {"stop"})):
            self.app.show_page(page)
            self.assertEqual(set(self.app.service.configure.call_args.args[0]), expected)

    def test_settings_capture_updates_field_without_starting_task(self):
        self.app.show_page(3)
        for vk, value in ((117, "F6"), (192, "BACKTICK"), (36, "HOME")):
            self.app.arm_capture(self.app.hotkey_entries["click"], self.app.hotkey_vars["click"], self.app.capture_hint, True)
            token = self.app.capture["token"]
            text, complete = chord_from_vk(vk, set())
            self.app.receive_capture((token, text, complete))
            self.assertEqual(self.app.hotkey_vars["click"].get(), value)
            self.assertIsNone(self.app.active)
            self.assertIsNone(self.app.capture)


if __name__ == "__main__":
    unittest.main()
