from hhd.controller import Axis, Button, Configuration
from hhd.controller.physical.evdev import B, to_map

AYANEO_TOUCHPAD_BUTTON_MAP: dict[int, Button] = to_map(
    {
        "touchpad_touch": [B("BTN_TOOL_FINGER")],  # also BTN_TOUCH
        "touchpad_right": [B("BTN_TOOL_DOUBLETAP"), B("BTN_RIGHT")],
        "touchpad_left": [B("BTN_MOUSE")],
    }
)

AYANEO_TOUCHPAD_AXIS_MAP: dict[int, Axis] = to_map(
    {
        "touchpad_x": [B("ABS_X")],  # also ABS_MT_POSITION_X
        "touchpad_y": [B("ABS_Y")],  # also ABS_MT_POSITION_Y
    }
)

AYANEO_DEFAULT_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", 1, 3),
    "accel_y": ("accel_x", "accel", 1, 3),
    "accel_z": ("accel_y", "accel", 1, 3),
    "anglvel_x": ("gyro_x", "anglvel", 1, None),
    "anglvel_y": ("gyro_z", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("gyro_ts", None, 1, None),
}

AYANEO_AIR_PLUS_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", 1, 3),
    "accel_y": ("accel_x", "accel", 1, 3),
    "accel_z": ("accel_y", "accel", 1, 3),
    "anglvel_x": ("gyro_z", "anglvel", 1, None),
    "anglvel_y": ("gyro_x", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", 1, None),
    "timestamp": ("gyro_ts", None, 1, None),
}

AYANEO_DEFAULT_BTN_MAPPINGS: dict[int, str] = {
    B("KEY_F15"): "extra_l1",
    B("KEY_F16"): "extra_r1",
    B("KEY_F17"): "mode",
    B("KEY_D"): "share",
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
}

AYANEO_NEXT_BTN_MAPPINGS: dict[int, str] = {
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    B("D"): "share",
    B("KEY_F12"): "mode",
}