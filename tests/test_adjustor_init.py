import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from adjustor.core.const import ASUS_DATA
from adjustor.decky import DeckyPlugin
from adjustor.drivers.asus import AsusDriverPlugin
from adjustor.hhd import AdjustorInitPlugin
from hhd.http.steamos import _tdp as steamos_tdp
from hhd.plugins import Config
from hhd.plugins.settings import (
    load_state_yaml,
    merge_settings,
    parse_defaults,
    save_state_yaml,
)


class AdjustorInitTest(unittest.TestCase):
    def setUp(self):
        self.plugin = AdjustorInitPlugin(7, 15, 35, use_acpi_call=True)
        self.plugin.emit = MagicMock()
        self.find_decky = self.enterContext(
            patch("adjustor.hhd.find_decky_plugins", return_value=[])
        )
        self.initialize = self.enterContext(patch("adjustor.hhd.initialize"))
        self.check_perms = self.enterContext(
            patch("adjustor.hhd.check_perms", return_value=True)
        )
        self.start = self.enterContext(patch.object(self.plugin, "_start"))
        self.stop = self.enterContext(patch.object(self.plugin, "_stop"))
        self.settings = merge_settings([self.plugin.settings()])
        self.conf = Config(parse_defaults(self.settings))
        self.conf["tdp.tdp.tdp_enable"] = False
        self.conf["hhd.settings.tdp_enable"] = True

    def test_reload_restores_asus_control_and_steam_limits(self):
        asus = AsusDriverPlugin(ASUS_DATA["ROG XBOX Ally X RC74X"])
        asus.emit = MagicMock()
        self.plugin.update(self.conf)
        asus.update(self.conf)

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.yml")
            save_state_yaml(path, self.settings, self.conf)
            # A full reload rebuilds settings and replaces the configuration,
            # but keeps the initialized plugin objects.
            settings = merge_settings([self.plugin.settings(), asus.settings()])
            conf = load_state_yaml(path, settings)

        self.assertTrue(conf["hhd.settings.tdp_enable"].conf)
        self.assertIsNone(conf["hhd.settings.tdp_ready"].conf)
        self.assertIsNone(conf["hhd.steamos.tdp_status"].conf)
        self.assertIsNone(conf["hhd.steamos.tdp_max"].conf)

        with patch("adjustor.drivers.asus.set_thermal_profile") as set_profile:
            # ASUS first captures the new configuration, then applies it.
            for _ in range(2):
                self.plugin.update(conf)
                asus.update(conf)

        self.assertTrue(conf["hhd.settings.tdp_ready"].conf)
        self.assertEqual(conf["hhd.steamos.tdp_status"].conf, "enabled")
        self.assertEqual(conf["hhd.steamos.tdp_min"].conf, 7)
        self.assertEqual(conf["hhd.steamos.tdp_default"].conf, 15)
        self.assertEqual(conf["hhd.steamos.tdp_max"].conf, 35)
        set_profile.assert_called_once_with(0)
        self.find_decky.assert_called_once_with()
        self.initialize.assert_called_once_with()
        self.check_perms.assert_called_once_with()
        self.start.assert_called_once_with()

        output = io.StringIO()
        with (
            patch("hhd.http.steamos.get_state", return_value=conf.conf),
            redirect_stdout(output),
        ):
            self.assertEqual(steamos_tdp(["get"]), 0)
        self.assertEqual(output.getvalue().strip(), "7 35 15")

    def test_disable_clears_runtime_state_after_initialization(self):
        self.plugin.update(self.conf)
        self.conf["hhd.settings.tdp_enable"] = False
        self.plugin.update(self.conf)
        self.plugin.update(self.conf)

        self.assertFalse(self.conf["hhd.settings.tdp_ready"].conf)
        self.assertEqual(self.conf["hhd.steamos.tdp_status"].conf, "disabled")
        for key in ("tdp_min", "tdp_default", "tdp_max"):
            self.assertIsNone(self.conf[f"hhd.steamos.{key}"].conf)
        self.start.assert_called_once_with()
        self.stop.assert_called_once_with()

    def test_decky_conflict_does_not_publish_readiness(self):
        self.find_decky.return_value = [DeckyPlugin("PowerControl", "/fake/path")]
        self.plugin.update(self.conf)
        self.plugin.update(self.conf)

        self.assertFalse(self.conf["hhd.settings.tdp_ready"].conf)
        self.assertEqual(self.conf["hhd.steamos.tdp_status"].conf, "conflict")
        self.assertTrue(self.plugin.failed)
        self.start.assert_not_called()

    def test_permission_failure_does_not_publish_readiness(self):
        self.check_perms.return_value = False
        self.plugin.update(self.conf)
        self.plugin.update(self.conf)

        self.assertFalse(self.conf["hhd.settings.tdp_ready"].conf)
        self.assertNotEqual(self.conf["hhd.steamos.tdp_status"].conf, "enabled")
        self.assertTrue(self.plugin.failed)
        self.check_perms.assert_called_once_with()
        self.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
