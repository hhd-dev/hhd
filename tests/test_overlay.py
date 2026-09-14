import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hhd.plugins import Config
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


if __name__ == "__main__":
    unittest.main()
