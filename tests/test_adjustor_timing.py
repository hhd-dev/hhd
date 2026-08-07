import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from adjustor.drivers.unified import APPLY_DELAY, SLEEP_DELAY, UnifiedDriverPlugin


class UnifiedTimingTest(unittest.TestCase):
    def setUp(self):
        self.plugin = UnifiedDriverPlugin.__new__(UnifiedDriverPlugin)
        self.plugin.profiles = SimpleNamespace(fn="platform-profile-0")
        self.plugin.tdp = object()
        self.plugin.queue_tdp = None
        self.plugin.emit = MagicMock()
        self.plugin.initialized = True

    def test_ac_change_uses_perf_counter(self):
        with (
            patch(
                "adjustor.drivers.unified.get_tdp_values",
                return_value=self.plugin.tdp,
            ),
            patch(
                "adjustor.drivers.unified.time.perf_counter", return_value=100.0
            ),
        ):
            self.plugin.notify([{"type": "acpi", "event": "dc"}])

        self.assertEqual(self.plugin.queue_tdp, 100.0 + APPLY_DELAY)

    def test_wakeup_uses_perf_counter(self):
        with patch(
            "adjustor.drivers.unified.time.perf_counter", return_value=100.0
        ):
            self.plugin.notify([{"type": "special", "event": "wakeup"}])

        self.assertEqual(self.plugin.queue_tdp, 100.0 + SLEEP_DELAY)


if __name__ == "__main__":
    unittest.main()
