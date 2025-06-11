from hhd.controller import Axis, Button, Configuration
from hhd.controller.physical.evdev import B, to_map
from hhd.plugins import gen_gyro_state

DEFAULT_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_x", "accel", 1, None),
    "accel_y": ("accel_z", "accel", 1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_x", "anglvel", 1, None),
    "anglvel_y": ("gyro_z", "anglvel", 1, None), 
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

AT_BTN_MAPPINGS: dict[int, str] = {
    # Volume buttons come from the same keyboard
    B("KEY_F16"): "mode",  # Big Button
    B("KEY_F15"): "share",  # Small Button
    # B("KEY_F17"): "extra_l1",  # LC Button
    # B("KEY_F18"): "extra_r1",  # RC Button
}

GAMEPAD_BTN_MAPPINGS: dict[int, str] = {
    # Volume buttons come from the same keyboard
    # B("KEY_F16"): "mode",  # Big Button
    # B("KEY_F15"): "share",  # Small Button
    B("KEY_F17"): "extra_l1",  # LC Button
    B("KEY_F18"): "extra_r1",  # RC Button
}

CONFS = {
    # New hardware new firmware, the unit below was dissassembled
    # "G1621-02": {"name": "OrangePi G1621-02/G1621-02", "hrtimer": True},
    "NEO-01": {"name": "OrangePi NEO-01/NEO-01", "hrtimer": True},
}


def get_default_config(product_name: str):
    out = {
        "name": product_name,
        "hrtimer": True,
        "untested": True,
    }

    return out
