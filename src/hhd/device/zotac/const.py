from hhd.controller import Axis, Button
from hhd.controller.physical.evdev import B
from hhd.controller.physical.hidraw import BM
from hhd.plugins import gen_gyro_state

# 0x1E19 as listed by InputPlumber and the original zotac-zone-hid driver;
# not seen on our test device (1ee9:1590).
ZOTAC_VIDS = [0x1EE9, 0x1E19]
ZOTAC_PID = 0x1590

# USB interfaces of the controller (1ee9:1590)
# 0: xpad gamepad, 1: keyboard (0x02), dials (0x03), mouse (0x04-0x06) reports,
# 2: unused, 3: vendor command interface (64 byte reports, 0xE1 header)
DIAL_INTERFACE = 1
CMD_INTERFACE = 3

# Keys sent by the controller keyboard (USB interface 1). The firmware sends
# them with modifiers (Zotac: Ctrl+Meta+F17, More: Ctrl+Meta+F18); only the
# main key is matched. M1/M2 are remapped to F22/F21 on startup.
ZOTAC_BTN_MAPPINGS: dict[int, Button] = {
    B("KEY_F17"): "mode",  # Zotac button
    B("KEY_F18"): "share",  # More button (QAM)
    B("KEY_F21"): "extra_l1",  # M2 (left hand)
    B("KEY_F22"): "extra_r1",  # M1 (right hand)
    # Home button: short press sends Meta+D, long press Ctrl+Alt+KP Delete
    B("KEY_D"): "keyboard",
    B("KEY_KPDOT"): "share",
    # Touchpad click zones mapped to touchpad clicks
    B("KEY_F13"): "touchpad_left",
    B("KEY_F14"): "touchpad_right",
}

# Touchpad click zones (button mapping sources). Each touchpad has four click
# zones. Factory default: only the left and right zones of the right touchpad
# are mapped (mouse left and right click).
TOUCHPAD_ZONES = {
    "left_up": 0x03,
    "left_down": 0x04,
    "left_left": 0x05,
    "left_right": 0x06,
    "right_up": 0x07,
    "right_down": 0x08,
    "right_left": 0x09,
    "right_right": 0x0A,
}

# Dials: report 0x03, byte 3. Each detent sends one report with a single bit
# set followed by a null report.
DIAL_REPORT = 0x03
DIAL_RIGHT_CW = BM((3 << 3) + 7)  # bit 0
DIAL_RIGHT_CCW = BM((3 << 3) + 6)  # bit 1
DIAL_LEFT_CW = BM((3 << 3) + 4)  # bit 3
DIAL_LEFT_CCW = BM((3 << 3) + 3)  # bit 4

# IMU (i2c-BMI0160:00). Measured with the accelerometer in three positions
# (flat, upright, right side down): right = -raw y, up = -raw x,
# towards the player = -raw z. HHD uses y for the axis towards the player and
# z for up (verified in Steam: pitch, roll and yaw).
ZOTAC_GYRO_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = (
    gen_gyro_state("z", True, "x", True, "y", True)
)

CONFS = {
    # Zotac Gaming Zone 1st gen, board name: G0A1W
    "ZOTAC GAMING ZONE": {
        "name": "Zotac Gaming Zone (1st gen)",
        "extra_buttons": "dual",
        "mapping": ZOTAC_GYRO_MAPPINGS,
        "hrtimer": True,
    },
}
