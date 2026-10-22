import unittest
from unittest.mock import Mock, mock_open, patch

from adjustor.drivers.battery import BatteryPlugin
from hhd.plugins import Config
from hhd.plugins.settings import merge_settings, parse_defaults


BASE = "/sys/class/power_supply/BATT"


class BatteryTest(unittest.TestCase):
    def detect(self, files, vendor="LENOVO"):
        contents = {
            f"{BASE}/type": "Battery\n",
            "/sys/devices/virtual/dmi/id/sys_vendor": vendor,
            **{f"{BASE}/{name}": value for name, value in files.items()},
        }
        self.files = {
            path: mock_open(read_data=value) for path, value in contents.items()
        }

        def open_file(path, mode="r"):
            if path not in self.files:
                raise FileNotFoundError(path)
            return self.files[path](path, mode)

        self.enterContext(patch("adjustor.drivers.battery.open", side_effect=open_file))
        with (
            patch("adjustor.drivers.battery.os.listdir", return_value=["BATT"]),
            patch("adjustor.drivers.battery.os.path.exists", side_effect=contents.__contains__),
        ):
            plugin = BatteryPlugin(always_enable=True)
            plugin.open(Mock(), None)
        plugin.update(Config())
        settings = plugin.settings()
        conf = Config(parse_defaults(merge_settings([settings])))
        return plugin, settings["gamemode"]["battery"]["children"], conf

    def test_charge_types_not_overridden_by_other_interfaces(self):
        plugin, settings, conf = self.detect({
            "charge_types": "[Standard] Long_Life BypassS0 Bypass\n",
            "charge_type": "Standard\n",
            "charge_behaviour": "[auto] inhibit-charge\n",
        })
        self.assertEqual(plugin.charge_bypass_fn, f"{BASE}/charge_types")
        self.assertEqual(
            set(settings["charge_bypass"]["options"]),
            {"disabled", "p80", "awake", "always"},
        )
        for mode, value in (
            ("p80", "Long_Life"), ("awake", "BypassS0"),
            ("always", "Bypass"), ("disabled", "Standard"),
        ):
            conf["gamemode.battery.charge_bypass"] = mode
            plugin.update(conf)
            self.files[f"{BASE}/charge_types"]().write.assert_called_with(f"{value}\n")
        self.files[f"{BASE}/charge_type"]().write.assert_not_called()
        self.files[f"{BASE}/charge_behaviour"]().write.assert_not_called()

    def test_behaviour_fallback_uses_its_own_capabilities(self):
        plugin, settings, conf = self.detect({
            "charge_types": "[Standard]\n",
            "charge_type": "Standard\n",
            "charge_behaviour": "[auto] inhibit-charge-awake\n",
        })
        self.assertEqual(plugin.charge_bypass_fn, f"{BASE}/charge_behaviour")
        self.assertEqual(set(settings["charge_bypass"]["options"]), {"disabled", "awake"})
        conf["gamemode.battery.charge_bypass"] = "awake"
        plugin.update(conf)
        self.files[f"{BASE}/charge_behaviour"]().write.assert_called_once_with(
            "inhibit-charge-awake\n"
        )

    def test_behaviour_application_and_unset(self):
        plugin, settings, conf = self.detect({
            "charge_behaviour": "[auto] inhibit-charge\n",
        })
        self.assertEqual(set(settings["charge_bypass"]["options"]), {"disabled", "always"})
        plugin.update(conf)
        writer = self.files[f"{BASE}/charge_behaviour"]().write
        writer.assert_not_called()
        conf["gamemode.battery.charge_bypass"] = "always"
        plugin.update(conf)
        writer.assert_called_with("inhibit-charge\n")
        conf["gamemode.battery.charge_bypass"] = "disabled"
        plugin.update(conf)
        writer.assert_called_with("auto\n")

    def test_behaviour_without_bypass_modes_is_not_exposed(self):
        plugin, settings, _ = self.detect({"charge_behaviour": "[auto] force-discharge\n"})
        self.assertIsNone(plugin.charge_bypass_fn)
        self.assertNotIn("charge_bypass", settings)

    def test_legacy_onexplayer_fallback(self):
        plugin, settings, conf = self.detect({
            "charge_types": "[Standard]\n",
            "charge_type": "Standard\n",
        }, vendor="ONE-NETBOOK")
        self.assertEqual(set(settings["charge_bypass"]["options"]), {"disabled", "awake", "always"})
        conf["gamemode.battery.charge_bypass"] = "always"
        plugin.update(conf)
        self.files[f"{BASE}/charge_type"]().write.assert_called_once_with("Bypass\n")

    def test_behaviour_still_preferred_over_legacy_onexplayer_interface(self):
        plugin, settings, conf = self.detect({
            "charge_type": "Standard\n",
            "charge_behaviour": "[auto] inhibit-charge\n",
        }, vendor="ONE-NETBOOK")
        self.assertEqual(set(settings["charge_bypass"]["options"]), {"disabled", "always"})
        conf["gamemode.battery.charge_bypass"] = "always"
        plugin.update(conf)
        self.files[f"{BASE}/charge_behaviour"]().write.assert_called_once_with(
            "inhibit-charge\n"
        )
        self.files[f"{BASE}/charge_type"]().write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
