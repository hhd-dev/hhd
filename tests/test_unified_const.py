import unittest
from unittest.mock import patch

from adjustor.drivers.unified.const import get_profile_units


def dmi_values(board: str | None, product: str | None):
    return lambda name: board if name == "board_name" else product


class UnifiedProfileUnitsTest(unittest.TestCase):
    def get_units(
        self,
        board: str | None,
        product: str | None,
        ac: bool | None,
    ):
        with (
            patch(
                "adjustor.drivers.unified.const._read_dmi",
                side_effect=dmi_values(board, product),
            ),
            patch(
                "adjustor.drivers.unified.const.get_ac_status",
                return_value=ac,
            ),
            patch(
                "adjustor.drivers.unified.const.get_ac_status_fn",
                return_value="/sys/class/power_supply/AC/online",
            ),
        ):
            return get_profile_units()

    def test_board_match_takes_precedence(self):
        units = self.get_units("RC71L", "83N0", True)

        self.assertEqual(
            units,
            {
                "low-power": 10,
                "quiet": 10,
                "balanced": 15,
                "performance": 30,
            },
        )

    def test_product_match_is_used_as_fallback(self):
        units = self.get_units("LNVNB161216", "83N0", False)

        self.assertEqual(
            units,
            {
                "low-power": 8,
                "quiet": 8,
                "balanced": 16,
                "performance": 20,
            },
        )

    def test_dptc_board_class(self):
        units = self.get_units("AIR Plus", "unknown", True)

        self.assertEqual(
            units,
            {
                "low-power": 5,
                "quiet": 5,
                "balanced": 12,
                "performance": 18,
            },
        )

    def test_minisforum_v3_dptc_profile(self):
        units = self.get_units("HPPAC", "V3", True)

        self.assertEqual(
            units,
            {
                "low-power": 8,
                "quiet": 8,
                "balanced": 15,
                "performance": 25,
            },
        )

    def test_dptc_product_quirk(self):
        units = self.get_units("Default string", "G1618-05", False)

        self.assertEqual(
            units,
            {
                "low-power": 15,
                "quiet": 15,
                "balanced": 25,
                "performance": 45,
            },
        )

    def test_unknown_power_source_defaults_to_ac(self):
        units = self.get_units("GZ302EA", "unknown", None)

        self.assertEqual(
            units,
            {
                "low-power": 40,
                "quiet": 40,
                "balanced": 45,
                "performance": 65,
            },
        )

    def test_unknown_identity_returns_no_units(self):
        units = self.get_units("unknown-board", "unknown-product", True)

        self.assertIsNone(units)


if __name__ == "__main__":
    unittest.main()
