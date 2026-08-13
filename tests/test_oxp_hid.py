import unittest

from hhd.controller.physical.evdev import B
from hhd.device.oxp.base import X1_MINI_PID, X1_MINI_VID, get_keyboard
from hhd.device.oxp.const import CONFS
from hhd.device.oxp.hid_v1 import INITIALIZE, INITIALIZE_X2


class OxpX2HidTest(unittest.TestCase):
    def test_x2_uses_x2_protocol(self):
        self.assertEqual(
            CONFS["ONEXPLAYER X2Mini PRO"]["protocol"],
            "hid_v2_x2",
        )

    def test_x2_maps_m1_and_m2_to_f15_and_f16(self):
        self.assertEqual(INITIALIZE_X2[1][50:56], bytes.fromhex("220201680000"))
        self.assertEqual(INITIALIZE_X2[1][56:62], bytes.fromhex("230201690000"))

        self.assertEqual(INITIALIZE[1][50:56], bytes.fromhex("220200000000"))
        self.assertEqual(INITIALIZE[1][56:62], bytes.fromhex("230200000000"))

    def test_x2_keyboard_is_grabbed_and_maps_f_keys(self):
        keyboard = get_keyboard("hid_v2_x2", True)

        self.assertEqual(keyboard.vid, [X1_MINI_VID])
        self.assertEqual(keyboard.pid, [X1_MINI_PID])
        self.assertTrue(keyboard.grab)
        self.assertEqual(keyboard.capabilities, {B("EV_KEY"): [B("KEY_O")]})
        self.assertEqual(keyboard.btn_map[B("KEY_F15")], "extra_l1")
        self.assertEqual(keyboard.btn_map[B("KEY_F16")], "extra_r1")

    def test_x2_nonturbo_mapping_keeps_back_buttons(self):
        keyboard = get_keyboard("hid_v2_x2", False)

        self.assertNotIn(B("KEY_LEFTALT"), keyboard.btn_map)
        self.assertEqual(keyboard.btn_map[B("KEY_F15")], "extra_l1")
        self.assertEqual(keyboard.btn_map[B("KEY_F16")], "extra_r1")


if __name__ == "__main__":
    unittest.main()
