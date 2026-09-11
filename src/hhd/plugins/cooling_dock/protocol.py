"""CoolingStatus byte-array protocol for the CoolingSystem_ONEC1 BLE dock.

GATT: service 0xFFE0, characteristic 0xFFE1 (read+write), 64 bytes.
Read (From) and write (Fill) use DIFFERENT byte indices for some fields.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9b34fb"
DEVICE_NAME = "CoolingSystem_ONEC1"

TOTAL_BYTES = 64
WRITE_CMD = 0x02
READ_CMD = 0x10

# Chunked write: dock requires 3x20-byte frames with 0x1C/0x2C/0x3C headers
WRITE_PAYLOAD_SIZE = 58
CHUNK_HEADERS = (0x1C, 0x2C, 0x3C)
CHUNK_SIZE = 19
CHUNK_DELAY_S = 0.02
POST_WRITE_DELAY_S = 0.3
WRITE_RETRY_MAX = 3
WRITE_RETRY_DELAY_S = 0.5
ON_RETRY_DELAY_S = 0.5
MAX_ON_WRITE_RETRIES = 10


class DockMode(IntEnum):
    STOPPED = 0x00
    LEVEL_1 = 0x01
    LEVEL_2 = 0x02
    LEVEL_3 = 0x03
    LEVEL_4 = 0x04
    LEVEL_5 = 0x05
    AUTO = 0xFE
    MANUAL = 0xFF


@dataclass
class CoolingStatus:
    version: int = 0
    mode: int = 0
    fan_speed_percent: int = 0
    fan_speed: int = 0
    pump_speed_percent: int = 0
    pump_speed: int = 0
    water_flow: int = 0
    in_water_temp: int = 0
    out_water_temp: int = 0
    status_flag: int = 0
    rgb_mode: int = 0
    rgb_enable: bool = False
    rgb_light_level: int = 0
    rgb_r: int = 0
    rgb_g: int = 0
    rgb_b: int = 0
    fan_curve: list[tuple[int, int]] = field(
        default_factory=lambda: [(0, 0)] * 9
    )

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "CoolingStatus":
        if len(data) < 41:
            raise ValueError(f"Need >=41 bytes, got {len(data)}")
        s = cls()
        s.version = data[2]
        s.mode = data[4]
        s.fan_speed_percent = data[5]
        s.fan_speed = (data[6] << 8) | data[7]
        s.pump_speed_percent = data[8]
        s.pump_speed = (data[9] << 8) | data[10]
        s.water_flow = (data[11] << 8) | data[12]
        s.in_water_temp = data[13]
        s.out_water_temp = data[14]
        s.status_flag = data[15]
        s.rgb_mode = data[16]
        s.rgb_enable = data[17] == 1
        s.rgb_light_level = data[19]
        s.rgb_r = data[20]
        s.rgb_g = data[21]
        s.rgb_b = data[22]
        s.fan_curve = []
        idx = 23
        for _ in range(9):
            if idx + 1 < len(data):
                s.fan_curve.append((data[idx], data[idx + 1]))
                idx += 2
            else:
                s.fan_curve.append((0, 0))
        return s

    def to_write_bytes(self, current: bytes | bytearray) -> bytearray:
        out = bytearray(current)
        out[1] = WRITE_CMD
        out[2] = self.version or current[2]
        out[4] = self.mode

        out[15] = self.status_flag
        out[16] = self.rgb_mode
        out[17] = 1 if self.rgb_enable else 0
        out[19] = self.rgb_light_level
        out[20] = self.rgb_r
        out[21] = self.rgb_g
        out[22] = self.rgb_b
        idx = 23
        for f, t in self.fan_curve:
            out[idx] = f
            out[idx + 1] = t
            idx += 2
        return out

    def __str__(self) -> str:
        lines = [
            f"CoolingStatus v{self.version} mode=0x{self.mode:02X}",
            f"  Fan:   {self.fan_speed_percent:3d}%  {self.fan_speed:5d} RPM",
            f"  Pump:  {self.pump_speed_percent:3d}%  {self.pump_speed:5d} RPM",
            f"  Flow:  {self.water_flow}",
            f"  Temp:  in={self.in_water_temp}C  out={self.out_water_temp}C",
            f"  RGB:   mode=0x{self.rgb_mode:02X} en={self.rgb_enable} lvl={self.rgb_light_level} ({self.rgb_r},{self.rgb_g},{self.rgb_b})",
            f"  Flag:  0x{self.status_flag:02X}",
            "  Curve:",
        ]
        for i, (f, t) in enumerate(self.fan_curve, 1):
            lines.append(f"    f{i}={f:3d}% @ {t:3d}C")
        return "\n".join(lines)


def build_write_chunks(state: bytes | bytearray) -> list[bytes]:
    """Split a modified 64-byte state into the 3 chunked write frames.

    The dock only accepts writes as 3 x 20-byte frames with 0x1C/0x2C/0x3C
    headers; a single 64-byte write is silently ignored. The 58-byte payload
    is ``[0x02] + state[2:59]`` (byte 57 of the payload is unused).
    """
    payload = bytearray(WRITE_PAYLOAD_SIZE)
    payload[0] = WRITE_CMD
    payload[1:] = state[2:59]
    chunks = []
    for i, header in enumerate(CHUNK_HEADERS):
        start = i * CHUNK_SIZE
        end = start + CHUNK_SIZE
        chunks.append(bytes([header]) + bytes(payload[start:end]))
    return chunks
