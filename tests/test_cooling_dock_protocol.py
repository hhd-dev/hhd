"""Protocol-level tests for the CoolingSystem_ONEC1 BLE dock.

Covers the byte-level wire format (CoolingStatus.From/.Fill recovered from
CompatLayerCT.exe JIT disassembly), the 3x20-byte chunked write framing,
and the fan curve interpolation helper.
"""

import unittest
from unittest.mock import mock_open, patch

from hhd.plugins.cooling_dock.base import fan_pct_for_temp, get_cpu_temp
from hhd.plugins.cooling_dock.protocol import (
    CHUNK_DELAY_S,
    CHUNK_HEADERS,
    CHUNK_SIZE,
    READ_CMD,
    SERVICE_UUID,
    TOTAL_BYTES,
    WRITE_CMD,
    WRITE_PAYLOAD_SIZE,
    CoolingStatus,
    DockMode,
    build_write_chunks,
)


def _sample_status_bytes() -> bytearray:
    """Build a realistic 64-byte GATT notification frame."""
    data = bytearray(TOTAL_BYTES)
    data[0] = 0xA5  # sync/header byte
    data[1] = READ_CMD
    data[2] = 3  # version
    data[4] = DockMode.AUTO
    data[5] = 55  # fan_speed_percent
    data[6] = 0x04  # fan_speed hi (0x04B0 = 1200 RPM)
    data[7] = 0xB0  # fan_speed lo
    data[8] = 80  # pump_speed_percent
    data[9] = 0x0E  # pump_speed hi (0x0E74 = 3700 RPM)
    data[10] = 0x74  # pump_speed lo
    data[11] = 0x01  # water_flow hi (0x0102 = 258)
    data[12] = 0x02  # water_flow lo
    data[13] = 32  # in_water_temp
    data[14] = 35  # out_water_temp
    data[15] = 0x07  # status_flag
    data[16] = 0x02  # rgb_mode
    data[17] = 1  # rgb_enable
    data[19] = 3  # rgb_light_level
    data[20] = 255  # r
    data[21] = 128  # g
    data[22] = 0  # b
    # Fan curve: 9 points starting at offset 23
    curve = [(30, 40), (40, 50), (50, 60), (60, 70), (70, 80),
             (80, 90), (90, 100), (100, 100), (110, 100)]
    for i, (f, t) in enumerate(curve):
        data[23 + i * 2] = f
        data[24 + i * 2] = t
    return data


class DockModeTest(unittest.TestCase):
    def test_mode_values_match_wire_protocol(self):
        self.assertEqual(DockMode.STOPPED, 0x00)
        self.assertEqual(DockMode.LEVEL_1, 0x01)
        self.assertEqual(DockMode.LEVEL_5, 0x05)
        self.assertEqual(DockMode.AUTO, 0xFE)
        self.assertEqual(DockMode.MANUAL, 0xFF)

    def test_modes_are_ints(self):
        for mode in DockMode:
            self.assertIsInstance(mode, int)


class GattConstantsTest(unittest.TestCase):
    def test_uuids(self):
        self.assertEqual(SERVICE_UUID, "0000ffe0-0000-1000-8000-00805f9b34fb")
        from hhd.plugins.cooling_dock.protocol import CHAR_UUID, NOTIFY_UUID
        self.assertEqual(CHAR_UUID, "0000ffe1-0000-1000-8000-00805f9b34fb")
        self.assertEqual(NOTIFY_UUID, "0000ffe4-0000-1000-8000-00805f9b34fb")

    def test_chunk_framing_constants(self):
        self.assertEqual(CHUNK_HEADERS, (0x1C, 0x2C, 0x3C))
        self.assertEqual(CHUNK_SIZE, 19)
        self.assertEqual(WRITE_PAYLOAD_SIZE, 58)
        self.assertEqual(3 * CHUNK_SIZE, WRITE_PAYLOAD_SIZE - 1)
        self.assertGreater(CHUNK_DELAY_S, 0)


class CoolingStatusFromBytesTest(unittest.TestCase):
    def test_parses_all_fields(self):
        s = CoolingStatus.from_bytes(bytes(_sample_status_bytes()))
        self.assertEqual(s.version, 3)
        self.assertEqual(s.mode, DockMode.AUTO)
        self.assertEqual(s.fan_speed_percent, 55)
        self.assertEqual(s.fan_speed, 1200)
        self.assertEqual(s.pump_speed_percent, 80)
        self.assertEqual(s.pump_speed, 3700)
        self.assertEqual(s.water_flow, 258)
        self.assertEqual(s.in_water_temp, 32)
        self.assertEqual(s.out_water_temp, 35)
        self.assertEqual(s.status_flag, 0x07)
        self.assertEqual(s.rgb_mode, 0x02)
        self.assertTrue(s.rgb_enable)
        self.assertEqual(s.rgb_light_level, 3)
        self.assertEqual((s.rgb_r, s.rgb_g, s.rgb_b), (255, 128, 0))
        self.assertEqual(len(s.fan_curve), 9)
        self.assertEqual(s.fan_curve[0], (30, 40))
        self.assertEqual(s.fan_curve[8], (110, 100))

    def test_rgb_enable_is_strict_one(self):
        data = _sample_status_bytes()
        data[17] = 2  # any value other than 1 means disabled
        s = CoolingStatus.from_bytes(bytes(data))
        self.assertFalse(s.rgb_enable)

    def test_short_frame_raises(self):
        with self.assertRaises(ValueError):
            CoolingStatus.from_bytes(bytes(40))

    def test_minimum_length_accepted(self):
        s = CoolingStatus.from_bytes(bytes(41))
        self.assertEqual(s.version, 0)
        self.assertEqual(s.fan_curve[-1], (0, 0))

    def test_minimum_length_frame_parses_full_curve(self):
        """41 bytes is exactly enough for the header + 9 curve points."""
        data = _sample_status_bytes()
        s = CoolingStatus.from_bytes(bytes(data[:41]))
        self.assertEqual(len(s.fan_curve), 9)
        self.assertEqual(s.fan_curve[0], (30, 40))
        self.assertEqual(s.fan_curve[-1], (110, 100))


class CoolingStatusWriteTest(unittest.TestCase):
    def test_write_sets_cmd_and_preserves_version(self):
        current = _sample_status_bytes()
        s = CoolingStatus.from_bytes(bytes(current))
        s.mode = DockMode.LEVEL_3
        out = s.to_write_bytes(current)
        self.assertEqual(out[1], WRITE_CMD)
        self.assertEqual(out[2], 3)  # version preserved
        self.assertEqual(out[4], DockMode.LEVEL_3)

    def test_write_zero_version_uses_current(self):
        current = _sample_status_bytes()
        s = CoolingStatus.from_bytes(bytes(current))
        s.version = 0
        out = s.to_write_bytes(current)
        self.assertEqual(out[2], 3)  # falls back to current version

    def test_read_only_bytes_not_touched_by_fields(self):
        """fan/pump percent+speed (5..10) come from the current snapshot."""
        current = _sample_status_bytes()
        s = CoolingStatus.from_bytes(bytes(current))
        s.mode = DockMode.MANUAL
        out = s.to_write_bytes(current)
        self.assertEqual(out[5], current[5])
        self.assertEqual(out[6], current[6])
        self.assertEqual(out[7], current[7])
        self.assertEqual(out[8], current[8])

    def test_roundtrip_from_write_to_parse(self):
        current = _sample_status_bytes()
        s = CoolingStatus.from_bytes(bytes(current))
        s.mode = DockMode.LEVEL_2
        s.rgb_r = 10
        s.rgb_g = 20
        s.rgb_b = 30
        out = s.to_write_bytes(current)
        parsed = CoolingStatus.from_bytes(bytes(out))
        self.assertEqual(parsed.mode, DockMode.LEVEL_2)
        self.assertEqual((parsed.rgb_r, parsed.rgb_g, parsed.rgb_b), (10, 20, 30))
        self.assertEqual(parsed.fan_curve, s.fan_curve)


class BuildWriteChunksTest(unittest.TestCase):
    def test_produces_three_twenty_byte_chunks(self):
        state = bytes(_sample_status_bytes())
        chunks = build_write_chunks(state)
        self.assertEqual(len(chunks), 3)
        for c in chunks:
            self.assertEqual(len(c), CHUNK_SIZE + 1)  # header + payload

    def test_chunk_headers_in_order(self):
        chunks = build_write_chunks(bytes(_sample_status_bytes()))
        self.assertEqual([c[0] for c in chunks], list(CHUNK_HEADERS))

    def test_payload_reassembly_matches_state(self):
        """payload == [0x02] + state[2:59]; verify per-chunk."""
        state = bytes(_sample_status_bytes())
        chunks = build_write_chunks(state)
        payload = bytearray(WRITE_PAYLOAD_SIZE)
        payload[0] = WRITE_CMD
        payload[1:] = state[2:59]
        pos = 0
        for c in chunks:
            body = c[1:]
            self.assertEqual(body, bytes(payload[pos:pos + CHUNK_SIZE]))
            pos += CHUNK_SIZE

    def test_modified_field_lands_in_correct_chunk(self):
        """mode is state[4] -> payload[3] -> chunk 0."""
        state = bytearray(_sample_status_bytes())
        state[4] = DockMode.LEVEL_5
        chunks = build_write_chunks(bytes(state))
        self.assertEqual(chunks[0][1 + 3], DockMode.LEVEL_5)

    def test_rgb_bytes_land_in_chunk_1(self):
        """rgb fields are state[19..22] -> payload[18..21]: chunk 0 [18],
        chunk 1 [0..2]."""
        state = bytearray(_sample_status_bytes())
        state[19] = 7
        state[22] = 9
        chunks = build_write_chunks(bytes(state))
        self.assertEqual(chunks[0][1 + 18], 7)
        self.assertEqual(chunks[1][1 + 2], 9)


class FanCurveTest(unittest.TestCase):
    # Curve points are (fan_pct, temp): 0% @40C, 30% @50C, ... 85% @80C
    CURVE = [(0, 40), (30, 50), (50, 60), (70, 70), (85, 80)]

    def test_empty_curve_returns_zero(self):
        self.assertEqual(fan_pct_for_temp(50, []), 0)

    def test_below_first_point_clamps_to_first_fan(self):
        self.assertEqual(fan_pct_for_temp(-10, self.CURVE), 0)
        self.assertEqual(fan_pct_for_temp(40, self.CURVE), 0)

    def test_above_last_point_clamps_to_last_fan(self):
        self.assertEqual(fan_pct_for_temp(200, self.CURVE), 85)

    def test_exact_point_returns_exact_value(self):
        self.assertEqual(fan_pct_for_temp(50, self.CURVE), 30)
        self.assertEqual(fan_pct_for_temp(60, self.CURVE), 50)
        self.assertEqual(fan_pct_for_temp(85, self.CURVE), 85)

    def test_interpolates_linearly_between_points(self):
        # Between (0,40) and (30,50): midpoint 45C -> 15%
        self.assertEqual(fan_pct_for_temp(45, self.CURVE), 15)
        # Between (30,50) and (50,60): midpoint 55C -> 40%
        self.assertEqual(fan_pct_for_temp(55, self.CURVE), 40)
        # Between (70,70) and (85,80): midpoint 75C -> 77.5% -> truncates to 77
        self.assertEqual(fan_pct_for_temp(75, self.CURVE), 77)

    def test_unsorted_curve_is_sorted(self):
        shuffled = [(85, 80), (0, 40), (70, 70), (50, 60), (30, 50)]
        self.assertEqual(fan_pct_for_temp(45, shuffled), 15)

    def test_duplicate_temps_do_not_crash(self):
        curve = [(10, 40), (30, 50), (60, 50), (90, 90)]
        # Boundary at the duplicated temp resolves via the earlier segment
        self.assertEqual(fan_pct_for_temp(50, curve), 30)
        # Just past it interpolates toward the next point: 60 + (5/40)*30
        self.assertEqual(fan_pct_for_temp(55, curve), 63)

    def test_single_point_curve_is_constant(self):
        self.assertEqual(fan_pct_for_temp(10, [(100, 60)]), 100)
        self.assertEqual(fan_pct_for_temp(90, [(100, 60)]), 100)


class GetCpuTempTest(unittest.TestCase):
    def _fake_hwmon(self, entries):
        """entries: dict of hwmon dir name -> (name, {tempN_input: millidegrees})"""
        import os

        def fake_join(*parts):
            return "/".join(parts)

        def fake_listdir(path):
            if path == "/sys/class/hwmon":
                return list(entries.keys())
            if os.path.basename(path) in entries:
                name, temps = entries[os.path.basename(path)]
                return list(temps.keys()) + ["name"]
            raise FileNotFoundError(path)

        def fake_open(path, mode="r"):
            base = os.path.basename(path)
            parent = os.path.basename(os.path.dirname(path))
            if parent in entries:
                name, temps = entries[parent]
                if base == "name":
                    return mock_open(read_data=name)()
                if base in temps:
                    return mock_open(read_data=str(temps[base]))()
            raise FileNotFoundError(path)

        return fake_listdir, fake_open

    def test_reads_highest_k10temp_sensor(self):
        listdir, open_fn = self._fake_hwmon({
            "hwmon0": ("k10temp", {"temp1_input": 55000, "temp2_input": 67500}),
            "hwmon1": ("nvme", {"temp1_input": 90000}),  # ignored device
        })
        with patch("os.path.exists", return_value=True), \
             patch("os.listdir", side_effect=listdir), \
             patch("builtins.open", side_effect=open_fn):
            self.assertEqual(get_cpu_temp(), 67.5)

    def test_prefers_highest_across_devices(self):
        listdir, open_fn = self._fake_hwmon({
            "hwmon0": ("k10temp", {"temp1_input": 55000}),
            "hwmon1": ("oxpec", {"temp1_input": 61000}),
        })
        with patch("os.path.exists", return_value=True), \
             patch("os.listdir", side_effect=listdir), \
             patch("builtins.open", side_effect=open_fn):
            self.assertEqual(get_cpu_temp(), 61.0)

    def test_missing_sysfs_returns_zero(self):
        with patch("os.path.exists", return_value=False):
            self.assertEqual(get_cpu_temp(), 0.0)

    def test_unreadable_device_is_skipped(self):
        import os

        real_listdir = os.listdir

        def listdir(path):
            if path == "/sys/class/hwmon":
                return ["hwmon0", "hwmon1"]
            if path.endswith("hwmon0"):
                raise PermissionError(path)
            return real_listdir(path)

        def open_fn(path, mode="r"):
            if "hwmon1" in path:
                if path.endswith("name"):
                    return mock_open(read_data="k10temp")()
                return mock_open(read_data="48000")()
            raise FileNotFoundError(path)

        with patch("os.path.exists", return_value=True), \
             patch("os.listdir", side_effect=listdir), \
             patch("builtins.open", side_effect=open_fn):
            self.assertEqual(get_cpu_temp(), 48.0)


if __name__ == "__main__":
    unittest.main()
