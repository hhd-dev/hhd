from hhd.controller.physical.evdev import B

MSI_CLAW_MAPPINGS = {
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    B("KEY_F15"): "mode",
    B("KEY_F16"): "share",
}

CONFS = { 
    "MS-1T41": {
        "name": "MSI Claw (1st gen)",
        # "hrtimer": True, Uses sensor fusion garbage? From intel? Will need custom work
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_MAPPINGS,
        "type": "claw",
        "display_gyro": False,
    },
    "MS-1T42": {
        "name": "MSI Claw 7 (2nd gen)",
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_MAPPINGS,
        "type": "claw",
        "display_gyro": False,
    },
    "MS-1T52": {
        "name": "MSI Claw 8",
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_MAPPINGS,
        "type": "claw",
        "display_gyro": False,
    },
}
