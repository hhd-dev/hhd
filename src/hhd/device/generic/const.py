from hhd.controller import Axis, Button, Configuration
from hhd.controller.physical.evdev import B, to_map
from hhd.plugins import gen_gyro_state

DEFAULT_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", 1, None),
    "accel_y": ("accel_x", "accel", -1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_z", "anglvel", 1, None),
    "anglvel_y": ("gyro_x", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

BTN_MAPPINGS: dict[int, str] = {
    # Volume buttons come from the same keyboard
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    #
    # AOKZOE A1 mappings And onexplayer mini pro mappings
    #
    # Turbo Button [29, 56, 125] KEY_LEFTCTRL + KEY_LEFTALT + KEY_LEFTMETA
    B("KEY_LEFTALT"): "share",
    # Short press orange [32, 125] KEY_D + KEY_LEFTMETA
    B("KEY_D"): "mode",
    # KB Button [24, 97, 125]  KEY_O + KEY_RIGHTCTRL + KEY_LEFTMETA
    B("KEY_O"): "extra_l1",
    #
    # Loki Max
    #
    # Provided by AOKZOE A1 Turbo button as KEY_LEFTALT
    # B("KEY_T"): "share",  # T + LCTRL + LSHFT + LALT
}

AMBERNIC_MAPPINGS: dict[int, str] = {
    B("KEY_LEFTMETA"): "share",
    B("KEY_G"): "mode",
}

MSI_CLAW_MAPPINGS = {
    B("KEY_F15"): "share",
    B("KEY_F16"): "mode",
}

AYANEO_DEFAULT_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", 1, None),
    "accel_y": ("accel_x", "accel", -1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_z", "anglvel", 1, None),
    "anglvel_y": ("gyro_x", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

AYANEO_AIR_PLUS_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_z", "accel", -1, None),
    "accel_y": ("accel_x", "accel", -1, None),
    "accel_z": ("accel_y", "accel", 1, None),
    "anglvel_x": ("gyro_z", "anglvel", -1, None),
    "anglvel_y": ("gyro_x", "anglvel", -1, None),
    "anglvel_z": ("gyro_y", "anglvel", 1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

AYANEO_BTN_MAPPINGS: dict[int, str] = {
    # Volume buttons come from the same keyboard
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    # Air Plus mappings
    B("KEY_F17"): "mode",  # Big Button
    B("KEY_D"): "share",  # Small Button
    B("KEY_F15"): "extra_l1",  # LC Button
    B("KEY_F16"): "extra_r1",  # RC Button
    # NEXT mappings
    B(
        "KEY_F12"
    ): "mode",  # Big Button NEXT:[[96, 105, 133], [88, 97, 125]] ; Air [88, 97, 125]
    # B("KEY_D"): "share", # Small Button [[40, 133], [32, 125]]
    # 2021 Mappings
    B("KEY_DELETE"): "share",  # TM Button [97,100,111]
    B("KEY_ESC"): "extra_l1",  # ESC Button [1]
    B("KEY_O"): "extra_r1",  # KB Button [97, 24, 125]
    # B("KEY_LEFTMETA"): "extra_r1", # Win Button [125], Conflict with KB Button
    # Air mappings
    B("KEY_F11"): "extra_l1",  # LC Button [87, 97, 125] F11 + LCTRL + LMETA
    B("KEY_F10"): "extra_r1",  # Rc Button [68, 97, 125] F10 + LCTRL + LMETA
}

AYA_DEFAULT_CONF = {
    "hrtimer": True,
    "btn_mapping": AYANEO_BTN_MAPPINGS,
    "mapping": AYANEO_DEFAULT_MAPPINGS,
}

CONFS = {
    # Aokzoe
    "AOKZOE A1 AR07": {"name": "AOKZOE A1", "hrtimer": True},
    "AOKZOE A1 Pro": {"name": "AOKZOE A1 Pro", "hrtimer": True},
    # Onexplayer
    "ONEXPLAYER Mini Pro": {"name": "ONEXPLAYER Mini Pro", "hrtimer": True},
    "ONEXPLAYER F1": {"name": "ONEXPLAYER ONEXFLY", "hrtimer": True},
    "ONEXPLAYER F1 EVA-01": {"name": "ONEXPLAYER ONEXFLY", "hrtimer": True},
    "ONEXPLAYER X1 mini": {"name": "ONEXPLAYER X1 mini", "hrtimer": True},
    "ONEXPLAYER mini A07": {"name": "ONEXPLAYER mini", "hrtimer": True},
    "ONEXPLAYER 2 ARP23": {"name": "ONEXPLAYER 2", "hrtimer": True},
    "ONEXPLAYER 2 PRO ARP23": {"name": "ONEXPLAYER 2 PRO", "hrtimer": True},
    "ONEXPLAYER 2 PRO ARP23 EVA-01": {"name": "ONEXPLAYER 2 PRO", "hrtimer": True},
    # Ayn
    "Loki MiniPro": {
        "name": "Loki MiniPro",
        "hrtimer": True,
        "mapping": gen_gyro_state("x", False, "z", False, "y", True),
        "extra_buttons": "none",
    },
    "Loki Max": {
        "name": "Loki Max",
        "hrtimer": True,
        "mapping": gen_gyro_state("x", False, "z", False, "y", True),
        "extra_buttons": "none",
    },
    "Loki Zero": {
        "name": "Loki Zero",
        "hrtimer": True,
        "mapping": gen_gyro_state("x", False, "z", False, "y", True),
        "extra_buttons": "none",
    },
    # Ayaneo
    "AIR Plus": {
        "name": "AYANEO AIR Plus",
        **AYA_DEFAULT_CONF,
        "mapping": AYANEO_AIR_PLUS_MAPPINGS,
    },
    "AIR 1S": {"name": "AIR 1S", **AYA_DEFAULT_CONF},
    "AIR 1S Limited": {"name": "AIR 1S Limited", **AYA_DEFAULT_CONF},
    "AYANEO 2": {"name": "AYANEO 2", **AYA_DEFAULT_CONF},
    "AYANEO 2S": {"name": "AYANEO S2", **AYA_DEFAULT_CONF},
    "GEEK": {"name": "AYANEO GEEK", **AYA_DEFAULT_CONF},
    "GEEK 1S": {"name": "AYANEO GEEK 1S", **AYA_DEFAULT_CONF},
    "AIR": {"name": "AYANEO AIR", **AYA_DEFAULT_CONF},
    "AIR Pro": {"name": "AYANEO AIR Pro", **AYA_DEFAULT_CONF},
    "NEXT Advance": {"name": "AYANEO NEXT Advance", **AYA_DEFAULT_CONF},
    "NEXT Lite": {"name": "AYANEO NEXT Lite", **AYA_DEFAULT_CONF},
    "NEXT Pro": {"name": "AYANEO NEXT Pro", **AYA_DEFAULT_CONF},
    "NEXT": {"name": "AYANEO NEXT", **AYA_DEFAULT_CONF},
    "SLIDE": {
        "name": "AYANEO SLIDE",
        **AYA_DEFAULT_CONF,
        "mapping": gen_gyro_state("z", False, "x", False, "y", False),
    },
    "AYA NEO FOUNDER": {"name": "AYA NEO FOUNDER", **AYA_DEFAULT_CONF},
    "AYA NEO 2021": {"name": "AYA NEO 2021", **AYA_DEFAULT_CONF},
    "AYANEO 2021": {"name": "AYANEO 2021", **AYA_DEFAULT_CONF},
    "AYANEO 2021 Pro": {"name": "AYANEO 2021 Pro", **AYA_DEFAULT_CONF},
    "AYANEO 2021 Pro Retro Power": {
        "name": "AYANEO 2021 Pro Retro Power",
        **AYA_DEFAULT_CONF,
    },
    # Ambernic
    "Win600": {
        "name": "Ambernic Win600",
        "btn_mapping": AMBERNIC_MAPPINGS,
        "extra_buttons": "none",
    },
    # MSI Claw
    "Claw A1M": {
        "name": "MSI Claw (1st gen)",
        # "hrtimer": True, Uses sensor fusion garbage? From intel? Will need custom work
        "extra_buttons": "none",
        "btn_mapping": MSI_CLAW_MAPPINGS,
    },
}


def get_default_config(product_name: str, manufacturer: str):
    out = {
        "name": product_name,
        "manufacturer": manufacturer,
        "hrtimer": True,
        "untested": True,
    }

    if manufacturer == "AYA":
        out["btn_mapping"] = AYANEO_BTN_MAPPINGS
        out["mapping"] = AYANEO_DEFAULT_MAPPINGS

    return out
