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

    def test_oxp_superx_matches_dev_data_with_dock_aware(self):
        def side_effect(file, *args, **kwargs):
            if file == "/sys/devices/virtual/dmi/id/product_name":
                return mock_open(read_data="ONEXPLAYER SUPER X").return_value
            if file == "/sys/devices/virtual/dmi/id/board_name":
                return mock_open(read_data="ONEXPLAYER SUPER X").return_value
            if file == "/proc/cpuinfo":
                return mock_open(read_data="AMD Ryzen 7 8840U").return_value
            return mock_open(read_data="").return_value

        smu = MagicMock(name="smu")
        qam = MagicMock(name="qam")

        with (
            patch("builtins.open", side_effect=side_effect),
            patch("adjustor.hhd.USE_UNIFIED", False),
            patch("adjustor.hhd.ASUS_DATA", {}),
            patch("adjustor.hhd.MSI_DATA", {}),
            patch("adjustor.drivers.smu.SmuDriverPlugin", return_value=smu) as smu_cls,
            patch("adjustor.drivers.smu.SmuQamPlugin", return_value=qam) as qam_cls,
        ):
            plugins = autodetect([])

        self.assertIn(smu, plugins)
        self.assertIn(qam, plugins)
        # SUPER X / APEX are dock-aware: dock state relaxes the TDP cap
        self.assertEqual(smu_cls.call_args.kwargs["dock_aware"], True)
        self.assertEqual(qam_cls.call_args.kwargs["dock_aware"], True)
        # DC cap should be passed for battery-mode TDP limiting
        self.assertIsNotNone(smu_cls.call_args.kwargs["dc_cap"])
        self.assertIsNotNone(qam_cls.call_args.kwargs["dc_cap"])
        self.assertTrue(
            any(isinstance(plugin, AdjustorInitPlugin) for plugin in plugins)
        )


if __name__ == "__main__":
    unittest.main()
