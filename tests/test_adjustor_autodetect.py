import unittest
from unittest.mock import MagicMock, mock_open, patch

from adjustor.hhd import AdjustorInitPlugin, autodetect


class AdjustorAutodetectTest(unittest.TestCase):
    def test_unified_match_returns_only_companion_plugins(self):
        unified = MagicMock(name="unified")
        unified.is_supported.return_value = True
        gpu = MagicMock(name="gpu")
        battery = MagicMock(name="battery")

        with (
            patch("builtins.open", mock_open(read_data="test-device")),
            patch("adjustor.hhd.USE_UNIFIED", True),
            patch("adjustor.hhd.ASUS_DATA", {}),
            patch("adjustor.hhd.MSI_DATA", {}),
            patch("adjustor.drivers.unified.UnifiedDriverPlugin", return_value=unified),
            patch("adjustor.drivers.gpu.GpuPlugin", return_value=gpu),
            patch("adjustor.drivers.battery.BatteryPlugin", return_value=battery),
        ):
            plugins = autodetect([])

        self.assertEqual(plugins, [unified, gpu, battery])
        self.assertFalse(
            any(isinstance(plugin, AdjustorInitPlugin) for plugin in plugins)
        )

    def test_legacy_vendor_match_keeps_precedence(self):
        asus = MagicMock(name="asus")
        asus_data = {
            "test-device": {
                "min_tdp": 5,
                "max_tdp": 30,
            }
        }

        with (
            patch("builtins.open", mock_open(read_data="test-device")),
            patch("adjustor.hhd.USE_UNIFIED", True),
            patch("adjustor.hhd.ASUS_DATA", asus_data),
            patch("adjustor.hhd.MSI_DATA", {}),
            patch("adjustor.drivers.asus.AsusDriverPlugin", return_value=asus),
            patch("adjustor.drivers.unified.UnifiedDriverPlugin") as unified,
        ):
            plugins = autodetect([])

        self.assertIs(plugins[0], asus)
        self.assertTrue(
            any(isinstance(plugin, AdjustorInitPlugin) for plugin in plugins)
        )
        unified.assert_not_called()


if __name__ == "__main__":
    unittest.main()
