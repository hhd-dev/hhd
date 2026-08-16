import unittest
from unittest.mock import patch

from hhd.controller.lib import hide


class TestHideRule(unittest.TestCase):
    def test_targeted_usb_rule_hides_input_and_raw_interfaces(self):
        rule = hide.get_hide_rule("input42", "3-1", 0x17EF, 0x61EB, False)

        self.assertIn('KERNELS=="input42"', rule)
        self.assertIn('ENV{ID_CLASS}="hhd-hidden"', rule)
        self.assertIn('ENV{ID_INPUT_JOYSTICK}="0"', rule)
        self.assertIn('SUBSYSTEM=="hidraw", KERNELS=="3-1"', rule)
        self.assertIn('KERNEL=="hiddev[0-9]*", KERNELS=="3-1"', rule)

    def test_hide_all_rule_matches_usb_vid_pid(self):
        rule = hide.get_hide_rule("input42", "3-1", 0x17EF, 0x61EB, True)

        self.assertIn(
            'ENV{ID_BUS}=="usb", ATTRS{id/vendor}=="17ef"', rule
        )
        self.assertIn(
            'SUBSYSTEMS=="usb", ATTRS{idVendor}=="17ef", '
            'ATTRS{idProduct}=="61eb"',
            rule,
        )

    def test_non_usb_rule_only_hides_input_nodes(self):
        rule = hide.get_hide_rule("input42", None, 0x1234, 0x5678, False)

        self.assertNotIn('SUBSYSTEM=="hidraw"', rule)
        self.assertNotIn('KERNEL=="hiddev', rule)

    def test_usb_device_returns_kernel_name_and_parent(self):
        syspath = "/devices/pci/usb1/1-2/1-2:1.0/input/input42/event7"

        self.assertEqual(
            hide.get_usb_device(syspath),
            ("1-2", "/devices/pci/usb1/1-2"),
        )

    def test_unhide_retriggers_usb_parent(self):
        syspath = "/devices/pci/usb1/1-2/1-2:1.0/input/input42/event7"

        with (
            patch.object(hide, "HIDE_ALL", False),
            patch.object(hide, "get_device_info", return_value=syspath),
            patch.object(hide.os, "remove"),
            patch.object(hide, "reload_children") as reload_children,
        ):
            hide.unhide_gamepad("/dev/input/event7", "input42")

        reload_children.assert_called_once_with(
            "/devices/pci/usb1/1-2"
        )


if __name__ == "__main__":
    unittest.main()
