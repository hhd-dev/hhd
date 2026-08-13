import unittest
from unittest.mock import patch

import evdev

from hhd.controller import Multiplexer
from hhd.controller.physical.evdev import B
from hhd.device.gpd.win import (
    GPD_CONFS,
    GpdWinControllersPlugin,
    GpdWinControlsPlugin,
)
from hhd.device.gpd.win.base import BackbuttonsEvdev, DIRECT_BUTTONS
from hhd.device.gpd.win.const import GPD_WIN_5_BTN_MAPPINGS


class RecordingEmitter:
    def __init__(self):
        self.events = []
        self.qam_calls = []

    def __call__(self, event):
        self.events.append(event)

    def simple_qam(self):
        return False

    def set_capabilities(self, unique, capabilities):
        pass

    def inject_recv(self):
        return []

    def intercept(self, unique, events):
        return False

    def send_qam(self, expanded=False):
        self.qam_calls.append(expanded)
        return False


class GpdWinButtonTest(unittest.TestCase):
    def test_win5_maps_f13_separately_from_keyboard_button(self):
        self.assertEqual(DIRECT_BUTTONS[B("KEY_F13")], "share")
        self.assertNotIn(B("KEY_F13"), GPD_WIN_5_BTN_MAPPINGS)
        self.assertEqual(GPD_WIN_5_BTN_MAPPINGS[B("KEY_O")], "keyboard")
        self.assertEqual(GPD_WIN_5_BTN_MAPPINGS[B("KEY_DELETE")], "keyboard")

    def test_win5_f13_is_not_debounced(self):
        class Device:
            def read(self):
                return [
                    evdev.InputEvent(0, 0, B("EV_KEY"), B("KEY_F13"), 1),
                    evdev.InputEvent(0, 0, B("EV_KEY"), B("KEY_F13"), 0),
                ]

        device = BackbuttonsEvdev(
            vid=[],
            pid=[],
        )
        device.dev = Device()
        device.fd = 1

        with patch("hhd.device.gpd.win.base.can_read", side_effect=[True, False]):
            events = device.produce([1])

        self.assertEqual(
            events,
            [
                {"type": "button", "code": "share", "value": True},
                {"type": "button", "code": "share", "value": False},
            ],
        )

    def test_win5_hides_only_controller_l4r4_setting(self):
        dconf = GPD_CONFS["G1618-05"]

        controller_children = GpdWinControllersPlugin(
            "G1618-05", dconf
        ).settings()["controllers"]["gpd_win"]["children"]
        wincontrols_children = GpdWinControlsPlugin(
            "G1618-05", dconf
        ).settings()["wincontrols"]["wincontrols"]["children"]

        self.assertNotIn("l4r4", controller_children)
        self.assertIn("l4r4", wincontrols_children)

    def test_other_gpd_devices_keep_controller_l4r4_setting(self):
        children = GpdWinControllersPlugin(
            "G1618-04", GPD_CONFS["G1618-04"]
        ).settings()["controllers"]["gpd_win"]["children"]

        self.assertIn("l4r4", children)
        self.assertEqual(children["l4r4"]["default"], "menu")

    def test_win5_bypasses_l4r4_fixes(self):
        dconf = GPD_CONFS["G1618-05"]

        self.assertFalse(dconf["manage_l4r4"])
        self.assertTrue(dconf["dedicated_hhd_button"])

    def test_win5_f13_uses_hhd_and_keyboard_opens_steam_qam(self):
        now = [100.0]

        with patch(
            "hhd.controller.base.time.perf_counter", side_effect=lambda: now[0]
        ):
            hhd_emit = RecordingEmitter()
            hhd_mux = Multiplexer(
                share_to_qam=True,
                keyboard_is="qam",
                qam_hhd=True,
                emit=hhd_emit,
            )
            hhd_mux.process([{"type": "button", "code": "share", "value": True}])
            now[0] += 0.01
            hhd_mux.process(
                [{"type": "button", "code": "share", "value": False}]
            )
            now[0] += 0.21
            hhd_mux.process([])

            keyboard_emit = RecordingEmitter()
            keyboard_mux = Multiplexer(
                share_to_qam=True,
                keyboard_is="steam_qam",
                qam_hhd=True,
                emit=keyboard_emit,
            )
            keyboard_mux.process(
                [{"type": "button", "code": "keyboard", "value": True}]
            )
            now[0] += 0.01
            keyboard_mux.process(
                [{"type": "button", "code": "keyboard", "value": False}]
            )

        self.assertIn(
            {"type": "special", "event": "qam_double"}, hhd_emit.events
        )
        self.assertEqual(keyboard_emit.qam_calls, [False])
        self.assertEqual(keyboard_emit.events, [])


if __name__ == "__main__":
    unittest.main()
