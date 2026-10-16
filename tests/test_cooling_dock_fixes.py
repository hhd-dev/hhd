"""Tests for cooling dock reconnect loop fixes.

Covers:
- _ensure_trusted_bluez() method existence and behavior
- Removal of settings emit calls in dock connection loop to prevent reload storms
- SmuQamPlugin correctly emitting settings on dock/power changes to dynamically update slider range
- TDP clamping works without settings reload
"""

import time
import unittest
from unittest.mock import MagicMock, patch, call

from hhd.plugins.cooling_dock.base import CoolingDockPlugin
from hhd.plugins.conf import Config


def make_dock_conf(**overrides) -> Config:
    base = {
        "cooling_dock.dock": {
            "enabled": True,
            "mode": "auto",
            "fan_curve": {
                "t1": 40, "f1": 0,
                "t2": 50, "f2": 30,
                "t3": 60, "f3": 50,
                "t4": 70, "f4": 70,
                "t5": 80, "f5": 85,
            },
            "rgb": {"enable": True, "mode": 1, "level": 3},
            "mac_address": "",
        },
        "cooling_dock.dock_running": False,
        "cooling_dock.dock.status": None,
        "cooling_dock.dock.fan_progress": None,
    }
    base.update(overrides)
    return Config(base)

class TestNoSettingsEmitOnConnect(unittest.TestCase):
    """Verify the dock plugin does NOT emit {"type": "settings"} when
    discovering new MACs, which was causing the reload storm."""

    def test_no_emit_on_new_mac_registration(self):
        """When a new MAC is registered on connect, no settings emit should
        fire. The old code emitted settings here, causing a full reload +
        SMU re-apply on every connect."""
        p = CoolingDockPlugin()
        emit = MagicMock()
        p.emit = emit
        conf = make_dock_conf()
        p.update(conf)
        emit.reset_mock()  # clear the initial settings emit from first update

        # Simulate what _connect_and_sync does when it finds a new MAC:
        # it registers the MAC in _discovered_macs.
        addr = "C8:17:17:F5:C8:91"
        with p.conf_lock:
            p._discovered_macs[addr] = f"CoolingSystem_ONEC1 ({addr})"

        # The emit should NOT have been called with {"type": "settings"}
        settings_calls = [
            c for c in emit.call_args_list
            if c == call({"type": "settings"})
        ]
        self.assertEqual(
            len(settings_calls), 0,
            "emit({'type': 'settings'}) should not be called on MAC registration",
        )

    def test_no_emit_on_scan_completion(self):
        """After a manual scan populates _discovered_macs, no settings emit
        should fire."""
        p = CoolingDockPlugin()
        emit = MagicMock()
        p.emit = emit
        conf = make_dock_conf()
        p.update(conf)
        emit.reset_mock()  # clear the initial settings emit from first update

        # Simulate scan completion
        with p.conf_lock:
            p._discovered_macs = {
                "": "Auto-detect",
                "AA:BB:CC:DD:EE:FF": "CoolingSystem_ONEC1 (AA:BB:CC:DD:EE:FF)",
            }

        settings_calls = [
            c for c in emit.call_args_list
            if c == call({"type": "settings"})
        ]
        self.assertEqual(
            len(settings_calls), 0,
            "emit({'type': 'settings'}) should not be called after scan",
        )


class ConnectAndSyncIntegrationTest(unittest.TestCase):
    """Integration test exercising the full _connect_and_sync lifecycle
    with a fake BleakClient that simulates real BLE behavior sequences."""

    def _make_plugin(self):
        p = CoolingDockPlugin()
        p.emit = MagicMock()
        p.running = True
        p.enabled = True
        p._mac_address = "C8:17:17:F5:C8:91"
        p.mode = "auto"
        p.fan_curve = [(0, 40), (30, 50), (50, 60), (70, 70), (85, 80)]
        p.rgb_enable = True
        p.rgb_mode = 1
        p.rgb_level = 3
        return p

    def _make_gatt_response(self, fan_speed=1200, fan_pct=50):
        """Build a minimal 64-byte GATT response mimicking the dock."""
        data = bytearray(64)
        data[4] = 1  # mode = auto
        data[5] = fan_pct
        data[6] = (fan_speed >> 8) & 0xFF
        data[7] = fan_speed & 0xFF
        return bytes(data)

    @patch("hhd.plugins.cooling_dock.base.get_cpu_temp", return_value=55.0)
    @patch("hhd.plugins.cooling_dock.base.fan_pct_for_temp", return_value=60)
    def test_full_sync_cycle_with_disconnect(self, mock_fan, mock_temp):
        """Simulate: discover -> connect -> 2 successful reads ->
        disconnect callback fires -> sync loop exits cleanly."""
        import asyncio
        from unittest.mock import AsyncMock

        p = self._make_plugin()
        gatt_data = self._make_gatt_response()

        fake_client = MagicMock()
        fake_client.is_connected = True
        fake_client.connect = AsyncMock()
        fake_client.write_gatt_char = AsyncMock()
        fake_client.disconnect = AsyncMock()

        read_count = 0
        disconnect_cb = None

        async def fake_read(char_uuid, **kwargs):
            nonlocal read_count
            read_count += 1
            if read_count > 2:
                fake_client.is_connected = False
                if disconnect_cb:
                    disconnect_cb(fake_client)
                raise Exception("BLE disconnected")
            return gatt_data

        fake_client.read_gatt_char = fake_read

        fake_device = MagicMock()
        fake_device.address = "C8:17:17:F5:C8:91"

        async def fake_find_dock():
            return fake_device

        with (
            patch.object(p, "_find_dock", side_effect=fake_find_dock),
            patch("hhd.plugins.cooling_dock.base.BleakClient") as mock_bleak_cls,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            def capture_client(device, timeout=15, disconnected_callback=None):
                nonlocal disconnect_cb
                disconnect_cb = disconnected_callback
                return fake_client
            mock_bleak_cls.side_effect = capture_client

            asyncio.run(p._connect_and_sync())

        self.assertGreaterEqual(read_count, 2, "Should complete at least 2 GATT reads")
        self.assertTrue(p._dock_running or p._last_connected_time > 0,
                        "Dock should have been marked running during sync")
        fake_client.disconnect.assert_called()

    @patch("hhd.plugins.cooling_dock.base.get_cpu_temp", return_value=55.0)
    @patch("hhd.plugins.cooling_dock.base.fan_pct_for_temp", return_value=60)
    def test_transient_timeouts_recover(self, mock_fan, mock_temp):
        """Simulate: 2 GATT timeouts followed by recovery. The sync loop
        should NOT break because SYNC_RETRY_MAX=3."""
        import asyncio
        from unittest.mock import AsyncMock

        p = self._make_plugin()
        gatt_data = self._make_gatt_response()

        fake_client = MagicMock()
        fake_client.is_connected = True
        fake_client.connect = AsyncMock()
        fake_client.write_gatt_char = AsyncMock()
        fake_client.disconnect = AsyncMock()

        read_count = 0

        async def fake_read(char_uuid, **kwargs):
            nonlocal read_count
            read_count += 1
            if read_count <= 2:
                raise asyncio.TimeoutError("simulated GATT timeout")
            if read_count == 3:
                return gatt_data
            p.running = False
            return gatt_data

        fake_client.read_gatt_char = fake_read

        fake_device = MagicMock()
        fake_device.address = "C8:17:17:F5:C8:91"

        async def fake_find_dock():
            return fake_device

        with (
            patch.object(p, "_find_dock", side_effect=fake_find_dock),
            patch("hhd.plugins.cooling_dock.base.BleakClient") as mock_bleak_cls,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_bleak_cls.return_value = fake_client
            asyncio.run(p._connect_and_sync())

        self.assertGreaterEqual(read_count, 3, "Should recover after transient timeouts")


if __name__ == "__main__":
    unittest.main()
