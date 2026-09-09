import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adjustor.core.fan import get_fan_info
from adjustor.core.fan import utils
from adjustor.core.fan.core import set_fans_to_pwm, update_fan_speed


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


if __name__ == "__main__":
    unittest.main()
