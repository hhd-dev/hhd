from typing import Literal, Sequence

from hhd.controller import Event
from hhd.controller.lib.hid import Device
from .const import (
    COMMANDS_INIT,
    COMMANDS_GAME,
    COMMANDS_MOUSE,
    RGB_APPLY,
    RGB_SET,
    RGB_INIT,
    buf,
    RGB_BRIGHTNESS_MAX,
)

Zone = Literal["all", "left_left", "left_right", "right_left", "right_right"]
RgbMode = Literal["solid", "pulse", "dynamic", "spiral"]
GamepadMode = Literal["default", "mouse", "macro"]


def rgb_command(zone: Zone, mode: RgbMode, red: int, green: int, blue: int):
    match mode:
        case "solid":
            # Static
            c_mode = 0x00
        case "pulse":
            # Breathing
            c_mode = 0x01
        case "dynamic":
            # Color cycle
            c_mode = 0x02
        case "spiral":
            # Rainbow
            c_mode = 0x03
        # case "adsf":
        #     # Strobing
        #     c_mode = 0x0A
        # case "asdf":
        #     # Direct (?)
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
            0x00,  # speed
            0x00,  # direction
            0x00,  # breathing
            # red,
            # green,
            # blue,
        ]
    )


def rgb_set(
    side: Literal["main", "left", "right"],
    mode: RgbMode,
    red: int,
    green: int,
    blue: int,
):
    match side:
        case "left":
            return [
                rgb_command("left_left", mode, red, green, blue),
                rgb_command("left_right", mode, red, green, blue),
                RGB_APPLY,
            ]
        case "right":
            return [
                rgb_command("right_right", mode, red, green, blue),
                rgb_command("right_left", mode, red, green, blue),
                RGB_APPLY,
            ]
        case _:
            return [rgb_command("all", mode, red, green, blue), RGB_APPLY]


def rgb_initialize(
    dev: Device,
):
    for cmd in [
        RGB_INIT,  # what does this do ?
        RGB_BRIGHTNESS_MAX,
        *rgb_set("main", "solid", 0, 0, 0),
    ]:
        dev.write(cmd)


def rgb_callback(dev: Device, events: Sequence[Event]):
    for ev in events:
        if ev["type"] == "led":
            if ev["mode"] == "disable":
                reps = rgb_set(ev["code"], "solid", 0, 0, 0)
            else:
                match ev["mode"]:
                    case "blinking":
                        mode = "pulse"
                    case "rainbow":
                        mode = "dynamic"
                    case "solid":
                        mode = "solid"
                    case "spiral":
                        mode = "spiral"
                    case _:
                        assert False, f"Mode '{ev['mode']}' not supported."
                reps = rgb_set(
                    ev["code"],
                    mode,
                    ev["red"],
                    ev["green"],
                    ev["blue"],
                )

            for r in reps:
                dev.write(r)


def initialize(dev: Device):
    for cmd in COMMANDS_INIT:
        dev.write(cmd)


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
