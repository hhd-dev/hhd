import unittest
from unittest.mock import MagicMock, patch

from adjustor.decky import DeckyPlugin
from adjustor.drivers.unified import FwattrData, PPData, UnifiedDriverPlugin
from hhd.http.steamos import _tdp as steamos_tdp
from hhd.plugins import Config
from hhd.plugins.settings import parse_defaults

PROFILES = PPData(
    fn="lenovo-wmi-gamezone",
    pp="platform-profile-0",
    provider="lenovo-wmi-gamezone",
    has_custom=True,
    profiles=(
        ("low-power", "Quiet"),
        ("balanced", "Balanced"),
        ("performance", "Performance"),
        ("custom", "Custom"),
    ),
)
AC_TDP = FwattrData(
    fn="lenovo-wmi-other-0",
    provider="lenovo-wmi-other",
    pl1=(4, 15, 30),
)
DC_TDP = FwattrData(
    fn="lenovo-wmi-other-0",
    provider="lenovo-wmi-other",
    pl1=(4, 12, 20),
)


def make_plugin(tdp=AC_TDP):
    with (
        patch("adjustor.drivers.unified.get_profiles", return_value=PROFILES),
        patch("adjustor.drivers.unified.get_tdp_values", return_value=tdp),
        patch("adjustor.drivers.unified.get_fwattr", return_value=None),
        patch("adjustor.drivers.unified.get_fan", return_value=None),
    ):
        plugin = UnifiedDriverPlugin()
    plugin.emit = MagicMock()
    return plugin


def initial_config(plugin: UnifiedDriverPlugin, enabled: bool):
    conf = Config(parse_defaults(plugin.settings()))
    conf["tdp.tdp.tdp_enable"] = False
    conf["hhd.settings.tdp_enable"] = enabled
    return conf


class UnifiedInitTest(unittest.TestCase):
    def test_disabled_state_exposes_init_settings(self):
        plugin = make_plugin()
        settings = plugin.settings()
        conf = Config(parse_defaults(settings))
        conf["tdp.tdp.tdp_enable"] = False

        with patch("adjustor.drivers.unified.find_decky_plugins"):
            plugin.update(conf)

        self.assertIn("tdp", settings["tdp"])
        self.assertNotIn("enforce_limits", settings["hhd"]["settings"]["children"])
        self.assertFalse(conf["hhd.settings.tdp_ready"].to(bool))
        self.assertEqual(conf["hhd.steamos.tdp_status"].to(str), "disabled")
        self.assertIsNone(conf["hhd.steamos.tdp_max"].conf)

    def test_enable_publishes_limits_and_unified_settings(self):
        plugin = make_plugin()
        conf = initial_config(plugin, enabled=True)

        with patch("adjustor.drivers.unified.find_decky_plugins", return_value=[]):
            plugin.update(conf)

        settings = plugin.settings()
        self.assertTrue(conf["hhd.settings.tdp_ready"].to(bool))
        self.assertEqual(conf["hhd.steamos.tdp_status"].to(str), "enabled")
        self.assertEqual(conf["hhd.steamos.tdp_min"].to(int), 4)
        self.assertEqual(conf["hhd.steamos.tdp_default"].to(int), 15)
        self.assertEqual(conf["hhd.steamos.tdp_max"].to(int), 30)
        self.assertIn("unified", settings["tdp"])

    def test_profile_units_are_added_without_overriding_custom(self):
        plugin = make_plugin()
        plugin.enabled = True

        with patch(
            "adjustor.drivers.unified.get_profile_units",
            return_value={
                "low-power": 8,
                "balanced": 15,
                "performance": 25,
            },
        ):
            settings = plugin.settings()

        modes = settings["tdp"]["unified"]["children"]["tdp"]["modes"]
        self.assertEqual(modes["low-power"]["unit"], "8W")
        self.assertEqual(modes["balanced"]["unit"], "15W")
        self.assertEqual(modes["performance"]["unit"], "25W")
        self.assertEqual(modes["custom"]["unit"], "→ 30")

    def test_profiles_only_prevents_steamos_fallback(self):
        plugin = make_plugin(tdp=None)
        conf = initial_config(plugin, enabled=True)

        with patch("adjustor.drivers.unified.find_decky_plugins", return_value=[]):
            plugin.update(conf)

        settings = plugin.settings()
        modes = settings["tdp"]["unified"]["children"]["tdp"]["modes"]
        self.assertTrue(conf["hhd.settings.tdp_ready"].to(bool))
        self.assertEqual(conf["hhd.steamos.tdp_status"].to(str), "conflict")
        self.assertIsNone(conf["hhd.steamos.tdp_min"].conf)
        self.assertIsNone(conf["hhd.steamos.tdp_max"].conf)
        self.assertNotIn("custom", modes)
        with (
            patch("hhd.http.steamos.get_state", return_value=conf.conf),
            patch("builtins.print"),
        ):
            self.assertEqual(steamos_tdp(["get"]), 2)

    def test_decky_conflict_can_be_removed(self):
        plugin = make_plugin()
        conf = initial_config(plugin, enabled=True)
        conflict = DeckyPlugin(
            name="PowerControl",
            path="/home/deck/homebrew/plugins/PowerControl",
        )

        with patch(
            "adjustor.drivers.unified.find_decky_plugins", return_value=[conflict]
        ):
            plugin.update(conf)

        self.assertFalse(conf["hhd.settings.tdp_ready"].to(bool))
        self.assertEqual(conf["hhd.steamos.tdp_status"].to(str), "conflict")
        self.assertTrue(plugin.failed)

        settings = plugin.settings()
        conf = Config([parse_defaults(settings), conf.conf])
        # A normal failed update restores self.enabled to the requested value.
        # Decky removal must still request a settings rebuild afterward.
        plugin.update(conf)
        conf["tdp.tdp.decky_remove"] = True
        plugin.emit.reset_mock()
        with (
            patch("adjustor.drivers.unified.find_decky_plugins", return_value=[]),
            patch("adjustor.drivers.unified.disable_decky_plugins") as disable,
        ):
            plugin.update(conf)

        disable.assert_called_once_with()
        plugin.emit.assert_any_call({"type": "settings"})
        self.assertTrue(conf["hhd.settings.tdp_ready"].to(bool))
        self.assertFalse(plugin.failed)

    def test_ac_change_clamps_and_retains_steam_tdp(self):
        plugin = make_plugin()
        conf = initial_config(plugin, enabled=True)
        with patch("adjustor.drivers.unified.find_decky_plugins", return_value=[]):
            plugin.update(conf)

        conf = Config([parse_defaults(plugin.settings()), conf.conf])
        conf["tdp.unified.tdp.mode"] = "custom"
        conf["tdp.unified.tdp.custom.tdp"] = 25
        plugin.old_conf = conf["tdp.unified"]
        plugin.startup = False
        plugin.mode = "custom"

        plugin.notify([{"type": "tdp", "tdp": 25}])
        plugin.new_tdp = None
        with (
            patch("adjustor.drivers.unified.get_tdp_values", return_value=DC_TDP),
            patch("adjustor.drivers.unified.time.perf_counter", return_value=100.0),
        ):
            plugin.notify([{"type": "acpi", "event": "dc"}])

        plugin.settings()
        with (
            patch("adjustor.drivers.unified.find_decky_plugins", return_value=[]),
            patch(
                "adjustor.drivers.unified.time.perf_counter",
                side_effect=[101.0, 102.0],
            ),
            patch("adjustor.drivers.unified.set_mode"),
            patch("adjustor.drivers.unified.set_tdp") as set_tdp,
        ):
            plugin.update(conf)
            plugin.update(conf)

        self.assertEqual(conf["tdp.unified.tdp.custom.tdp"].to(int), 20)
        self.assertEqual(conf["hhd.steamos.tdp_max"].to(int), 20)
        self.assertTrue(conf["hhd.steamos.tdp_set"].to(bool))
        set_tdp.assert_any_call("ppt_pl1_spl", DC_TDP, 20)

    def test_disable_clears_steamos_limits(self):
        plugin = make_plugin()
        conf = initial_config(plugin, enabled=True)
        with patch("adjustor.drivers.unified.find_decky_plugins", return_value=[]):
            plugin.update(conf)

        conf["hhd.settings.tdp_enable"] = False
        plugin.update(conf)

        self.assertFalse(conf["hhd.settings.tdp_ready"].to(bool))
        self.assertEqual(conf["hhd.steamos.tdp_status"].to(str), "disabled")
        self.assertIsNone(conf["hhd.steamos.tdp_min"].conf)
        self.assertIsNone(conf["hhd.steamos.tdp_default"].conf)
        self.assertIsNone(conf["hhd.steamos.tdp_max"].conf)


if __name__ == "__main__":
    unittest.main()
