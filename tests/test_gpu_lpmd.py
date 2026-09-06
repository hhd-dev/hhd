import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import yaml

from adjustor.drivers.gpu import (
    LPMD_BUS,
    LPMD_INTERFACE,
    LPMD_PATH,
    get_lpmd,
    get_lpmd_mode,
    set_lpmd,
)


class IntelLpmdTest(unittest.TestCase):
    def test_setting_is_nested_under_manual_cpu_settings(self):
        settings_path = (
            Path(__file__).parents[1] / "src/adjustor/drivers/gpu/settings.yml"
        )
        settings = yaml.safe_load(settings_path.read_text())
        children = settings["enabled"]["children"]
        lpmd = children["mode"]["modes"]["manual"]["children"]["lpmd"]

        self.assertNotIn("lpmd", children)
        self.assertEqual(lpmd["title"], "Intel Low Power Mode")
        self.assertEqual(lpmd["tags"], ["ordinal"])
        self.assertEqual(
            lpmd["options"], {"off": "Off", "auto": "Auto", "on": "On"}
        )

    def test_initializes_only_when_dbus_name_has_owner(self):
        bus = MagicMock()
        proxy = MagicMock()
        bus.get_object.return_value = proxy
        dbus = SimpleNamespace(SystemBus=MagicMock(return_value=bus))

        with patch.dict(sys.modules, {"dbus": dbus}):
            bus.name_has_owner.return_value = False
            self.assertIsNone(get_lpmd())
            bus.get_object.assert_not_called()

            bus.name_has_owner.return_value = True
            self.assertIs(get_lpmd(), proxy)

        bus.name_has_owner.assert_called_with(LPMD_BUS)
        bus.get_object.assert_called_once_with(LPMD_BUS, LPMD_PATH)

    def test_auto_uses_lpmd_auto_only_for_power_saving_profiles(self):
        for target in ("power", "power-saver", "powersave", "low-power", "quiet"):
            with self.subTest(target=target):
                self.assertEqual(get_lpmd_mode("auto", "off", target), "LPM_AUTO")

        for target in ("balanced", "performance"):
            with self.subTest(target=target):
                self.assertEqual(
                    get_lpmd_mode("auto", "on", target), "LPM_FORCE_OFF"
                )

    def test_manual_mode_applies_selected_lpmd_policy(self):
        self.assertEqual(
            get_lpmd_mode("manual", "on", "performance"), "LPM_FORCE_ON"
        )
        self.assertEqual(get_lpmd_mode("manual", "auto", "balanced"), "LPM_AUTO")
        self.assertEqual(
            get_lpmd_mode("manual", "off", "power"), "LPM_FORCE_OFF"
        )

    def test_calls_lpmd_method_on_expected_interface(self):
        lpmd = MagicMock()
        method = lpmd.get_dbus_method.return_value

        set_lpmd(lpmd, "LPM_AUTO")

        lpmd.get_dbus_method.assert_called_once_with("LPM_AUTO", LPMD_INTERFACE)
        method.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
