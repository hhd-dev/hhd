import logging
from typing import Literal, Sequence

from hhd.controller import Event
from hhd.controller.lib.hid import Device
import time

from .const import (
    COMMANDS_GAME,
    COMMANDS_MOUSE,
    RGB_APPLY,
    RGB_INIT_1,
    RGB_INIT_2,
    RGB_SET,
    buf,
)

Zone = Literal["all", "left_left", "left_right", "right_left", "right_right"]
RgbMode = Literal["disabled", "solid", "pulse", "dynamic", "spiral"]
GamepadMode = Literal["default", "mouse", "macro"]
Brightness = Literal["off", "low", "medium", "high"]

logger = logging.getLogger(__name__)


def rgb_set_brightness(brightness: Brightness):
    match brightness:
        case "high":
            c = 0x03
        case "medium":
            c = 0x02
        case "low":
            c = 0x01
        case _:
            c = 0x00
    return buf([0x5A, 0xBA, 0xC5, 0xC4, c])


def rgb_command(
    zone: Zone, mode: RgbMode, direction, speed: float, red: int, green: int, blue: int
):
    c_speed = int(speed * (0xF5 - 0xE1) + 0xE1)
    c_direction = 0x00

    match mode:
        case "solid":
            # Static
            c_mode = 0x00
        # case "breathing":
        #     # Breathing
        #     c_mode = 0x01
        case "dynamic":
            # Color cycle
            c_mode = 0x02
        case "spiral":
            # Wave
            c_mode = 0x03
            red = 255
            green = 255
            blue = 255
            if direction == "left":
                c_direction = 0x01
        case "pulse":
            # Strobing
            c_mode = 0x0A
        # case "asdf":
        #     # Direct/Aura
        #     c_mode = 0xFF
        case _:
            c_mode = 0x00

    match zone:
        case "left_left":
            c_zone = 0x01
        case "left_right":
            c_zone = 0x02
        case "right_left":
            c_zone = 0x03
        case "right_right":
            c_zone = 0x04
        case _:
            c_zone = 0x00

    return buf(
        [
            0x5A,
            0xB3,
            c_zone,  # zone
            c_mode,  # mode
            red,
            green,
            blue,
            c_speed if mode != "solid" else 0x00,
            c_direction,
            0x00,  # breathing
            # red, # these only affect the breathing mode
            # green,
            # blue,
        ]
    )


def rgb_set(
    side: str,
    mode: RgbMode,
    direction: str,
    speed: float,
    red: int,
    green: int,
    blue: int,
):
    match side:
        case "left_left" | "left_right" | "right_left" | "right_right":
            return [
                rgb_command(side, mode, direction, speed, red, green, blue),
            ]
        case "left":
            return [
                rgb_command("left_left", mode, direction, speed, red, green, blue),
                rgb_command("left_right", mode, direction, speed, red, green, blue),
            ]
        case "right":
            return [
                rgb_command("right_right", mode, direction, speed, red, green, blue),
                rgb_command("right_left", mode, direction, speed, red, green, blue),
            ]
        case _:
            return [
                rgb_command("all", mode, direction, speed, red, green, blue),
            ]


INIT_EVERY_S = 10


def process_events(events: Sequence[Event], prev_mode: str | None):
    cmds = []
    mode = None
    br_cmd = None
    init = False
    for ev in events:
        if ev["type"] == "led":
            if ev["initialize"]:
                init = True
            if ev["mode"] == "disabled":
                mode = "disabled"
                br_cmd = rgb_set_brightness("off")
                # cmds.extend(rgb_set(ev["code"], "solid", "left", 0, 0, 0, 0))
            else:
                match ev["mode"]:
                    case "pulse":
                        mode = "pulse"
                        set_level = False
                    case "rainbow":
                        mode = "dynamic"
                        set_level = False
                    case "solid":
                        mode = "solid"
                        set_level = True
                    case "spiral":
                        mode = "spiral"
                        set_level = True
                    case _:
                        assert False, f"Mode '{ev['mode']}' not supported."

                if set_level:
                    br_cmd = rgb_set_brightness(ev["level"])

                cmds.extend(
                    rgb_set(
                        ev["code"],
                        mode,
                        ev["direction"],
                        ev["speed"],
                        ev["red"],
                        ev["green"],
                        ev["blue"],
                    )
                )

    if not mode or (not cmds and mode != "disabled"):
        # Avoid sending init commands without a mode.
        # The exception being the disabled mode, which just sets the led
        # brightness.
        return [], None

    # Set brightness once per update
    if mode != prev_mode:
        init = True
        if not br_cmd:
            br_cmd = rgb_set_brightness("high")

    if init:
        cmds = [
            RGB_INIT_1,
            RGB_INIT_2,
            *cmds,
            RGB_SET,
            RGB_APPLY,
        ]

    if br_cmd:
        cmds.insert(0, br_cmd)
    return cmds, mode


class RgbCallback:
    def __init__(self) -> None:
        self.prev_mode = None

    def __call__(self, dev: Device, events: Sequence[Event]):
        cmds, mode = process_events(events, self.prev_mode)
        if mode:
            self.prev_mode = mode
        if not cmds:
            return
        logger.warning(
            f"Running RGB commands:\n{'\n'.join([cmd[:20].hex() for cmd in cmds])}"
        )
        for r in cmds:
            dev.write(r)


def switch_mode(dev: Device, mode: GamepadMode):
    match mode:
        case "default":
            cmds = COMMANDS_GAME
        # case "macro":
        #     cmds = MODE_MACRO
        case "mouse":
            cmds = COMMANDS_MOUSE
        case _:
            assert False, f"Mode '{mode}' not supported."

    for cmd in cmds:
        dev.write(cmd)
