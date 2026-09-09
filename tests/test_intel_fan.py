import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from adjustor.core.rapl import RaplData
from adjustor.drivers.intel import DEFAULT_FAN_CURVE, IntelDriverPlugin
from hhd.plugins import Config


class IntelFanTest(unittest.TestCase):
    def setUp(self):
        self.info = {"edge": "/temperature", "tctl": None,
                     "fans": [("/pwm", "/enable", "/rpm", False)]}
        self.plugin = IntelDriverPlugin(RaplData((), 5, 17, 28))
        with patch("adjustor.drivers.intel.get_fan_info", return_value=self.info):
            self.plugin.open(MagicMock(), None)
        self.addCleanup(self.plugin.close)
        self.conf = Config({"hhd.settings.tdp_ready": True,
                            "tdp.intel.fan.mode": "manual"})

    def test_settings_require_detected_fan(self):
        self.assertEqual(self.plugin.settings(), {})
        self.plugin.enabled = True
        fan = self.plugin.settings()["tdp"]["intel"]["children"]["fan"]
        self.assertEqual(set(fan["modes"]), {"disabled", "manual"})
        self.assertEqual(fan["default"], "disabled")
        children = fan["modes"]["manual"]["children"]
        for temp, speed in DEFAULT_FAN_CURVE.items():
            self.assertEqual(children[f"st{temp}"]["default"], speed)
        self.plugin.fan_info = None
        self.assertNotIn("fan", self.plugin.settings()["tdp"]["intel"]["children"])

    @patch("adjustor.drivers.intel.Thread")
    def test_curve_updates_reset_and_disable(self, thread):
        self.conf["tdp.intel.fan.manual.st60"] = 72
        self.plugin.update_fan(self.conf)
        self.assertEqual(self.plugin.fan_curve[60], 0.72)
        self.assertFalse(self.plugin.fan_junction.is_set())
        self.plugin.update_fan(self.conf)
        thread.assert_called_once()
        self.conf["tdp.intel.fan.manual.reset"] = True
        self.plugin.update_fan(self.conf)
        self.assertEqual(self.plugin.fan_curve[60], DEFAULT_FAN_CURVE[60] / 100)
        self.assertFalse(self.conf.get("tdp.intel.fan.manual.reset", True))
        self.conf["tdp.intel.fan.mode"] = "disabled"
        self.plugin.update_fan(self.conf)
        thread.return_value.join.assert_called_once()
        self.assertTrue(self.plugin.fan_should_exit.is_set())
        self.assertIsNone(self.plugin.fan_t)

    @patch("adjustor.drivers.intel.Thread")
    def test_tdp_disable_stops_worker(self, thread):
        self.plugin.update(self.conf)
        thread.return_value.start.assert_called_once()
        self.conf["hhd.settings.tdp_ready"] = False
        self.plugin.update(self.conf)
        thread.return_value.join.assert_called_once()
        self.assertIsNone(self.plugin.fan_t)

    @patch("adjustor.drivers.intel.Thread")
    def test_no_manual_mode_does_not_start_worker(self, thread):
        self.conf = Config({"hhd.settings.tdp_ready": True})
        self.plugin.update(self.conf)
        thread.assert_not_called()

    def test_worker_writes_pwm_and_restores_automatic_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, value in {"temp": "60000", "pwm": "0",
                                "enable": "2", "rpm": "3000"}.items():
                (root / name).write_text(value)
            self.plugin.fan_info = {
                "edge": str(root / "temp"), "tctl": None,
                "fans": [(str(root / "pwm"), str(root / "enable"),
                          str(root / "rpm"), False)],
            }
            # Stop after one iteration, keeping the real worker and sysfs I/O.
            with patch("adjustor.core.fan.core.time.sleep",
                       side_effect=lambda _: self.plugin.fan_should_exit.set()):
                self.plugin.update_fan(self.conf)
                self.plugin.fan_t.join(timeout=2)
                self.assertFalse(self.plugin.fan_t.is_alive())
            self.assertGreater(int((root / "pwm").read_text()), 0)
            self.assertEqual((root / "enable").read_text(), "2")
            self.assertEqual(self.plugin.fan_state["t_edge"], 60)
            self.assertIsNone(self.plugin.fan_state["t_junction"])
            self.plugin.close()


if __name__ == "__main__":
    unittest.main()
