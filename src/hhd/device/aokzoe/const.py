from hhd.controller import Axis, Button, Configuration
from hhd.controller.physical.evdev import B, to_map

AOKZOE_DEFAULT_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", 1, 3),
    "accel_y": ("accel_x", "accel", 1, 3),
    "accel_z": ("accel_y", "accel", 1, 3),
    "anglvel_x": ("gyro_z", "anglvel", -1, None),
    "anglvel_y": ("gyro_x", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("gyro_ts", None, 1, None),
}

AOKZOE_BTN_MAPPINGS: dict[int, str] = {
    # Volume buttons come from the same keyboard
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    # A1 mappings
    B("KEY_LEFTALT"): "share", # Turbo Button [29, 56, 125] KEY_LEFTCTRL + KEY_LEFTALT + KEY_LEFTMETA
    B("KEY_D"): "mode", # Short press orange [32, 125] KEY_D + KEY_LEFTMETA
    B("KEY_O"): "extra_l1", # KB Button [24, 97, 125]  KEY_O + KEY_RIGHTCTRL + KEY_LEFTMETA
}
