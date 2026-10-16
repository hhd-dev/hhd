import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

from hhd.plugins import Config
from hhd.plugins.cec import CecPlugin
from hhd.plugins.overlay import OverlayPlugin
from hhd.plugins.overlay.controllers import B, find_devices, process_events


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
