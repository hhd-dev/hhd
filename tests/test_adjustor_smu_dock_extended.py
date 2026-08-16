import unittest
from unittest.mock import patch

from adjustor.core.const import (
    ALIB_PARAMS_AIMAX,
    DC_CAP_OXP_SUPERX,
    DEV_PARAMS_OXP_SUPERX,
    ENERGY_MAP_OXP_SUPERX,
)
from adjustor.drivers.smu import SmuDriverPlugin, SmuQamPlugin
from hhd.plugins.conf import Config


class SmuStartupAcDetectionTest(unittest.TestCase):
    def test_qam_startup_on_battery_detects_dc(self):
        p = SmuQamPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ENERGY_MAP_OXP_SUPERX,
            dock_aware=True,
            dc_cap=DC_CAP_OXP_SUPERX,
        )
        p.enabled = True
        with (
            patch("hhd.utils.get_ac_status_fn", return_value="/sys/class/power_supply/AC/online"),
            patch("hhd.utils.get_ac_status", return_value=False),
            patch("adjustor.drivers.smu.get_fan_info", return_value=None),
        ):
            p.open(None, None)

        self.assertFalse(p.on_ac)
        s = p.settings()
        tdp = s["tdp"]["qam"]["children"]["tdp"]
        self.assertEqual(tdp["max"], 55)

    def test_driver_startup_on_battery_detects_dc(self):
        p = SmuDriverPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ALIB_PARAMS_AIMAX,
            dock_aware=True,
            dc_cap=DC_CAP_OXP_SUPERX,
        )
        p.enabled = True
        p.initialized = True
        with (
            patch("hhd.utils.get_ac_status_fn", return_value="/sys/class/power_supply/AC/online"),
            patch("hhd.utils.get_ac_status", return_value=False),
        ):
            p.open(None, None)

        self.assertFalse(p.on_ac)


class SmuBoostCalculationTest(unittest.TestCase):
    def test_boost_calculation_scales_accurately_on_ac(self):
        p = SmuQamPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ENERGY_MAP_OXP_SUPERX,
            dock_aware=True,
            dc_cap=DC_CAP_OXP_SUPERX,
        )
        p.enabled = True
        p.on_ac = True
        p.settings()
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            p.open(None, None)

        conf = Config({
            "hhd.settings.tdp_ready": True,
            "hhd.settings.enforce_limits": True,
            "cooling_dock.dock_running": False,
            "tdp.qam.tdp": 75,
            "tdp.qam.boost": True,
            "tdp.qam.fan.mode": "disabled",
        })
        p.update(conf)
        # On AC: fmax=95, smax=75 -> fast_limit = 75 * (95/75) = 95
        self.assertEqual(conf["tdp.smu.std.fast_limit"].to(int), 95)
        # slow_limit = min(75 + 2, 95) = 77
        self.assertEqual(conf["tdp.smu.std.slow_limit"].to(int), 77)

    def test_boost_calculation_scales_accurately_on_battery(self):
        p = SmuQamPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ENERGY_MAP_OXP_SUPERX,
            dock_aware=True,
            dc_cap=DC_CAP_OXP_SUPERX,
        )
        p.enabled = True
        p.on_ac = False
        p.settings()
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            p.open(None, None)

        conf = Config({
            "hhd.settings.tdp_ready": True,
            "hhd.settings.enforce_limits": True,
            "cooling_dock.dock_running": False,
            "tdp.qam.tdp": 55,
            "tdp.qam.boost": True,
            "tdp.qam.fan.mode": "disabled",
        })
        p.update(conf)
        # On Battery: fmax=70, smax=55 -> fast_limit = 55 * (70/55) = 70
        self.assertEqual(conf["tdp.smu.std.fast_limit"].to(int), 70)
        # slow_limit = min(55 + 2, 70) = 57
        self.assertEqual(conf["tdp.smu.std.slow_limit"].to(int), 57)


if __name__ == "__main__":
    unittest.main()
