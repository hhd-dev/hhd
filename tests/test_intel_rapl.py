import unittest
from unittest.mock import MagicMock, mock_open, patch

from adjustor.drivers.intel_rapl import (
    PL1_POWER_MASK,
    get_power_exponent,
    replace_pl1_power,
    watts_to_raw,
)
from adjustor.hhd import AdjustorInitPlugin, autodetect


class IntelRaplHelpersTest(unittest.TestCase):
    def test_onexplayer3_known_values(self):
        self.assertEqual(get_power_exponent(0xA0E03), 3)
        self.assertEqual(watts_to_raw(25, 3), 0x0C8)
        self.assertEqual(watts_to_raw(30, 3), 0x0F0)
        self.assertEqual(watts_to_raw(35, 3), 0x118)

    def test_replace_pl1_preserves_every_other_bit(self):
        old = 0x000081A000DD80C8
        new = replace_pl1_power(old, 0x118)

        self.assertEqual(new, 0x000081A000DD8118)
        self.assertEqual(new & PL1_POWER_MASK, 0x118)
        self.assertEqual(new & ~PL1_POWER_MASK, old & ~PL1_POWER_MASK)


class IntelRaplAutodetectTest(unittest.TestCase):
    def test_onexplayer3_rapl_precedes_unified(self):
        rapl = MagicMock(name="intel_rapl")
        rapl.is_supported.return_value = True
        general = MagicMock(name="general")

        file_data = [
            "ONEXPLAYER 3",
            "ONEXPLAYER 3",
            "vendor_id : GenuineIntel\nmodel name : Intel Panther Lake",
        ]

        def fake_open(*args, **kwargs):
            if not file_data:
                raise AssertionError(f"Unexpected open: {args[0]}")
            return mock_open(read_data=file_data.pop(0))()

        with (
            patch("builtins.open", side_effect=fake_open),
            patch("adjustor.hhd.USE_UNIFIED", True),
            patch("adjustor.hhd.ASUS_DATA", {}),
            patch("adjustor.hhd.MSI_DATA", {}),
            patch(
                "adjustor.drivers.intel_rapl.IntelRaplDriverPlugin",
                return_value=rapl,
            ),
            patch(
                "adjustor.drivers.general.GeneralPowerPlugin",
                return_value=general,
            ),
            patch("adjustor.drivers.unified.UnifiedDriverPlugin") as unified,
        ):
            plugins = autodetect([])

        self.assertIs(plugins[0], rapl)
        self.assertIs(plugins[1], general)
        self.assertTrue(
            any(isinstance(plugin, AdjustorInitPlugin) for plugin in plugins)
        )
        unified.assert_not_called()


if __name__ == "__main__":
    unittest.main()
