import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

from hhd.plugins import Config
from hhd.plugins.cec import CecPlugin
from hhd.plugins.overlay import OverlayPlugin
from hhd.plugins.overlay.controllers import B, find_devices, process_events
from hhd.plugins.overlay.x11 import find_x11_display, get_active_seat_user


class OverlayDesktopDisplayTest(unittest.TestCase):
    def find_display(self, active_uid, owners):
        with (
            patch("hhd.plugins.overlay.x11.get_active_seat_user", return_value=active_uid),
            patch("hhd.plugins.overlay.x11.os.listdir", return_value=list(owners)),
            patch(
                "hhd.plugins.overlay.x11.os.stat",
                side_effect=lambda path: SimpleNamespace(
                    st_uid=owners[path.rsplit(b"/", 1)[-1]]
                ),
            ),
        ):
            return find_x11_display()

    def test_cosmic_desktop_is_selected_instead_of_greeter(self):
        self.assertEqual(
            self.find_display(1000, {b"X0": 978, b"X1": 1000}), (":1", 1000)
        )

    def test_other_users_display_is_not_used_for_active_session(self):
        self.assertEqual(self.find_display(1000, {b"X0": 978}), (None, 0))

    def test_discovery_without_logind_preserves_non_root_preference(self):
        self.assertEqual(
            self.find_display(None, {b"X0": 0, b"X1": 1000}), (":1", 1000)
        )
        self.assertEqual(self.find_display(None, {b"X0": 0}), (":0", 0))

    def test_missing_x11_directory(self):
        with (
            patch("hhd.plugins.overlay.x11.get_active_seat_user", return_value=1000),
            patch("hhd.plugins.overlay.x11.os.listdir", side_effect=FileNotFoundError),
        ):
            self.assertEqual(find_x11_display(), (None, 0))

    def test_active_user_is_read_from_seat_session(self):
        with patch(
            "hhd.plugins.overlay.x11.subprocess.run",
            side_effect=[SimpleNamespace(stdout="2\n"), SimpleNamespace(stdout="1000\n")],
        ) as run:
            self.assertEqual(get_active_seat_user(), 1000)
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["loginctl", "show-session", "2", "-p", "User", "--value"],
        )

    def test_logind_unavailable_or_session_missing(self):
        for error in (
            FileNotFoundError(),
            subprocess.CalledProcessError(1, "loginctl"),
            subprocess.TimeoutExpired("loginctl", 2),
        ):
            with (
                self.subTest(error=error),
                patch("hhd.plugins.overlay.x11.subprocess.run", side_effect=error),
            ):
                self.assertIsNone(get_active_seat_user())
        with patch(
            "hhd.plugins.overlay.x11.subprocess.run", return_value=SimpleNamespace(stdout="")
        ) as run:
            self.assertIsNone(get_active_seat_user())
            run.assert_called_once()


class OverlayKeyboardTest(unittest.TestCase):
    def test_at_keyboard_without_meta_or_armoury_is_detected(self):
        keys = bytearray(4)
        for code in (B("KEY_LEFTCTRL"), B("KEY_3"), B("KEY_4")):
            keys[code >> 3] |= 1 << (code & 7)
        keyboard = {
            "name": "AT Translated Set 2 keyboard",
            "bus": 0x11,
            "vendor": 1,
            "product": 1,
            "version": 0xAB83,
            "byte": {"key": bytes(keys)},
        }
        with patch(
            "hhd.plugins.overlay.controllers.list_evs",
            return_value={"/dev/input/event3": keyboard},
        ):
            devices = find_devices()
            self.assertTrue(devices["/dev/input/event3"]["is_keyboard"])
            self.assertEqual(find_devices(keyboard=False), {})

    def test_ctrl_shortcuts_work_and_meta_is_ignored(self):
        events = []
        device = {
            "is_keyboard": True,
            "is_controller": False,
            "is_touchscreen": False,
            "is_custom": False,
            "sdl_info": {},
            "state_kbd": {},
            "pretty": "AT Translated Set 2 keyboard",
        }
        sequence = [
            ("KEY_LEFTMETA", 1),
            ("KEY_LEFTMETA", 2),
            ("KEY_LEFTMETA", 0),
            ("KEY_3", 1),
            ("KEY_3", 0),
            ("KEY_LEFTCTRL", 1),
            ("KEY_3", 1),
            ("KEY_3", 0),
            ("KEY_4", 1),
            ("KEY_4", 0),
            ("KEY_LEFTCTRL", 0),
            ("KEY_4", 1),
            ("KEY_4", 0),
        ]
        process_events(
            events.append,
            device,
            [
                SimpleNamespace(type=B("EV_KEY"), code=B(key), value=value)
                for key, value in sequence
            ],
        )
        self.assertEqual(
            events,
            [
                {"type": "special", "event": "kbd_ctrl_3"},
                {"type": "special", "event": "kbd_ctrl_4"},
            ],
        )


class OverlayDpmsTest(unittest.TestCase):
    def setUp(self):
        self.plugin = OverlayPlugin()
        self.plugin.ovf = SimpleNamespace(gsconf={}, launch_overlay=MagicMock())

    def test_dpms_setting_is_not_exposed(self):
        with (
            patch(
                "hhd.plugins.overlay.get_touchscreen_quirk",
                return_value=(False, None),
            ),
            patch("hhd.plugins.overlay.has_touchscreen", return_value=True),
        ):
            settings = self.plugin.settings()

        self.assertNotIn("dpms", settings["gamemode"]["gamescope"]["children"])

    def test_dpms_capability_always_enables_dpms(self):
        self.plugin.emit = MagicMock()
        conf = Config({"gamemode.gamescope.dpms": False})

        with patch("hhd.plugins.overlay.SUPPORTS_DPMS", True):
            self.plugin.update(conf)

        self.assertTrue(self.plugin.ovf.gsconf["dpms"])


class OverlayFramegenShortcutTest(unittest.TestCase):
    def setUp(self):
        capability = patch("hhd.plugins.overlay.SUPPORTS_FRAMEGEN", True)
        capability.start()
        self.addCleanup(capability.stop)
        self.plugin = OverlayPlugin()
        self.plugin.emit = MagicMock()
        self.plugin.ovf = MagicMock()
        self.plugin.ovf.gsconf = {}
        self.plugin.old_shortcuts = Config({"controller.xbox_x": "framegen_toggle"})
        self.conf = Config(
            {
                "gamemode.gamescope.framegen.mode": "disabled",
                "gamemode.gamescope.framegen.enabled.quality": 4,
            }
        )

    def press(self):
        self.plugin.notify([{"type": "special", "event": "xbox_x"}])

    def test_toggle_updates_setting_and_gamescope_and_preserves_quality(self):
        for expected in ("enabled", "disabled"):
            self.press()
            self.plugin.update(self.conf)

            self.assertEqual(
                self.conf.get("gamemode.gamescope.framegen.mode", ""), expected
            )
            self.assertEqual(self.plugin.ovf.gsconf["framegen"], expected)
            self.assertEqual(self.plugin.ovf.gsconf["framegen_quality"], 4)
            self.assertEqual(
                self.conf.get("gamemode.gamescope.framegen.enabled.quality", 0), 4
            )

            # An ordinary update must not toggle again.
            self.plugin.update(self.conf)
            self.assertEqual(self.plugin.ovf.gsconf["framegen"], expected)

    def test_toggle_uses_current_setting_after_manual_change(self):
        self.plugin.update(self.conf)
        self.conf["gamemode.gamescope.framegen.mode"] = "enabled"
        self.press()
        self.plugin.update(self.conf)

        self.assertEqual(self.plugin.ovf.gsconf["framegen"], "disabled")

    def test_two_presses_before_update_cancel(self):
        self.press()
        self.press()
        self.plugin.update(self.conf)

        self.assertEqual(self.plugin.ovf.gsconf["framegen"], "disabled")

    def test_toggle_defaults_to_enabled_when_setting_is_missing(self):
        self.press()
        conf = Config({})
        self.plugin.update(conf)

        self.assertEqual(conf.get("gamemode.gamescope.framegen.mode", ""), "enabled")

    def test_unsupported_toggle_is_ignored(self):
        with patch("hhd.plugins.overlay.SUPPORTS_FRAMEGEN", False):
            self.press()
            self.plugin.update(self.conf)

        self.assertEqual(
            self.conf.get("gamemode.gamescope.framegen.mode", ""), "disabled"
        )
        self.assertNotIn("framegen", self.plugin.ovf.gsconf)
        self.plugin.update(self.conf)
        self.assertEqual(self.plugin.ovf.gsconf["framegen"], "disabled")

    def test_all_shortcut_sources_can_toggle(self):
        sources = {
            "controller": ("xbox_a", "xbox_b", "xbox_x", "xbox_y"),
            "keyboard": ("ctrl_3", "ctrl_4"),
            "custom": ("armoury", "fan"),
            "touchscreen": (
                "bottom", "top", "left_top", "left_bottom", "right_top", "right_bottom"
            ),
            "cec": ("back_double", "back_hold", "back_triple"),
        }
        prefixes = {
            "controller": "",
            "keyboard": "kbd_",
            "custom": "custom_",
            "touchscreen": "swipe_",
            "cec": "cec_",
        }
        for section, shortcuts in sources.items():
            for shortcut in shortcuts:
                with self.subTest(section=section, shortcut=shortcut):
                    self.conf["gamemode.gamescope.framegen.mode"] = "disabled"
                    self.plugin.old_shortcuts = Config(
                        {f"{section}.{shortcut}": "framegen_toggle"}
                    )
                    with patch(
                        "hhd.plugins.overlay.is_gamescope_running", return_value=True
                    ):
                        self.plugin.notify(
                            [{"type": "special", "event": prefixes[section] + shortcut}]
                        )
                    self.plugin.update(self.conf)
                    self.assertEqual(self.plugin.ovf.gsconf["framegen"], "enabled")

    def test_shortcut_option_follows_capability_for_all_sources(self):
        for supported in (False, True):
            with (
                self.subTest(supported=supported),
                patch("hhd.plugins.overlay.SUPPORTS_FRAMEGEN", supported),
                patch("hhd.plugins.cec.SUPPORTS_FRAMEGEN", supported),
                patch(
                    "hhd.plugins.overlay.open",
                    mock_open(read_data="ASUSTeK COMPUTER INC"),
                    create=True,
                ),
                patch(
                    "hhd.plugins.overlay.get_touchscreen_quirk", return_value=(False, None)
                ),
                patch("hhd.plugins.overlay.has_touchscreen", return_value=True),
            ):
                settings = self.plugin.settings()
                sections = settings["shortcuts"] | CecPlugin().settings()["shortcuts"]
                for section in sections.values():
                    for shortcut in section["children"].values():
                        if shortcut["type"] == "multiple":
                            self.assertEqual(
                                "framegen_toggle" in shortcut["options"], supported
                            )
                self.assertEqual(
                    "framegen" in settings["gamemode"]["gamescope"]["children"],
                    supported,
                )


if __name__ == "__main__":
    unittest.main()
