from typing import Literal, Sequence

from hhd.controller import Event
from hhd.controller.lib.hid import Device

Side = Literal["left", "right"]
RgbMode = Literal["solid", "pulse", "dynamic", "spiral"]


def rgb_brightness():
    return [  # Brightness Command
        bytes(
            [
                0x5A,
                0xBA,
                0xC5,
                0xC4,
                0x03,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        ),
    ]


def rgb_command(side: Side, mode: RgbMode, red: int, green: int, blue: int):
    match side:
        case "left":
            c_side = 0x01
        case "right":
            c_side = 0x00
        case _:
            c_side = 0x00

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

    return [
        bytes(  # Color Command
            [
                0x5A,
                0xB3,
                0x00,
                c_mode,
                red,
                green,
                blue,
                0x00,
                c_side,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        ),
    ]


def rgb_set_both(mode: RgbMode, red: int, green: int, blue: int):
    return [
        *rgb_brightness(),
        *rgb_command("left", mode, red, green, blue),
        *rgb_command("right", mode, red, green, blue),
    ]


def rgb_callback(dev: Device, events: Sequence[Event]):
    for ev in events:
        if ev["type"] == "led":
            if ev["mode"] == "disable":
                reps = rgb_set_both("solid", 0, 0, 0)
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
                reps = rgb_set_both(
                    mode,
                    ev["red"],
                    ev["green"],
                    ev["blue"],
                )

            for r in reps:
                dev.write(r)
