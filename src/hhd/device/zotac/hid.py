import logging
import time
from typing import Sequence

from hhd.controller import Button, Event, can_read
from hhd.controller.lib.common import get_button
from hhd.controller.physical.hidraw import GenericGamepadHidraw

from .const import (
    CMD_INTERFACE,
    DIAL_INTERFACE,
    DIAL_LEFT_CCW,
    DIAL_LEFT_CW,
    DIAL_REPORT,
    DIAL_RIGHT_CCW,
    DIAL_RIGHT_CW,
    ZOTAC_PID,
    ZOTAC_VIDS,
)

logger = logging.getLogger(__name__)

# Command packets (USB interface 3): 64 bytes, [0] 0xE1, [1] 0, [2] sequence,
# [3] 0x3C, [4] command, [5:62] payload, [62:64] CRC16 (big endian) over
# bytes 4-61. Sent with a leading 0 report id. Replies echo the command.
CMD_HEADER = 0xE1
CMD_PAYLOAD_SIZE = 0x3C

CMD_SET_MAPPING = 0xA1
CMD_GET_MAPPING = 0xA2
CMD_SET_VIBRATION = 0xA9
CMD_SET_RGB = 0xAD

RGB_COLOR = 0x00
RGB_SPEED = 0x01
RGB_EFFECT = 0x02
RGB_BRIGHTNESS = 0x03

EFFECT_RAINBOW = 0x00  # rainbow travelling along the band ("spiral")
EFFECT_BREATHE = 0x01
EFFECT_STARS = 0x02
EFFECT_FADE = 0x03  # whole band cycles through colors ("rainbow")
EFFECT_SOLID = 0x04  # called "Dance" by Zotac, solid with host brightness
EFFECT_FLASH = 0x05
EFFECT_WINK = 0x06
EFFECT_RANDOM = 0x07
EFFECT_OFF = 0xF0

# The firmware drops commands sent right after an effect change
EFFECT_DELAY = 0.5
WRITE_DELAY = 0.02
REPLY_TIMEOUT_MS = 200

# Button mapping sources and the 13 byte target that follows them
SRC_M1 = 0x01  # right hand
SRC_M2 = 0x02  # left hand
HID_KEY_F13 = 0x68
HID_KEY_F14 = 0x69
HID_KEY_F21 = 0x70
HID_KEY_F22 = 0x71

# Mapping target: gamepad bits [0:4], modifier [4], keys [6:12], mouse [12]
TARGET_GAMEPAD_BITS = {
    "dpad_up": (0, 0x01),
    "dpad_down": (0, 0x02),
    "dpad_left": (0, 0x04),
    "dpad_right": (0, 0x08),
    "ls": (0, 0x40),
    "rs": (0, 0x80),
    "lb": (1, 0x01),
    "rb": (1, 0x02),
    "a": (1, 0x10),
    "b": (1, 0x20),
    "x": (1, 0x40),
    "y": (1, 0x80),
}
TARGET_MOUSE_BITS = {"mouse_left": 0x01, "mouse_right": 0x02}
TARGET_KEYS = {
    "touchpad_click": HID_KEY_F13,
    "touchpad_right": HID_KEY_F14,
    "f21": HID_KEY_F21,
    "f22": HID_KEY_F22,
}


def zotac_crc(data: bytes | bytearray) -> int:
    crc = 0
    for b in data:
        h1 = (crc ^ b) & 0xFF
        h2 = h1 & 0x0F
        h3 = (h2 << 4) ^ h1
        h4 = h3 >> 4
        crc = ((((((h3 << 1) ^ h4) << 4) ^ h2) << 3) ^ h4 ^ (crc >> 8)) & 0xFFFF
    return crc


def zotac_cmd(cmd: int, payload: bytes = b"", seq: int = 0) -> bytes:
    pkt = bytearray(64)
    pkt[0] = CMD_HEADER
    pkt[2] = seq & 0xFF
    pkt[3] = CMD_PAYLOAD_SIZE
    pkt[4] = cmd
    pkt[5 : 5 + len(payload)] = payload
    pkt[62:64] = zotac_crc(pkt[4:62]).to_bytes(2, "big")
    return b"\x00" + bytes(pkt)


def action_target(action: str) -> bytes:
    """13 byte mapping target for an action ('disabled' clears the mapping)."""
    t = bytearray(13)
    if action in TARGET_GAMEPAD_BITS:
        idx, bit = TARGET_GAMEPAD_BITS[action]
        t[idx] = bit
    elif action in TARGET_MOUSE_BITS:
        t[12] = TARGET_MOUSE_BITS[action]
    elif action in TARGET_KEYS:
        t[6] = TARGET_KEYS[action]
    return bytes(t)


def rgb_effect(ev) -> int | None:
    """Firmware effect for an RGB led event, None if the mode is unsupported."""
    match ev["mode"]:
        case "disabled":
            return EFFECT_OFF
        case "solid":
            return EFFECT_SOLID
        case "pulse":
            return EFFECT_BREATHE
        case "rainbow":
            return EFFECT_FADE
        case "spiral":
            return EFFECT_RAINBOW
        case "strobe":
            return EFFECT_WINK
        case "zotac":
            match ev.get("zotac", None):
                case "random":
                    return EFFECT_RANDOM
                case "flash":
                    return EFFECT_FLASH
                case _:
                    return EFFECT_STARS
        case _:
            return None


def rgb_cmds(ev, set_effect: bool = True) -> list[tuple[bytes, float]]:
    """Translate an RGB led event into (payload, delay) tuples for 0xAD.

    Modes with a color carry the brightness in the color and leave the
    hardware brightness at 100%. Without set_effect, only color, speed and
    brightness are sent; they apply immediately to the running effect."""
    effect = rgb_effect(ev)
    if effect is None:
        logger.warning(f"Unsupported RGB mode '{ev['mode']}'.")
        return []

    off = (bytes([RGB_EFFECT, EFFECT_OFF]), EFFECT_DELAY)
    if effect == EFFECT_OFF:
        return [off]

    color = bytes([ev["red"], ev["green"], ev["blue"]]) * 10
    brightness = min(100, max(0, int(ev["brightness"] * 100)))
    speed = min(2, max(0, int(ev["speed"] * 3)))
    cmds = [
        (bytes([RGB_COLOR, 0, 0, 0]) + color, WRITE_DELAY),
        (bytes([RGB_COLOR, 1, 0, 0]) + color, WRITE_DELAY),
        (bytes([RGB_SPEED, speed]), WRITE_DELAY),
        (bytes([RGB_BRIGHTNESS, brightness]), WRITE_DELAY),
    ]
    if not set_effect:
        return cmds
    # Setting the effect that is already active (e.g., loaded from flash on
    # boot) does not restart it and the band stays dark, so go through off.
    return [off, (bytes([RGB_EFFECT, effect]), EFFECT_DELAY), *cmds]


class ZotacCmdHidraw(GenericGamepadHidraw):
    """Vendor command interface: button mappings (paddles, touchpad click
    zones), vibration strength, RGB.

    All writes are volatile (no 0xFB save), the controller resets to its
    stored configuration when it re-enumerates (e.g., after sleep), and the
    plugin re-initializes on reconnect. Mappings are volatile and not
    restored when the plugin stops."""

    def __init__(self, *, vibration: int, touchpad_zones: dict[int, str]) -> None:
        super().__init__(
            vid=ZOTAC_VIDS,
            pid=[ZOTAC_PID],
            interface=CMD_INTERFACE,
            report_size=65,
            lossless=False,  # only drain command replies
            required=False,
        )
        self.mappings = {
            SRC_M1: action_target("f22"),
            SRC_M2: action_target("f21"),
            **{src: action_target(act) for src, act in touchpad_zones.items()},
        }
        self.vibration = min(100, max(0, vibration))
        self.seq = 0
        self.queue: list[tuple[bytes, float]] = []
        self.next_write = 0
        # Effect last written to the controller, None until the first write
        self.effect = None

    def _write(self, cmd: int, payload: bytes):
        assert self.dev
        self.seq = (self.seq + 1) & 0xFF
        self.dev.write(zotac_cmd(cmd, payload, self.seq))

    def _exchange(self, cmd: int, payload: bytes):
        """Synchronous command, only used during open."""
        assert self.dev
        self._write(cmd, payload)
        end = time.perf_counter() + REPLY_TIMEOUT_MS / 1000
        while time.perf_counter() < end:
            rep = self.dev.read(self.report_size, timeout=REPLY_TIMEOUT_MS)
            if len(rep) == 65 and rep[0] == 0:
                rep = rep[1:]
            if len(rep) >= 64 and rep[0] == CMD_HEADER and rep[4] == cmd:
                return
        logger.warning(f"No reply for command {cmd:02x}.")

    def open(self) -> Sequence[int]:
        fds = super().open()
        if not self.dev:
            return fds

        self.queue = []
        self.next_write = 0
        self.effect = None
        # Errors propagate so the controller loop restarts and retries
        for src, target in self.mappings.items():
            self._exchange(CMD_SET_MAPPING, bytes([src]) + target)
        logger.info(
            "Set button mappings for sources: "
            + ", ".join(f"{src:02x}" for src in self.mappings)
        )
        self._exchange(CMD_SET_VIBRATION, bytes([self.vibration] * 2 + [0, 0]))
        logger.info(f"Set vibration strength to {self.vibration}%.")
        return fds

    def consume(self, events: Sequence[Event]):
        if not self.dev:
            return

        for ev in events:
            if ev["type"] == "led":
                # A newer state replaces any pending RGB commands. Go through
                # an effect change only if the effect differs from the one on
                # the controller, so color changes do not blank the band.
                self.queue = rgb_cmds(ev, rgb_effect(ev) != self.effect)

        # Send one queued command, respecting the delay after effect changes
        now = time.perf_counter()
        if self.queue and now >= self.next_write:
            payload, delay = self.queue.pop(0)
            try:
                self._write(CMD_SET_RGB, payload)
                if payload[0] == RGB_EFFECT:
                    self.effect = payload[1]
            except Exception as e:
                logger.error(f"Failed to send RGB command:\n{e}")
            self.next_write = now + delay


class ZotacDialHidraw(GenericGamepadHidraw):
    """Dials on USB interface 1 (report 0x03). Each detent becomes a short
    button press, the release is sent on a later loop iteration because the
    uinput device only keeps the last value per key in a batch."""

    def __init__(self, *, left: str, right: str) -> None:
        super().__init__(
            vid=ZOTAC_VIDS,
            pid=[ZOTAC_PID],
            interface=DIAL_INTERFACE,
            report_size=64,
            report_id_offset=0,
            required=False,
        )
        self.actions = {
            DIAL_RIGHT_CW: _dial_action(right, True),
            DIAL_RIGHT_CCW: _dial_action(right, False),
            DIAL_LEFT_CW: _dial_action(left, True),
            DIAL_LEFT_CCW: _dial_action(left, False),
        }
        self.pending: list[Button] = []

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        out: list[Event] = []
        # Release keys pressed on the previous iteration
        for btn in self.pending:
            out.append({"type": "button", "code": btn, "value": False})
        self.pending = []

        if not self.dev or self.fd not in fds:
            return out

        while can_read(self.fd):
            rep = self.dev.read(self.report_size)
            if not rep or rep[0] != DIAL_REPORT:
                continue
            for bm, btn in self.actions.items():
                if btn and get_button(rep, bm):
                    out.append({"type": "button", "code": btn, "value": True})
                    self.pending.append(btn)
        return out


def _dial_action(func: str, cw: bool) -> Button | None:
    match func:
        case "volume":
            return "key_volumeup" if cw else "key_volumedown"
        case "brightness":
            return "key_brightnessup" if cw else "key_brightnessdown"
        case _:
            return None
