import os
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

from adjustor.decky import DeckyPlugin, disable_decky_plugins, find_decky_plugins
from adjustor.hhd import AdjustorInitPlugin
from hhd.plugins import Config
from hhd.plugins.settings import parse_defaults


class DeckyHandlerTest(unittest.TestCase):
    def test_finds_plugins_under_user_home(self):
        with tempfile.TemporaryDirectory() as home:
            plugin_path = os.path.join(
                home, "deck", "homebrew", "plugins", "PowerControl"
            )
            os.makedirs(plugin_path)

            plugins = find_decky_plugins(home)

            self.assertEqual(len(plugins), 1)
            self.assertEqual(plugins[0].name, "PowerControl")
            self.assertEqual(plugins[0].path, plugin_path)

    def test_moves_plugins_and_restarts_decky(self):
        with tempfile.TemporaryDirectory() as home:
            plugin_path = os.path.join(
                home, "deck", "homebrew", "plugins", "SimpleDeckyTDP"
            )
            os.makedirs(plugin_path)

            with patch("adjustor.decky.os.system") as system:
                disable_decky_plugins(home)

            disabled_path = os.path.join(
                home,
                "deck",
                "homebrew",
                "plugins",
                "hhd-disabled",
                "SimpleDeckyTDP",
            )
            self.assertFalse(os.path.exists(plugin_path))
            self.assertTrue(os.path.isdir(disabled_path))
            self.assertEqual(
                system.call_args_list,
                [
                    call("systemctl stop plugin_loader"),
                    call("systemctl start plugin_loader"),
                ],
            )

    def test_legacy_init_uses_shared_detection(self):
        plugin = AdjustorInitPlugin(
            min_tdp=4,
            default_tdp=15,
            max_tdp=30,
            use_acpi_call=False,
        )
        plugin.emit = MagicMock()
        conf = Config(parse_defaults(plugin.settings()))
        conf["tdp.tdp.tdp_enable"] = False
        conf["hhd.settings.tdp_enable"] = True
        conflict = DeckyPlugin(
            name="PowerControl",
            path="/home/deck/homebrew/plugins/PowerControl",
        )

        with patch("adjustor.hhd.find_decky_plugins", return_value=[conflict]) as find:
            plugin.update(conf)

        find.assert_called_once_with()
        self.assertTrue(plugin.failed)
        self.assertEqual(conf["hhd.steamos.tdp_status"].to(str), "conflict")


if __name__ == "__main__":
    unittest.main()
