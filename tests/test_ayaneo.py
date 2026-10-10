import unittest
from contextlib import ExitStack
from threading import Event
from unittest.mock import Mock, mock_open, patch

from hhd.controller.physical.evdev import B
from hhd.device.ayaneo import AyaneoControllersPlugin, autodetect, base
from hhd.device.ayaneo.const import CONFS
from hhd.plugins import Config


class AyaneoTest(unittest.TestCase):
    def setUp(self):
        self.conf = Config(
            {
                "controller_mode": {"mode": "xbox_elite"},
                "imu": False,
                "imu_hz": 400,
                "imu_axis": {"mode": "default"},
                "nintendo_mode": False,
            }
        )

    def test_ab09_detected_without_vendor_fallback(self):
        with patch("builtins.open", mock_open(read_data="AB09\n")):
            plugins = autodetect([])
        self.assertEqual(len(plugins), 1)
        self.assertIsInstance(plugins[0], AyaneoControllersPlugin)
        self.assertEqual(plugins[0].dconf["name"], "AYANEO NEXT 2")
        self.assertNotIn("magic_modules", plugins[0].settings())
        self.assertIn(
            "magic_modules",
            AyaneoControllersPlugin("AYANEO 3", CONFS["AYANEO 3"]).settings(),
        )

    def test_next2_never_touches_module_power_or_ejection(self):
        stop = Event()
        others = Config({"pop": "both", "reset": True})
        with ExitStack() as stack:
            hardware = [
                stack.enter_context(patch.object(base, name))
                for name in (
                    "read_modules", "read_power", "write_power", "Ayaneo3Hidraw",
                )
            ]
            stack.enter_context(
                patch.object(base, "enumerate_evs", return_value={1: {}})
            )
            loop = stack.enter_context(
                patch.object(base, "controller_loop", side_effect=lambda *a: stop.set())
            )
            stack.enter_context(patch.object(base, "unhide_all"))
            stack.enter_context(patch.object(base.UInputDevice, "close_volume_cached"))
            base.plugin_run(
                self.conf, Mock(), None, stop, Event(), CONFS["AB09"], others
            )
        loop.assert_called_once()
        for call in hardware:
            call.assert_not_called()

    def run_controller(self, product):
        stop = Event()
        stop.set()
        with ExitStack() as stack:
            inputs = stack.enter_context(patch.object(base, "GenericGamepadEvdev"))
            inputs.return_value.open.return_value = []
            vendor = stack.enter_context(patch.object(base, "Ayaneo3Hidraw"))
            vendor.return_value.open.return_value = []
            vendor.return_value.check.return_value = False
            volume = stack.enter_context(patch.object(base, "UInputDevice"))
            volume.return_value.open.return_value = []
            stack.enter_context(patch.object(base, "HrtimerTrigger"))
            outputs = stack.enter_context(
                patch.object(
                    base, "get_outputs", return_value=([], [], {"uses_motion": False})
                )
            )
            stack.enter_context(patch.object(base, "_reset", True))
            base.controller_loop(
                self.conf, stop, Event(), CONFS[product], Mock(), Config()
            )
        return inputs, vendor.return_value, volume.return_value, outputs

    def test_next2_uses_shared_core_without_module_initialization(self):
        inputs, vendor, volume, outputs = self.run_controller("AB09")
        keyboard = inputs.call_args_list[2].kwargs
        self.assertEqual(keyboard["vid"], [0x1C4F])
        self.assertEqual(keyboard["pid"], [0x0002])
        self.assertTrue(keyboard["required"])
        self.assertTrue(keyboard["grab"])
        self.assertEqual(keyboard["capabilities"], {B("EV_KEY"): [B("KEY_F21")]})
        self.assertEqual(keyboard["btn_map"][B("KEY_F21")], "extra_l3")
        self.assertEqual(keyboard["btn_map"][B("KEY_F20")], "extra_r1")
        self.assertEqual(keyboard["btn_map"][B("KEY_D")], "share")
        self.assertEqual(inputs.call_args_list[1].kwargs["btn_map"], {})
        for name in ("check", "init", "reset", "save"):
            getattr(vendor, name).assert_not_called()
        vendor.cfg.assert_called_once()
        volume.open.assert_called_once()
        self.assertIn("rainbow", outputs.call_args.kwargs["rgb_modes"])

    def test_aya3_keeps_existing_initialization_and_button_map(self):
        inputs, vendor, _, _ = self.run_controller("AYANEO 3")
        keyboard = inputs.call_args_list[2].kwargs["btn_map"]
        self.assertEqual(keyboard[B("KEY_F21")], "extra_l2")
        self.assertEqual(keyboard[B("KEY_L")], "extra_l1")
        self.assertEqual(
            inputs.call_args_list[1].kwargs["btn_map"], {B("KEY_F23"): "mode"}
        )
        for name in ("check", "init", "reset", "save"):
            getattr(vendor, name).assert_called_once()

    def test_shared_rgb_report_and_resume_reapply(self):
        for mode, expected_mode in (
            ("disabled", 0xFF), ("solid", 1), ("pulse", 2), ("rainbow", 3)
        ):
            with self.subTest(mode=mode), patch.dict(base._cfg, mode=None):
                vendor = base.Ayaneo3Hidraw(
                    vibration="medium", config=Config(), emit=Mock()
                )
                vendor.dev = Mock()
                vendor.dev.read.return_value = bytes(64)
                vendor.consume(
                    [{
                        "type": "led", "mode": mode,
                        "red": 0, "green": 0, "blue": 0, "brightness": 1,
                    }]
                )
                report = vendor.dev.write.call_args.args[0]
                self.assertEqual(len(report), 65)
                self.assertEqual(report[3:5], b"\x21\x09")
                self.assertEqual(
                    (report[8], report[12]), (expected_mode, expected_mode)
                )
                self.assertEqual(
                    int.from_bytes(report[1:3], "little"), sum(report[7:])
                )
                vendor.dev.reset_mock()
                vendor.cfg()
                vendor.dev.write.assert_called_once_with(report)


if __name__ == "__main__":
    unittest.main()
