from hhd.controller import Axis, Button, Configuration
from hhd.controller.physical.evdev import B, to_map
from hhd.controller.physical.hidraw import AM, BM, CM

LGO_TOUCHPAD_BUTTON_MAP: dict[int, Button] = to_map(
    {
        "touchpad_touch": [B("BTN_TOOL_FINGER")],  # also BTN_TOUCH
        "touchpad_right": [B("BTN_TOOL_DOUBLETAP")],
    }
)

LGO_TOUCHPAD_AXIS_MAP: dict[int, Axis] = to_map(
    {
        "touchpad_x": [B("ABS_X")],  # also ABS_MT_POSITION_X
        "touchpad_y": [B("ABS_Y")],  # also ABS_MT_POSITION_Y
    }
)

LGO_RAW_INTERFACE_BTN_ESSENTIALS: dict[int | None, dict[Button, BM]] = {
    0x74: {
        # Misc
        "mode": BM((18 << 3)),
        "share": BM((18 << 3) + 1),
        # Back buttons
        "extra_l1": BM((20 << 3)),
        "extra_l2": BM((20 << 3) + 1),
        "extra_r1": BM((20 << 3) + 2),
        "extra_r2": BM((20 << 3) + 5),
        "extra_r3": BM((20 << 3) + 4),
    }
}


LGO_RAW_INTERFACE_BTN_MAP: dict[int | None, dict[Button, BM]] = {
    0x74: {
        # Misc
        "mode": BM((18 << 3)),
        "share": BM((18 << 3) + 1),
        # Sticks
        "ls": BM((18 << 3) + 2),
        "rs": BM((18 << 3) + 3),
        # D-PAD
        "dpad_up": BM((18 << 3) + 4),
        "dpad_down": BM((18 << 3) + 5),
        "dpad_left": BM((18 << 3) + 6),
        "dpad_right": BM((18 << 3) + 7),
        # Thumbpad
        "a": BM((19 << 3) + 0),
        "b": BM((19 << 3) + 1),
        "x": BM((19 << 3) + 2),
        "y": BM((19 << 3) + 3),
        # Bumpers
        "lb": BM((19 << 3) + 4),
        "lt": BM((19 << 3) + 5),
        "rb": BM((19 << 3) + 6),
        "rt": BM((19 << 3) + 7),
        # Back buttons
        "extra_l1": BM((20 << 3)),
        "extra_l2": BM((20 << 3) + 1),
        "extra_r1": BM((20 << 3) + 2),
        "extra_r2": BM((20 << 3) + 5),
        "extra_r3": BM((20 << 3) + 4),
        # Select
        "start": BM((20 << 3) + 7),
        "select": BM((20 << 3) + 6),
        # Mouse
        "btn_middle": BM((21 << 3)),
    }
}


LGO_RAW_INTERFACE_AXIS_MAP: dict[int | None, dict[Axis, AM]] = {
    0x74: {
        "ls_x": AM(14 << 3, "m8"),
        "ls_y": AM(15 << 3, "m8"),
        "rs_x": AM(16 << 3, "m8"),
        "rs_y": AM(17 << 3, "m8"),
        "rt": AM(22 << 3, "u8"),
        "lt": AM(23 << 3, "u8"),
        # "mouse_wheel": AM(25 << 3, "m8", scale=1), # TODO: Fix weird behavior
        # "touchpad_x": AM(26 << 3, "u16"),
        # "touchpad_y": AM(28 << 3, "u16"),
        # Legacy
        # "left_gyro_x": AM(30 << 3, "m8"),
        # "left_gyro_y": AM(31 << 3, "m8"),
        # "right_gyro_x": AM(32 << 3, "m8"),
        # "right_gyro_y": AM(33 << 3, "m8"),
        # Per controller IMU
        # Left
        "left_imu_ts": AM(34 << 3, "u8", scale=1),
        "left_accel_x": AM(35 << 3, "i16", scale=-0.00212, order="big"),
        "left_accel_z": AM(37 << 3, "i16", scale=-0.00212, order="big"),
        "left_accel_y": AM(39 << 3, "i16", scale=-0.00212, order="big"),
        "left_gyro_x": AM(41 << 3, "i16", scale=-0.001065, order="big"),
        "left_gyro_z": AM(43 << 3, "i16", scale=-0.001065, order="big"),
        "left_gyro_y": AM(45 << 3, "i16", scale=-0.001065, order="big"),
        # Right
        "right_imu_ts": AM(47 << 3, "u8", scale=1),
        "right_accel_z": AM(48 << 3, "i16", scale=0.00212, order="big"),
        "right_accel_x": AM(50 << 3, "i16", scale=-0.00212, order="big"),
        "right_accel_y": AM(52 << 3, "i16", scale=-0.00212, order="big"),
        "right_gyro_z": AM(54 << 3, "i16", scale=0.001065, order="big"),
        "right_gyro_x": AM(56 << 3, "i16", scale=-0.001065, order="big"),
        "right_gyro_y": AM(58 << 3, "i16", scale=-0.001065, order="big"),
    }
}

LGO_RAW_INTERFACE_CONFIG_MAP: dict[int | None, dict[Configuration, CM]] = {
    0x74: {
        "battery_left": CM(5 << 3, "u8", scale=1, bounds=(0, 100)),
        "battery_right": CM(7 << 3, "u8", scale=1, bounds=(0, 100)),
        "is_connected_left": CM((10 << 3) + 7, "bit"),
        "is_connected_right": CM((11 << 3) + 7, "bit"),
        "is_attached_left": CM((12 << 3) + 7, "bit", flipped=True),
        "is_attached_right": CM((13 << 3) + 7, "bit", flipped=True),
    }
}
