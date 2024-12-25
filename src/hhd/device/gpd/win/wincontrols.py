import logging
import time

from hhd.controller.lib.hid import Device, enumerate_unique

logger = logging.getLogger(__name__)

ACTION_MAP = {
    "none": 0x00,
    # Standard HID codes
    # Letters
    "a": 0x04,
    "b": 0x05,
    "c": 0x06,
    "d": 0x07,
    "e": 0x08,
    "f": 0x09,
    "g": 0x0A,
    "h": 0x0B,
    "i": 0x0C,
    "j": 0x0D,
    "k": 0x0E,
    "l": 0x0F,
    "m": 0x10,
    "n": 0x11,
    "o": 0x12,
    "p": 0x13,
    "q": 0x14,
    "r": 0x15,
    "s": 0x16,
    "t": 0x17,
    "u": 0x18,
    "v": 0x19,
    "w": 0x1A,
    "x": 0x1B,
    "y": 0x1C,
    "z": 0x1D,
    # Numbers
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
    # Special characters
    "enter": 0x28,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "minus": 0x2D,
    "equal": 0x2E,
    "leftbrace": 0x2F,
    "rightbrace": 0x30,
    "backslash": 0x31,
    "hashtilde": 0x32,
    "semicolon": 0x33,
    "apostrophe": 0x34,
    "grave": 0x35,
    "comma": 0x36,
    "dot": 0x37,
    "slash": 0x38,
    "capslock": 0x39,
    "f1": 0x3A,
    "f2": 0x3B,
    "f3": 0x3C,
    "f4": 0x3D,
    "f5": 0x3E,
    "f6": 0x3F,
    "f7": 0x40,
    "f8": 0x41,
    "f9": 0x42,
    "f10": 0x43,
    "f11": 0x44,
    "f12": 0x45,
    "sysrq": 0x46,
    "scrolllock": 0x47,
    "pause": 0x48,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B,
    "delete": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
    "numlock": 0x53,
    "kpslash": 0x54,
    "kpasterisk": 0x55,
    "kpminus": 0x56,
    "kpplus": 0x57,
    "kpenter": 0x58,
    "kp1": 0x59,
    "kp2": 0x5A,
    "kp3": 0x5B,
    "kp4": 0x5C,
    "kp5": 0x5D,
    "kp6": 0x5E,
    "kp7": 0x5F,
    "kp8": 0x60,
    "kp9": 0x61,
    "kp0": 0x62,
    "kpdot": 0x63,
    "102nd": 0x64,
    "compose": 0x65,
    "power": 0x66,
    "kpequal": 0x67,
    "f13": 0x68,
    "f14": 0x69,
    "f15": 0x6A,
    "f16": 0x6B,
    "f17": 0x6C,
    "f18": 0x6D,
    "f19": 0x6E,
    "f20": 0x6F,
    "f21": 0x70,
    "f22": 0x71,
    "f23": 0x72,
    "f24": 0x73,
    "open": 0x74,
    "help": 0x75,
    "props": 0x76,
    "front": 0x77,
    "stop": 0x78,
    "again": 0x79,
    "undo": 0x7A,
    "cut": 0x7B,
    "copy": 0x7C,
    "paste": 0x7D,
    "find": 0x7E,
    "mute": 0x7F,
    "volumeup": 0x80,
    "volumedown": 0x81,
    "kpcomma": 0x85,
    "ro": 0x87,
    "katakanahiragana": 0x88,
    "yen": 0x89,
    "henkan": 0x8A,
    "muhenkan": 0x8B,
    "kpjpcomma": 0x8C,
    "hangeul": 0x90,
    "hanja": 0x91,
    "katakana": 0x92,
    "hiragana": 0x93,
    "zenkakuhankaku": 0x94,
    "kpleftparen": 0xB6,
    "kprightparen": 0xB7,
    "leftctrl": 0xE0,
    "leftshift": 0xE1,
    "leftalt": 0xE2,
    "leftmeta": 0xE3,
    "rightctrl": 0xE4,
    "rightshift": 0xE5,
    "rightalt": 0xE6,
    "rightmeta": 0xE7,
    "mouse_wheelup": 0xE8,
    "mouse_wheeldown": 0xE9,
    "mouse_left": 0xEA,
    "mouse_right": 0xEB,
    "mouse_middle": 0xEC,
    "mouse_fast": 0xED,
    # Vendor Mappings by GPD
    # Gamepad Buttons
    "dpad_up": 0xFF01,
    "dpad_down": 0xFF02,
    "dpad_left": 0xFF03,
    "dpad_right": 0xFF04,
    "btn_a": 0xFF05,
    "btn_b": 0xFF06,
    "btn_x": 0xFF07,
    "btn_y": 0xFF08,
    "ls_up": 0xFF09,
    "ls_down": 0xFF0A,
    "ls_left": 0xFF0B,
    "ls_right": 0xFF0C,
    "ls": 0xFF0D,
    "rs": 0xFF0E,
    "start": 0xFF0F,
    "select": 0xFF10,
    "menu": 0xFF11,
    "lb": 0xFF12,
    "rb": 0xFF13,
    "lt": 0xFF14,
    "rt": 0xFF15,
    "rs_up": 0xFF16,
    "rs_down": 0xFF17,
    "rs_left": 0xFF18,
    "rs_right": 0xFF19,
}


BUTTON_MAP = {
    # Standard buttons (rs is mouse always)
    "dpad_up": 0,
    "dpad_down": 2,
    "dpad_left": 4,
    "dpad_right": 6,
    "a": 8,
    "b": 10,
    "x": 12,
    "y": 14,
    "ls_up": 16,
    "ls_down": 18,
    "ls_left": 20,
    "ls_right": 22,
    "ls": 24,
    "rs": 26,
    "start": 28,
    "select": 30,
    "menu": 32,
    "lb": 34,
    "rb": 36,
    "lt": 38,
    "rt": 40,
    # Macro chains
    "extra_l1": 50,
    "extra_l2": 52,
    "extra_l3": 54,
    "extra_l4": 56,
    "extra_r1": 58,
    "extra_r2": 60,
    "extra_r3": 62,
    "extra_r4": 64,
}

DEADZONE_MAP = {
    "ls_boundary": 72,
    "ls_center": 73,
    "rs_boundary": 74,
    "rs_center": 75,
}

DELAY_MAP = {
    "extra_l1": 80,
    "extra_l2": 82,
    "extra_l3": 84,
    "extra_l4": 86,
    "extra_r1": 88,
    "extra_r2": 90,
    "extra_r3": 92,
    "extra_r4": 94,
}

RGB_MODES = {
    "off": 0,
    "constant": 1,
    "breathed": 0x11,
    "rotated": 0x21,
}

RUMBLE_MODES = {
    "off": 0,
    "medium": 1,
    "high": 2,
}

BACKBUTTONS_HHD = {
    "buttons": {
        "extra_l1": "f20",  # "sysrq",
        "extra_l2": "none",
        "extra_l3": "none",
        "extra_l4": "none",
        "extra_r1": "f21",  # "pause",
        "extra_r2": "none",
        "extra_r3": "none",
        "extra_r4": "none",
    },
    "delays": {
        "extra_l1": 0,
        "extra_l2": 0,
        "extra_l3": 0,
        "extra_l4": 25,
        "extra_r1": 0,
        "extra_r2": 0,
        "extra_r3": 0,
        "extra_r4": 25,
    },
}
BACKBUTTONS_DEFAULT = {
    "buttons": {
        "extra_l1": "sysrq",
        "extra_l2": "none",
        "extra_l3": "none",
        "extra_l4": "none",
        "extra_r1": "pause",
        "extra_r2": "none",
        "extra_r3": "none",
        "extra_r4": "none",
    },
    "delays": {
        "extra_l1": 0,
        "extra_l2": 0,
        "extra_l3": 0,
        "extra_l4": 300,
        "extra_r1": 0,
        "extra_r2": 0,
        "extra_r3": 0,
        "extra_r4": 300,
    },
}

BUTTONS_DEFAULT = {
    "dpad_up": "mouse_wheelup",
    "dpad_down": "mouse_wheeldown",
    "dpad_left": "home",
    "dpad_right": "end",
    "a": "down",
    "b": "right",
    "x": "left",
    "y": "up",
    "ls_up": "w",
    "ls_down": "s",
    "ls_left": "a",
    "ls_right": "d",
    "ls": "space",
    "rs": "enter",
    "start": "none",
    "select": "none",
    "menu": "none",
}

BUTTONS_PHAWX = {
    "dpad_up": "up",
    "dpad_down": "down",
    "dpad_left": "left",
    "dpad_right": "right",
    "a": "space",
    "b": "leftctrl",
    "x": "z",
    "y": "leftalt",
    "ls_up": "w",
    "ls_down": "s",
    "ls_left": "a",
    "ls_right": "d",
    "ls": "leftshift",
    "rs": "enter",
    "start": "escape",
    "select": "enter",
    "menu": "none",
}

BUTTONS_TRIGGERS_DEFAULT = {
    "lb": "mouse_left",
    "rb": "mouse_right",
    "lt": "mouse_middle",
    "rt": "mouse_fast",
}

BUTTONS_TRIGGERS_STEAMOS = {
    "lb": "mouse_middle",
    "rb": "mouse_fast",
    "lt": "mouse_right",
    "rt": "mouse_left",
}

WSIZE = 33
RSIZE = 64


def get_command(cid: int, ofs: int = 0, payload: bytes = b"") -> bytes:
    base = bytes([0x01, 0xA5, cid, 0x5A, 0xFF ^ cid, 0x00, ofs, 0x00]) + payload
    return base + bytes([0x00] * (33 - len(base)))


PAUSE = 0.05

GM_SUPPROTED_VERSIONS = {3: 0x14, 4: 0x09, 5: 0x10}  # Win Max 2  # Win 4  # Win Mini
EXT_SUPPORTED_VERSIONS = {1: 0x23, 4: 0x07, 5: 0x04}


def check_fwver(res: bytes):
    ready = res[8] == 0xAA
    gm_major_ver = res[9]
    gm_minor_ver = res[10]
    ext_major_ver = res[11]
    ext_minor_ver = res[12]

    fwver = f"X{gm_major_ver}{gm_minor_ver:02x}K{ext_major_ver}{ext_minor_ver:02x}"

    # Version check
    for k, v in GM_SUPPROTED_VERSIONS.items():
        if gm_major_ver == k:
            assert (
                gm_minor_ver <= v
            ), f"Unsupported gamepad firmware version {fwver} (up to X{k}{v:02x})"
            break
    else:
        raise ValueError(f"Unsupported gamepad major version {gm_major_ver} in {fwver}")
    for k, v in EXT_SUPPORTED_VERSIONS.items():
        if ext_major_ver == k:
            assert (
                ext_minor_ver <= v
            ), f"Unsupported extendboard firmware {fwver} version (up to K{k}{v:02x})"
            break
    else:
        raise ValueError(
            f"Unsupported extendboard major version {gm_major_ver} in {fwver}"
        )

    return ready, fwver


def read_config(d: Device) -> tuple[str, bytes]:
    ready = False
    while not ready:
        d.send_feature_report(get_command(0x10))
        time.sleep(PAUSE)
        fw_data = d.get_feature_report(0x01)
        time.sleep(PAUSE)
        ready, fwver = check_fwver(fw_data)

    logger.info(f"Device ready, firmware version: {fwver}")

    cfg = bytes()
    for i in range(4):
        d.send_feature_report(get_command(0x11, i))
        time.sleep(PAUSE)
        cfg += d.get_feature_report(0x01)
        time.sleep(PAUSE)

    logger.info("")
    logger.info("Config:")
    tmp = cfg
    i = 0
    while sum(tmp):
        logger.info(f"{i:02d}: {tmp[:16].hex()}")
        tmp = tmp[16:]
        i += 1

    logger.info("")
    d.send_feature_report(get_command(0x12))
    time.sleep(PAUSE)

    fw_data = d.get_feature_report(0x1)
    ready, fwver_new = check_fwver(fw_data)
    assert fwver == fwver_new, "Firmware version changed during read."
    assert ready, "Device not ready after read."

    chash = int.from_bytes(fw_data[24:28], "little")
    logger.info(f"Sum: x{chash:x}")
    # What is this number, it is on 0x10 too
    # chash2 = int.from_bytes(fw_data[28:32], "little")
    # logger.info(f"Ukn: " + str(chash2))
    computed = sum(cfg)
    logger.info(f"Computed Sum: x{computed:x}")

    assert computed == chash, "Did not read config properly: hash mismatch"
    return fwver, cfg


def write_config(d: Device, fwver: str, cfg: bytes):
    d.send_feature_report(get_command(0x21))
    time.sleep(PAUSE)
    fw_data = d.get_feature_report(0x01)
    time.sleep(PAUSE)
    ready = False
    while not ready:
        ready, fwver_new = check_fwver(fw_data)
        assert fwver == fwver_new, "Firmware version changed during write."

    logger.info(f"Firmware version: {fwver}")
    logger.info("")
    logger.info("Writing Config:")
    for i in range(8):
        sls = cfg[16 * i : 16 * i + 16]
        logger.info(f"{i:02d}: {sls.hex()}")
        d.send_feature_report(get_command(0x21, i, sls))

    d.send_feature_report(get_command(0x22))
    time.sleep(PAUSE)
    fw_data = d.get_feature_report(0x1)
    ready, fwver_new = check_fwver(fw_data)
    assert ready, "Device not ready after write."
    assert fwver == fwver_new, "Firmware version changed during write."

    chash = int.from_bytes(fw_data[24:28], "little")
    logger.info("")
    logger.info(f"Sum: x{chash:x}")
    computed = sum(cfg)
    logger.info(f"Computed Sum: x{computed:x}")

    assert computed == chash, "Did not write config properly: hash mismatch"

    logger.info("Writing config to memory and restarting device.")
    d.send_feature_report(get_command(0x23))


def update_config(
    buttons: dict[str, str] = {},
    delays: dict[str, int] = {},
    deadzones: dict[str, int] = {},
    rumble: str | None = None,
    rgb_mode: str | None = None,
    rgb_color: tuple[int, int, int] | None = None,
):
    devs = enumerate_unique(0x2F24, 0x0135, 0xFF00, 0x0001)
    assert devs, "No devices found."

    dev = devs[0]
    with Device(path=dev["path"]) as d:
        fwver, cfg = read_config(d)

    # Apply changes
    init_cfg = cfg
    cfg = bytearray(cfg)

    for k, v in buttons.items():
        assert k in BUTTON_MAP, f"Unknown button {k}"
        assert v in ACTION_MAP, f"Unknown action {v}"
        cfg[BUTTON_MAP[k] : BUTTON_MAP[k] + 2] = ACTION_MAP[v].to_bytes(2, "little")

    for k, v in delays.items():
        assert k in DELAY_MAP, f"Unknown delay {k}"
        cfg[DELAY_MAP[k] : DELAY_MAP[k] + 2] = v.to_bytes(2, "little")

    for k, v in deadzones.items():
        assert k in DEADZONE_MAP, f"Unknown deadzone {k}"
        cfg[DEADZONE_MAP[k] : DEADZONE_MAP[k] + 1] = v.to_bytes(
            1, "little", signed=True
        )

    if rumble is not None:
        assert rumble in RUMBLE_MODES, f"Unknown rumble mode {rumble}"
        cfg[66 : 66 + 2] = RUMBLE_MODES[rumble].to_bytes(2, "little")

    deadzones = {k: min(max(v, -10), 10) for k, v in deadzones.items()}
    for k, v in deadzones.items():
        assert k in DEADZONE_MAP, f"Unknown deadzone {k}"
        cfg[DEADZONE_MAP[k] : DEADZONE_MAP[k] + 1] = v.to_bytes(
            1, "little", signed=True
        )

    if "K4" in fwver:
        # Limit RGB changes to Win 4 with firmware 40X
        if rgb_mode is not None:
            assert rgb_mode in RGB_MODES, f"Unknown rgb mode {rgb_mode}"
            cfg[68] = RGB_MODES[rgb_mode]

        if rgb_color is not None:
            assert len(rgb_color) == 3, "RGB color must be a tuple of 3 integers"
            cfg[69 : 69 + 3] = bytes(rgb_color)

    if all(i == j for i, j in zip(cfg, init_cfg)):
        logger.info("No changes to apply. Skipping write.")
        return fwver

    with Device(path=dev["path"]) as d:
        write_config(d, fwver, bytes(cfg))

    return fwver


def explain_config():
    ACTION_MAP_REV = {v: k for k, v in ACTION_MAP.items()}
    RGB_MODES_REV = {v: k for k, v in RGB_MODES.items()}

    devs = enumerate_unique(0x2F24, 0x0135, 0xFF00, 0x0001)
    assert devs, "No devices found."

    dev = devs[0]
    with Device(path=dev["path"]) as d:
        _, cfg = read_config(d)

    logger.info("\nButtons:")
    for k, v in BUTTON_MAP.items():
        val = int.from_bytes(cfg[v : v + 2], "little")
        val = ACTION_MAP_REV.get(val, f"0x{val:02x}")
        logger.info(f"  {k}: {val}")

    logger.info("\nMacro Delays:")
    for k, v in DELAY_MAP.items():
        val = int.from_bytes(cfg[v : v + 2], "little")
        logger.info(f"  {k}: {val}ms")

    logger.info("\nDeadzones:")
    for k, v in DEADZONE_MAP.items():
        val = int.from_bytes(cfg[v : v + 2], "little", signed=True)
        logger.info(f"  {k}: {val}")

    rumbl = "ukn"
    match int.from_bytes(cfg[66 : 66 + 2], "little"):
        case 0:
            rumbl = "off"
        case 1:
            rumbl = "medium"
        case 2:
            rumbl = "high"
    logger.info(f"\nRumble: {rumbl}")

    rgb_mode = RGB_MODES_REV.get(cfg[68], "ukn")
    rgb_color = cfg[69 : 69 + 3].hex()

    logger.info(f"RGB: {rgb_mode} #{rgb_color}")


# From factory, the following are the default values:
# Buttons:
#   dpad_up: mouse_wheelup
#   dpad_down: mouse_wheeldown
#   dpad_left: home
#   dpad_right: end
#   a: down
#   b: right
#   x: left
#   y: up
#   ls_up: w
#   ls_down: s
#   ls_left: a
#   ls_right: d
#   ls: space
#   rs: enter
#   start: none
#   select: none
#   menu: none
#   lb: mouse_left
#   rb: mouse_right
#   lt: mouse_middle
#   rt: mouse_fast
#   extra_l1: sysrq
#   extra_l2: none
#   extra_l3: none
#   extra_l4: none
#   extra_r1: pause
#   extra_r2: none
#   extra_r3: none
#   extra_r4: none
#
# I might have changed the macro delays
# Macro Delays:
#   extra_l1: 0ms
#   extra_l2: 0ms
#   extra_l3: 0ms
#   extra_l4: 300ms
#   extra_r1: 0ms
#   extra_r2: 0ms
#   extra_r3: 0ms
#   extra_r4: 300ms
#
# Deadzones:
#   ls_deadzone: 0
#   ls_center: 0
#   rs_deadzone: 0
#   rs_center: 0

# Rumble: medium
# RGB: rotated #0000ff

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    update_config(**BACKBUTTONS_HHD)
