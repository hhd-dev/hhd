import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from adjustor.core.rapl import RaplData, get_rapl, set_rapl
from adjustor.drivers.intel import IntelDriverPlugin, SLEEP_DELAY
from adjustor.hhd import AdjustorInitPlugin, autodetect
from hhd.plugins import Config


class RaplTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch("adjustor.core.rapl.POWERCAP", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def zone(self, dirname="intel-rapl:0", name="package-0", current=17,
             maximum=28, index=0):
        zone = self.root / dirname
        zone.mkdir()
        for file, value in {
            "name": name, "enabled": 1,
            f"constraint_{index}_name": "long_term",
            f"constraint_{index}_power_limit_uw": current * 1_000_000,
            f"constraint_{index}_max_power_uw": maximum * 1_000_000,
            "constraint_7_name": "short_term",
            "constraint_7_power_limit_uw": 80_000_000,
        }.items():
            (zone / file).write_text(str(value))
        return zone / f"constraint_{index}_power_limit_uw"

    def test_discovers_named_package_constraints_and_both_interfaces(self):
        msr = self.zone(current=80, index=3)
        mmio = self.zone("intel-rapl-mmio:0")
        self.zone("intel-rapl:0:0", "core")
        self.zone("intel-rapl:1", "psys")
        data = get_rapl()
        self.assertEqual(set(data.limits), {msr, mmio})
        self.assertEqual(data[1:4], (5, 15, 28))
        self.assertTrue(set_rapl(data, 20))
        for limit in (msr, mmio):
            self.assertEqual(int(limit.read_text()), 20_000_000)
            self.assertEqual(int((limit.parent / "constraint_7_power_limit_uw").read_text()), 22_000_000)

    def test_absent_disabled_readonly_and_multiple_packages(self):
        self.assertIsNone(get_rapl())
        limit = self.zone()
        (limit.parent / "enabled").write_text("0")
        self.assertIsNone(get_rapl())
        (limit.parent / "enabled").write_text("1")
        limit.chmod(0o444)
        self.assertIsNone(get_rapl())
        limit.chmod(0o644)
        self.zone("intel-rapl:1", "package-1")
        self.assertIsNone(get_rapl())

    def test_boost_scales_pl4_and_clips_pl2_on_both_interfaces(self):
        for dirname in ("intel-rapl:0", "intel-rapl-mmio:0"):
            zone = self.zone(dirname).parent
            (zone / "constraint_7_max_power_uw").write_text("29000000")
            (zone / "constraint_9_name").write_text("peak_power")
            (zone / "constraint_9_power_limit_uw").write_text("144000000")
            (zone / "constraint_9_max_power_uw").write_text("0")
            (zone / "constraint_0_time_window_us").write_text("27983872")
        data = get_rapl()
        self.assertEqual(len(data.pl4), 2)
        self.assertTrue(set_rapl(data, 14, True))
        for limit in data.pl2:
            self.assertEqual(int(limit.path.read_text()), 16_000_000)
        for limit in data.pl4:
            self.assertEqual(limit.max_tdp, 144)
            self.assertEqual(int(limit.path.read_text()), 72_000_000)
        self.assertTrue(set_rapl(data, 28, True))
        for limit in data.pl2:
            self.assertEqual(int(limit.path.read_text()), 29_000_000)
        for limit in data.pl4:
            self.assertEqual(int(limit.path.read_text()), 144_000_000)
        self.assertTrue(set_rapl(data, 14, False))
        for limit in (*data.pl2, *data.pl4):
            self.assertEqual(int(limit.path.read_text()), 14_000_000)
        for path in data.limits:
            self.assertEqual((path.parent / "constraint_0_time_window_us").read_text(), "27983872")

    def test_missing_boost_constraints_still_allows_pl1(self):
        path = self.zone()
        (path.parent / "constraint_7_power_limit_uw").unlink()
        data = get_rapl()
        self.assertEqual((data.pl2, data.pl4), ((), ()))
        self.assertTrue(set_rapl(data, 15, True))
        self.assertEqual(int(path.read_text()), 15_000_000)

    def test_locked_boost_constraint_rolls_back_pl1(self):
        path = self.zone()
        data = get_rapl()
        original = Path.write_text

        def write(target, value):
            if target == data.pl2[0].path:
                raise PermissionError("Boost locked")
            return original(target, value)

        with patch.object(Path, "write_text", write):
            self.assertFalse(set_rapl(data, 20, True))
        self.assertEqual(int(path.read_text()), 17_000_000)

    def test_missing_or_zero_maximum_uses_current_limit(self):
        limit = self.zone(maximum=0)
        self.assertEqual(get_rapl().max_tdp, 17)
        (limit.parent / "constraint_0_max_power_uw").unlink()
        self.assertEqual(get_rapl().max_tdp, 17)
        limit.write_text("invalid")
        self.assertIsNone(get_rapl())

    def test_rejects_out_of_range_without_writes(self):
        limit = self.zone()
        for watts in (0, 4, 29):
            with self.assertRaises(ValueError):
                set_rapl(get_rapl(), watts)
        self.assertEqual(int(limit.read_text()), 17_000_000)

    def test_rolls_back_first_cap_if_second_is_locked(self):
        self.zone()
        self.zone("intel-rapl-mmio:0", current=15)
        data = get_rapl()
        original = Path.write_text
        before = [p.read_text() for p in data.limits]

        def write(path, value):
            if path == data.limits[1]:
                raise PermissionError("Firmware lock")
            return original(path, value)

        with patch.object(Path, "write_text", write):
            self.assertFalse(set_rapl(data, 20))
        self.assertEqual([p.read_text() for p in data.limits], before)

    def test_autodetect_intel_in_both_modes(self):
        from unittest.mock import mock_open

        self.zone()
        for vendor in ("GPD", "ONE-NETBOOK TECHNOLOGY CO., LTD.", "LENOVO", ""):
            for unified in (False, True):
                def read(path):
                    value = vendor if str(path).endswith("sys_vendor") else "GenuineIntel"
                    return mock_open(read_data=value)()

                with (
                    patch("builtins.open", side_effect=read),
                    patch("adjustor.hhd.USE_UNIFIED", unified),
                    patch("adjustor.hhd.ASUS_DATA", {}),
                    patch("adjustor.hhd.MSI_DATA", {}),
                    patch("adjustor.drivers.unified.UnifiedDriverPlugin") as unified_driver,
                ):
                    unified_driver.return_value.is_supported.return_value = False
                    plugins = autodetect([])
                if vendor in ("LENOVO", ""):
                    self.assertFalse(any(isinstance(p, IntelDriverPlugin) for p in plugins))
                    continue
                self.assertIsInstance(plugins[0], IntelDriverPlugin)
                init = next(p for p in plugins if isinstance(p, AdjustorInitPlugin))
                self.assertFalse(init.use_acpi_call)
                self.assertEqual((init.min_tdp, init.default_tdp, init.max_tdp), (5, 15, 28))

    def test_unified_takes_precedence_over_intel(self):
        from unittest.mock import mock_open

        with (
            patch("builtins.open", mock_open(read_data="GenuineIntel")),
            patch("adjustor.hhd.USE_UNIFIED", True),
            patch("adjustor.hhd.ASUS_DATA", {}),
            patch("adjustor.hhd.MSI_DATA", {}),
            patch("adjustor.drivers.unified.UnifiedDriverPlugin") as unified,
            patch("adjustor.core.rapl.get_rapl") as rapl,
        ):
            unified.return_value.is_supported.return_value = True
            plugins = autodetect([])
        self.assertIs(plugins[0], unified.return_value)
        rapl.assert_not_called()



class IntelPluginTest(unittest.TestCase):
    def setUp(self):
        self.plugin = IntelDriverPlugin(RaplData((), 5, 17, 28))
        self.plugin.open(MagicMock(), None)
        self.conf = Config({"hhd.settings.tdp_ready": True, "tdp.intel.tdp": 17})

    def update(self, now):
        with patch("adjustor.drivers.intel.time.perf_counter", return_value=now):
            self.plugin.update(self.conf)

    @patch("adjustor.drivers.intel.set_rapl", return_value=True)
    def test_boost_toggle_alone_queues_update(self, write):
        self.update(0)
        self.update(1)
        self.conf["tdp.intel.boost"] = False
        self.update(2)
        self.assertEqual(write.call_count, 1)
        self.update(3)
        write.assert_called_with(self.plugin.data, 17, False)

    @patch("adjustor.drivers.intel.set_rapl", return_value=True)
    def test_enable_debounce_steam_clamp_and_disable(self, write):
        self.update(0)
        self.update(0.5)
        write.assert_not_called()
        self.update(1)
        write.assert_called_once_with(self.plugin.data, 17, True)
        self.plugin.notify([{"type": "tdp", "tdp": 99}])
        self.update(2)
        self.update(3)
        write.assert_called_with(self.plugin.data, 28, True)
        self.assertEqual(self.conf.get("tdp.intel.tdp", 0), 28)
        self.conf["hhd.settings.tdp_ready"] = False
        self.plugin.notify([{"type": "tdp", "tdp": 10}])
        self.update(4)
        self.assertEqual(write.call_count, 2)
        self.assertIsNone(self.plugin.queue_tdp)

    @patch("adjustor.drivers.intel.set_rapl", return_value=True)
    def test_wakeup_delay_survives_ac_and_slider_change(self, write):
        self.update(0)
        self.update(1)
        with patch("adjustor.drivers.intel.time.perf_counter", return_value=10):
            self.plugin.notify([{"type": "special", "event": "wakeup"},
                                {"type": "acpi", "event": "dc"}])
        self.conf["tdp.intel.tdp"] = 15
        self.update(11)
        self.update(14)
        self.assertEqual(write.call_count, 1)
        self.update(10 + SLEEP_DELAY)
        write.assert_called_with(self.plugin.data, 15, True)

    @patch("adjustor.drivers.intel.set_rapl", return_value=False)
    def test_failure_is_reported_and_retried_after_ac_event(self, write):
        self.update(0)
        self.update(1)
        self.assertEqual(self.conf.get("hhd.steamos.tdp_status", ""), "conflict")
        self.assertTrue(self.conf.get("tdp.intel.error", ""))
        write.return_value = True
        with patch("adjustor.drivers.intel.time.perf_counter", return_value=2):
            self.plugin.notify([{"type": "acpi", "event": "ac"}])
        self.update(3)
        self.assertEqual(self.conf.get("hhd.steamos.tdp_status", ""), "enabled")


if __name__ == "__main__":
    unittest.main()
