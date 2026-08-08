import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hhd.plugins import Config
from hhd.plugins.overlay import OverlayPlugin


class OverlayDpmsTest(unittest.TestCase):
    def setUp(self):
        self.plugin = OverlayPlugin()
        self.plugin.ovf = SimpleNamespace(gsconf={}, launch_overlay=MagicMock())

    def test_dpms_setting_is_not_exposed(self):
        with (
            patch(
                "hhd.plugins.overlay.get_touchscreen_quirk",
                return_value=(False, None),
            ),
            patch("hhd.plugins.overlay.has_touchscreen", return_value=True),
        ):
            settings = self.plugin.settings()

        self.assertNotIn("dpms", settings["gamemode"]["gamescope"]["children"])

    def test_dpms_capability_always_enables_dpms(self):
        self.plugin.emit = MagicMock()
        conf = Config({"gamemode.gamescope.dpms": False})

        with patch("hhd.plugins.overlay.SUPPORTS_DPMS", True):
            self.plugin.update(conf)

        self.assertTrue(self.plugin.ovf.gsconf["dpms"])


if __name__ == "__main__":
    unittest.main()
