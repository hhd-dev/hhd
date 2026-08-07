import unittest
from unittest.mock import mock_open, patch

from hhd.utils import get_ac_status


class AcStatusTest(unittest.TestCase):
    def read_status(self, status: str):
        with (
            patch("hhd.utils.os.path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=status)),
        ):
            return get_ac_status("/sys/class/power_supply/AC/online")

    def test_online_is_ac(self):
        self.assertIs(self.read_status("1\n"), True)

    def test_offline_is_dc(self):
        self.assertIs(self.read_status("0\n"), False)

    def test_invalid_status_is_unknown(self):
        self.assertIsNone(self.read_status("Discharging\n"))


if __name__ == "__main__":
    unittest.main()
