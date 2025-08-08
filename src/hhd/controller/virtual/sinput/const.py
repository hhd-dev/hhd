from hhd.controller.lib.common import AM, BM

SINPUT_HID_REPORT = bytes([
    0x05, 0x01,                    # Usage Page (Generic Desktop Ctrls)
    0x09, 0x05,                    # Usage (Gamepad)
    0xA1, 0x01,                    # Collection (Application)
    
    # INPUT REPORT ID 0x01 - Main gamepad data
    0x85, 0x01,                    #   Report ID (1)
    
    # Padding bytes (bytes 2-3) - Plug status and Charge Percent (0-100)
    0x06, 0x00, 0xFF,              #   Usage Page (Vendor Defined)
    0x09, 0x01,                    #   Usage (Vendor Usage 1)
    0x15, 0x00,                    #   Logical Minimum (0)
    0x25, 0xFF,                    #   Logical Maximum (255)
    0x75, 0x08,                    #   Report Size (8)
    0x95, 0x02,                    #   Report Count (2)
    0x81, 0x02,                    #   Input (Data,Var,Abs)

    # --- 32 buttons ---
    0x05, 0x09,        # Usage Page (Button)
    0x19, 0x01,        #   Usage Minimum (Button 1)
    0x29, 0x20,        #   Usage Maximum (Button 32)
    0x15, 0x00,        #   Logical Min (0)
    0x25, 0x01,        #   Logical Max (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x20,        #   Report Count (32)
    0x81, 0x02,        #   Input (Data,Var,Abs)
    
    # Analog Sticks and Triggers
    0x05, 0x01,                    # Usage Page (Generic Desktop)
    # Left Stick X (bytes 8-9)
    0x09, 0x30,                    #   Usage (X)
    # Left Stick Y (bytes 10-11)
    0x09, 0x31,                    #   Usage (Y)
    # Right Stick X (bytes 12-13)
    0x09, 0x32,                    #   Usage (Z)
    # Right Stick Y (bytes 14-15)
    0x09, 0x35,                    #   Usage (Rz)
    # Right Trigger (bytes 18-19)
    0x09, 0x33,                    #   Usage (Rx)
    # Left Trigger  (bytes 16-17)
    0x09, 0x34,                     #  Usage (Ry)
    0x16, 0x00, 0x80,              #   Logical Minimum (-32768)
    0x26, 0xFF, 0x7F,              #   Logical Maximum (32767)
    0x75, 0x10,                    #   Report Size (16)
    0x95, 0x06,                    #   Report Count (6)
    0x81, 0x02,                    #   Input (Data,Var,Abs)
    
    # Motion data and Reserved data (bytes 20-63) - 44 bytes
    # This includes gyro/accel data that apps can use if supported
    0x06, 0x00, 0xFF,              # Usage Page (Vendor Defined)
    
    # Motion Input Timestamp (Microseconds)
    0x09, 0x20,                    #   Usage (Vendor Usage 0x20)
    0x15, 0x00,                    #   Logical Minimum (0)
    0x26, 0xFF, 0xFF,              #   Logical Maximum (655535)
    0x75, 0x20,                    #   Report Size (32)
    0x95, 0x01,                    #   Report Count (1)
    0x81, 0x02,                    #   Input (Data,Var,Abs)

    # Motion Input Accelerometer XYZ (Gs) and Gyroscope XYZ (Degrees Per Second)
    0x09, 0x21,                    #   Usage (Vendor Usage 0x21)
    0x16, 0x00, 0x80,              #   Logical Minimum (-32768)
    0x26, 0xFF, 0x7F,              #   Logical Maximum (32767)
    0x75, 0x10,                    #   Report Size (16)
    0x95, 0x06,                    #   Report Count (6)
    0x81, 0x02,                    #   Input (Data,Var,Abs)

    # Reserved padding
    0x09, 0x22,                    #   Usage (Vendor Usage 0x22)
    0x15, 0x00,                    #   Logical Minimum (0)
    0x26, 0xFF, 0x00,              #   Logical Maximum (255)
    0x75, 0x08,                    #   Report Size (8)
    0x95, 0x1D,                    #   Report Count (29)
    0x81, 0x02,                    #   Input (Data,Var,Abs)
    
    # INPUT REPORT ID 0x02 - Vendor COMMAND data
    0x85, 0x02,                    #   Report ID (2)
    0x09, 0x23,                    #   Usage (Vendor Usage 0x23)
    0x15, 0x00,                    #   Logical Minimum (0)
    0x26, 0xFF, 0x00,              #   Logical Maximum (255)
    0x75, 0x08,                    #   Report Size (8 bits)
    0x95, 0x3F,                    #   Report Count (63) - 64 bytes minus report ID
    0x81, 0x02,                    #   Input (Data,Var,Abs)
    
    # FEATURE REPORT ID 0x02 - Vendor Feature data
    0x09, 0x24,                    #   Usage (Vendor Usage 0x24)
    0x19, 0x00,                    #   Usage Minimum (0)
    0x2a, 0xff, 0x00,              #   Usage Maximum (255)
    0x15, 0x00,                    #   Logical Minimum (0)
    0x26, 0xff, 0x00,              #   Logical Maximum (255)
    0x75, 0x08,                    #   Report Size (8)
    0x95, 0x3f,                    #   Report Count (63)
    0xb1, 0x00,                    #   Feature (Data,Arr,Abs)

    # OUTPUT REPORT ID 0x03 - Vendor COMMAND data
    0x85, 0x03,                    #   Report ID (3)
    0x09, 0x24,                    #   Usage (Vendor Usage 0x24)
    0x15, 0x00,                    #   Logical Minimum (0)
    0x26, 0xFF, 0x00,              #   Logical Maximum (255)
    0x75, 0x08,                    #   Report Size (8 bits)
    0x95, 0x2F,                    #   Report Count (47) - 48 bytes minus report ID
    0x91, 0x02,                    #   Output (Data,Var,Abs)

    0xC0                           # End Collection 
])

ACCEL_MAX_G = 3
ACCEL_SCALE = (2**15 - 1) / ACCEL_MAX_G / 9.80665
GYRO_MAX_DPS = 1600
GYRO_SCALE = -(2**15 - 1) * 180 / 3.14 / GYRO_MAX_DPS

SINPUT_AXIS_MAP_V1 = {
    "ls_x": AM((7 << 3), "i16"),
    "ls_y": AM((9 << 3), "i16"),
    "rs_x": AM((11 << 3), "i16"),
    "rs_y": AM((13 << 3), "i16"),
    "rt": AM((15 << 3), "i16", scale=2**16 - 2, offset=-(2**15 - 1)),
    "lt": AM((17 << 3), "i16", scale=2**16 - 2, offset=-(2**15 - 1)),
    "accel_x": AM(
        (23 << 3), "i16", scale=ACCEL_SCALE, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "accel_y": AM(
        (25 << 3), "i16", scale=ACCEL_SCALE, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "accel_z": AM(
        (27 << 3), "i16", scale=ACCEL_SCALE, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "gyro_x": AM((29 << 3), "i16", scale=GYRO_SCALE),
    "gyro_y": AM((31 << 3), "i16", scale=GYRO_SCALE),
    "gyro_z": AM((33 << 3), "i16", scale=GYRO_SCALE),
}

ACCEL_SCALE_V2 = 10197
GYRO_SCALE_V2 = 11465

SINPUT_AXIS_MAP_V2 = {
    "ls_x": AM((7 << 3), "i16"),
    "ls_y": AM((9 << 3), "i16"),
    "rs_x": AM((11 << 3), "i16"),
    "rs_y": AM((13 << 3), "i16"),
    "rt": AM((15 << 3), "i16", scale=2**16 - 2, offset=-(2**15 - 1)),
    "lt": AM((17 << 3), "i16", scale=2**16 - 2, offset=-(2**15 - 1)),
    "accel_x": AM(
        (23 << 3), "i16", scale=ACCEL_SCALE_V2 / 10, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "accel_y": AM(
        (25 << 3), "i16", scale=ACCEL_SCALE_V2 / 10, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "accel_z": AM(
        (27 << 3), "i16", scale=ACCEL_SCALE_V2 / 10, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "gyro_x": AM((29 << 3), "i16", scale=-GYRO_SCALE_V2 / 10),
    "gyro_y": AM((31 << 3), "i16", scale=-GYRO_SCALE_V2 / 10),
    "gyro_z": AM((33 << 3), "i16", scale=-GYRO_SCALE_V2 / 10),
}

get_button_mask = lambda ofs: {
    # Byte 0
    "b": BM((ofs << 3) + 7),
    "a": BM((ofs << 3) + 6),
    "y": BM((ofs << 3) + 5),
    "x": BM((ofs << 3) + 4),
    "dpad_up": BM((ofs << 3) + 3),
    "dpad_down": BM((ofs << 3) + 2),
    "dpad_left": BM((ofs << 3) + 1),
    "dpad_right": BM((ofs << 3)),
    # Byte 1
    "ls": BM(((ofs + 1) << 3) + 7),
    "rs": BM(((ofs + 1) << 3) + 6),
    "lb": BM(((ofs + 1) << 3) + 5),
    "rb": BM(((ofs + 1) << 3) + 4),
    # "lt": BM(((ofs + 1) << 3) + 3),
    # "rt": BM(((ofs + 1) << 3) + 2),
    "extra_l1": BM(((ofs + 1) << 3) + 1),
    "extra_r1": BM(((ofs + 1) << 3)),
    # Byte 2
    "start": BM(((ofs + 2) << 3) + 7),
    "select": BM(((ofs + 2) << 3) + 6),
    "mode": BM(((ofs + 2) << 3) + 5),
    "share": BM(((ofs + 2) << 3) + 4),
    "extra_r2": BM(((ofs + 2) << 3) + 3),
    "extra_l2": BM(((ofs + 2) << 3) + 2),
    "touchpad_left": BM(((ofs + 2) << 3) + 1),
}

SINPUT_BTN_MAP = get_button_mask(3)

XINPUT = [
    "b",
    "a",
    "y",
    "x",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
    "ls",
    "rs",
    "lb",
    "rb",
    "start",
    "select",
    "mode",
]

STANDARD_BUTTONS = XINPUT + [
    "share",
]

DUAL_PADDLES = [
    "extra_l1",
    "extra_r1",
] + STANDARD_BUTTONS

QUAD_PADDLES = [
    "extra_l1",
    "extra_r1",
    "extra_l2",
    "extra_r2",
] + STANDARD_BUTTONS

SDL_SUBTYPE_FULL_MAPPING = 0x00
SDL_SUBTYPE_XINPUT_ONLY = 0x01
SDL_SUBTYPE_XINPUT_SHARE_NONE = 0x02
SDL_SUBTYPE_XINPUT_SHARE_DUAL = 0x03
SDL_SUBTYPE_XINPUT_SHARE_QUAD = 0x04
SDL_SUBTYPE_XINPUT_SHARE_NONE_CLICK = 0x05
SDL_SUBTYPE_XINPUT_SHARE_DUAL_CLICK = 0x06
SDL_SUBTYPE_XINPUT_SHARE_QUAD_CLICK = 0x07
SDL_SUBTYPE_LOAD_FIRMWARE = 0xFF

SINPUT_AVAILABLE_BUTTONS = {
    SDL_SUBTYPE_XINPUT_ONLY: STANDARD_BUTTONS,
    SDL_SUBTYPE_XINPUT_SHARE_NONE: STANDARD_BUTTONS,
    SDL_SUBTYPE_XINPUT_SHARE_DUAL: DUAL_PADDLES,
    SDL_SUBTYPE_XINPUT_SHARE_QUAD: QUAD_PADDLES,
    SDL_SUBTYPE_XINPUT_SHARE_NONE_CLICK: STANDARD_BUTTONS + ["touchpad_left"],
    SDL_SUBTYPE_XINPUT_SHARE_DUAL_CLICK: DUAL_PADDLES + ["touchpad_left"],
    SDL_SUBTYPE_XINPUT_SHARE_QUAD_CLICK: QUAD_PADDLES + ["touchpad_left"],
}
