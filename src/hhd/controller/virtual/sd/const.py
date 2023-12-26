SDCONT_VENDOR = 0x28DE
SDCONT_PRODUCT = 0x1205
SDCONT_VERSION = 256
SDCONT_COUNTRY = 0
SDCONT_NAME = b"Emulated Steam Controller"

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
