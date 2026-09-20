import ctypes as C
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from app import App
from assistant.tray import TrayIcon, NOTIFYICONDATA, shell, u

ICON = Path(__file__).resolve().parents[1] / "assets" / "autotools.ico"


class TrayWindowTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.shell_calls = []

        def notify(action, pointer):
            data = C.cast(pointer, C.POINTER(NOTIFYICONDATA)).contents
            self.shell_calls.append((action, data.uVersion, data.hIcon, data.szTip))
            return True

        self.notify = patch.object(shell, "Shell_NotifyIconW", side_effect=notify)
        self.notify.start()
        self.tray = TrayIcon(ICON, lambda k, v: self.events.append((k, v)))

    def tearDown(self):
        self.tray.close()
        self.notify.stop()

    def test_native_icon_load_and_lifecycle(self):
        self.assertEqual(C.sizeof(NOTIFYICONDATA), 976)
        self.tray.show()
        self.assertTrue(self.tray.visible)
        self.assertTrue(self.tray.hicon)
        self.assertEqual([c[0] for c in self.shell_calls], [0, 4])
        self.assertEqual(self.shell_calls[1][1], 4)
        self.assertIn("AutoTools", self.shell_calls[0][3])
        self.tray.show()
        self.assertEqual(len(self.shell_calls), 2)
        self.tray.hide()
        self.assertFalse(self.tray.visible)
        self.assertEqual(self.shell_calls[-1][0], 2)
        self.tray.close()
        self.assertFalse(self.tray.thread.is_alive())

    def test_explorer_restart_readds_icon(self):
        self.tray.show()
        u.PostMessageW(self.tray.hwnd, self.tray.taskbar_created, 0, 0)
        self.tray.show()
        self.assertEqual([c[0] for c in self.shell_calls], [0, 4, 0, 4])

    def test_mouse_and_keyboard_activation_restore(self):
        self.tray.show()
        for event in (0x203, 0x400, 0x401):
            u.PostMessageW(self.tray.hwnd, self.tray.CALLBACK, 0, (1 << 16) | event)
        self.tray.show()
        self.assertEqual(self.events, [("tray", "restore")] * 3)

    def test_menu_actions_and_resource_cleanup(self):
        self.tray.show()
        with patch.object(u, "GetCursorPos", return_value=True), patch.object(u, "SetForegroundWindow"), \
             patch.object(u, "TrackPopupMenu") as select, patch.object(u, "DestroyMenu", wraps=u.DestroyMenu) as destroy:
            for command, action in ((1, "restore"), (2, "stop"), (3, "exit")):
                select.return_value = command
                self.tray._menu()
                self.assertEqual(self.events[-1], ("tray", action))
            self.assertEqual(destroy.call_count, 3)

    def test_shell_failure_does_not_report_visible(self):
        with patch.object(shell, "Shell_NotifyIconW", return_value=False):
            with self.assertRaises(OSError):
                self.tray.show()
        self.assertFalse(self.tray.visible)


class TrayUiTests(unittest.TestCase):
    def setUp(self):
        self.app = App.__new__(App)
        a = self.app
        a.root = Mock(); a.root.state.return_value = "iconic"
        a.tray = Mock(); a.tray_hidden = False; a.closing = False
        a.minimize_to_tray = Mock(); a.minimize_to_tray.get.return_value = True
        a.cancel_capture = Mock(); a.log = Mock(); a.save_config = Mock()
        a.restore_state = "normal"
        a.active = "keys"

    def test_enabled_hides_only_after_icon_is_created(self):
        events = []
        self.app.tray.show.side_effect = lambda: events.append("icon")
        self.app.root.withdraw.side_effect = lambda: events.append("hide")
        self.app.handle_minimize()
        self.assertEqual(events, ["icon", "hide"])
        self.assertTrue(self.app.tray_hidden)
        self.assertEqual(self.app.active, "keys")

    def test_disabled_retains_taskbar_window(self):
        self.app.minimize_to_tray.get.return_value = False
        self.app.handle_minimize()
        self.app.tray.show.assert_not_called()
        self.app.root.withdraw.assert_not_called()

    def test_failed_icon_retains_taskbar_window(self):
        self.app.tray.show.side_effect = OSError("shell failed")
        self.app.handle_minimize()
        self.app.root.withdraw.assert_not_called()
        self.assertFalse(self.app.tray_hidden)

    def test_restore_window_and_remove_icon(self):
        self.app.tray_hidden = True
        self.app.restore_window()
        self.app.root.deiconify.assert_called_once()
        self.app.tray.hide.assert_called_once()
        self.assertFalse(self.app.tray_hidden)

    def test_turning_off_while_hidden_restores_and_saves(self):
        self.app.tray_hidden = True
        self.app.minimize_to_tray.get.return_value = False
        self.app.apply_tray_preference()
        self.app.root.deiconify.assert_called_once()
        self.app.save_config.assert_called_once()

    def test_tray_stop_and_exit(self):
        self.app.stop_all = Mock(); self.app.close = Mock()
        self.app.on_tray_action("stop")
        self.app.stop_all.assert_called_once()
        self.app.root.deiconify.assert_not_called()
        self.app.on_tray_action("exit")
        self.app.close.assert_called_once()
        self.app.root.deiconify.assert_called_once()
