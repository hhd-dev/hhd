import time
import unittest
from unittest.mock import mock_open, patch, AsyncMock, MagicMock

from hhd.plugins.cooling_dock.base import (
    CoolingDockPlugin,
    _is_supported_device,
    SCAN_BACKOFF_MIN,
    SCAN_BACKOFF_MAX,
    SCAN_BACKOFF_FACTOR,
    GATT_OP_TIMEOUT,
    SYNC_RETRY_MAX,
    SYNC_RETRY_DELAY,
    RECONNECT_DELAY,
    DOCK_RUNNING_GRACE,
)
from hhd.plugins.cooling_dock.protocol import (
    build_write_chunks,
    WRITE_CMD,
    CHUNK_HEADERS,
    CHUNK_SIZE,
    WRITE_RETRY_MAX,
)
from hhd.plugins.conf import Config


def make_dock_conf(stale_running: bool = False) -> Config:
    return Config(
        {
            "cooling_dock.dock": {
                "enabled": True,
                "mode": "auto",
                "fan_curve": {
                    "t1": 40,
                    "f1": 0,
                    "t2": 50,
                    "f2": 30,
                    "t3": 60,
                    "f3": 50,
                    "t4": 70,
                    "f4": 70,
                    "t5": 80,
                    "f5": 85,
                },
                "rgb": {"enable": True, "mode": 1, "level": 3},
            },
            "cooling_dock.dock_running": stale_running,
            "cooling_dock.dock.status": (
                "Connected - Fan 50% (1000 RPM)" if stale_running else None
            ),
        }
    )


def make_dock_device(mac: str = "AA:BB:CC:DD:EE:FF"):
    """Build a BLEDevice-like object with an address for _find_dock tests."""
    device = MagicMock()
    device.address = mac
    device.name = "CoolingSystem_ONEC1"
    return device


class CoolingDockPluginTest(unittest.TestCase):
    def test_update_self_heals_stale_runtime_state(self):
        p = CoolingDockPlugin()
        # Simulate a previous session that saved dock_running=True while the
        # dock was connected. On startup the plugin must clear it so the
        # adjustor does not unlock TDP without an actual dock.
        conf = make_dock_conf(stale_running=True)
        p.update(conf)

        self.assertEqual(conf["cooling_dock.dock_running"].to(bool), False)
        self.assertEqual(conf["cooling_dock.dock.status"].to(str), "Disconnected")
        self.assertIsNone(conf["cooling_dock.dock.fan_progress"].conf)

    def test_update_does_not_rewrite_on_second_call(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        p.update(conf)
        conf.updated = False
        p.update(conf)
        self.assertFalse(conf.updated)

    def test_publish_dock_running_writes_on_change(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        p.update(conf)
        conf.updated = False

        p._publish_dock_running(True)
        self.assertEqual(conf["cooling_dock.dock_running"].to(bool), True)
        self.assertTrue(conf.updated)

    def test_publish_status_writes_status_and_progress(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        p.update(conf)
        conf.updated = False

        p._publish_status(
            "Connected - Fan 50% (1000 RPM)",
            {"value": 50, "max": 100, "unit": "%", "text": "Dock Fan"},
        )
        self.assertEqual(
            conf["cooling_dock.dock.status"].to(str),
            "Connected - Fan 50% (1000 RPM)",
        )
        self.assertEqual(
            conf["cooling_dock.dock.fan_progress"].to(dict),
            {"value": 50, "max": 100, "unit": "%", "text": "Dock Fan"},
        )
        self.assertTrue(conf.updated)

    def test_publish_status_skips_unchanged(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        p.update(conf)
        conf.updated = False

        # Same as the initial self-healed state: no write, config stays clean
        p._publish_status("Disconnected", None)
        self.assertFalse(conf.updated)


class ScanBackoffTest(unittest.TestCase):
    def test_initial_delay_is_min(self):
        p = CoolingDockPlugin()
        self.assertEqual(p._scan_delay, SCAN_BACKOFF_MIN)

    def test_backoff_increases(self):
        p = CoolingDockPlugin()
        # Simulate a failed scan cycle: the delay should increase
        initial = p._scan_delay
        p._scan_delay = min(p._scan_delay * SCAN_BACKOFF_FACTOR, SCAN_BACKOFF_MAX)
        self.assertEqual(p._scan_delay, initial * SCAN_BACKOFF_FACTOR)

    def test_backoff_caps_at_max(self):
        p = CoolingDockPlugin()
        # Run many backoff steps
        for _ in range(20):
            p._scan_delay = min(
                p._scan_delay * SCAN_BACKOFF_FACTOR, SCAN_BACKOFF_MAX
            )
        self.assertLessEqual(p._scan_delay, SCAN_BACKOFF_MAX)


class DmiGateTest(unittest.TestCase):
    def test_supported_device_superx(self):
        with patch(
            "builtins.open",
            mock_open(read_data="ONEXPLAYER SUPER X"),
        ):
            self.assertTrue(_is_supported_device())

    def test_supported_device_apex(self):
        with patch(
            "builtins.open",
            mock_open(read_data="ONEXPLAYER APEX"),
        ):
            self.assertTrue(_is_supported_device())

    def test_unsupported_device(self):
        with patch(
            "builtins.open",
            mock_open(read_data="ROG Ally RC71L"),
        ):
            self.assertFalse(_is_supported_device())

    def test_missing_dmi_file(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            self.assertFalse(_is_supported_device())


class StickyPairingTest(unittest.TestCase):
    def test_update_reads_mac_address(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        conf["cooling_dock.dock.mac_address"] = "AA:BB:CC:DD:EE:FF"
        p.update(conf)
        self.assertEqual(p._mac_address, "AA:BB:CC:DD:EE:FF")

    def test_forget_dock_clears_mac_and_forces_reconnect(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        conf["cooling_dock.dock.mac_address"] = "AA:BB:CC:DD:EE:FF"
        conf["cooling_dock.dock.forget_dock"] = True
        p.update(conf)

        self.assertEqual(p._mac_address, "")
        self.assertEqual(conf["cooling_dock.dock.mac_address"].to(str), "")
        self.assertFalse(conf["cooling_dock.dock.forget_dock"].to(bool))
        self.assertTrue(p._force_reconnect)


import asyncio


class FindDockTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the _find_dock discovery logic (Bugs 1 & 6)."""

    async def test_saved_mac_uses_find_device_by_address(self):
        """With a saved MAC, _find_dock should verify the dock is in range
        via find_device_by_address, not skip scanning entirely."""
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        conf["cooling_dock.dock.mac_address"] = "AA:BB:CC:DD:EE:FF"
        p.update(conf)

        mock_device = MagicMock()
        mock_device.address = "AA:BB:CC:DD:EE:FF"

        with patch(
            "hhd.plugins.cooling_dock.base.BleakScanner.find_device_by_address",
            new_callable=AsyncMock,
            return_value=mock_device,
        ) as mock_find:
            result = await p._find_dock()
            mock_find.assert_called_once_with("AA:BB:CC:DD:EE:FF", timeout=5)
            self.assertEqual(result.address, "AA:BB:CC:DD:EE:FF")

    async def test_saved_mac_not_in_range_returns_none(self):
        """If the saved MAC is not in range, find_device_by_address returns
        None and _find_dock returns None quickly (no 15s connect timeout)."""
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        conf["cooling_dock.dock.mac_address"] = "AA:BB:CC:DD:EE:FF"
        p.update(conf)

        with patch(
            "hhd.plugins.cooling_dock.base.BleakScanner.find_device_by_address",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakScanner.find_device_by_name",
            new_callable=AsyncMock,
            return_value=None,
        ), patch.object(
            p, "_find_dock_in_bluez_objects", return_value=None
        ), patch.object(
            p, "_bluez_start_discovery", new_callable=AsyncMock
        ):
            result = await p._find_dock()
            self.assertIsNone(result)

    async def test_no_dock_selected_returns_none(self):
        """Without a saved MAC, _find_dock should return None without scanning."""

class SyncLoopRetryTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the sync loop retry logic (Bug 2)."""

    async def test_transient_error_does_not_break_immediately(self):
        """A single GATT error should not break the connection — the loop
        should retry up to SYNC_RETRY_MAX times."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)

        # Mock the client and _find_dock to return a connected client
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        # First read fails, then all subsequent reads succeed
        mock_client.read_gatt_char = AsyncMock(
            side_effect=[Exception("transient BLE error")]
            + [b"\x00" * 64] * 20
        )
        mock_client.write_gatt_char = AsyncMock()

        # Stop the loop after a few successful cycles by setting running=False
        original_sleep = asyncio.sleep

        async def limited_sleep(t):
            if mock_client.read_gatt_char.call_count > 3:
                p.running = False
            await original_sleep(0)

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock, return_value=make_dock_device()
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", return_value=mock_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", side_effect=limited_sleep
        ):
            await p._connect_and_sync()
            # read_gatt_char should have been called more than once (error + retry)
            self.assertGreater(mock_client.read_gatt_char.call_count, 1)
            # Should NOT have disconnected due to errors — the single error
            # was retried and succeeded. Disconnect happened because we set
            # running=False to stop the loop.
            self.assertLess(
                mock_client.read_gatt_char.call_count, SYNC_RETRY_MAX * 3
            )

    async def test_breaks_after_max_consecutive_errors(self):
        """After SYNC_RETRY_MAX consecutive errors, the loop should break
        and disconnect."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.read_gatt_char = AsyncMock(
            side_effect=Exception("persistent BLE error")
        )
        mock_client.write_gatt_char = AsyncMock()

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock, return_value=make_dock_device()
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", return_value=mock_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", new_callable=AsyncMock
        ):
            await p._connect_and_sync()
            # Should have tried SYNC_RETRY_MAX times before breaking
            self.assertEqual(
                mock_client.read_gatt_char.call_count, SYNC_RETRY_MAX
            )
            # Should have disconnected
            mock_client.disconnect.assert_called_once()

    async def test_gatt_timeout_handled_as_retryable(self):
        """An asyncio.TimeoutError on GATT read should be caught and retried,
        not crash the loop."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        # First read times out, then all subsequent reads succeed
        mock_client.read_gatt_char = AsyncMock(
            side_effect=[asyncio.TimeoutError()] + [b"\x00" * 64] * 20
        )
        mock_client.write_gatt_char = AsyncMock()

        original_sleep = asyncio.sleep

        async def limited_sleep(t):
            if mock_client.read_gatt_char.call_count > 3:
                p.running = False
            await original_sleep(0)

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock, return_value=make_dock_device()
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", return_value=mock_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", side_effect=limited_sleep
        ):
            await p._connect_and_sync()
            # Should have retried after the timeout (more than 1 call)
            self.assertGreater(mock_client.read_gatt_char.call_count, 1)
            self.assertLess(
                mock_client.read_gatt_char.call_count, SYNC_RETRY_MAX * 3
            )


class DisconnectedCallbackTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the disconnected_callback (Bug 7)."""

    async def test_disconnected_callback_breaks_sync_loop(self):
        """When the BLE link drops, the disconnected_callback should fire
        and break the sync loop immediately."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.read_gatt_char = AsyncMock(return_value=b"\x00" * 64)
        mock_client.write_gatt_char = AsyncMock()

        # Capture the disconnected_callback passed to BleakClient
        captured_callback = {}

        def capture_client(addr, **kwargs):
            captured_callback["cb"] = kwargs.get("disconnected_callback")
            return mock_client

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock, return_value=make_dock_device()
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", side_effect=capture_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            # Make the first sleep trigger the disconnect callback
            async def trigger_disconnect(t):
                if captured_callback.get("cb"):
                    captured_callback["cb"](mock_client)

            mock_sleep.side_effect = trigger_disconnect

            await p._connect_and_sync()
            # The callback should have been set
            self.assertIsNotNone(captured_callback.get("cb"))
            # Should have disconnected
            mock_client.disconnect.assert_called_once()


class ReconnectDelayTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the reconnect delay after disconnect (Bug 3)."""

    async def test_delay_after_disconnect(self):
        """After disconnecting, _connect_and_sync should wait RECONNECT_DELAY
        seconds before returning (to let BlueZ clean up)."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.read_gatt_char = AsyncMock(
            side_effect=Exception("connection lost")
        )
        mock_client.write_gatt_char = AsyncMock()

        sleep_calls = []

        async def track_sleep(t):
            sleep_calls.append(t)

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock, return_value=make_dock_device()
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", return_value=mock_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", side_effect=track_sleep
        ):
            await p._connect_and_sync()
            # After SYNC_RETRY_MAX errors, the loop breaks and disconnects.
            # Then RECONNECT_DELAY 1-second sleeps should follow.
            one_second_sleeps = sum(1 for t in sleep_calls if t == 1)
            self.assertGreaterEqual(one_second_sleeps, RECONNECT_DELAY)


class ChunkedWriteProtocolTest(unittest.TestCase):
    """Tests for the chunked write protocol (PR #321)."""

    def test_build_write_chunks_headers_and_payload(self):
        """The state must be split into 3 x 20-byte frames with 0x1C/0x2C/0x3C
        headers and payload [0x02] + state[2:59]."""
        state = bytearray(range(64))
        chunks = build_write_chunks(state)

        self.assertEqual(len(chunks), 3)
        for i, chunk in enumerate(chunks):
            self.assertEqual(len(chunk), 20)
            self.assertEqual(chunk[0], CHUNK_HEADERS[i])

        # chunk_1 = [0x1C] + payload[0:19], payload[0] = 0x02
        self.assertEqual(chunks[0][1], WRITE_CMD)
        self.assertEqual(chunks[0][2], state[2])
        self.assertEqual(chunks[0][19], state[19])

        # chunk_2 = [0x2C] + payload[19:38] = state[20:39]
        self.assertEqual(chunks[1][1], state[20])
        self.assertEqual(chunks[1][19], state[38])

        # chunk_3 = [0x3C] + payload[38:57] = state[39:58]
        self.assertEqual(chunks[2][1], state[39])
        self.assertEqual(chunks[2][19], state[57])

    def test_build_write_chunks_carries_mode_byte(self):
        """A mode change at state[4] must appear in the first chunk."""
        state = bytearray(64)
        state[4] = 0xFE  # AUTO
        chunks = build_write_chunks(state)
        # payload[3] = state[4] -> chunk_1[4]
        self.assertEqual(chunks[0][4], 0xFE)

    def test_build_write_chunks_carries_curve(self):
        """The fan curve at state[23:41] must appear across the payload."""
        state = bytearray(64)
        for i in range(23, 41):
            state[i] = i
        chunks = build_write_chunks(state)
        # payload[k] = state[k+1]; state[23] = payload[22].
        # chunk_2 = [0x2C] + payload[19:38] -> payload[22] = chunk_2[4]
        self.assertEqual(chunks[1][4], 23)
        # state[40] = payload[39]; chunk_3 = [0x3C] + payload[38:57]
        # -> payload[39] = chunk_3[2]
        self.assertEqual(chunks[2][2], 40)


class WriteStateTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the plugin's chunked write path."""

    async def test_write_state_sends_three_chunks(self):
        """_write_state must send 3 sequential chunked writes, not one
        single 64-byte write."""
        p = CoolingDockPlugin()
        mock_client = MagicMock()
        mock_client.write_gatt_char = AsyncMock()

        state = bytearray(64)
        state[4] = 0x03

        with patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", new_callable=AsyncMock
        ):
            await p._write_state(mock_client, state)

        self.assertEqual(mock_client.write_gatt_char.call_count, 3)
        chunks = [c.args[1] for c in mock_client.write_gatt_char.call_args_list]
        self.assertEqual([c[0] for c in chunks], list(CHUNK_HEADERS))
        for chunk in chunks:
            self.assertEqual(len(chunk), 20)

    async def test_write_state_retries_on_error(self):
        """A transient write error should be retried up to WRITE_RETRY_MAX
        times before raising."""
        p = CoolingDockPlugin()
        mock_client = MagicMock()
        mock_client.write_gatt_char = AsyncMock(
            side_effect=Exception("In Progress")
        )

        with patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", new_callable=AsyncMock
        ):
            with self.assertRaises(Exception):
                await p._write_state(mock_client, bytearray(64))

        # Each attempt fails on the first chunk, so one write per attempt.
        self.assertEqual(
            mock_client.write_gatt_char.call_count, WRITE_RETRY_MAX
        )

    async def test_write_state_succeeds_after_retry(self):
        """If the first attempt fails but a later one succeeds, _write_state
        should not raise."""
        p = CoolingDockPlugin()
        mock_client = MagicMock()
        # First chunk write fails once, then succeeds
        calls = 0

        async def flaky_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise Exception("In Progress")

        mock_client.write_gatt_char = AsyncMock(side_effect=flaky_write)

        with patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", new_callable=AsyncMock
        ):
            await p._write_state(mock_client, bytearray(64))

        # 1 failed chunk (attempt 1) + 3 successful chunks (attempt 2) = 4
        self.assertEqual(mock_client.write_gatt_char.call_count, 4)


class DockDropdownTest(unittest.IsolatedAsyncioTestCase):
    """Tests for populating the 'Dock Device' dropdown."""

    async def test_connect_adds_mac_to_dropdown(self):
        """After a successful auto-connect, the dock's MAC must appear in
        the 'Dock Device' dropdown options."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)
        p.emit = MagicMock()

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.read_gatt_char = AsyncMock(
            return_value=b"\x00" * 64
        )
        mock_client.write_gatt_char = AsyncMock()

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock,
            return_value=make_dock_device(),
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", return_value=mock_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", new_callable=AsyncMock
        ):
            # Stop the loop after the first sync cycle
            original_sleep = asyncio.sleep

            async def stop_sleep(t):
                p.running = False

            with patch(
                "hhd.plugins.cooling_dock.base.asyncio.sleep",
                side_effect=stop_sleep,
            ):
                await p._connect_and_sync()

        self.assertIn("AA:BB:CC:DD:EE:FF", p._discovered_macs)
        # The MAC must be registered WITHOUT triggering a settings reload.
        # The old code emitted {"type": "settings"} here, which caused a
        # full settings reload + SMU re-apply on every connect cycle.
        settings_calls = [
            c for c in p.emit.call_args_list
            if c == unittest.mock.call({"type": "settings"})
        ]
        self.assertEqual(
            len(settings_calls), 0,
            "Settings emit should NOT fire on MAC registration (causes reload storm)",
        )

    def test_settings_includes_connected_mac(self):
        """settings() must include the connected MAC in the dropdown even if
        it was never scanned."""
        p = CoolingDockPlugin()
        p._mac_address = "AA:BB:CC:DD:EE:FF"
        p._discovered_macs = {"": "Auto-detect"}

        base = p.settings()
        opts = base["cooling_dock"]["dock"]["children"]["mac_address"]["options"]
        self.assertIn("AA:BB:CC:DD:EE:FF", opts)


class BluezConnectedDockTest(unittest.TestCase):
    """Tests for finding a connected-but-not-advertising dock via BlueZ."""

    def test_finds_connected_dock(self):
        """bluetoothctl devices + info should reveal a connected dock that
        is not advertising."""
        p = CoolingDockPlugin()
        devices_out = (
            "Device AA:BB:CC:DD:EE:FF CoolingSystem_ONEC1\n"
            "Device 11:22:33:44:55:66 SomeOtherDevice\n"
        )
        info_out = (
            "Device AA:BB:CC:DD:EE:FF\n"
            "\tName: CoolingSystem_ONEC1\n"
            "\tConnected: yes\n"
        )
        with patch(
            "subprocess.run",
            side_effect=[
                MagicMock(stdout=devices_out),
                MagicMock(stdout=info_out),
            ],
        ), patch(
            "dbus.SystemBus", side_effect=Exception("no bus in test")
        ):
            result = p._find_connected_dock_via_bluez()
        self.assertEqual(result.address, "AA:BB:CC:DD:EE:FF")

    def test_ignores_disconnected_dock(self):
        """A known but disconnected dock should not be returned."""
        p = CoolingDockPlugin()
        devices_out = "Device AA:BB:CC:DD:EE:FF CoolingSystem_ONEC1\n"
        info_out = (
            "Device AA:BB:CC:DD:EE:FF\n"
            "\tName: CoolingSystem_ONEC1\n"
            "\tConnected: no\n"
        )
        with patch(
            "subprocess.run",
            side_effect=[
                MagicMock(stdout=devices_out),
                MagicMock(stdout=info_out),
            ],
        ), patch(
            "dbus.SystemBus", side_effect=Exception("no bus in test")
        ):
            result = p._find_connected_dock_via_bluez()
        self.assertIsNone(result)

    def test_respects_target_mac(self):
        """When a target MAC is given, only that dock should be returned."""
        p = CoolingDockPlugin()
        devices_out = (
            "Device AA:BB:CC:DD:EE:FF CoolingSystem_ONEC1\n"
            "Device 11:22:33:44:55:66 CoolingSystem_ONEC1\n"
        )
        info_out = (
            "Device 11:22:33:44:55:66\n"
            "\tName: CoolingSystem_ONEC1\n"
            "\tConnected: yes\n"
        )
        with patch(
            "subprocess.run",
            side_effect=[
                MagicMock(stdout=devices_out),
                MagicMock(stdout=info_out),
            ],
        ), patch(
            "dbus.SystemBus", side_effect=Exception("no bus in test")
        ):
            result = p._find_connected_dock_via_bluez("11:22:33:44:55:66")
        self.assertEqual(result.address, "11:22:33:44:55:66")


class WriteOnChangeTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the write-only-on-change sync behavior."""

    async def test_writes_only_on_change(self):
        """The sync loop should write when the target changes, then skip
        writes while the target is unchanged."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.read_gatt_char = AsyncMock(return_value=b"\x00" * 64)
        mock_client.write_gatt_char = AsyncMock()

        original_sleep = asyncio.sleep

        async def limited_sleep(t):
            if mock_client.read_gatt_char.call_count > 4:
                p.running = False
            await original_sleep(0)

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock, return_value=make_dock_device()
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", return_value=mock_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", side_effect=limited_sleep
        ):
            await p._connect_and_sync()

        # 5 reads, but only 1 write (first cycle; target unchanged after)
        self.assertEqual(mock_client.read_gatt_char.call_count, 5)
        self.assertEqual(mock_client.write_gatt_char.call_count, 3)

    async def test_writes_again_when_mode_changes(self):
        """Changing the mode should trigger a new write."""
        p = CoolingDockPlugin()
        p.running = True
        conf = make_dock_conf()
        p.update(conf)

        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.read_gatt_char = AsyncMock(return_value=b"\x00" * 64)
        mock_client.write_gatt_char = AsyncMock()

        original_sleep = asyncio.sleep
        read_count = 0

        async def limited_sleep(t):
            nonlocal read_count
            if mock_client.read_gatt_char.call_count > 2 and read_count == 0:
                read_count = 1
                # Change the mode mid-loop to trigger a new write
                with p.conf_lock:
                    p.mode = "3"
            if mock_client.read_gatt_char.call_count > 5:
                p.running = False
            await original_sleep(0)

        with patch.object(
            p, "_find_dock", new_callable=AsyncMock, return_value=make_dock_device()
        ), patch(
            "hhd.plugins.cooling_dock.base.BleakClient", return_value=mock_client
        ), patch(
            "hhd.plugins.cooling_dock.base.asyncio.sleep", side_effect=limited_sleep
        ):
            await p._connect_and_sync()

        # Initial write + write after mode change = 2 writes (6 chunks)
        self.assertEqual(mock_client.write_gatt_char.call_count, 6)


class DisconnectGraceTest(unittest.TestCase):
    """Tests for the dock_running grace period (transient BLE flaps must
    not flip dock_running, which would make the adjustor re-apply TDP and
    cause SMU/ACPI spam + fan cycling)."""

    def test_does_not_publish_when_recently_connected(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        p.update(conf)
        p._dock_running = True
        p._last_connected_time = time.time()  # connected just now
        p._status = "Connected"
        conf["cooling_dock.dock_running"] = True
        conf.updated = False

        p._publish_disconnected_if_stale()

        # No publish: dock_running stays True, config not dirtied
        self.assertEqual(conf["cooling_dock.dock_running"].to(bool), True)
        self.assertFalse(conf.updated)

    def test_publishes_after_grace_period(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        p.update(conf)
        conf.updated = False
        p._dock_running = True
        p._last_connected_time = time.time() - DOCK_RUNNING_GRACE - 1
        p._status = "Connected"
        conf["cooling_dock.dock_running"] = True

        p._publish_disconnected_if_stale()

        self.assertEqual(conf["cooling_dock.dock_running"].to(bool), False)
        self.assertEqual(conf["cooling_dock.dock.status"].to(str), "Disconnected")
        self.assertTrue(conf.updated)


class ForgetDockTest(unittest.TestCase):
    """The 'Forget Dock' action must also unpair from BlueZ, otherwise the
    Trusted dock stays connected and fan control keeps working."""

    def test_forget_clears_mac_and_unpairs_bluez(self):
        p = CoolingDockPlugin()
        conf = make_dock_conf()
        conf["cooling_dock.dock.mac_address"] = "AA:BB:CC:DD:EE:FF"
        p.update(conf)

        with patch.object(p, "_forget_bluez_device") as mock_forget:
            conf["cooling_dock.dock.forget_dock"] = True
            p.update(conf)

        mock_forget.assert_called_once()
        self.assertEqual(conf["cooling_dock.dock.mac_address"].to(str), "")
        self.assertEqual(conf["cooling_dock.dock.forget_dock"].to(bool), False)

    def test_forget_bluez_device_removes_from_adapter(self):
        p = CoolingDockPlugin()
        p._mac_address = "AA:BB:CC:DD:EE:FF"

        objects = {
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF": {
                "org.bluez.Device1": {"Address": "AA:BB:CC:DD:EE:FF"}
            }
        }
        mock_iface = MagicMock()
        mock_iface.GetManagedObjects.return_value = objects

        with patch("dbus.Interface", return_value=mock_iface), patch(
            "dbus.SystemBus"
        ):
            p._forget_bluez_device()

        mock_iface.RemoveDevice.assert_called_once_with(
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        )


if __name__ == "__main__":
    unittest.main()