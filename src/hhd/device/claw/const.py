from hhd.controller.physical.evdev import B

MSI_CLAW_MAPPINGS = {
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    B("KEY_F15"): "mode",
    B("KEY_F16"): "share",
}

CONFS = {
    # MSI Claw
    "Claw A1M": {
        "name": "MSI Claw (1st gen)",
        # "hrtimer": True, Uses sensor fusion garbage? From intel? Will need custom work
        "extra_buttons": "none",
        "btn_mapping": MSI_CLAW_MAPPINGS,
        "type": "claw",
        "display_gyro": False,
    },
    "Claw 7 AI+ A2VM": {
        "name": "MSI Claw 7 (2nd gen)",
        "extra_buttons": "none",
        "btn_mapping": MSI_CLAW_MAPPINGS,
        "type": "claw",
        "display_gyro": False,
    },
    "Claw 8 AI+ A2VM": {
        "name": "MSI Claw 8",
        "extra_buttons": "none",
        "btn_mapping": MSI_CLAW_MAPPINGS,
        "type": "claw",
        "display_gyro": False,
    },
}
