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

X1_MAPPING = gen_gyro_state("x", True, "z", False, "y", False)
X1_MINI_MAPPING = gen_gyro_state("z", True, "x", False, "y", True)

BTN_MAPPINGS: dict[int, Button] = {
    # Volume buttons come from the same keyboard
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    # Turbo Button [29, 56, 125] KEY_LEFTCTRL + KEY_LEFTALT + KEY_LEFTMETA
    B("KEY_LEFTALT"): "share",
    # Short press orange [32, 125] KEY_D + KEY_LEFTMETA
    B("KEY_D"): "mode",
    # KB Button [24, 97, 125]  KEY_O + KEY_RIGHTCTRL + KEY_LEFTMETA
    B("KEY_O"): "keyboard",
}

BTN_MAPPINGS_NONTURBO: dict[int, Button] = {
    # Volume buttons come from the same keyboard
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    # Short press orange [32, 125] KEY_D + KEY_LEFTMETA
    B("KEY_D"): "mode",
    # KB Button [24, 97, 125]  KEY_O + KEY_RIGHTCTRL + KEY_LEFTMETA
    # If we do not have turbo takeover, let turbo do its turbo thing, and
    # failover to having the keyboard button open the overlay
    B("KEY_O"): "share",
}

ONEX_DEFAULT_CONF = {
    "hrtimer": True,
}

OXP_F1_CONF = {
    "name": "ONEXPLAYER ONEXFLY",
    **ONEX_DEFAULT_CONF,
    "protocol": "mixed",
}
OXP_2_CONF = {
    "name": "ONEXPLAYER 2",
    **ONEX_DEFAULT_CONF,
    "protocol": "mixed",
    "rgb": False,
    "buttons": "none",
    "protocol": "none",  # explicitly disable
}
AOKZOE_CONF = {
    "name": "AOKZOE A1",
    "hrtimer": True,
    "protocol": "none",
    "rgb": False,
}

CONFS = {
    # Aokzoe
    "AOKZOE A1 AR07": AOKZOE_CONF,
    "AOKZOE A1 Pro": AOKZOE_CONF,
    # Onexplayer
    "ONE XPLAYER": {"name": "ONE XPLAYER", **ONEX_DEFAULT_CONF},
    "ONEXPLAYER Mini Pro": {
        "name": "ONEXPLAYER Mini Pro",
        **ONEX_DEFAULT_CONF,
        "protocol": "hid_v2",
    },
    "ONEXPLAYER mini A07": {"name": "ONEXPLAYER mini", **ONEX_DEFAULT_CONF},
    # OneXFly
    "ONEXPLAYER F1": OXP_F1_CONF,
    "ONEXPLAYER F1 EVA-01": OXP_F1_CONF,
    "ONEXPLAYER F1L": OXP_F1_CONF,
    "ONEXPLAYER F1 OLED": OXP_F1_CONF,
    "ONEXPLAYER F1Pro": OXP_F1_CONF,
    "ONEXPLAYER F1 EVA-02": OXP_F1_CONF, # F1Pro variant
    # OXP 2
    "ONEXPLAYER 2": OXP_2_CONF,
    "ONEXPLAYER 2 ARP23": OXP_2_CONF,
    "ONEXPLAYER 2 GA18": OXP_2_CONF,
    # Pro is a bit different
    "ONEXPLAYER 2 PRO ARP23": OXP_2_CONF,
    "ONEXPLAYER 2 PRO ARP23 EVA-01": OXP_2_CONF,
    # X1 Line
    "ONEXPLAYER X1 mini": {
        **ONEX_DEFAULT_CONF,
        "name": "ONEXPLAYER X1 mini",
        "x1": True,
        "mapping": X1_MINI_MAPPING,
        "protocol": "hid_v1",
    },
    "ONEXPLAYER X1 A": {
        **ONEX_DEFAULT_CONF,
        "name": "ONEXPLAYER X1 (AMD)",
        "x1": True,
        "rgb_secondary": True,
        "mapping": X1_MAPPING,
        "protocol": "serial",
    },
    "ONEXPLAYER X1 i": {
        **ONEX_DEFAULT_CONF,
        "name": "ONEXPLAYER X1 (Intel)",
        "x1": True,
        "rgb_secondary": True,
        "mapping": X1_MAPPING,
        "protocol": "serial",
        "turbo": False,  # disable turbo takeover so that it can be used for TDP
    },
}


def get_default_config(product_name: str, manufacturer: str):
    out = {
        "name": product_name,
        "manufacturer": manufacturer,
        "hrtimer": True,
        "untested": True,
        "x1": "X1" in product_name,
    }

    if "X1" in product_name and "mini" not in product_name.lower():
        out["rgb_secondary"] = True

    if "aokzoe" in manufacturer.lower():
        out["protocol"] = "none"
        out["rgb"] = False

    return out
