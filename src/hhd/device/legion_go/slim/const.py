from hhd.controller import Axis, Button, Configuration
from hhd.controller.physical.evdev import B, to_map
from hhd.controller.physical.hidraw import AM, BM, CM

GOS_INTERFACE_BTN_ESSENTIALS: dict[Button, BM] = {
    # Misc
    "mode": BM((0 << 3) + 7),
    "share": BM((0 << 3) + 6),
    # Back buttons
    "extra_l1": BM((2 << 3) + 7),
    "extra_r1": BM((2 << 3) + 6),
}


GOS_INTERFACE_BTN_MAP: dict[Button, BM] = {
    # Misc
    "mode": BM((0 << 3) + 7),
    "share": BM((0 << 3) + 6),
    # Sticks
    "ls": BM((0 << 3) + 5),
    "rs": BM((0 << 3) + 4),
    # D-PAD
    "dpad_up": BM((0 << 3) + 3),
    "dpad_down": BM((0 << 3) + 2),
    "dpad_left": BM((0 << 3) + 1),
    "dpad_right": BM((0 << 3) + 0),
    # Thumbpad
    "a": BM((1 << 3) + 7),
    "b": BM((1 << 3) + 6),
    "x": BM((1 << 3) + 5),
    "y": BM((1 << 3) + 4),
    # Bumpers
    "lb": BM((1 << 3) + 3),
    "lt": BM((1 << 3) + 2),
    "rb": BM((1 << 3) + 1),
    "rt": BM((1 << 3) + 0),
    # Back buttons
    "extra_l1": BM((2 << 3) + 7),
    "extra_r1": BM((2 << 3) + 6),
    # Select
    "start": BM((2 << 3) + 0),
    "select": BM((2 << 3) + 1),
}


GOS_INTERFACE_AXIS_MAP: dict[Axis, AM] = {
    "ls_x": AM(4 << 3, "m8"),
    "ls_y": AM(5 << 3, "m8"),
    "rs_x": AM(6 << 3, "m8"),
    "rs_y": AM(7 << 3, "m8"),
    "rt": AM(12 << 3, "u8"),
    "lt": AM(13 << 3, "u8"),
    # # Controller IMU
    "accel_x": AM(14 << 3, "i16", scale=-0.00212, order="little"),
    "accel_z": AM(16 << 3, "i16", scale=-0.00212, order="little"),
    "accel_y": AM(18 << 3, "i16", scale=-0.00212, order="little"),
    "gyro_x": AM(20 << 3, "i16", scale=-0.0005325, order="little"),
    "gyro_z": AM(22 << 3, "i16", scale=0.0005325, order="little"),
    "gyro_y": AM(24 << 3, "i16", scale=-0.0005325, order="little"),
}

GOS_TOUCHPAD_BUTTON_MAP: dict[int, Button] = to_map(
    {
        "touchpad_touch": [B("BTN_TOOL_FINGER")],  # also BTN_TOUCH
        "touchpad_left": [B("BTN_LEFT")],
    }
)

GOS_TOUCHPAD_AXIS_MAP: dict[int, Axis] = to_map(
    {
        "touchpad_x": [B("ABS_X")],  # also ABS_MT_POSITION_X
        "touchpad_y": [B("ABS_Y")],  # also ABS_MT_POSITION_Y
    }
)
