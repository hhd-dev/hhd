from enum import Enum
from typing import Literal, Sequence

from hhd.controller import Event
from hhd.controller.lib.hid import Device

Controller = Literal["left", "right"]
RgbMode = Literal["solid", "pulse", "dynamic", "spiral"]

RGB_MODE_PULSE = 0x02
RGB_MODE_DYNAMIC = 0x03
RGB_MODE_SPIRAL = 0x04


def _get_controller(c: Controller):
    if c == "left":
        return 0x03
    elif c == "right":
        return 0x04
    assert False, f"Controller '{c}' not supported."


def rgb_set_profile(
    controller: Controller,
    profile: Literal[1, 2, 3],
    mode: RgbMode,
    red: int,
    green: int,
    blue: int,
    brightness: float = 1,
    speed: float = 1,
):
    r_controller = _get_controller(controller)
    assert profile in (1, 2, 3), f"Invalid profile '{profile}' selected."

    match mode:
        case "solid":
            r_mode = 1
        case "pulse":
            r_mode = 2
        case "dynamic":
            r_mode = 3
        case "spiral":
            r_mode = 4
        case _:
            assert False, f"Mode '{mode}' not supported. "

    r_brightness = min(max(int(64 * brightness), 0), 63)
    r_period = min(max(int(64 * (1 - speed)), 0), 63)

    return bytes(
        [
            0x05,
            0x0C,
            0x72,
            0x01,
            r_controller,
            r_mode,
            red,
            green,
            blue,
            r_brightness,
            r_period,
            profile,
            0x01,
        ]
    )


def rgb_load_profile(
    controller: Controller,
    profile: Literal[1, 2, 3],
):
    r_controller = _get_controller(controller)

    return bytes(
        [
            0x05,
            0x06,
            0x73,
            0x02,
            r_controller,
            profile,
            0x01,
        ]
    )


def rgb_enable(controller: Controller, enable: bool):
    r_enable = enable & 0x01
    r_controller = _get_controller(controller)
    return bytes(
        [
            0x05,
            0x06,
            0x70,
            0x02,
            r_controller,
            r_enable,
            0x01,
        ]
    )


def rgb_multi_load_settings(
    mode: RgbMode,
    profile: Literal[1, 2, 3],
    red: int,
    green: int,
    blue: int,
    brightness: float = 1,
    speed: float = 1,
    init: bool = True,
):
    base = [
        rgb_set_profile("left", profile, mode, red, green, blue, brightness, speed),
        rgb_set_profile("right", profile, mode, red, green, blue, brightness, speed),
    ]
    # Always update
    # Old firmware has issues with new way
    # if not init:
    #     return base

    return [
        *base,
        rgb_load_profile("left", profile),
        rgb_load_profile("right", profile),
        rgb_enable("left", True),
        rgb_enable("right", True),
    ]


def rgb_multi_disable():
    return [
        rgb_enable("left", False),
        rgb_enable("right", False),
    ]


class RgbCallback:
    def __init__(self) -> None:
        self.prev_mode = None

    def __call__(self, dev: Device, events: Sequence[Event]):
        for ev in events:
            if ev["type"] != "led":
                continue

            reps = None
            mode = None
            match ev["mode"]:
                case "disable":
                    pass
                case "blinking":
                    mode = "pulse"
                case "rainbow":
                    mode = "dynamic"
                case "solid":
                    if ev["red"] or ev['green'] or ev['blue']:
                        mode = "solid"
                    else:
                        # Disable if brightness is 0
                        mode = None
                case "spiral":
                    mode = "spiral"
                case _:
                    pass

            if mode:
                reps = rgb_multi_load_settings(
                    mode,
                    0x03,
                    ev["red"],
                    ev["green"],
                    ev["blue"],
                    ev["brightness"],
                    ev["speed"],
                    self.prev_mode != mode,
                )
                # Only init sparingly, to speed up execution
                self.prev_mode = mode
            else:
                reps = rgb_multi_disable()

            for r in reps:
                dev.write(r)
