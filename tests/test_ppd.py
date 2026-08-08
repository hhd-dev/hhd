import unittest
from unittest.mock import patch

from adjustor.drivers.gpu.ppd import BASE_NAME, create_interface


class PpdInterfaceTest(unittest.TestCase):
    def setUp(self):
        with patch("dbus.service.Object.__init__", return_value=None):
            self.ppd = create_interface(False)(None)

    def test_hhd_profile_update_is_not_echoed_as_external_request(self):
        with (
            patch("builtins.print") as output,
            patch.object(self.ppd, "PropertiesChanged") as changed,
        ):
            self.ppd.set_profile("balanced")

        self.assertEqual(self.ppd.profile, "balanced")
        output.assert_not_called()
        changed.assert_called_once_with(BASE_NAME, {"ActiveProfile": "balanced"}, [])

    def test_external_profile_update_is_forwarded_to_hhd(self):
        self.ppd.profile = "balanced"
        with (
            patch("builtins.print") as output,
            patch.object(self.ppd, "PropertiesChanged") as changed,
        ):
            self.ppd.Set(BASE_NAME, "ActiveProfile", "power-saver")

        self.assertEqual(self.ppd.profile, "power-saver")
        output.assert_called_once_with("power", flush=True)
        changed.assert_called_once_with(BASE_NAME, {"ActiveProfile": "power-saver"}, [])

    def test_duplicate_external_profile_update_is_ignored(self):
        with (
            patch("builtins.print") as output,
            patch.object(self.ppd, "PropertiesChanged") as changed,
        ):
            self.ppd.Set(BASE_NAME, "ActiveProfile", "power-saver")

        output.assert_not_called()
        changed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
