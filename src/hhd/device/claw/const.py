from hhd.controller.physical.evdev import B

MSI_CLAW_MAPPINGS = {
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    B("KEY_F15"): "mode",
    B("KEY_F16"): "share",
    B("KEY_G"): "share", # claw a8 after bios 104, it is KEY_LEFTMETA + KEY_G
}

MSI_CLAW_EX_MAPPINGS = {
    B("KEY_VOLUMEUP"): "key_volumeup",
    B("KEY_VOLUMEDOWN"): "key_volumedown",
    B("KEY_F16"): "mode",
    B("KEY_G"): "mode",
}

CONFS = { 
    "MS-1T41": {
        "name": "MSI Claw A1M",
        # "hrtimer": True, Uses sensor fusion garbage? From intel? Will need custom work
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_MAPPINGS,
    },
    "MS-1T42": {
        "name": "MSI Claw 7 AI+ A2VM",
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_MAPPINGS,
    },
    "MS-1T52": {
        "name": "MSI Claw 8 AI+ A2VM",
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_MAPPINGS,
    },
    "MS-1T91": {
        "name": "MSI Claw 8 EX AI+ CG3EM",
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_EX_MAPPINGS,
        "ex": True,
    },
    "MS-1T8K": {
        "name": "MSI Claw A8 BZ2EM",
        "extra_buttons": "dual",
        "btn_mapping": MSI_CLAW_MAPPINGS,
    },
}
