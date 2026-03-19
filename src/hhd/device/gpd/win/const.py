from hhd.controller import Axis, Button
from hhd.controller.physical.evdev import B, to_map
from hhd.controller.physical.hidraw import BM
from hhd.plugins import gen_gyro_state

GPD_TOUCHPAD_BUTTON_MAP: dict[int, Button] = to_map(
    {
        "touchpad_touch": [B("BTN_TOOL_FINGER")],  # also BTN_TOUCH
        "touchpad_right": [B("BTN_TOOL_DOUBLETAP"), B("BTN_RIGHT")],
        "touchpad_left": [B("BTN_MOUSE")],
    }
)

GPD_TOUCHPAD_AXIS_MAP: dict[int, Axis] = to_map(
    {
        "touchpad_x": [B("ABS_X")],  # also ABS_MT_POSITION_X
        "touchpad_y": [B("ABS_Y")],  # also ABS_MT_POSITION_Y
    }
)

GPD_WIN_DEFAULT_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_x", "accel", 1, None),
    "accel_y": ("accel_z", "accel", 1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_x", "anglvel", 1, None),
    "anglvel_y": ("gyro_z", "anglvel", 1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

GPD_WIN_MAX_2_2023_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", -1, None),
    "accel_y": ("accel_x", "accel", -1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_z", "anglvel", -1, None),
    "anglvel_y": ("gyro_x", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

GPD_WIN_4_8840U_MAPPINGS = gen_gyro_state("z", True, "x", False, "y", True)

GPD_WIN_5_MAPPINGS = gen_gyro_state("z", True, "x", False, "y", True)

GPD_WIN_5_BTN_MAPPINGS: dict[int, Button] = {
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    B("KEY_O"): "share", # Keyboard button: LMETA + LCTRL + O
    B("KEY_DELETE"): "share", # Keyboard button hold: DEL
    B("KEY_D"): "mode", # Home button: LMETA + D
    B("KEY_TAB"): "mode", # Home button hold: TAB
}

# GPD Win 5 new firmware: back buttons via vendor HID report (0x2f24:0x0137)
# Idle:  01 a5 00 5a ff 00 01 09 00 00 00 00
# rep[8]=0x68 mode switch, rep[9]=0x69 left back, rep[10]=0x6a right back
# Detect press by checking bit 5 (0x20), which is set in all key values
# and clear when idle (0x00).
GPD_WIN5_HID_BTN_MAP: dict[int | None, dict[Button, BM]] = {
    None: {
        "extra_r2": BM((8 << 3) + 2),
        "extra_l1": BM((9 << 3) + 2),
        "extra_r1": BM((10 << 3) + 2),
    }
}
