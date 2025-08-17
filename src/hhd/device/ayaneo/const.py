from hhd.controller import Axis

DEFAULT_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", 1, None),
    "accel_y": ("accel_x", "accel", -1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_z", "anglvel", 1, None),
    "anglvel_y": ("gyro_x", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

AYA_DEFAULT_CONF = {
    "hrtimer": True,
    "mapping": DEFAULT_MAPPINGS,
}

CONFS = {
    # Ayaneo
    "AYANEO 3": {
        "name": "AYANEO 3",
        "extra_buttons": "quad",
        "rgb": True,
        **AYA_DEFAULT_CONF,
    },
}