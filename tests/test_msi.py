import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from adjustor.core.const import MSI_DATA
from adjustor.drivers import msi
from adjustor.hhd import AdjustorInitPlugin, autodetect
from hhd.plugins import Config
from hhd.plugins.settings import merge_settings, parse_defaults


# PL1/PL2/PL3 ranges from msi-wmi-platform's generation quirks.
LIMITS = {
    "MS-1T41": ((8, 43), (9, 45), None),
    "MS-1T42": ((8, 30), (9, 37), None),
    "MS-1T52": ((8, 30), (9, 37), None),
    "MS-1T8K": ((7, 35), (9, 40), (10, 48)),
    "MS-1T91": ((8, 35), (9, 45), None),
}


class MsiPowerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = [Path(tmp.name) / name for name in ("pl1", "pl2", "pl3")]
        patcher = patch.multiple(
            msi, TDP_PL1_FN=str(self.paths[0]), TDP_PL2_FN=str(self.paths[1]),
            TDP_PL3_FN=str(self.paths[2]),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(msi.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def configure(self, board, mode="custom", watts=15, boost=True):
        for path, limits in zip(self.paths, LIMITS[board]):
            path.unlink(missing_ok=True)
            if limits:
                path.write_text(str(limits[0]))
        plugin = msi.MsiDriverPlugin(MSI_DATA[board])
        plugin.emit = MagicMock()
        plugin.enabled = True
        conf = Config(parse_defaults(merge_settings([plugin.settings()])))
        conf.update({
            "hhd.settings.tdp_ready": True,
            "hhd.settings.enforce_limits": True,
            "tdp.msi.tdp.mode": mode,
            "tdp.msi.tdp.custom.tdp": watts,
            "tdp.msi.tdp.custom.boost": boost,
        })
        return plugin, conf

    def apply(self, plugin, conf):
        with patch.object(msi.time, "perf_counter", side_effect=[0, 1, 2]):
            for _ in range(3):
                plugin.update(conf)

    def assert_kernel_limits(self, board):
        values = []
        for path, limits in zip(self.paths, LIMITS[board]):
            if limits is None:
                self.assertFalse(path.exists())
                continue
            value = int(path.read_text())
            self.assertGreaterEqual(value, limits[0])
            self.assertLessEqual(value, limits[1])
            values.append(value)
        self.assertGreaterEqual(values[1], values[0] + 1)
        if len(values) == 3:
            self.assertGreaterEqual(values[2], values[1])
        return values

    @patch.object(msi, "set_platform_profile", return_value=True)
    def test_all_generations_custom_limits_with_and_without_boost(self, profile):
        for board, (pl1, _, _) in LIMITS.items():
            for watts in range(pl1[0], pl1[1] + 1):
                for boost in (False, True):
                    with self.subTest(board=board, watts=watts, boost=boost):
                        plugin, conf = self.configure(board, watts=watts, boost=boost)
                        self.apply(plugin, conf)
                        self.assertEqual(self.assert_kernel_limits(board)[0], watts)
                        data = MSI_DATA[board]
                        expected_profile = (
                            "low-power" if watts < data["balanced_min"] else
                            "balanced" if watts < data["performance_min"] else
                            "performance"
                        )
                        profile.assert_called_with(expected_profile)

    @patch.object(msi, "set_platform_profile", return_value=True)
    def test_presets_remain_in_kernel_ranges(self, profile):
        for board in LIMITS:
            for mode, expected_profile in (
                ("quiet", "low-power"), ("balanced", "balanced"),
                ("performance", "performance"),
            ):
                with self.subTest(board=board, mode=mode):
                    plugin, conf = self.configure(board, mode=mode)
                    self.apply(plugin, conf)
                    self.assertEqual(
                        self.assert_kernel_limits(board),
                        [value for value in MSI_DATA[board][mode] if value is not None],
                    )
                    modes = plugin.settings()["tdp"]["msi"]["children"]["tdp"]["modes"]
                    self.assertEqual(modes[mode]["unit"], f"{MSI_DATA[board][mode][0]}W")
                    profile.assert_called_with(expected_profile)

    @patch.object(msi, "set_platform_profile", return_value=True)
    def test_ex_steam_request_uses_performance_and_boosts_to_45w(self, profile):
        plugin, conf = self.configure("MS-1T91", mode="balanced")
        plugin.notify([{"type": "tdp", "tdp": 35}])
        self.apply(plugin, conf)
        profile.assert_called_with("performance")
        self.assertEqual(conf["tdp.msi.tdp.mode"].to(str), "custom")
        self.assertEqual(self.assert_kernel_limits("MS-1T91"), [35, 45])

    def test_ex_autodetection_exposes_limits_without_acpi_call(self):
        fields = {
            "product_name": "Claw 8 EX AI+ CG3EM Launch Pack",
            "board_name": "MS-1T91", "cpuinfo": "GenuineIntel",
        }
        with patch("builtins.open", side_effect=lambda path: mock_open(
            read_data=fields[Path(path).name]
        )()):
            plugins = autodetect([])
        driver = next(p for p in plugins if isinstance(p, msi.MsiDriverPlugin))
        self.assertIs(driver.tdp_data, MSI_DATA["MS-1T91"])
        init = next(p for p in plugins if isinstance(p, AdjustorInitPlugin))
        self.assertFalse(init.use_acpi_call)
        self.assertEqual((init.min_tdp, init.max_tdp), (8, 35))


if __name__ == "__main__":
    unittest.main()
