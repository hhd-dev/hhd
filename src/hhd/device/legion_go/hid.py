import logging
from enum import Enum
from typing import Literal, Sequence

from hhd.controller import Event
from hhd.controller.lib.hid import Device
from hhd.controller.physical.hidraw import GenericGamepadHidraw

logger = logging.getLogger(__name__)

Controller = Literal["left", "right"]
RgbMode = Literal["solid", "pulse", "dynamic", "spiral"]

RGB_MODE_PULSE = 0x02
RGB_MODE_DYNAMIC = 0x03
RGB_MODE_SPIRAL = 0x04


def to_bytes(s: str):
    return bytes.fromhex(s.replace(" ", ""))


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


def controller_enable_gyro(controller: Controller):
    rc = _get_controller(controller)
    EN = 0x01
    M = 0x02
    return [
        # Enable the gyro if its disabled
        bytes([0x05, 0x06, 0x6A, 0x02, rc, EN, 0x01]),
        # Enable high quality report
        bytes([0x05, 0x06, 0x6A, 0x07, rc, M, 0x01]),
    ]


def controller_disable_gyro(controller: Controller):
    rc = _get_controller(controller)
    M = 0x01
    return [
        # Disable high quality report
        bytes([0x05, 0x06, 0x6A, 0x07, rc, M, 0x01]),
    ]


def controller_factory_reset():
    return [
        # RX
        to_bytes("0405 05 01 01 01 01"),
        # Dongle (?)
        to_bytes("0405 05 01 01 02 01"),
        # Left
        to_bytes("0405 05 01 01 03 01"),
        # Right
        to_bytes("0405 05 01 01 04 01"),
    ]


def controller_legion_swap(enabled):
    return [to_bytes(f"0506 69 0401 {'02' if enabled else '01'} 01")]


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
        try:
            for ev in events:
                if ev["type"] != "led":
                    continue

                reps = None
                mode = None
                match ev["mode"]:
                    case "disabled":
                        pass
                    case "pulse":
                        mode = "pulse"
                    case "rainbow":
                        mode = "dynamic"
                    case "solid":
                        if ev["red"] or ev["green"] or ev["blue"]:
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
        except Exception as e:
            logger.error(f"Error while setting RGB:\n{e}")


class LegionHidraw(GenericGamepadHidraw):
    def with_settings(
        self,
        gyro: str | None,
        reset: bool,
        use_touchpad: bool = False,
        swap_legion: bool = False,
    ):
        self.gyro = gyro
        self.reset = reset
        self.use_touchpad = use_touchpad
        self.old_touched = False
        self.old_x = 0
        self.old_y = 0
        self.touch_changed = None
        self.touchpad_init = True
        self.swap_legion = swap_legion
        return self

    def open(self):
        out = super().open()
        if not out:
            return out
        if not self.dev:
            return out

        cmds = []

        if self.reset:
            logger.warning(f"Factory Resetting controllers")
            cmds.extend(controller_factory_reset())
        gyro_active = self.gyro in ("left", "right", "both")
        if self.gyro in ("left", "both") or (not gyro_active and self.use_touchpad):
            cmds.extend(controller_enable_gyro("left"))
        if self.gyro in ("right", "both"):
            cmds.extend(controller_enable_gyro("right"))
        # Always disable legion swap and use our version
        cmds.extend(controller_legion_swap(False))

        for r in cmds:
            self.dev.write(r)

        return out

    def produce(self, fds: Sequence[int]):
        out = super().produce(fds)

        # TODO: Cleanup
        # Or remove, since this option is problematic
        # If removing, remove the produce function completely
        if self.use_touchpad and self.report:
            if self.touchpad_init:
                self.touchpad_init = False
                out = [
                    *out,
                    {
                        "type": "configuration",
                        "code": "touchpad_aspect_ratio",
                        "value": 1,
                    },
                ]

            x = int.from_bytes(self.report[26:28])
            y = int.from_bytes(self.report[28:30])
            touched = bool(x or y)
            changed = touched != self.old_touched or x != self.old_x or y != self.old_y
            if changed:
                out = list(out)
                if touched != self.old_touched:
                    self.old_touched = touched
                    out.append(
                        {"type": "button", "code": "touchpad_touch", "value": touched}
                    )
                if x != self.old_x:
                    self.old_x = x
                    out.append(
                        {"type": "axis", "code": "touchpad_x", "value": x / 1000}
                    )
                if y != self.old_y:
                    self.old_y = y
                    out.append(
                        {"type": "axis", "code": "touchpad_y", "value": y / 1000}
                    )

        return out

    def close(self, exit: bool) -> bool:
        if not self.dev:
            return super().close(exit)

        cmds = []
        # Always reset both gyros to avoid leaving them on
        # in case they use battery
        cmds.extend(controller_disable_gyro("left"))
        cmds.extend(controller_disable_gyro("right"))
        # Restore the windows legion swap version for continuity
        cmds.extend(controller_legion_swap(self.swap_legion))
        for r in cmds:
            self.dev.write(r)

        return super().close(exit)
