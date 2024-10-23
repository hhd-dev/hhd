import logging
import time
from collections import deque
from typing import Literal

from hhd.controller import can_read
from hhd.controller.physical.hidraw import GenericGamepadHidraw

logger = logging.getLogger(__name__)


def gen_cmd(cid: int, cmd: bytes | list[int] | str, size: int = 64):
    # Command: [idx, cid, 0x3f, *cmd, 0x3f, cid], idx is optional
    if isinstance(cmd, str):
        c = bytes.fromhex(cmd)
    else:
        c = bytes(cmd)
    base = bytes([cid, 0xFF, *c])
    return base + bytes([0] * (size - len(base)))


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
    return gen_cmd(0x07, [mc])


gen_intercept = lambda enable: gen_cmd(0xB2, [0x03 if enable else 0x00, 0x01, 0x02])


def gen_brightness(
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

    return gen_cmd(0x07, [0xFD, enabled, 0x05, bc])


def gen_rgb_solid(r, g, b):
    return gen_cmd(0x07, [0xFE] + 20 * [r, g, b] + [0x00])


KBD_NAME = "keyboard"
HOME_NAME = "guide"
KBD_NAME_NON_TURBO = "share"
KBD_HOLD = 0.2
OXP_BUTTONS = {
    0x24: KBD_NAME,
    0x21: HOME_NAME,
    0x22: "extra_l1",
    0x23: "extra_r1",
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


class OxpHidrawV2(GenericGamepadHidraw):
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
        # self.prev_center = None
        # self.prev_center_enabled = None

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

        match ev["mode"]:
            case "solid":
                stick = ev["red"], ev["green"], ev["blue"]
            case "oxp":
                brightness = ev["brightnessd"]
                stick = ev["oxp"]
                if stick == "classic":
                    # Classic mode is a cherry red
                    stick = 0xb7, 0x30, 0x00
            case _:  # "disabled":
                stick_enabled = False
        
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
            self.queue_cmd.append(gen_brightness(stick_enabled, brightness))
            self.prev_brightness = brightness
            self.prev_stick_enabled = stick_enabled

        if stick_enabled and stick != self.prev_stick:
            if isinstance(stick, str):
                self.queue_cmd.append(gen_rgb_mode(stick))
            else:
                self.queue_cmd.append(gen_rgb_solid(*stick))
            self.prev_stick = stick
            self.prev_brightness = brightness
            self.prev_stick_enabled = stick_enabled

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
