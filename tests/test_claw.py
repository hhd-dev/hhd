import unittest
from contextlib import ExitStack
from threading import Event
from unittest.mock import Mock, patch

from evdev import InputEvent

from hhd.controller.physical.evdev import B
from hhd.device.claw import base
from hhd.device.claw.const import CONFS, MSI_CLAW_EX_MAPPINGS, MSI_CLAW_MAPPINGS
from hhd.plugins import Config


class ClawShareTest(unittest.TestCase):
    def open_keyboards(self, use_dinput, board="MS-1T91"):
        keyboards = []
        keyboard_type = base.MsiAtKbd

        def keyboard(**kwargs):
            device = keyboard_type(**kwargs)
            device.fd = 10 + len(keyboards)
            device.started = False

            def open_keyboard():
                device.dev = Mock()
                return [device.fd]

            device.open = Mock(side_effect=open_keyboard)
            device.close = Mock()
            keyboards.append(device)
            return device

        stop = Event()
        stop.set()
        conf = Config({
            "controller_mode": {"mode": "uinput"},
            "nintendo_mode": False,
            "swap_guide": False,
        })
        with ExitStack() as stack:
            stack.enter_context(patch.object(base, "MsiAtKbd", side_effect=keyboard))
            for name in ("GenericGamepadEvdev", "UInputDevice", "ClawDInputHidraw"):
                constructor = stack.enter_context(patch.object(base, name))
                constructor.return_value.open.return_value = []
            stack.enter_context(patch.object(base, "get_outputs", return_value=([], [], {})))
            stack.enter_context(patch.object(base, "Multiplexer"))
            base.controller_loop(
                conf, stop, Event(), CONFS[board], Mock(), Event(),
                test_mode=True, use_dinput=use_dinput,
            )
        return keyboards

    def produce(self, device, codes, value):
        if not device.dev:
            return list(device.produce([]))
        device.dev.read.return_value = [
            InputEvent(0, 0, B("EV_KEY"), B(code), value) for code in codes
        ]
        with patch("hhd.controller.physical.evdev.can_read", side_effect=[True, False]):
            return list(device.produce([device.fd]))

    def test_ex_share_uses_only_atkbd_in_both_modes(self):
        for use_dinput in (False, True):
            with self.subTest(dinput=use_dinput):
                wmi, atkbd = self.open_keyboards(use_dinput)
                wmi.open.assert_not_called()
                wmi.close.assert_not_called()
                self.assertIsNone(wmi.dev)
                atkbd.open.assert_called_once_with()
                self.assertEqual(atkbd.btn_map, MSI_CLAW_EX_MAPPINGS)
                for value, now in ((1, 100), (0, 101)):
                    with patch.object(base.time, "perf_counter", return_value=now):
                        events = self.produce(atkbd, ["KEY_F15"], value)
                    self.assertEqual(events, [{
                        "type": "button", "code": "share", "value": bool(value),
                    }])

    def test_ex_preserves_mode_and_volume(self):
        for use_dinput in (False, True):
            with self.subTest(dinput=use_dinput):
                _, atkbd = self.open_keyboards(use_dinput)
                events = self.produce(atkbd, [
                    "KEY_G", "KEY_F16", "KEY_VOLUMEUP", "KEY_VOLUMEDOWN",
                ], 1)
                self.assertEqual([event["code"] for event in events], [
                    "mode", "mode", "key_volumeup", "key_volumedown",
                ])

    def test_other_claws_keep_both_keyboard_maps(self):
        for use_dinput in (False, True):
            with self.subTest(dinput=use_dinput):
                wmi, atkbd = self.open_keyboards(use_dinput, "MS-1T41")
                wmi.open.assert_called_once_with()
                self.assertEqual(wmi.btn_map, MSI_CLAW_MAPPINGS)
                self.assertEqual(atkbd.btn_map, MSI_CLAW_MAPPINGS)


if __name__ == "__main__":
    unittest.main()
