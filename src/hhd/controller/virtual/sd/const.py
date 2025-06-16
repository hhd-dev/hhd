from hhd.controller.lib.common import AM, BM

SDCONT_VENDOR = 0x28DE
SDCONT_VERSION = 256
SDCONT_COUNTRY = 0

SDCONT_DESCRIPTOR = bytes(
    [
        0x06,
        0xFF,
        0xFF,  # // Usage Page (Vendor Usage Page 0xffff) 0
        0x09,
        0x01,  # // Usage (Vendor Usage 0x01)           3
        0xA1,
        0x01,  # // Collection (Application)            5
        0x09,
        0x02,  # //  Usage (Vendor Usage 0x02)          7
        0x09,
        0x03,  # //  Usage (Vendor Usage 0x03)          9
        0x15,
        0x00,  # //  Logical Minimum (0)                11
        0x26,
        0xFF,
        0x00,  # //  Logical Maximum (255)              13
        0x75,
        0x08,  # //  Report Size (8)                    16
        0x95,
        0x40,  # //  Report Count (64)                  18
        0x81,
        0x02,  # //  Input (Data,Var,Abs)               20
        0x09,
        0x06,  # //  Usage (Vendor Usage 0x06)          22
        0x09,
        0x07,  # //  Usage (Vendor Usage 0x07)          24
        0x15,
        0x00,  # //  Logical Minimum (0)                26
        0x26,
        0xFF,
        0x00,  # //  Logical Maximum (255)              28
        0x75,
        0x08,  # //  Report Size (8)                    31
        0x95,
        0x40,  # //  Report Count (64)                  33
        0xB1,
        0x02,  # //  Feature (Data,Var,Abs)             35
        0xC0,  # // End Collection                      37
    ]
)

SD_AXIS_MAP = {
    "touchpad_x": AM((20 << 3), "u16", scale=2**14 - 2, offset=2**14),
    "touchpad_y": AM((22 << 3), "u16", scale=2**14 - 2, offset=2**14),
    "touchpad_force": AM((58 << 3), "u16", scale=2**14 - 2),
    "accel_x": AM(
        (24 << 3), "i16", scale=16384 / 9.80665, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "accel_y": AM(
        (26 << 3), "i16", scale=-16384 / 9.80665, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "accel_z": AM(
        (28 << 3), "i16", scale=16384 / 9.80665, bounds=(-(2**15) + 2, 2**15 - 1)
    ),
    "gyro_x": AM((30 << 3), "i16", scale=16 * 180 / 3.14),
    "gyro_z": AM((32 << 3), "i16", scale=-16 * 180 / 3.14),
    "gyro_y": AM((34 << 3), "i16", scale=16 * 180 / 3.14),
    "rt": AM((44 << 3), "u16"),
    "lt": AM((46 << 3), "u16"),
    "ls_x": AM((48 << 3), "i16"),
    "ls_y": AM((50 << 3), "i16", flipped=True),
    "rs_x": AM((52 << 3), "i16"),
    "rs_y": AM((54 << 3), "i16", flipped=True),
}

# 0 -> 10000000 (0x80)
# 1 -> 01000000 (0x40)
# 2 -> 00100000 (0x20)
# 3 -> 00010000 (0x10)
# 4 -> 00001000 (0x08)
# 5 -> 00000100 (0x04)
# 6 -> 00000010 (0x02)
# 7 -> 00000001 (0x01)

SD_BTN_MAP = {
    "a": BM((8 << 3)),
    "x": BM((8 << 3) + 1),
    "b": BM((8 << 3) + 2),
    "y": BM((8 << 3) + 3),
    "lb": BM((8 << 3) + 4),
    "rb": BM((8 << 3) + 5),
    "lt": BM((8 << 3) + 6),
    "rt": BM((8 << 3) + 7),
    "extra_l2": BM((9 << 3)),
    "start": BM((9 << 3) + 1),
    "mode": BM((9 << 3) + 2),
    "select": BM((9 << 3) + 3),
    "dpad_down": BM((9 << 3) + 4),
    "dpad_left": BM((9 << 3) + 5),
    "dpad_right": BM((9 << 3) + 6),
    "dpad_up": BM((9 << 3) + 7),
    "ls": BM((10 << 3) + 1),
    "touchpad_touch": BM((10 << 3) + 3),
    "touchpad_left": BM((10 << 3) + 5),
    "extra_r2": BM((10 << 3) + 7),
    "rs": BM((11 << 3) + 5),
    "extra_r1": BM((13 << 3) + 5),
    "extra_l1": BM((13 << 3) + 6),
    "share": BM((14 << 3) + 5),
    # "touchpad_touch": BM((32 << 3), flipped=True),
    # "touchpad_touch2": BM((36 << 3), flipped=True),
    # "touchpad_left": BM((9 << 3) + 6),
}
