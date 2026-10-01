import unittest
from unittest.mock import patch

from hhd.plugins.cooling_dock.base import (
    fan_pct_for_temp,
    get_cpu_temp,
)
from hhd.plugins.cooling_dock.protocol import (
    WRITE_CMD,
    CoolingStatus,
    DockMode,
)


class CoolingStatusProtocolTest(unittest.TestCase):
    def test_from_bytes_short_raises_value_error(self):
        with self.assertRaises(ValueError):
            CoolingStatus.from_bytes(b"\x00" * 40)

    def test_from_bytes_full_parsing(self):
        raw = bytearray(64)
        raw[0] = 0xC1
        raw[1] = 0x10
        raw[2] = 6  # version
        raw[4] = int(DockMode.LEVEL_3)
        raw[5] = 75  # fan %
        raw[6] = 0x08  # fan speed rpm hi
        raw[7] = 0xD0  # fan speed rpm lo = 2256
        raw[8] = 50  # pump %
        raw[9] = 0x06
        raw[10] = 0x30  # pump rpm = 1584
        raw[11] = 0x01
        raw[12] = 0xF4  # water flow = 500
        raw[13] = 25  # in temp
        raw[14] = 28  # out temp
        raw[15] = 0x01  # status flag
        raw[16] = 0x02  # rgb mode
        raw[17] = 0x01  # rgb enable
        raw[19] = 0x04  # rgb level
        raw[20] = 255  # r
        raw[21] = 87   # g
        raw[22] = 34   # b
        # 9 curve pairs (fan%, temp)
        for i in range(9):
            raw[23 + i * 2] = 10 * (i + 1)
            raw[23 + i * 2 + 1] = 30 + 5 * i

        status = CoolingStatus.from_bytes(raw)
        self.assertEqual(status.version, 6)
        self.assertEqual(status.mode, int(DockMode.LEVEL_3))
        self.assertEqual(status.fan_speed_percent, 75)
        self.assertEqual(status.fan_speed, 2256)
        self.assertEqual(status.pump_speed_percent, 50)
        self.assertEqual(status.pump_speed, 1584)
        self.assertEqual(status.water_flow, 500)
        self.assertEqual(status.in_water_temp, 25)
        self.assertEqual(status.out_water_temp, 28)
        self.assertEqual(status.rgb_mode, 2)
        self.assertTrue(status.rgb_enable)
        self.assertEqual(status.rgb_light_level, 4)
        self.assertEqual((status.rgb_r, status.rgb_g, status.rgb_b), (255, 87, 34))
        self.assertEqual(len(status.fan_curve), 9)
        self.assertEqual(status.fan_curve[0], (10, 30))

    def test_to_write_bytes_preserves_readonly_fields(self):
        current = bytearray(64)
        current[2] = 5
        current[5] = 80  # dock reports 80% fan
        current[8] = 60  # dock reports 60% pump
        current[14] = 35

        status = CoolingStatus(
            version=5,
            mode=int(DockMode.AUTO),
            rgb_enable=True,
            rgb_mode=1,
            rgb_light_level=3,
        )
        out = status.to_write_bytes(current)
        self.assertEqual(out[1], WRITE_CMD)
        self.assertEqual(out[4], int(DockMode.AUTO))
        # Read-only fields must NOT be overwritten
        self.assertEqual(out[5], 80)
        self.assertEqual(out[8], 60)
        self.assertEqual(out[14], 35)


class FanCurveCalculationTest(unittest.TestCase):
    def test_fan_pct_interpolation(self):
        curve = [(0, 40), (30, 50), (50, 60), (70, 70), (85, 80)]
        self.assertEqual(fan_pct_for_temp(35, curve), 0)
        self.assertEqual(fan_pct_for_temp(40, curve), 0)
        self.assertEqual(fan_pct_for_temp(45, curve), 15)  # halfway between 0 and 30
        self.assertEqual(fan_pct_for_temp(50, curve), 30)
        self.assertEqual(fan_pct_for_temp(65, curve), 60)  # halfway between 50 and 70
        self.assertEqual(fan_pct_for_temp(80, curve), 85)
        self.assertEqual(fan_pct_for_temp(90, curve), 85)

    def test_empty_curve_returns_zero(self):
        self.assertEqual(fan_pct_for_temp(50, []), 0)


class ExtendedDockPluginTest(unittest.TestCase):
    def test_get_cpu_temp_fallback(self):
        with patch("os.path.exists", return_value=False):
            self.assertEqual(get_cpu_temp(), 0.0)


if __name__ == "__main__":
    unittest.main()
