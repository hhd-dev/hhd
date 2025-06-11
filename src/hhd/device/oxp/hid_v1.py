import logging
import time
from collections import deque
from typing import Literal

from hhd.controller import can_read
from hhd.controller.physical.hidraw import GenericGamepadHidraw

logger = logging.getLogger(__name__)


def gen_cmd(cid: int, cmd: bytes | list[int] | str, idx: int = 0x01, size: int = 64):
    # Command: [idx, cid, 0x3f, *cmd, 0x3f, cid], idx is optional
    if isinstance(cmd, str):
        c = bytes.fromhex(cmd)
    else:
        c = bytes(cmd)
    base = bytes([cid, 0x3F, idx, *c])
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
    return gen_cmd(0xB8, [mc, 0x00, 0x02])


gen_intercept = lambda enable: gen_cmd(0xB2, [0x03 if enable else 0x00, 0x01, 0x02])


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

    return gen_cmd(0xB8, [0xFD, 0x00, 0x02, enabled, 0x05, bc])

# Sides on the g1
# 1 = left controller
# 2 = right controller
# 3 = center V
# 4 = touch keyboard
# 5 = device color on the front (triangle)
def gen_rgb_solid(r, g, b, side: int = 0x00):
    return gen_cmd(0xB8, [0xFE, side, 0x02] + 18 * [r, g, b] + [r, g])


KBD_NAME = "keyboard"
HOME_NAME = "guide"
KBD_NAME_NON_TURBO = "share"
KBD_HOLD = 0.12
OXP_BUTTONS = {
    0x24: KBD_NAME,
    0x21: HOME_NAME,
    0x22: "extra_l1",
    0x23: "extra_r1",
}


INITIALIZE = [
    gen_cmd(
        0xB4,
        "0238020101010101000000020102000000030103000000040104000000050105000000060106000000070107000000080108000000090109000000",
    ),
    gen_cmd(
        0xB4,
        "02380202010a010a0000000b010b0000000c010c0000000d010d0000000e010e0000000f010f000000100110000000220200000000230200000000",
    ),
    gen_intercept(False),
]

INIT_DELAY = 4
CONNECT_DELAY = 0.3
WRITE_DELAY = 0.05
SCAN_DELAY = 1

_init_done = False


class OxpHidraw(GenericGamepadHidraw):
    def __init__(self, *args, turbo: bool = True, g1: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.prev = {}
        self.queue_kbd = None
        self.queue_home = None
        self.queue_cmd = deque(maxlen=10)
        self.next_send = 0
        self.queue_led = None
        self.turbo = turbo

        self.g1 = g1
        self.send_init = not g1  # g1 has no extra buttons
        self.prev_brightness = None
        self.prev_stick = None
        self.prev_stick_enabled = None
        # self.prev_center = None
        # self.prev_center_enabled = None

    def open(self):
        a = super().open()
        self.queue_kbd = None
        self.queue_home = None
        self.prev = {}

        global _init_done
        self.next_send = time.perf_counter() + CONNECT_DELAY
        if self.send_init:
            if not _init_done:
                self.next_send = time.perf_counter() + INIT_DELAY
                self.queue_cmd.extend(INITIALIZE)
                # Setting the mappings is a bit aggressive and causes the device
                # to flash its leds. Only do it during boot.
                _init_done = True
            else:
                self.queue_cmd.append(gen_intercept(False))
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
        # center = None
        # center_enabled = True
        # init = ev["initialize"]

        match ev["mode"]:
            case "solid":
                stick = ev["red"], ev["green"], ev["blue"]
                # r2, g2, b2 = ev["red2"], ev["green2"], ev["blue2"]
                # center = r2, g2, b2
                # center_enabled = r2 > 10 or g2 > 10 or b2 > 10
            # case "duality":
            #     stick = ev["red"], ev["green"], ev["blue"]
            #     center = ev["red2"], ev["green2"], ev["blue2"]
            case "oxp":
                brightness = ev["brightnessd"]
                stick = ev["oxp"]
                if stick == "classic":
                    # Classic mode is a cherry red
                    stick = 0xB7, 0x30, 0x00
                # r2, g2, b2 = ev["red2"], ev["green2"], ev["blue2"]
                # center = r2, g2, b2
                # center_enabled = r2 > 10 or g2 > 10 or b2 > 10
                # init = True
            case _:  # "disabled":
                stick_enabled = False
                # center_enabled = False

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

        if stick_enabled and stick and stick != self.prev_stick:
            if isinstance(stick, str):
                self.queue_cmd.append(gen_rgb_mode(stick))
            else:
                self.queue_cmd.append(gen_rgb_solid(*stick, side=0x00))
            self.prev_stick = stick
            self.prev_brightness = brightness
            self.prev_stick_enabled = stick_enabled

        # if center_enabled != self.prev_center_enabled:
        #     self.queue_cmd.append(gen_brightness(0x03, center_enabled, "high"))
        #     self.queue_cmd.append(gen_brightness(0x04, center_enabled, "high"))
        #     self.prev_center_enabled = center_enabled

        # # Only apply center colors on init on init
        # if init and center_enabled and center and center != self.prev_center:
        #     self.queue_cmd.append(gen_rgb_solid(*center, side=0x03))
        #     self.queue_cmd.append(gen_rgb_solid(*center, side=0x04))
        #     self.prev_center = center

    def produce(self, fds):
        if not self.dev:
            return []

        evs = []
        # A bit unclean with 2 buttons but it works
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
        if self.queue_home:
            curr = time.perf_counter()
            if curr - KBD_HOLD > self.queue_home:
                evs = [
                    {
                        "type": "button",
                        "code": HOME_NAME,
                        "value": False,
                    }
                ]
                self.queue_home = None

        if self.fd not in fds:
            return evs

        while can_read(self.fd):
            cmd = self.dev.read()
            # logger.info(f"OXP R: {cmd.hex()}")

            cid = cmd[0]
            valid = cmd[1] == 0x3F and cmd[-2] == 0x3F

            if not valid:
                logger.warning(f"OXP HID invalid command: {cmd.hex()}")
                continue

            if cid in (0xF5, 0xB8):
                # Initialization (0xf5) and rgb (0xb8) command responses, skip
                continue

            if cid != 0xB2:
                logger.warning(f"OXP HID unknown command: {cmd.hex()}")
                continue

            btn = cmd[6]

            if btn not in OXP_BUTTONS:
                logger.warning(
                    f"OXP HID unknown button: {btn:x} from cmd:\n{cmd.hex()}"
                )
                continue

            btn = OXP_BUTTONS[btn]
            pressed = cmd[12] == 1

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

            if btn == HOME_NAME:
                if pressed and (btn not in self.prev or self.prev[btn] != pressed):
                    evs.append(
                        {
                            "type": "button",
                            "code": HOME_NAME,
                            "value": True,
                        }
                    )
                    self.queue_home = time.perf_counter()
                self.prev[btn] = pressed
                continue

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
