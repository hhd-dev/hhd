import tempfile
import unittest
from pathlib import Path
from threading import Event, Lock
from unittest.mock import patch

from adjustor.core.fan import get_fan_info
from adjustor.core.fan import utils
from adjustor.core.fan.core import fan_worker, set_fans_to_pwm, update_fan_speed
from adjustor.drivers.unified import ManagedFan, get_fan, setup_fan


class FanDetectionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.parameter = self.root / "fan_control"
        for name, value in (
            ("HWMON_DIR", str(self.root)),
            ("THINKPAD_FAN_CONTROL", str(self.parameter)),
        ):
            patcher = patch.object(utils, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def hwmon(self, index, name, files):
        path = self.root / f"hwmon{index}"
        path.mkdir()
        for filename, value in {"name": name, **files}.items():
            (path / filename).write_text(value)
        return path

    def test_intel_package_label_and_input_required(self):
        path = self.hwmon(7, "coretemp", {
            "temp2_label": "Core 0", "temp2_input": "51000",
            "temp5_label": "Package id 0", "temp5_input": "63000",
        })
        self.assertEqual(utils.find_intel_temp(), str(path / "temp5_input"))
        (path / "temp5_input").unlink()
        self.assertIsNone(utils.find_intel_temp())
        (path / "temp5_input").write_text("invalid")
        self.assertIsNone(utils.find_intel_temp())
        (path / "temp5_input").write_text("63000")
        (path / "temp5_label").write_text("Physical id 0")
        self.assertEqual(utils.find_intel_temp(), str(path / "temp5_input"))

    def test_thinkpad_requires_enabled_parameter_and_pwm_pair(self):
        path = self.hwmon(3, "thinkpad", {
            "pwm1": "128", "pwm1_enable": "2", "fan1_input": "3000",
            "fan2_input": "3100",
        })
        self.assertEqual(utils.find_fans(), [])
        for value in ("N", "0", "", "invalid"):
            self.parameter.write_text(value)
            self.assertEqual(utils.find_fans(), [])
        for value in ("Y\n", "1\n"):
            self.parameter.write_text(value)
            self.assertEqual(utils.find_fans(), [(
                str(path / "pwm1"), str(path / "pwm1_enable"),
                str(path / "fan1_input"), False,
            )])
        self.assertEqual((path / "pwm1_enable").read_text(), "2")
        (path / "pwm1_enable").unlink()
        self.assertEqual(utils.find_fans(), [])

    def test_intel_thinkpad_integrates_without_amd_gpu(self):
        cpu = self.hwmon(5, "coretemp", {
            "temp1_label": "Package id 0", "temp1_input": "65000",
        })
        fan = self.hwmon(8, "thinkpad", {"pwm1": "128", "pwm1_enable": "2"})
        self.parameter.write_text("Y")
        info = get_fan_info()
        self.assertIsNotNone(info)
        self.assertEqual(info["edge"], str(cpu / "temp1_input"))
        self.assertIsNone(info["tctl"])
        _, state = update_fan_speed(
            None, info, {50: 0.4, 70: 0.8, 90: 1.0}, False, observe_only=True
        )
        self.assertEqual(state["t_edge"], 65.0)
        self.assertIsNone(state["t_junction"])
        with self.assertRaises(AssertionError):
            update_fan_speed(None, info, {50: 0.4}, True, observe_only=True)
        set_fans_to_pwm(True, info)
        self.assertEqual((fan / "pwm1_enable").read_text(), "1")
        set_fans_to_pwm(False, info)
        self.assertEqual((fan / "pwm1_enable").read_text(), "2")

    def test_existing_fans_do_not_require_thinkpad_parameter(self):
        self.hwmon(0, "gpdfan", {"pwm1": "128", "pwm1_enable": "2"})
        self.assertEqual(len(utils.find_fans()), 1)

    def test_acer_requires_pwm_pair_and_supports_gpu_only_channel(self):
        path = self.hwmon(3, "acer", {
            "temp1_input": "65000", "fan1_input": "3000",
            "fan2_input": "3100",
        })
        # acer-wmi hides PWM attributes on models without ACER_CAP_PWM.
        self.assertEqual(utils.find_fans(), [])
        (path / "pwm2").write_text("128")
        self.assertEqual(utils.find_fans(), [])
        (path / "pwm2_enable").write_text("2")
        self.assertEqual(utils.find_fans(), [(
            str(path / "pwm2"), str(path / "pwm2_enable"),
            str(path / "fan2_input"), False,
        )])
        self.assertEqual((path / "pwm2_enable").read_text(), "2")

    def test_unified_acer_curve_controls_both_fans_and_restores_auto(self):
        self.hwmon(5, "coretemp", {
            "temp1_label": "Package id 0", "temp1_input": "65000",
        })
        path = self.hwmon(8, "acer", {
            "pwm1": "0", "pwm1_enable": "2", "fan1_input": "3000",
            "pwm2": "0", "pwm2_enable": "2", "fan2_input": "3100",
        })
        with patch("adjustor.drivers.unified.HWMON", str(self.root)):
            fan = get_fan()
        self.assertIsInstance(fan, ManagedFan)
        self.assertEqual(len(fan.info["fans"]), 2)
        settings = {}
        setup_fan(fan, settings)
        self.assertEqual(set(settings["modes"]), {"disabled", "manual_edge"})

        should_exit = Event()
        state = {}

        def stop_after_update(_):
            for channel in (1, 2):
                self.assertEqual((path / f"pwm{channel}_enable").read_text(), "1")
            should_exit.set()

        # Exercise one real worker iteration against the Acer sysfs layout.
        with patch("adjustor.core.fan.core.time.sleep", side_effect=stop_after_update):
            fan_worker(fan.info, should_exit, Lock(), {50: 0.8, 90: 1.0}, state, Event())

        self.assertTrue(should_exit.is_set())
        self.assertEqual(state["t_edge"], 65.0)
        self.assertCountEqual(state["v_rpm"], [3000, 3100])
        for channel in (1, 2):
            self.assertEqual((path / f"pwm{channel}").read_text(), "204")
            self.assertEqual((path / f"pwm{channel}_enable").read_text(), "2")


if __name__ == "__main__":
    unittest.main()
