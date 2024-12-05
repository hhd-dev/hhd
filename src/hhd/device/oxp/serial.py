import logging
import os
import select
import subprocess
import time
from collections import deque
from typing import Literal

from hhd.controller.base import Consumer, Producer

logger = logging.getLogger(__name__)


def gen_cmd(
    cid: int, cmd: bytes | list[int] | str, idx: int | None = None, size: int = 64
):
    # Command: [idx, cid, 0x3f, *cmd, 0x3f, cid], idx is optional
    if isinstance(cmd, str):
        c = bytes.fromhex(cmd)
    else:
        c = bytes(cmd)
    base = bytes([cid, 0x3F, *c])
    if idx is not None:
        base = bytes([idx]) + base
    return base + bytes([0] * (size - len(base) - 2)) + bytes([0x3F, cid])


def gen_rgb_mode(mode: str):
    mc = 0
    match mode:
        case "monster_woke":
            mc = 0x0D
        case "flowing":
            mc = 0x03
        case "sunset":
            mc = 0x0B
        case "neon":
            mc = 0x05
        case "dreamy":
            mc = 0x07
        case "cyberpunk":
            mc = 0x09
        case "colorful":
            mc = 0x0C
        case "aurora":
            mc = 0x01
        case "sun":
            mc = 0x08
    return gen_cmd(0xFD, [0x00, mc])


gen_intercept = lambda enable: gen_cmd(0xA1, 2 * [int(enable)], idx=0x00)


def gen_brightness(
    side: Literal[0, 3, 4],
    enabled: bool,
    brightness: Literal["low", "medium", "high"],
):
    match brightness:
        case "low":
            bc = 0x01
        case "medium":
            bc = 0x03
        case _:  # "high":
            bc = 0x04

    return gen_cmd(
        0xFD, [side, 0xFD, 0x00 if side else 0x03, 0x00, int(enabled), 0x05, bc]
    )


def gen_rgb_solid(r, g, b, side: Literal[0x00, 0x03, 0x04] = 0x00):
    start = [side, 0xFE, 0x00, 0x00]
    end = [r, g]
    return gen_cmd(0xFD, start + 18 * [r, g, b] + end)


KBD_NAME = "keyboard"
KBD_NAME_NON_TURBO = "share"
KBD_HOLD = 0.12
OXP_BUTTONS = {
    0x24: KBD_NAME,
    0x22: "extra_l1",
    0x23: "extra_r1",
}


INITIALIZE = [
    # gen_intercept(True),
    gen_cmd(
        0xF5,
        "0000000001010101000000020102000000030103000000040104000000050105000000060106000000070107000000080108000000090109000000",
        idx=0x01,
    ),
    gen_cmd(
        0xF5,
        "00000000010a010a0000000b010b0000000c010c0000000d010d0000000e010e0000000f010f000000100110000000220200000000230200000000",
        idx=0x02,
    ),
    # gen_intercept(False), # does not seem to be needed
]

INIT_DELAY = 2
WRITE_DELAY = 0.05
SCAN_DELAY = 1

_mappings_init = True


def get_serial():

    VID = "1a86"
    PID = "7523"

    dev = None
    buttons_only = False
    for d in os.listdir("/dev"):
        if not d.startswith("ttyUSB"):
            continue

        path = os.path.join("/dev", d)

        out = subprocess.run(
            ["udevadm", "info", "--name", path],
            check=True,
            capture_output=True,
            text=True,
        )

        if f"ID_VENDOR_ID={VID}" not in out.stdout:
            continue

        if f"ID_MODEL_ID={PID}" not in out.stdout:
            continue

        dev = path
        break

    for d in os.listdir("/dev"):
        if not d.startswith("ttyS"):
            continue

        path = os.path.join("/dev", d)

        out = subprocess.run(
            ["udevadm", "info", "--name", path],
            check=True,
            capture_output=True,
            text=True,
        )

        # OneXFly device is pnp
        if "devices/pnp" not in out.stdout:
            continue

        # TODO: We need to get a baseline to quirk this type properly
        logger.info(f"Serial port information:\n{out.stdout}")

        dev = path
        buttons_only = True
        break
    return dev, buttons_only


def init_serial():
    import serial

    dev, buttons_only = get_serial()

    if not dev:
        logger.warning("OXP CH340 serial device not found.")
        return None, buttons_only

    logger.info(f"OXP CH340 serial device found at {dev}")

    ser = serial.Serial(
        dev,
        115200,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_TWO,
        bytesize=serial.EIGHTBITS,
        timeout=0,
        exclusive=True,
    )

    return ser, buttons_only


class SerialDevice(Consumer, Producer):
    def __init__(self, required: bool = False, turbo: bool = True) -> None:
        self.required = required
        self.ser = None
        self.buf = bytearray()
        self.prev = {}
        self.queue_kbd = None
        self.queue_cmd = deque(maxlen=10)
        self.last_sent = 0
        self.queue_led = None
        self.turbo = turbo
        self.buttons_only = False

        self.prev_brightness = None
        self.prev_stick = None
        self.prev_stick_enabled = None
        self.prev_center = None
        self.prev_center_enabled = None

    def open(self):
        ser, self.buttons_only = init_serial()
        if ser is None:
            if self.required:
                raise RuntimeError("OXP CH340 serial device not found.")
            return []
        self.ser = ser
        self.queue_kbd = None
        self.prev = {}

        self.next_send = time.perf_counter() + INIT_DELAY

        global _mappings_init
        if _mappings_init:
            self.queue_cmd.extend(INITIALIZE)
            _mappings_init = False

        return [ser.fd]

    def consume(self, events):
        if not self.ser:
            return

        # Capture led events
        for ev in events:
            if ev["type"] == "led":
                # if self.queue_led:
                #     logger.warning("OXP CH340 LED event queue overflow.")
                self.queue_led = ev

        # Send queued event if applicable
        curr = time.perf_counter()
        if self.queue_cmd and curr - self.last_sent > WRITE_DELAY:
            cmd = self.queue_cmd.popleft()
            logger.info(f"OXP C: {cmd.hex()}")
            self.ser.write(cmd)
            self.last_sent = time.perf_counter()
        
        # No LEDs, skip the rest
        if self.buttons_only:
            return

        # Queue needs to flush before switching to next event
        # Also, there needs to be a led event to queue
        if self.queue_cmd or not self.queue_led:
            return
        ev = self.queue_led
        self.queue_led = None

        brightness = "high"
        stick = None
        stick_enabled = True
        center = None
        center_enabled = True
        init = ev["initialize"]

        match ev["mode"]:
            case "solid":
                stick = ev["red"], ev["green"], ev["blue"]
                r2, g2, b2 = ev["red2"], ev["green2"], ev["blue2"]
                center = r2, g2, b2
                center_enabled = r2 > 10 or g2 > 10 or b2 > 10
            case "duality":
                stick = ev["red"], ev["green"], ev["blue"]
                center = ev["red2"], ev["green2"], ev["blue2"]
            case "oxp":
                brightness = ev["brightnessd"]
                stick = ev["oxp"]
                if stick == "classic":
                    # Classic mode is a cherry red
                    stick = 0xB7, 0x30, 0x00
                r2, g2, b2 = ev["red2"], ev["green2"], ev["blue2"]
                center = r2, g2, b2
                center_enabled = r2 > 10 or g2 > 10 or b2 > 10
                init = True
            case _:  # "disabled":
                stick_enabled = False
                center_enabled = False

        # Force RGB to not initialize to workaround RGB breaking
        # rumble when being set
        if self.prev_stick_enabled is None:
            self.prev_stick_enabled = stick_enabled
        if self.prev_brightness is None:
            self.prev_brightness = brightness
        if self.prev_stick is None:
            self.prev_stick = stick

        if (
            stick_enabled != self.prev_stick_enabled
            or brightness != self.prev_brightness
        ):
            self.queue_cmd.append(gen_brightness(0, stick_enabled, brightness))
            self.prev_brightness = brightness
            self.prev_stick_enabled = stick_enabled

        if stick_enabled and stick != self.prev_stick:
            if isinstance(stick, str):
                self.queue_cmd.append(gen_rgb_mode(stick))
            else:
                self.queue_cmd.append(gen_rgb_solid(*stick, side=0x00))
            self.prev_stick = stick
            self.prev_brightness = brightness
            self.prev_stick_enabled = stick_enabled

        if center_enabled != self.prev_center_enabled:
            self.queue_cmd.append(gen_brightness(0x03, center_enabled, "high"))
            self.queue_cmd.append(gen_brightness(0x04, center_enabled, "high"))
            self.prev_center_enabled = center_enabled

        # Only apply center colors on init on init
        if init and center_enabled and center and center != self.prev_center:
            self.queue_cmd.append(gen_rgb_solid(*center, side=0x03))
            self.queue_cmd.append(gen_rgb_solid(*center, side=0x04))
            self.prev_center = center

    def produce(self, fds):
        if not self.ser:
            return []

        evs = []
        if self.queue_kbd:
            curr = time.perf_counter()
            if curr - KBD_HOLD > self.queue_kbd:
                evs = [
                    {
                        "type": "button",
                        "code": KBD_NAME if self.turbo else KBD_NAME_NON_TURBO,
                        "value": False,
                    }
                ]
                self.queue_kbd = None

        if self.ser.fd not in fds:
            return evs

        CMD_LEN = 14

        while out := self.ser.read():
            self.buf.extend(out)

        while len(self.buf) >= CMD_LEN:
            # Align to start boundary
            if self.buf[1] != 0x3F:
                self.buf = self.buf[1:]
                continue

            # Grab command id
            cmd = self.buf[:CMD_LEN]
            self.buf = self.buf[CMD_LEN:]
            cid = cmd[0]

            valid = cmd[-2] == 0x3F and cmd[-1] == cid
            if not valid:
                logger.warning(f"OXP CH340 invalid command: {self.buf.hex()}")
                continue

            if cid == 0xEF:
                # Initialization command, skip
                continue

            if cid != 0x1A:
                logger.warning(f"OXP CH340 unknown command: {cmd.hex()}")
                continue

            btn = cmd[2]

            if btn not in OXP_BUTTONS:
                logger.warning(
                    f"OXP CH340 unknown button: {btn:x} from cmd:\n{cmd.hex()}"
                )
                continue

            btn = OXP_BUTTONS[btn]
            pressed = cmd[8] == 1

            if btn == KBD_NAME:
                if pressed and (btn not in self.prev or self.prev[btn] != pressed):
                    evs.append(
                        {
                            "type": "button",
                            "code": KBD_NAME if self.turbo else KBD_NAME_NON_TURBO,
                            "value": True,
                        }
                    )
                    self.queue_kbd = time.perf_counter()
                self.prev[btn] = pressed
                continue

            # logger.info(f"OXP CH340 button: {btn} pressed: {pressed}")
            if btn in self.prev and self.prev[btn] == pressed:
                # Debounce
                continue

            self.prev[btn] = pressed
            evs.append(
                {
                    "type": "button",
                    "code": btn,
                    "value": pressed,
                }
            )

        return evs
