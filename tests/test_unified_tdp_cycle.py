import unittest
from unittest.mock import MagicMock

from adjustor.drivers.unified import PPData, UnifiedDriverPlugin


DPTC = PPData(
    fn="amd-dptc",
    pp="platform-profile-1",
    provider="amd-dptc",
    has_custom=True,
    profiles=(
        ("low-power", "Low Power"),
        ("balanced", "Balanced"),
        ("performance", "Performance"),
        ("custom", "Custom"),
    ),
)

ASUS = PPData(
    fn="asus-wmi",
    pp="platform-profile-0",
    provider="asus-wmi",
    has_custom=False,
    profiles=(
        ("quiet", "Silent"),
        ("balanced", "Performance"),
        ("performance", "Turbo"),
    ),
)


class UnifiedTdpCycleTest(unittest.TestCase):
    def make_plugin(self, profiles, tdp=True):
        plugin = UnifiedDriverPlugin.__new__(UnifiedDriverPlugin)
        plugin.profiles = profiles
        plugin.tdp = object() if tdp else None
        plugin.mode = None
        plugin.new_mode = None
        plugin.cycle_tdp = False
        plugin.emit = MagicMock()
        return plugin

    def cycle(self, plugin, mode, event="tdp_cycle"):
        plugin.mode = mode
        plugin.new_mode = None
        plugin.emit.reset_mock()
        plugin.notify([{"type": "special", "event": event}])
        return plugin.new_mode

    def test_cycles_through_low_power(self):
        plugin = self.make_plugin(DPTC)

        self.assertEqual(self.cycle(plugin, "low-power"), "balanced")
        self.assertEqual(self.cycle(plugin, "balanced"), "performance")
        self.assertEqual(self.cycle(plugin, "performance"), "custom")
        self.assertEqual(self.cycle(plugin, "custom"), "low-power")
        plugin.emit.assert_called_once_with(
            {"type": "special", "event": "tdp_cycle_quiet"}
        )

    def test_cycles_through_quiet(self):
        plugin = self.make_plugin(ASUS, tdp=False)

        self.assertEqual(self.cycle(plugin, "quiet"), "balanced")
        self.assertEqual(self.cycle(plugin, "performance"), "quiet")

    def test_skips_custom_without_tdp(self):
        plugin = self.make_plugin(DPTC, tdp=False)

        self.assertEqual(self.cycle(plugin, "performance"), "low-power")

    def test_unknown_mode_goes_to_balanced(self):
        plugin = self.make_plugin(DPTC)

        self.assertEqual(self.cycle(plugin, None), "balanced")

    def test_xbox_y_needs_setting(self):
        plugin = self.make_plugin(DPTC)

        self.assertIsNone(self.cycle(plugin, "balanced", "xbox_y_internal"))
        plugin.emit.assert_not_called()

        plugin.cycle_tdp = True
        self.assertEqual(
            self.cycle(plugin, "balanced", "xbox_y_internal"), "performance"
        )


if __name__ == "__main__":
    unittest.main()
