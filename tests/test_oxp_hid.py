import unittest
from unittest.mock import Mock, patch

from hhd.controller.physical.evdev import B
from hhd.device.oxp.base import (
    RGB_MODES_FULL,
    RGB_MODES_FULL_BREATHING,
)
from hhd.device.oxp.const import (
    BTN_MAPPINGS,
    BTN_MAPPINGS_NONTURBO,
    BTN_MAPPINGS_NONTURBO_X2,
    BTN_MAPPINGS_X2,
    CONFS,
)
from hhd.device.oxp import hid_v1
from hhd.device.oxp.hid_v1 import INITIALIZE, INITIALIZE_X2


class OxpX2HidTest(unittest.TestCase):
    def test_apex_swaps_hid_back_buttons(self):
        for quirk in (None, "apex"):
            with self.subTest(quirk=quirk):
                device = hid_v1.OxpHidraw(quirk=quirk, vibration=None)
                device.fd = 42
                device.dev = Mock()
                reports = []
                expected = []
                codes = ("extra_r1", "extra_l1") if quirk == "apex" else ("extra_l1", "extra_r1")
                for button, code in zip((0x22, 0x23), codes):
                    for state in (1, 2):
                        report = bytearray(64)
                        report[0:2] = b"\xb2\x3f"
                        report[-2:] = b"\x3f\xb2"
                        report[6] = button
                        report[12] = state
                        reports.append(bytes(report))
                        expected.append({"type": "button", "code": code, "value": state == 1})
                device.dev.read.side_effect = reports
                with patch.object(hid_v1, "can_read", side_effect=[True] * 4 + [False]):
                    self.assertEqual(device.produce([42]), expected)

    def test_oxp3_home_reports_mode_press_and_release(self):
        press = bytes.fromhex(
            "b23f01011f8024020205000001000000000000000000000000000000000000000000"
            "0000000000000000000000000000000000000000000000000000000000003fb2"
        )
        release = bytearray(press)
        release[12] = 2
        for turbo in (False, True):
            with self.subTest(turbo=turbo):
                device = hid_v1.OxpHidraw(quirk="oxp3", turbo=turbo, vibration=None)
                device.fd = 42
                device.dev = Mock()
                device.dev.read.side_effect = [press, press, bytes(release)]
                with patch.object(hid_v1, "can_read", side_effect=[True, True, True, False]):
                    self.assertEqual(device.produce([42]), [
                        {"type": "button", "code": "mode", "value": True},
                        {"type": "button", "code": "mode", "value": False},
                    ])
                self.assertIsNone(device.queue_kbd)
                self.assertEqual(device.produce([]), [])

    def setUp(self):
        self.init_done = hid_v1._init_done
        self.init_vibration = hid_v1._init_vibration
        hid_v1._init_done = False
        hid_v1._init_vibration = None

    def tearDown(self):
        hid_v1._init_done = self.init_done
        hid_v1._init_vibration = self.init_vibration

    def test_x2_uses_x2_protocol(self):
        conf = CONFS["ONEXPLAYER X2Mini PRO"]

        self.assertEqual(conf["protocol"], "hid_v2_x2")
        self.assertTrue(conf["rgb_secondary_breathing"])
        self.assertNotIn("oxp-secondary-breathing", RGB_MODES_FULL["oxp"])
        self.assertIn("oxp-secondary-breathing", RGB_MODES_FULL_BREATHING["oxp"])

    @staticmethod
    def led_event(
        primary=(1, 2, 3),
        secondary=(40, 50, 60),
        breathing=False,
        brightness="medium",
        initialize=True,
        mode="solid",
    ):
        return {
            "type": "led",
            "initialize": initialize,
            "code": "main",
            "mode": mode,
            "direction": "left",
            "brightness": 1,
            "brightnessd": brightness,
            "speed": 1,
            "speedd": "high",
            "red": primary[0],
            "green": primary[1],
            "blue": primary[2],
            "red2": secondary[0],
            "green2": secondary[1],
            "blue2": secondary[2],
            "oxp": "classic" if mode == "oxp" else None,
            "secondary_breathing": breathing,
        }

    def test_x2_rgb_zone_mapping_matches_windows_capture(self):
        device = hid_v1.OxpHidraw(
            x2=True,
            secondary=True,
            secondary_breathing=True,
            vibration=None,
        )
        device.dev = object()

        device.consume([self.led_event()])
        self.assertEqual(
            [(cmd[3], cmd[4]) for cmd in device.queue_cmd],
            [(0xFD, 0x05), (0xFD, 0x06), (0xFE, 0x05), (0xFE, 0x06)],
        )

        device.queue_cmd.clear()
        device.consume(
            [self.led_event(primary=(7, 8, 9), initialize=False)]
        )
        self.assertEqual(
            [(cmd[3], cmd[4]) for cmd in device.queue_cmd],
            [(0xFE, 0x01), (0xFE, 0x02), (0xFE, 0x07)],
        )

    def test_x2_secondary_breathing_uses_f0_and_can_be_toggled(self):
        device = hid_v1.OxpHidraw(
            x2=True,
            secondary=True,
            secondary_breathing=True,
            vibration=None,
        )
        device.dev = object()

        device.consume([self.led_event(breathing=True)])
        self.assertEqual(
            [(cmd[3], cmd[4]) for cmd in device.queue_cmd],
            [(0xFD, 0x05), (0xFD, 0x06), (0xF0, 0x05), (0xF0, 0x06)],
        )

        device.queue_cmd.clear()
        device.consume([self.led_event(breathing=False)])
        self.assertEqual(
            [(cmd[3], cmd[4]) for cmd in device.queue_cmd],
            [(0xFE, 0x05), (0xFE, 0x06)],
        )

    def test_x2_secondary_slider_updates_without_initialize(self):
        device = hid_v1.OxpHidraw(x2=True, secondary=True, vibration=None)
        device.dev = object()
        device.consume([self.led_event()])
        device.queue_cmd.clear()

        device.consume(
            [
                self.led_event(
                    secondary=(70, 80, 90),
                    initialize=False,
                    mode="duality",
                )
            ]
        )

        self.assertEqual(
            [(cmd[3], cmd[4]) for cmd in device.queue_cmd],
            [(0xFE, 0x05), (0xFE, 0x06)],
        )

    def test_existing_secondary_passthrough_remains_init_only(self):
        device = hid_v1.OxpHidraw(secondary=True, vibration=None)
        device.dev = object()
        device.consume([self.led_event()])
        device.queue_cmd.clear()

        changed = self.led_event(
            secondary=(70, 80, 90),
            initialize=False,
            mode="duality",
        )
        device.consume([changed])
        self.assertEqual(list(device.queue_cmd), [])

        changed["initialize"] = True
        device.consume([changed])
        self.assertEqual(
            [(cmd[3], cmd[4]) for cmd in device.queue_cmd],
            [(0xFE, 0x03), (0xFE, 0x04)],
        )

    def test_x2_secondary_zones_follow_brightness(self):
        device = hid_v1.OxpHidraw(x2=True, secondary=True, vibration=None)
        device.dev = object()

        device.consume([self.led_event(mode="oxp")])
        brightness = [cmd for cmd in device.queue_cmd if cmd[3] == 0xFD]
        self.assertEqual([(cmd[4], cmd[8]) for cmd in brightness], [(5, 3), (6, 3)])

        device.queue_cmd.clear()
        device.consume([self.led_event(mode="oxp", brightness="low")])
        brightness = [cmd for cmd in device.queue_cmd if cmd[3] == 0xFD]
        self.assertEqual(
            [(cmd[4], cmd[8]) for cmd in brightness],
            [(1, 1), (2, 1), (7, 1), (5, 1), (6, 1)],
        )

    def test_existing_secondary_zones_remain_at_high_brightness(self):
        device = hid_v1.OxpHidraw(secondary=True, vibration=None)
        device.dev = object()

        device.consume([self.led_event(mode="oxp")])
        brightness = [cmd for cmd in device.queue_cmd if cmd[3] == 0xFD]
        self.assertEqual([(cmd[4], cmd[8]) for cmd in brightness], [(3, 4), (4, 4)])

        device.queue_cmd.clear()
        device.consume([self.led_event(mode="oxp", brightness="low")])
        brightness = [cmd for cmd in device.queue_cmd if cmd[3] == 0xFD]
        self.assertEqual([(cmd[4], cmd[8]) for cmd in brightness], [(0, 1)])

    def test_secondary_breathing_defaults_to_disabled(self):
        device = hid_v1.OxpHidraw(x2=True, secondary=True, vibration=None)
        device.dev = object()

        device.consume([self.led_event(breathing=True)])
        self.assertEqual(
            [(cmd[3], cmd[4]) for cmd in device.queue_cmd],
            [(0xFD, 0x05), (0xFD, 0x06), (0xFE, 0x05), (0xFE, 0x06)],
        )

    def test_x2_maps_m1_and_m2_to_f15_and_f16(self):
        self.assertEqual(INITIALIZE_X2[0][3:8], bytes.fromhex("0238020101"))
        self.assertEqual(INITIALIZE_X2[1][3:8], bytes.fromhex("0238020201"))
        self.assertEqual(INITIALIZE_X2[1][50:56], bytes.fromhex("220201680000"))
        self.assertEqual(INITIALIZE_X2[1][56:62], bytes.fromhex("230201690000"))
        self.assertEqual(INITIALIZE_X2[2][3:8], bytes.fromhex("0238020301"))
        self.assertEqual(INITIALIZE_X2[2][8:14], bytes.fromhex("240202050000"))
        self.assertEqual(INITIALIZE_X2[2][14:20], bytes.fromhex("250121000000"))
        self.assertEqual(INITIALIZE_X2[3], hid_v1.gen_intercept(False))

        self.assertEqual(INITIALIZE[0][3:8], bytes.fromhex("0238020101"))
        self.assertEqual(INITIALIZE[1][3:8], bytes.fromhex("0238020201"))
        self.assertEqual(INITIALIZE[1][50:56], bytes.fromhex("220200000000"))
        self.assertEqual(INITIALIZE[1][56:62], bytes.fromhex("230200000000"))

    def test_x2_keyboard_maps_f_keys(self):
        self.assertEqual(BTN_MAPPINGS_X2[B("KEY_G")], "mode")
        self.assertEqual(BTN_MAPPINGS_NONTURBO_X2[B("KEY_G")], "mode")
        self.assertEqual(BTN_MAPPINGS_X2[B("KEY_F15")], "extra_l1")
        self.assertEqual(BTN_MAPPINGS_X2[B("KEY_F16")], "extra_r1")

    def test_at_keyboard_keeps_volume_buttons(self):
        for mappings in (BTN_MAPPINGS, BTN_MAPPINGS_NONTURBO):
            self.assertEqual(mappings[B("KEY_VOLUMEUP")], "key_volumeup")
            self.assertEqual(mappings[B("KEY_VOLUMEDOWN")], "key_volumedown")

    def test_x2_nonturbo_mapping_keeps_back_buttons(self):
        self.assertNotIn(B("KEY_LEFTALT"), BTN_MAPPINGS_NONTURBO_X2)
        self.assertEqual(BTN_MAPPINGS_NONTURBO_X2[B("KEY_F15")], "extra_l1")
        self.assertEqual(BTN_MAPPINGS_NONTURBO_X2[B("KEY_F16")], "extra_r1")

    def test_interrupted_x2_initialization_is_retried(self):
        def open_device():
            device = hid_v1.OxpHidraw(x2=True, vibration=None)
            with (
                patch.object(hid_v1.GenericGamepadHidraw, "open", return_value=[]),
                patch.object(hid_v1.time, "perf_counter", return_value=0),
            ):
                device.open()
            return device

        first = open_device()
        self.assertEqual(list(first.queue_cmd), INITIALIZE_X2)
        self.assertFalse(hid_v1._init_done)

        # Simulate startup aborting before the queued mappings reach the device.
        retry = open_device()
        self.assertEqual(list(retry.queue_cmd), INITIALIZE_X2)

        class FakeDevice:
            def write(self, cmd):
                pass

        retry.dev = FakeDevice()
        for i in range(len(INITIALIZE_X2)):
            retry.next_send = 0
            with patch.object(hid_v1.time, "perf_counter", return_value=1):
                retry.consume([])
            self.assertEqual(hid_v1._init_done, i == len(INITIALIZE_X2) - 1)

        reopened = open_device()
        self.assertEqual(list(reopened.queue_cmd), [hid_v1.gen_intercept(False)])


if __name__ == "__main__":
    unittest.main()
