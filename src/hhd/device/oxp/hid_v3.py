import logging
import time
from collections import deque
from typing import Literal

from hhd.controller import can_read
from hhd.controller.physical.hidraw import GenericGamepadHidraw

logger = logging.getLogger(__name__)


def gen_cmd(
    cmd: bytes | list[int] | str, size: int = 128
):
    # Command: [0x00, 0xB8, 0x3F, 0x00, *cmd, 0x3f, 0xB8]
    if isinstance(cmd, str):
        c = bytes.fromhex(cmd)
    else:
        c = bytes(cmd)
    base = bytes([0x00, 0xB8, 0x3F, 0x00, *c])

    return base + bytes([0] * (size - len(base) - 2)) + bytes([0x3F, 0xB8])



#b83f000d010200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003fb8
def gen_rgb_mode(mode: str, side: Literal[0x01, 0x02, 0x03, 0x04, 0x05] = 0x01):
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
            mc = 0x02
        case "sun":
            mc = 0x08
    return gen_cmd([mc, side, 0x02])


# b83f00fd010201050300000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003fb8
def gen_brightness(
    enabled: bool,
    brightness: Literal["low", "medium", "high"],
    side: Literal[0x01, 0x02, 0x03, 0x04, 0x05] = 0x01,
):
    match brightness:
        case "low":
            bc = 0x01
        case "medium":
            bc = 0x03
        case _:  # "high":
            bc = 0x04

    return gen_cmd([0xFD, side, 0x02, int(enabled), 0x05, bc])


# b83f00fe01021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c02021c023fb8
def gen_rgb_solid(r, g, b, side: Literal[0x01, 0x02, 0x03, 0x04, 0x05] = 0x01):
    start = [0xFE, side, 0x02]
    end = [r, g]
    return gen_cmd(start + 18 * [r, g, b] + end)


KBD_NAME = "keyboard"
HOME_NAME = "guide"
KBD_NAME_NON_TURBO = "share"
KBD_HOLD = 0.2
OXP_BUTTONS = {
}


INITIALIZE = [
    # gen_cmd(
    #     0xF5,
    #     "010238020101010101000000020102000000030103000000040104000000050105000000060106000000070107000000080108000000090109000000",
    # ),
    # gen_cmd(
    #     0xF5,
    #     "0102380202010a010a0000000b010b0000000c010c0000000d010d0000000e010e0000000f010f000000100110000000220200000000230200000000",
    # ),
    # gen_intercept(False),
]

INIT_DELAY = 4
WRITE_DELAY = 0.05
SCAN_DELAY = 1


class OxpHidrawV3(GenericGamepadHidraw):
    def __init__(self, *args, turbo: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.prev = {}
        self.queue_kbd = None
        self.queue_home = None
        self.queue_cmd = deque(maxlen=10)
        self.next_send = 0
        self.queue_led = None
        self.turbo = turbo

        self.prev_brightness = None
        self.prev_stick = None
        self.prev_stick_enabled = None
        self.prev_center = None
        self.prev_center_enabled = None

    def open(self):
        a = super().open()
        self.queue_kbd = None
        self.queue_home = None
        self.prev = {}
        self.next_send = time.perf_counter() + INIT_DELAY

        self.queue_cmd.extend(INITIALIZE)
        return a

    def consume(self, events):
        if not self.dev:
            return

        # Capture led events
        for ev in events:
            if ev["type"] == "led":
                # if self.queue_led:
                #     logger.warning("OXP HID LED event queue overflow.")
                self.queue_led = ev

        # Send queued event if applicable
        curr = time.perf_counter()
        if self.queue_cmd and curr - self.next_send > 0:
            cmd = self.queue_cmd.popleft()
            logger.info(f"OXP C: {cmd.hex()}")
            self.dev.write(cmd)
            self.next_send = curr + WRITE_DELAY

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
            self.queue_cmd.append(gen_brightness(stick_enabled, brightness, side=0x01))
            self.queue_cmd.append(gen_brightness(stick_enabled, brightness, side=0x02))
            self.queue_cmd.append(gen_brightness(stick_enabled, brightness, side=0x03))
            self.queue_cmd.append(gen_brightness(stick_enabled, brightness, side=0x04))
            self.queue_cmd.append(gen_brightness(stick_enabled, brightness, side=0x05))
            self.prev_brightness = brightness
            self.prev_stick_enabled = stick_enabled

        if stick_enabled and stick != self.prev_stick:
            if isinstance(stick, str):
                self.queue_cmd.append(gen_rgb_mode(stick, side=0x01))
                self.queue_cmd.append(gen_rgb_mode(stick, side=0x02))
                self.queue_cmd.append(gen_rgb_mode(stick, side=0x03))
            else:
                self.queue_cmd.append(gen_rgb_solid(*stick, side=0x01))
                self.queue_cmd.append(gen_rgb_solid(*stick, side=0x02))
                self.queue_cmd.append(gen_rgb_solid(*stick, side=0x03))
            self.prev_stick = stick
            self.prev_brightness = brightness
            self.prev_stick_enabled = stick_enabled

        if center_enabled != self.prev_center_enabled:
            self.queue_cmd.append(gen_brightness(center_enabled, "high", side=0x01))
            self.queue_cmd.append(gen_brightness(center_enabled, "high", side=0x02))
            self.queue_cmd.append(gen_brightness(center_enabled, "high", side=0x03))
            self.queue_cmd.append(gen_brightness(center_enabled, "high", side=0x04))
            self.queue_cmd.append(gen_brightness(center_enabled, "high", side=0x05))
            self.prev_center_enabled = center_enabled

        # Only apply center colors on init on init
        if init and center_enabled and center and center != self.prev_center:
            self.queue_cmd.append(gen_rgb_solid(*center, side=0x04))
            self.queue_cmd.append(gen_rgb_solid(*center, side=0x05))
            self.prev_center = center

    def produce(self, fds):
        if not self.dev:
            return []

        evs = []

        return evs
