import os
import logging

logger = logging.getLogger(__name__)

EV_KEY = 0x01
BTN_MISC = 0x100
BTN_JOYSTICK = 0x120
# KEY_MAX = 0x2ff
# BTN_TRIGGER_HAPPY = 0x2c0
BTN_GAMEPAD = 0x130
EV_ABS = 0x03
ABS_HAT0X = 0x10

BTN_FROM_SDL = {
    # Thumbpad
    "a": "a",
    "b": "b",
    "x": "x",
    "y": "y",
    # D-PAD
    "dpup": "dpad_up",
    "dpdown": "dpad_down",
    "dpleft": "dpad_left",
    "dpright": "dpad_right",
    # Sticks
    "leftstick": "ls",
    "rightstick": "rs",
    # Bumpers
    "leftshoulder": "lb",
    "rightshoulder": "rb",
    # Triggers
    "lefttrigger": "lt",
    "righttrigger": "rt",
    # Select
    "start": "start",
    "back": "select",
    # Misc
    "guide": "mode",
    "misc1": "share",
    # Back buttons
    "paddle1": "extra_l1",
    "paddle2": "extra_r1",
    "paddle3": "extra_l2",
    "paddle4": "extra_r2",
}

AXES_FROM_SDL = {
    "leftx": "ls_x",
    "lefty": "ls_y",
    "rightx": "rs_x",
    "righty": "rs_y",
    "lefttrigger": "lt",
    "righttrigger": "rt",
}

WAKE_KEYS = [
    "select",
    "mode",
    "b",
    "y",
    "a",
    "x",
]

OVERLAY_KEYS = [
    "a",
    "b",
    "x",
    "y",
    "lb",
    "rb",
    "mode",
    "select",
    "dpad_up",
    "dpad_down",
    "dpad_left",
    "dpad_right",
]

OVERLAY_AXES = [
    "ls_x",
    "ls_y",
    "rs_x",
    "rs_y",
]

CONTROLLERDB_FN = os.environ.get(
    "HHD_CONTROLLERDB", "/usr/share/sdl/gamecontrollerdb.txt"
)


def crc16_for_byte(byte):
    crc = 0
    for _ in range(8):
        if (byte ^ crc) & 1:
            crc = (crc >> 1) ^ 0xA001
        else:
            crc >>= 1
        byte >>= 1
    return crc


def sdl_crc16(crc, data):
    for byte in data:
        crc = crc16_for_byte(crc ^ byte) ^ (crc >> 8)
    return crc


def create_joystick_guid(v):
    # SDL_GUID SDL_CreateJoystickGUID function
    guid = bytearray(16)

    guid[0:2] = v["bus"].to_bytes(2, "little")
    guid[2:4] = sdl_crc16(0, v["name"].encode()).to_bytes(2, "little")
    if v["vendor"]:
        guid[4:6] = v["vendor"].to_bytes(2, "little")
        guid[8:10] = v["product"].to_bytes(2, "little")
        guid[12:14] = v["version"].to_bytes(2, "little")
        # Driver signatures, always 0
        # guid[14] = 0
        # guid[15] = 0
    else:
        # Here, there is a check for driver signature
        # However, sysjoystick (what we use) provides zeros
        guid[4:16] = v["name"].encode()[:12].ljust(12, b"\0")

    return guid


def get_joypad_buttons(dev):
    before_js = []
    after_js = []
    for i, b in enumerate(dev.get("byte", {}).get("key", bytes())):
        for j in range(8):
            if not (b & (1 << j)):
                continue
            key = i * 8 + j

            # Joydev kernel driver does the following\
            # but on e.g., 8bitdo KEY_MENU is used and missed
            # # Ignore smaller than BTN_MISC keys
            # if key < BTN_MISC:
            #     continue
            if key < BTN_JOYSTICK:
                before_js.append(key)
            else:
                after_js.append(key)

    return after_js + before_js


def get_joypad_axes(dev):
    abs = []
    hats = []
    for i, b in enumerate(dev.get("byte", {}).get("abs", bytes())):
        for j in range(8):
            if not (b & (1 << j)):
                continue
            key = i * 8 + j
            abs.append(key)
            if key >= ABS_HAT0X:
                hats.append(key)

    hats_x = [x for x in hats if x % 2 == 0]

    pairs = []
    for hat_x in hats_x:
        if hat_x + 1 in hats:
            pairs.append((hat_x, hat_x + 1))

    return abs, pairs


def load_mappings(fn: str = CONTROLLERDB_FN):
    mappings = {}

    try:
        with open(fn, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    guid_str, name, *bindings = line.split(",")
                    if guid_str == "xinput":
                        continue

                    # Check platform
                    different_platform = False
                    for bind in bindings:
                        if not bind.startswith("platform:"):
                            continue

                        platform = bind.split(":")[1].strip().lower()
                        if platform != "linux":
                            different_platform = True
                            break
                    if different_platform:
                        continue

                    mappings[bytes.fromhex(guid_str)] = (name, bindings)
                except Exception as e:
                    logger.info(f"Error parsing line '{line}': {e}")
    except Exception as e:
        logger.error(f"Failed to load SDL gamepad mappings from {fn}:\n{e}")
        return {}

    logger.info(f"Loaded {len(mappings)} SDL gamepad mappings from:\n{fn}")
    return mappings


def map_gamepad(bindings, jaxes, jbuttons, jhats):
    axes = {}
    buttons = {}

    for bind in bindings:
        if not bind:
            continue

        key, val = bind.split(":")

        if key == "crc" or key == "platform":
            continue

        hhd_btn = BTN_FROM_SDL.get(key, None)
        hhd_ax = AXES_FROM_SDL.get(key, None)
        if not (hhd_btn or hhd_ax):
            continue

        flip = False
        if val.startswith("-"):
            flip = True
            val = val[1:]
        if val.startswith("+"):
            val = val[1:]
        if val.endswith("~"):
            flip = True
            val = val[:-1]

        if val.startswith("a"):
            ax = jaxes[int(val[1:])]
            if hhd_ax:
                axes[ax] = {
                    "type": "axis",
                    "code": hhd_ax,
                    "flip": flip,
                }
            else:
                assert hhd_btn
                axes[ax] = {
                    "type": "button",
                    "code": hhd_btn,
                    "flip": flip,
                }

        elif val.startswith("b"):
            try:
                btn = jbuttons[int(val[1:])]
            except IndexError:
                # TODO: add error
                continue
            assert hhd_btn
            buttons[btn] = hhd_btn

        elif val.startswith("h"):
            hat_id, hat_ofs = val[1:].split(".")

            hat_x, hat_y = jhats[int(hat_id)]
            assert hhd_btn

            match int(hat_ofs):
                case 1:
                    axes[hat_y] = {
                        "type": "hat",
                        "up_code": axes.get(hat_y, {}).get("up_code", None),
                        "down_code": hhd_btn,
                    }
                case 2:
                    axes[hat_x] = {
                        "type": "hat",
                        "up_code": hhd_btn,
                        "down_code": axes.get(hat_x, {}).get("down_code", None),
                    }
                case 4:
                    axes[hat_y] = {
                        "type": "hat",
                        "up_code": hhd_btn,
                        "down_code": axes.get(hat_y, {}).get("down_code", None),
                    }
                case 8:
                    axes[hat_x] = {
                        "type": "hat",
                        "up_code": axes.get(hat_x, {}).get("up_code", None),
                        "down_code": hhd_btn,
                    }
                case _:
                    assert False, f"Unknown hat offset {hat_ofs}"

    return axes, buttons


def match_gamepad(device, mappings):
    guid = create_joystick_guid(device)
    # Matching CRC is not relevant for us
    # crc = int.from_bytes(guid[2:4], "little")
    guid[2:4] = b"\0\0"  # Clear CRC for matching

    match = mappings.get(bytes(guid), None)
    if not match:
        guid[12:14] = b"\0\0"  # Clear version for matching
        match = mappings.get(bytes(guid), None)

    if not match:
        return None

    name, bindings = match

    jaxes, jhats = get_joypad_axes(device)
    jbuttons = get_joypad_buttons(device)

    axes, buttons = map_gamepad(bindings, jaxes, jbuttons, jhats)

    # Find relevant events for wake-ups
    wake_buttons = [btn for btn, hhd_btn in buttons.items() if hhd_btn in WAKE_KEYS]
    overlay_axes = [
        ax
        for ax, data in axes.items()
        if data.get("code", None) in OVERLAY_AXES
        or data.get("code", data.get("up_code", None)) in OVERLAY_KEYS
    ]
    overlay_buttons = [
        btn for btn, hhd_btn in buttons.items() if hhd_btn in OVERLAY_KEYS
    ]

    return {
        "name": name,
        "guid": guid,
        "axes": axes,
        "buttons": buttons,
        "wake_buttons": wake_buttons,
        "overlay_axes": overlay_axes,
        "overlay_buttons": overlay_buttons,
    }


def test_match_gamepad(mappings):
    jaxes = [i for i in range(20)]
    jbuttons = [i for i in range(500)]
    jhats = [(2 * i, 2 * i + 1) for i in range(10)]

    for mapping in mappings.values():
        name, bindings = mapping
        axes, buttons = map_gamepad(bindings, jaxes, jbuttons, jhats)
        print(f"Checked: {name}")
        print(buttons, axes)
