import unittest
from unittest.mock import patch

from hhd.device.oxp.base import OxpAtKbd
from hhd.device.oxp.const import (
    BTN_MAPPINGS,
    CONFS,
    get_default_config,
)
from hhd.device.oxp.hid_v1 import (
    gen_rgb_mode as gen_hid1_rgb_mode,
)
from hhd.device.oxp.hid_v1 import (
    gen_rgb_solid as gen_hid1_rgb_solid,
)
from hhd.device.oxp.hid_v1 import (
    gen_vibration,
)
from hhd.device.oxp.hid_v2 import (
    gen_rgb_mode as gen_hid2_rgb_mode,
)
from hhd.device.oxp.hid_v2 import (
    gen_rgb_solid as gen_hid2_rgb_solid,
)
from hhd.device.oxp.serial import (
    gen_brightness as gen_serial_brightness,
)
from hhd.device.oxp.serial import (
    gen_cmd as gen_serial_cmd,
)
from hhd.device.oxp.serial import (
    gen_rgb_mode as gen_serial_rgb_mode,
)
from hhd.device.oxp.serial import (
    gen_rgb_solid as gen_serial_rgb_solid,
)


class OxpDeviceConfigTest(unittest.TestCase):
    def test_superx_and_apex_registered(self):
        self.assertIn("ONEXPLAYER SUPER X", CONFS)
        self.assertIn("ONEXPLAYER APEX", CONFS)
        superx = CONFS["ONEXPLAYER SUPER X"]
        self.assertEqual(superx["name"], "ONEXPLAYER SUPER X")
        self.assertEqual(superx["protocol"], "mixed")
        self.assertTrue(superx["hrtimer"])

    def test_default_config_fallback(self):
        conf = get_default_config("ONEXPLAYER SUPER X 2", "ONEXPLAYER")
        self.assertEqual(conf["name"], "ONEXPLAYER SUPER X 2")
        self.assertTrue(conf["untested"])
        self.assertTrue(conf["hrtimer"])


class OxpAtKbdMacroTest(unittest.TestCase):
    def test_turbo_macro_combination_emits_mode(self):
        kbd = OxpAtKbd(
            vid=[0x0001],
            pid=[0x0001],
            required=False,
            grab=False,
            btn_map=BTN_MAPPINGS,
        )
        # Simulate pressing Left Ctrl, Left Meta, and Left Alt together
        kbd.state["key_leftctrl"] = 1.0
        kbd.state["key_leftmeta"] = 1.0
        kbd.state["key_leftalt"] = 1.0

        with patch("hhd.device.oxp.base.GenericGamepadEvdev.produce", return_value=[]):
            evs = kbd.produce([])

        # Should consume the individual modifiers and emit a mode button press
        self.assertNotIn("key_leftctrl", kbd.state)
        self.assertNotIn("key_leftmeta", kbd.state)
        self.assertNotIn("key_leftalt", kbd.state)

        button_evs = [e for e in evs if e["type"] == "button" and e["value"] is True]
        self.assertTrue(any(e["code"] == "mode" for e in button_evs))


class OxpSerialProtocolTest(unittest.TestCase):
    def test_gen_cmd_framing(self):
        cmd = gen_serial_cmd(0xFD, [0x00, 0x01], size=64)
        self.assertEqual(len(cmd), 64)
        self.assertEqual(cmd[0], 0xFD)
        self.assertEqual(cmd[1], 0x3F)
        self.assertEqual(cmd[2], 0x00)
        self.assertEqual(cmd[3], 0x01)
        self.assertEqual(cmd[-2], 0x3F)
        self.assertEqual(cmd[-1], 0xFD)

    def test_gen_rgb_mode(self):
        cmd = gen_serial_rgb_mode("flowing")
        self.assertEqual(cmd[0], 0xFD)
        self.assertEqual(cmd[3], 0x03)

    def test_gen_rgb_solid(self):
        cmd = gen_serial_rgb_solid(255, 128, 64, side=0x00)
        self.assertEqual(cmd[0], 0xFD)
        self.assertEqual(cmd[2], 0x00)
        self.assertEqual(cmd[3], 0xFE)
        self.assertEqual(cmd[6], 255)
        self.assertEqual(cmd[7], 128)
        self.assertEqual(cmd[8], 64)

    def test_gen_brightness(self):
        cmd = gen_serial_brightness(0, True, "high")
        self.assertEqual(cmd[0], 0xFD)
        self.assertEqual(cmd[6], 1)
        self.assertEqual(cmd[8], 0x04)


class OxpHidProtocolsTest(unittest.TestCase):
    def test_hid_v1_rgb_mode(self):
        cmd = gen_hid1_rgb_mode("sunset")
        self.assertEqual(cmd[0], 0xB8)
        self.assertEqual(cmd[1], 0x3F)
        self.assertEqual(cmd[3], 0x0B)

    def test_hid_v1_rgb_solid(self):
        cmd = gen_hid1_rgb_solid(10, 20, 30, side=0x00)
        self.assertEqual(cmd[0], 0xB8)
        self.assertEqual(cmd[3], 0xFE)
        self.assertEqual(cmd[6], 10)
        self.assertEqual(cmd[7], 20)
        self.assertEqual(cmd[8], 30)

    def test_hid_v1_vibration(self):
        cmd = gen_vibration(5)
        self.assertEqual(cmd[0], 0xB3)
        self.assertEqual(cmd[1], 0x3F)

    def test_hid_v2_rgb_mode(self):
        cmd = gen_hid2_rgb_mode("neon")
        self.assertEqual(cmd[0], 0x07)
        self.assertEqual(cmd[1], 0xFF)
        self.assertEqual(cmd[2], 0x05)

    def test_hid_v2_rgb_solid(self):
        cmd = gen_hid2_rgb_solid(100, 150, 200)
        self.assertEqual(cmd[0], 0x07)
        self.assertEqual(cmd[1], 0xFF)
        self.assertEqual(cmd[2], 0xFE)
        self.assertEqual(cmd[3], 100)
        self.assertEqual(cmd[4], 150)
        self.assertEqual(cmd[5], 200)


if __name__ == "__main__":
    unittest.main()
