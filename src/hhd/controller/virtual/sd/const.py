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
    "touchpad_x": AM((20 << 3), "i16", scale=2**16-3, offset=-2**15+1),
    "touchpad_y": AM((22 << 3), "i16", scale=-2**16+3, offset=2**15-1),
    "touchpad_force": AM((58 << 3), "i16", scale=2**14 - 2),
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
    "gyro_z": AM((32 << 3), "i16", scale=16 * 180 / 3.14),
    "gyro_y": AM((34 << 3), "i16", scale=16 * 180 / 3.14),
    "rt": AM((44 << 3), "i16"),
    "lt": AM((46 << 3), "i16"),
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
    "rt": BM((8 << 3) + 6),
    "lt": BM((8 << 3) + 7),
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

SD_SETTINGS = [
    # /* 0 */
    "SETTING_MOUSE_SENSITIVITY",
    "SETTING_MOUSE_ACCELERATION",
    "SETTING_TRACKBALL_ROTATION_ANGLE",
    "SETTING_HAPTIC_INTENSITY_UNUSED",
    "SETTING_LEFT_GAMEPAD_STICK_ENABLED",
    "SETTING_RIGHT_GAMEPAD_STICK_ENABLED",
    "SETTING_USB_DEBUG_MODE",
    "SETTING_LEFT_TRACKPAD_MODE",
    "SETTING_RIGHT_TRACKPAD_MODE",
    "SETTING_MOUSE_POINTER_ENABLED",
    # /* 10 */
    "SETTING_DPAD_DEADZONE",
    "SETTING_MINIMUM_MOMENTUM_VEL",
    "SETTING_MOMENTUM_DECAY_AMMOUNT",
    "SETTING_TRACKPAD_RELATIVE_MODE_TICKS_PER_PIXEL",
    "SETTING_HAPTIC_INCREMENT",
    "SETTING_DPAD_ANGLE_SIN",
    "SETTING_DPAD_ANGLE_COS",
    "SETTING_MOMENTUM_VERTICAL_DIVISOR",
    "SETTING_MOMENTUM_MAXIMUM_VELOCITY",
    "SETTING_TRACKPAD_Z_ON",
    # /* 20 */
    "SETTING_TRACKPAD_Z_OFF",
    "SETTING_SENSITIVY_SCALE_AMMOUNT",
    "SETTING_LEFT_TRACKPAD_SECONDARY_MODE",
    "SETTING_RIGHT_TRACKPAD_SECONDARY_MODE",
    "SETTING_SMOOTH_ABSOLUTE_MOUSE",
    "SETTING_STEAMBUTTON_POWEROFF_TIME",
    "SETTING_UNUSED_1",
    "SETTING_TRACKPAD_OUTER_RADIUS",
    "SETTING_TRACKPAD_Z_ON_LEFT",
    "SETTING_TRACKPAD_Z_OFF_LEFT",
    # /* 30 */
    "SETTING_TRACKPAD_OUTER_SPIN_VEL",
    "SETTING_TRACKPAD_OUTER_SPIN_RADIUS",
    "SETTING_TRACKPAD_OUTER_SPIN_HORIZONTAL_ONLY",
    "SETTING_TRACKPAD_RELATIVE_MODE_DEADZONE",
    "SETTING_TRACKPAD_RELATIVE_MODE_MAX_VEL",
    "SETTING_TRACKPAD_RELATIVE_MODE_INVERT_Y",
    "SETTING_TRACKPAD_DOUBLE_TAP_BEEP_ENABLED",
    "SETTING_TRACKPAD_DOUBLE_TAP_BEEP_PERIOD",
    "SETTING_TRACKPAD_DOUBLE_TAP_BEEP_COUNT",
    "SETTING_TRACKPAD_OUTER_RADIUS_RELEASE_ON_TRANSITION",
    # /* 40 */
    "SETTING_RADIAL_MODE_ANGLE",
    "SETTING_HAPTIC_INTENSITY_MOUSE_MODE",
    "SETTING_LEFT_DPAD_REQUIRES_CLICK",
    "SETTING_RIGHT_DPAD_REQUIRES_CLICK",
    "SETTING_LED_BASELINE_BRIGHTNESS",
    "SETTING_LED_USER_BRIGHTNESS",
    "SETTING_ENABLE_RAW_JOYSTICK",
    "SETTING_ENABLE_FAST_SCAN",
    "SETTING_IMU_MODE",
    "SETTING_WIRELESS_PACKET_VERSION",
    # /* 50 */
    "SETTING_SLEEP_INACTIVITY_TIMEOUT",
    "SETTING_TRACKPAD_NOISE_THRESHOLD",
    "SETTING_LEFT_TRACKPAD_CLICK_PRESSURE",
    "SETTING_RIGHT_TRACKPAD_CLICK_PRESSURE",
    "SETTING_LEFT_BUMPER_CLICK_PRESSURE",
    "SETTING_RIGHT_BUMPER_CLICK_PRESSURE",
    "SETTING_LEFT_GRIP_CLICK_PRESSURE",
    "SETTING_RIGHT_GRIP_CLICK_PRESSURE",
    "SETTING_LEFT_GRIP2_CLICK_PRESSURE",
    "SETTING_RIGHT_GRIP2_CLICK_PRESSURE",
    # /* 60 */
    "SETTING_PRESSURE_MODE",
    "SETTING_CONTROLLER_TEST_MODE",
    "SETTING_TRIGGER_MODE",
    "SETTING_TRACKPAD_Z_THRESHOLD",
    "SETTING_FRAME_RATE",
    "SETTING_TRACKPAD_FILT_CTRL",
    "SETTING_TRACKPAD_CLIP",
    "SETTING_DEBUG_OUTPUT_SELECT",
    "SETTING_TRIGGER_THRESHOLD_PERCENT",
    "SETTING_TRACKPAD_FREQUENCY_HOPPING",
    # /* 70 */
    "SETTING_HAPTICS_ENABLED",
    "SETTING_STEAM_WATCHDOG_ENABLE",
    "SETTING_TIMP_TOUCH_THRESHOLD_ON",
    "SETTING_TIMP_TOUCH_THRESHOLD_OFF",
    "SETTING_FREQ_HOPPING",
    "SETTING_TEST_CONTROL",
    "SETTING_HAPTIC_MASTER_GAIN_DB",
    "SETTING_THUMB_TOUCH_THRESH",
    "SETTING_DEVICE_POWER_STATUS",
    "SETTING_HAPTIC_INTENSITY",
    # /* 80 */
    "SETTING_STABILIZER_ENABLED",
    "SETTING_TIMP_MODE_MTE",
]
