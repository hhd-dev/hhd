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


def make_conf(dock_running: bool, enforce_limits: bool = True) -> Config:
    conf = Config(
        {
            "hhd.settings.tdp_ready": True,
            "hhd.settings.enforce_limits": enforce_limits,
            "cooling_dock.dock_running": dock_running,
            "tdp.qam.tdp": 75,
            "tdp.qam.boost": False,
            "tdp.qam.fan.mode": "disabled",
        }
    )
    return conf


def make_driver_conf(dock_running: bool, tdp: int = 120, apply: bool = False) -> Config:
    conf = Config(
        {
            "hhd.settings.tdp_ready": True,
            "hhd.settings.enforce_limits": True,
            "cooling_dock.dock_running": dock_running,
            "tdp.smu.std": {
                "stapm_limit": tdp,
                "skin_limit": tdp,
                "slow_limit": tdp,
                "fast_limit": tdp,
                "slow_time": 10,
                "stapm_time": 200,
            },
            "tdp.smu.adv": {"enable": False},
            "tdp.smu.apply": apply,
            "tdp.smu.platform_profile": "disabled",
            "tdp.smu.energy_policy": "balanced",
        }
    )
    return conf


class SmuQamDockTest(unittest.TestCase):
    def setUp(self):
        self.p = SmuQamPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ENERGY_MAP_OXP_SUPERX,
            dock_aware=True,
            dc_cap=DC_CAP_OXP_SUPERX,
        )
        self.p.enabled = True
        self.p.settings()

    def test_no_dock_enforces_safe_limits(self):
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            self.p.open(None, None)
        self.p.update(make_conf(dock_running=False))
        self.assertTrue(self.p.enforce_limits)

    def test_dock_running_relaxes_limits(self):
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            self.p.open(None, None)
        self.p.update(make_conf(dock_running=True))
        self.assertFalse(self.p.enforce_limits)

    def test_dock_disconnect_re_enforces_and_clamps(self):
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            self.p.open(None, None)
        # Dock running: relaxed, user sets 120W
        conf = make_conf(dock_running=True)
        conf["tdp.qam.tdp"] = 120
        self.p.update(conf)
        self.assertFalse(self.p.enforce_limits)

        # Dock disconnects: enforced again, 120W clamped to 75W
        conf2 = make_conf(dock_running=False)
        conf2["tdp.qam.tdp"] = 120
        self.p.update(conf2)
        self.assertTrue(self.p.enforce_limits)
        self.assertEqual(conf2["tdp.qam.tdp"].to(int), 75)

    def test_user_enforce_off_overrides_dock(self):
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            self.p.open(None, None)
        # User disabled enforce_limits entirely: unlocked regardless of dock
        self.p.update(make_conf(dock_running=False, enforce_limits=False))
        self.assertFalse(self.p.enforce_limits)


class SmuQamBatteryTest(unittest.TestCase):
    """Tests for AC/DC power-aware TDP capping."""

    def setUp(self):
        self.p = SmuQamPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ENERGY_MAP_OXP_SUPERX,
            dock_aware=True,
            dc_cap=DC_CAP_OXP_SUPERX,
        )
        self.p.enabled = True
        self.p.settings()
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            self.p.open(None, None)

    def test_battery_clamps_to_55w(self):
        """On battery, TDP should be clamped to DC cap (55W), not AC cap (75W)."""
        self.p.on_ac = False
        conf = make_conf(dock_running=False)
        conf["tdp.qam.tdp"] = 75
        self.p.update(conf)
        self.assertEqual(conf["tdp.qam.tdp"].to(int), 55)

    def test_ac_allows_75w(self):
        """On AC without dock, TDP should be allowed up to 75W."""
        self.p.on_ac = True
        conf = make_conf(dock_running=False)
        conf["tdp.qam.tdp"] = 75
        self.p.update(conf)
        self.assertEqual(conf["tdp.qam.tdp"].to(int), 75)

    def test_ac_to_battery_transition_clamps(self):
        """Unplugging AC should immediately clamp TDP from 75W to 55W."""
        self.p.on_ac = True
        conf = make_conf(dock_running=False)
        conf["tdp.qam.tdp"] = 75
        self.p.update(conf)
        self.assertEqual(conf["tdp.qam.tdp"].to(int), 75)

        # Simulate AC -> DC event
        self.p.notify([{"type": "acpi", "event": "dc"}])
        self.assertFalse(self.p.on_ac)

        # Next update should clamp
        conf2 = make_conf(dock_running=False)
        conf2["tdp.qam.tdp"] = 75
        self.p.update(conf2)
        self.assertEqual(conf2["tdp.qam.tdp"].to(int), 55)

    def test_battery_to_ac_transition_does_not_increase(self):
        """Plugging in AC should not auto-increase TDP, just relax the cap."""
        self.p.on_ac = False
        conf = make_conf(dock_running=False)
        conf["tdp.qam.tdp"] = 50
        self.p.update(conf)
        # 50W is within both DC and AC range, should stay
        self.assertEqual(conf["tdp.qam.tdp"].to(int), 50)

        # AC event
        self.p.notify([{"type": "acpi", "event": "ac"}])
        conf2 = make_conf(dock_running=False)
        conf2["tdp.qam.tdp"] = 50
        self.p.update(conf2)
        # Should still be 50W (not auto-bumped)
        self.assertEqual(conf2["tdp.qam.tdp"].to(int), 50)

    def test_battery_with_dock_still_limited_to_55w(self):
        """On battery, even with dock running, TDP should not exceed DC cap.

        The dock running flag only relaxes enforce_limits when on AC power.
        On battery (on_ac=False), limits must always remain enforced (55W)
        to protect the battery from unsafe discharge currents."""
        self.p.on_ac = False
        conf = make_conf(dock_running=True)
        conf["tdp.qam.tdp"] = 120
        self.p.update(conf)
        self.assertTrue(self.p.enforce_limits)
        self.assertEqual(conf["tdp.qam.tdp"].to(int), 55)

    def test_status_message_on_battery(self):
        """Status message should indicate battery-limited TDP."""
        self.p.on_ac = False
        conf = make_conf(dock_running=False)
        conf["tdp.qam.tdp"] = 50
        self.p.update(conf)
        msg = conf["tdp.qam.sys_tdp"].to(str)
        self.assertIn("battery", msg)
        self.assertIn("55", msg)

    def test_status_message_dock_not_connected(self):
        """On AC without dock, show dock-not-connected message."""
        self.p.on_ac = True
        conf = make_conf(dock_running=False)
        conf["tdp.qam.tdp"] = 50
        self.p.update(conf)
        msg = conf["tdp.qam.sys_tdp"].to(str)
        self.assertIn("dock", msg.lower())
        self.assertIn("75", msg)

    def test_no_dc_cap_ignores_battery(self):
        """Without dc_cap (non-OXP devices), battery state has no effect."""
        p = SmuQamPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ENERGY_MAP_OXP_SUPERX,
            dock_aware=False,
            dc_cap=None,
        )
        p.enabled = True
        p.settings()
        with patch("adjustor.drivers.smu.get_fan_info", return_value=None):
            p.open(None, None)

        p.on_ac = False
        conf = make_conf(dock_running=False)
        conf["tdp.qam.tdp"] = 75
        p.update(conf)
        # Without dc_cap, 75W should still be allowed (smax=75)
        self.assertEqual(conf["tdp.qam.tdp"].to(int), 75)


class SmuDriverDockTest(unittest.TestCase):
    def make_plugin(self, dock_aware: bool = True) -> SmuDriverPlugin:
        p = SmuDriverPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ALIB_PARAMS_AIMAX,
            dock_aware=dock_aware,
            dc_cap=DC_CAP_OXP_SUPERX if dock_aware else None,
        )
        p.enabled = True
        p.initialized = True
        p.has_pp = False
        p.emit = lambda *args, **kwargs: None
        return p

    def test_driver_dock_disconnect_forces_apply_with_clamped_values(self):
        with patch("adjustor.drivers.smu.alib") as mock_alib:
            p = self.make_plugin(dock_aware=True)

            # Dock running: relaxed, first update forces an apply (startup)
            conf = make_driver_conf(dock_running=True, tdp=120)
            p.update(conf)
            self.assertFalse(p.enforce_limits)
            mock_alib.assert_called_once()
            mock_alib.reset_mock()

            # Dock disconnects: enforced, dock_changed forces immediate apply
            # with the values clamped to the safe (smax) range.
            conf2 = make_driver_conf(dock_running=False, tdp=120)
            p.update(conf2)
            self.assertTrue(p.enforce_limits)
            mock_alib.assert_called_once()
            args = mock_alib.call_args
            self.assertEqual(args.kwargs["limit"], "device")
            self.assertEqual(args.args[0]["stapm_limit"], 75)
            self.assertEqual(args.args[0]["skin_limit"], 75)
            self.assertEqual(args.args[0]["slow_limit"], 80)
            self.assertEqual(args.args[0]["fast_limit"], 95)

    def test_driver_no_forced_apply_without_dock_change(self):
        with patch("adjustor.drivers.smu.alib") as mock_alib:
            p = self.make_plugin(dock_aware=False)

            # No dock, enforce_limits stays True (matches old_enforce init):
            # no spurious apply on the first cycle.
            conf = make_driver_conf(dock_running=False, tdp=75, apply=False)
            p.update(conf)
            self.assertTrue(p.enforce_limits)
            mock_alib.assert_not_called()

    def test_driver_battery_clamps_to_dc_cap(self):
        """On battery, SmuDriverPlugin should clamp values to DC cap."""
        with patch("adjustor.drivers.smu.alib") as mock_alib:
            p = self.make_plugin(dock_aware=True)
            p.on_ac = False

            conf = make_driver_conf(dock_running=False, tdp=75, apply=True)
            p.update(conf)
            # Values should be clamped to DC cap
            mock_alib.assert_called_once()
            vals = mock_alib.call_args.args[0]
            self.assertLessEqual(vals["stapm_limit"], 55)
            self.assertLessEqual(vals["skin_limit"], 55)
            self.assertLessEqual(vals["fast_limit"], 70)

    def test_driver_ac_dc_event_updates_on_ac(self):
        """notify() should update on_ac state."""
        p = self.make_plugin(dock_aware=True)
        self.assertTrue(p.on_ac)

        p.notify([{"type": "acpi", "event": "dc"}])
        self.assertFalse(p.on_ac)

        p.notify([{"type": "acpi", "event": "ac"}])
        self.assertTrue(p.on_ac)


class SmuQamSettingsTest(unittest.TestCase):
    def test_dock_aware_dynamically_adjusts_range(self):
        p = SmuQamPlugin(
            DEV_PARAMS_OXP_SUPERX,
            ENERGY_MAP_OXP_SUPERX,
            dock_aware=True,
            dc_cap=DC_CAP_OXP_SUPERX,
        )
        p.enabled = True
        
        # When enforcing limits (dock disconnected), exposes safe range (75W)
        p.enforce_limits = True
        p.on_ac = True
        s = p.settings()
        tdp = s["tdp"]["qam"]["children"]["tdp"]
        self.assertEqual(tdp["min"], 4)
        self.assertEqual(tdp["max"], 75)

        # When on battery and enforcing limits, exposes DC cap (55W)
        p.on_ac = False
        s = p.settings()
        tdp = s["tdp"]["qam"]["children"]["tdp"]
        self.assertEqual(tdp["max"], 55)

        # When NOT enforcing limits (dock connected), exposes full dmax (120W)
        p.enforce_limits = False
        p.on_ac = True
        s = p.settings()
        tdp = s["tdp"]["qam"]["children"]["tdp"]
        self.assertEqual(tdp["min"], 0)
        self.assertEqual(tdp["max"], 120)


if __name__ == "__main__":
    unittest.main()