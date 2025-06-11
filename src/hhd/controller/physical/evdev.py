import glob
import logging
import os
import re
import stat
import subprocess
import time
from typing import Collection, Mapping, Sequence, TypeVar, cast

import evdev
from evdev import ecodes, ff

from hhd.controller import Axis, Button, Consumer, Event, Producer, can_read
from hhd.controller.base import Event
from hhd.controller.const import AbsAxis, GamepadButton, KeyboardButton
from hhd.controller.lib.common import hexify, matches_patterns
from hhd.controller.lib.hide import hide_gamepad, unhide_gamepad

logger = logging.getLogger(__name__)


def B(b: str):
    return cast(int, getattr(evdev.ecodes, b))


A = TypeVar("A")


def to_map(b: dict[A, Sequence[int]]) -> dict[int, A]:
    out = {}
    for btn, seq in b.items():
        for s in seq:
            out[s] = btn
    return out


CapabilityMatch = Mapping[int, Collection[int]]

XBOX_BUTTON_MAP: dict[int, GamepadButton] = to_map(
    {
        # Gamepad
        "a": [B("BTN_A")],
        "b": [B("BTN_B")],
        "x": [B("BTN_X")],
        "y": [B("BTN_Y")],
        # Sticks
        "ls": [B("BTN_THUMBL")],
        "rs": [B("BTN_THUMBR")],
        # Bumpers
        "lb": [B("BTN_TL")],
        "rb": [B("BTN_TR")],
        # Select
        "start": [B("BTN_START")],
        "select": [B("BTN_SELECT")],
        # Misc
        "mode": [B("BTN_MODE")],
    }
)

XBOX_AXIS_MAP: dict[int, AbsAxis] = to_map(
    {
        # Sticks
        # Values should range from -1 to 1
        "ls_x": [B("ABS_X")],
        "ls_y": [B("ABS_Y")],
        "rs_x": [B("ABS_RX")],
        "rs_y": [B("ABS_RY")],
        # Triggers
        # Values should range from -1 to 1
        "rt": [B("ABS_Z")],
        "lt": [B("ABS_RZ")],
        # Hat, implemented as axis. Either -1, 0, or 1
        "hat_x": [B("ABS_HAT0X")],
        "hat_y": [B("ABS_HAT0Y")],
    }
)

DINPUT_AXIS_MAP: dict[int, Axis] = to_map(
    {
        # Sticks
        # Values should range from -1 to 1
        "ls_x": [B("ABS_X")],
        "ls_y": [B("ABS_Y")],
        "rs_x": [B("ABS_Z")],
        "rs_y": [B("ABS_RZ")],
        # Triggers
        # Values should range from -1 to 1
        "rt": [B("ABS_BRAKE")],
        "lt": [B("ABS_GAS")],
        # Hat, implemented as axis. Either -1, 0, or 1
        "hat_x": [B("ABS_HAT0X")],
        "hat_y": [B("ABS_HAT0Y")],
    }
)
DINPUT_AXIS_POSTPROCESS = {
    "ls_x": {"zero_is_middle": True},
    "ls_y": {"zero_is_middle": True},
    "rs_x": {"zero_is_middle": True},
    "rs_y": {"zero_is_middle": True},
}

if calib := os.environ.get("HHD_CALIB"):
    # TODO: Move this into the gui
    # Accepts the following format: <axis>: <min> <max> <deadzone>
    # Everything below deadzone gets set to 0.
    # If axis is positive, it gets scaled so that it is 1 when max is hit
    # If negative, it is scaled to be -1 when it reaches the min value
    # HHD_CALIB=$(cat <<-END
    # {
    #     "ls_x": {"min": -1, "max": 1, "deadzone": 0.05},
    #     "ls_y": {"min": -1, "max": 1, "deadzone": 0.05},
    #     "rs_x": {"min": -1, "max": 1, "deadzone": 0.05},
    #     "rs_y": {"min": -1, "max": 1, "deadzone": 0.05},
    #     "lt": {"min": 0, "max": 1, "deadzone": 0.05},
    #     "rt": {"min": 0, "max": 1, "deadzone": 0.05}
    # }
    # END
    # )
    import json

    try:
        AXIS_CALIBRATION = json.loads(calib)
        logger.info(f"Loaded calibration:\n{calib}")
    except Exception as e:
        logger.info(f"Could not load Axis Calibration:\n{calib}\nError:{e}")
        AXIS_CALIBRATION = {}
else:
    AXIS_CALIBRATION = {}


def list_joysticks(input_device_dir="/dev/input"):
    return glob.glob(f"{input_device_dir}/js*")


def get_path(ev: str):
    path = None
    for line in subprocess.run(
        ["udevadm", "info", "-n", ev], capture_output=True
    ).stdout.splitlines():
        if line.startswith(b"P: "):
            path = line[3 : -len(ev[ev.rindex("/") :])]
            break
    return path


def find_joystick(ev: str):
    path = get_path(ev)
    for other in list_joysticks():
        if path == get_path(other):
            return other


def is_device(fn):
    """Check if ``fn`` is a readable and writable character device."""

    if not os.path.exists(fn):
        return False

    try:
        m = os.stat(fn)[stat.ST_MODE]
        if not stat.S_ISCHR(m):
            return False

        if not os.access(fn, os.R_OK | os.W_OK):
            return False
    except Exception:
        return False
    return True


def list_evs(filter_valid: bool = False, fn: str = "/proc/bus/input/devices"):
    with open(fn, "r") as f:
        data = f.read()

    devs = {}
    for d in data.split("\n\n"):
        out = {}
        out["hash"] = hash(d)
        for line in d.split("\n"):
            if not line:
                continue
            match line[0]:
                case "I":
                    for attr in line[3:-1].split(" "):
                        name, val = attr.split("=")
                        out[name.lower()] = int(val, 16)
                case "N":
                    out["name"] = line[len('N: Name="') : -1]
                case "B":
                    if "byte" not in out:
                        out["byte"] = {}
                    head, raw = line[3:].split("=")
                    arr = bytearray()
                    for x in raw.split(" "):
                        if not x:
                            continue
                        arr.extend(int(x, 16).to_bytes(8, "big"))
                    # Array is stacked using big endianness, so
                    # we reverse it to little endian
                    out["byte"][head.lower()] = bytes(reversed(arr))
                case "P":
                    out["phys"] = line[len('P: Phys="') : -1]
                case "S":
                    if "Sysfs" in line:
                        out["sysfs"] = line[len('S: Sysfs="') : -1]
                case "H":
                    if len(line) < len("H: Handlers=") + 1:
                        continue
                    for handler in line[len("H: Handlers=") : -1].split(" "):
                        if "event" in handler:
                            pth = "/dev/input/" + handler
                            if not filter_valid or is_device(pth):
                                devs[pth] = out

    return devs


def enumerate_evs(
    vid: int | None = None, pid: int | None = None, filter_valid: bool = False
):
    evs = list_evs(filter_valid)
    return {
        k: v
        for k, v in evs.items()
        if (vid is None or vid == v.get("vendor", None))
        and (pid is None or pid == v.get("product", None))
    }


class GenericGamepadEvdev(Producer, Consumer):

    def __init__(
        self,
        vid: Sequence[int],
        pid: Sequence[int],
        name: Sequence[str | re.Pattern] = "",
        capabilities: CapabilityMatch = {},
        btn_map: Mapping[int, Button] = XBOX_BUTTON_MAP,
        axis_map: Mapping[int, Axis] = XBOX_AXIS_MAP,
        aspect_ratio: float | None = None,
        required: bool = True,
        hide: bool = False,
        grab: bool = True,
        msc_map: Mapping[int, Button] = {},
        msc_delay: float = 0.1,
        postprocess: dict[str, dict] = AXIS_CALIBRATION,
        requires_start: bool = False,
    ) -> None:
        self.vid = vid
        self.pid = pid
        self.name = name
        self.capabilities = capabilities

        self.btn_map = btn_map
        self.axis_map = axis_map
        self.msc_map = msc_map
        self.msc_delay = msc_delay
        self.aspect_ratio = aspect_ratio

        self.dev: evdev.InputDevice | None = None
        self.fd = 0
        self.required = required
        self.hide = hide
        self.grab = grab
        self.hidden = None
        self.queue = []
        self.postprocess = postprocess
        self.start_pressed = None
        self.start_held = False
        self.requires_start = requires_start

    def open(self) -> Sequence[int]:
        for d, info in list_evs(filter_valid=True).items():
            if not matches_patterns(info.get("vendor", ""), self.vid):
                continue
            if not matches_patterns(info.get("product", ""), self.pid):
                continue
            if not matches_patterns(info.get("name", ""), self.name):
                continue
            dev = evdev.InputDevice(d)
            if self.capabilities:
                matches = True
                dev_cap = cast(dict[int, Sequence[int]], dev.capabilities())
                for cap_id, caps in self.capabilities.items():
                    if cap_id not in dev_cap:
                        matches = False
                        break
                    if cap_id != B("EV_ABS"):
                        dev_caps = dev_cap[cap_id]
                    else:
                        dev_caps = [c[0] for c in dev_cap[cap_id]]  # type: ignore
                    for cap in caps:
                        if cap not in dev_caps:
                            matches = False
                        break
                if not matches:
                    continue

            # hide_gamepad will destroy the current fds, so run it before
            # creating the final device
            if self.hide:
                # Check we are root
                if not os.getuid():
                    self.hidden = hide_gamepad(
                        dev.path, dev.info.vendor, dev.info.product
                    )
                    if not self.hidden:
                        logger.warning(f"Could not hide device:\n{dev}")
                else:
                    logger.warning(
                        f"Not running as root, device '{dev.name}' could not be hid."
                    )

            try:
                # Close the previous device
                # Will have been destroyed by hiding
                dev.close()
                self.dev = evdev.InputDevice(d)
                if self.grab:
                    self.dev.grab()
                self.ranges = {
                    a: (i.min, i.max) for a, i in self.dev.capabilities().get(B("EV_ABS"), [])  # type: ignore
                }
                self.supports_vibration = B("EV_FF") in dev.capabilities()
                self.fd = self.dev.fd
                self.started = True
                self.effect_id = -1
                self.queue = []
            except Exception as e:
                # Prevent leftover rules in case of error
                if self.hidden:
                    unhide_gamepad(d, self.hidden)
                raise e

            return [self.fd]

        err = f"Device with the following not found:\n"
        if self.vid:
            err += f"Vendor ID: {hexify(self.vid)}\n"
        if self.pid:
            err += f"Product ID: {hexify(self.pid)}\n"
        if self.name:
            err += f"Name: {self.name}\n"
        if self.capabilities:
            err += f"Capabilities: {self.capabilities}\n"
        logger.error(err)
        if self.required:
            raise RuntimeError()
        return []

    def close(self, exit: bool) -> bool:
        if self.dev:
            if self.hidden and exit:
                unhide_gamepad(self.dev.path, self.hidden)
            self.dev.close()
            self.dev = None
            self.fd = 0
        return True

    def consume(self, events: Sequence[Event]):
        if not self.dev:
            return

        for ev in events:
            match ev["type"]:
                case "rumble":
                    if not self.supports_vibration:
                        continue

                    # Erase old effect
                    if self.effect_id != -1:
                        self.dev.erase_effect(self.effect_id)
                        self.effect_id = -1

                    # Install new effect
                    if ev["strong_magnitude"] > 0 or ev["weak_magnitude"] > 0:
                        rumble = ff.Rumble(
                            strong_magnitude=min(
                                int(ev["strong_magnitude"] * 0xFFFF), 0xFFFF
                            ),
                            weak_magnitude=min(
                                int(ev["weak_magnitude"] * 0xFFFF), 0xFFFF
                            ),
                        )
                        duration_ms = 10000

                        effect = ff.Effect(
                            getattr(ecodes, "FF_RUMBLE"),
                            -1,
                            0,
                            ff.Trigger(0, 0),
                            ff.Replay(duration_ms, 0),
                            ff.EffectType(ff_rumble_effect=rumble),
                        )
                        self.effect_id = self.dev.upload_effect(effect)
                        self.dev.write(getattr(ecodes, "EV_FF"), self.effect_id, 1)

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        out: list[Event] = []
        curr = time.time()
        if self.queue:
            ev, t = self.queue[0]
            if curr >= t:
                out.append(ev)
                self.queue.pop(0)
        if self.start_pressed and curr - self.start_pressed > 0.07:
            self.start_pressed = None
            out.append(
                {
                    "type": "button",
                    "code": self.btn_map[B("KEY_LEFTMETA")],
                    "value": True,
                }
            )

        if not self.dev or not self.fd in fds:
            return out

        if self.started and self.aspect_ratio is not None:
            self.started = False
            out.append(
                {
                    "type": "configuration",
                    "code": "touchpad_aspect_ratio",
                    "value": self.aspect_ratio,
                }
            )

        while can_read(self.fd):
            for e in self.dev.read():
                if e.type == B("EV_KEY"):
                    if e.code == B("KEY_LEFTMETA"):
                        self.start_held = e.value != 0
                    if e.code in self.btn_map and (
                        not self.requires_start or self.start_held or not e.value
                    ):
                        # Only 1 is valid for press (look at sysrq)
                        if e.code == B("KEY_LEFTMETA") and e.value:
                            # start requires special handling
                            # If it exists on the button map, it may
                            # also be used for other shortcuts.
                            # So we have to wait a bit to see if it is
                            # a standalone press
                            self.start_pressed = curr
                        elif e.value == 0 or e.value == 1:
                            out.append(
                                {
                                    "type": "button",
                                    "code": self.btn_map[e.code],
                                    "value": bool(e.value),
                                }
                            )
                            self.start_pressed = None
                elif e.type == B("EV_ABS"):
                    if e.code in self.axis_map:
                        ax = self.axis_map[e.code]
                        if ax in self.postprocess and self.postprocess[ax].get(
                            "zero_is_middle", False
                        ):
                            mmax = self.ranges[e.code][1] + 1
                            val = (e.value - mmax // 2 + 1) / mmax * 2
                        else:
                            # Normalize
                            val = e.value / abs(
                                self.ranges[e.code][1 if e.value >= 0 else 0]
                            )

                        # Calibrate
                        if ax in self.postprocess:
                            calib = self.postprocess[ax]
                            if val < 0 and "min" in calib:
                                m = calib["min"]
                                if m:
                                    # avoid division by 0
                                    val = -max(m, val) / m
                            elif val > 0 and "max" in calib:
                                m = calib["max"]
                                val = min(m, val) / m

                            if "deadzone" in calib:
                                d = calib["deadzone"]
                                if abs(val) < d:
                                    val = 0

                        out.append(
                            {
                                "type": "axis",
                                "code": ax,
                                "value": val,
                            }
                        )
                elif e.type == B("EV_MSC"):
                    if e.code in self.msc_map:
                        out.append(
                            {
                                "type": "button",
                                "code": self.btn_map[e.code],
                                "value": True,
                            }
                        )
                        self.queue.append(
                            (
                                {
                                    "type": "button",
                                    "code": self.btn_map[e.code],
                                    "value": False,
                                },
                                curr + self.msc_delay,
                            )
                        )

        return out


_kbd_raw: dict[KeyboardButton, Sequence[int]] = {
    "key_esc": [B("KEY_ESC")],  # 1
    "key_enter": [B("KEY_ENTER")],  # 28
    "key_leftctrl": [B("KEY_LEFTCTRL")],  # 29
    "key_leftshift": [B("KEY_LEFTSHIFT")],  # 42
    "key_leftalt": [B("KEY_LEFTALT")],  # 56
    "key_rightctrl": [B("KEY_RIGHTCTRL")],  # 97
    "key_rightshift": [B("KEY_RIGHTSHIFT")],  # 54
    "key_rightalt": [B("KEY_RIGHTALT")],  # 100
    "key_leftmeta": [B("KEY_LEFTMETA")],  # 125
    "key_rightmeta": [B("KEY_RIGHTMETA")],  # 126
    "key_capslock": [B("KEY_CAPSLOCK")],  # 58
    "key_numlock": [B("KEY_NUMLOCK")],  # 69
    "key_scrolllock": [B("KEY_SCROLLLOCK")],  # 70
    "key_sysrq": [B("KEY_SYSRQ")],  # 99
    "key_minus": [B("KEY_MINUS")],  # 12
    "key_equal": [B("KEY_EQUAL")],  # 13
    "key_backspace": [B("KEY_BACKSPACE")],  # 14
    "key_tab": [B("KEY_TAB")],  # 15
    "key_leftbrace": [B("KEY_LEFTBRACE")],  # 26
    "key_rightbrace": [B("KEY_RIGHTBRACE")],  # 27
    "key_space": [B("KEY_SPACE")],  # 57
    "key_up": [B("KEY_UP")],  # 103
    "key_left": [B("KEY_LEFT")],  # 105
    "key_right": [B("KEY_RIGHT")],  # 106
    "key_down": [B("KEY_DOWN")],  # 108
    "key_home": [B("KEY_HOME")],  # 102
    "key_end": [B("KEY_END")],  # 107
    "key_pageup": [B("KEY_PAGEUP")],  # 104
    "key_pagedown": [B("KEY_PAGEDOWN")],  # 109
    "key_insert": [B("KEY_INSERT")],  # 110
    "key_delete": [B("KEY_DELETE")],  # 111
    "key_semicolon": [B("KEY_SEMICOLON")],  # 39
    "key_apostrophe": [B("KEY_APOSTROPHE")],  # 40
    "key_grave": [B("KEY_GRAVE")],  # 41
    "key_backslash": [B("KEY_BACKSLASH")],  # 43
    "key_comma": [B("KEY_COMMA")],  # 51
    "key_dot": [B("KEY_DOT")],  # 52
    "key_slash": [B("KEY_SLASH")],  # 53
    "key_102nd": [B("KEY_102ND")],  # 86
    "key_ro": [B("KEY_RO")],  # 89
    "key_power": [B("KEY_POWER")],  # 116
    "key_compose": [B("KEY_COMPOSE")],  # 127
    "key_stop": [B("KEY_STOP")],  # 128
    "key_again": [B("KEY_AGAIN")],  # 129
    "key_props": [B("KEY_PROPS")],  # 130
    "key_undo": [B("KEY_UNDO")],  # 131
    "key_front": [B("KEY_FRONT")],  # 132
    "key_copy": [B("KEY_COPY")],  # 133
    "key_open": [B("KEY_OPEN")],  # 134
    "key_paste": [B("KEY_PASTE")],  # 135
    "key_cut": [B("KEY_CUT")],  # 137
    "key_find": [B("KEY_FIND")],  # 136
    "key_help": [B("KEY_HELP")],  # 138
    "key_calc": [B("KEY_CALC")],  # 140
    "key_sleep": [B("KEY_SLEEP")],  # 142
    "key_www": [B("KEY_WWW")],  # 150
    "key_screenlock": [B("KEY_SCREENLOCK")],  # 152
    "key_back": [B("KEY_BACK")],  # 158
    "key_refresh": [B("KEY_REFRESH")],  # 173
    "key_edit": [B("KEY_EDIT")],  # 176
    "key_scrollup": [B("KEY_SCROLLUP")],  # 177
    "key_scrolldown": [B("KEY_SCROLLDOWN")],  # 178
    "key_1": [B("KEY_1")],  # 2
    "key_2": [B("KEY_2")],  # 3
    "key_3": [B("KEY_3")],  # 4
    "key_4": [B("KEY_4")],  # 5
    "key_5": [B("KEY_5")],  # 6
    "key_6": [B("KEY_6")],  # 7
    "key_7": [B("KEY_7")],  # 8
    "key_8": [B("KEY_8")],  # 9
    "key_9": [B("KEY_9")],  # 10
    "key_0": [B("KEY_0")],  # 11
    "key_a": [B("KEY_A")],  # 30
    "key_b": [B("KEY_B")],  # 48
    "key_c": [B("KEY_C")],  # 46
    "key_d": [B("KEY_D")],  # 32
    "key_e": [B("KEY_E")],  # 18
    "key_f": [B("KEY_F")],  # 33
    "key_g": [B("KEY_G")],  # 34
    "key_h": [B("KEY_H")],  # 35
    "key_i": [B("KEY_I")],  # 23
    "key_j": [B("KEY_J")],  # 36
    "key_k": [B("KEY_K")],  # 37
    "key_l": [B("KEY_L")],  # 38
    "key_m": [B("KEY_M")],  # 50
    "key_n": [B("KEY_N")],  # 49
    "key_o": [B("KEY_O")],  # 24
    "key_p": [B("KEY_P")],  # 25
    "key_q": [B("KEY_Q")],  # 16
    "key_r": [B("KEY_R")],  # 19
    "key_s": [B("KEY_S")],  # 31
    "key_t": [B("KEY_T")],  # 20
    "key_u": [B("KEY_U")],  # 22
    "key_v": [B("KEY_V")],  # 47
    "key_w": [B("KEY_W")],  # 17
    "key_x": [B("KEY_X")],  # 45
    "key_y": [B("KEY_Y")],  # 21
    "key_z": [B("KEY_Z")],  # 44
    "key_kpasterisk": [B("KEY_KPASTERISK")],  # 55
    "key_kpminus": [B("KEY_KPMINUS")],  # 74
    "key_kpplus": [B("KEY_KPPLUS")],  # 78
    "key_kpdot": [B("KEY_KPDOT")],  # 83
    "key_kpjpcomma": [B("KEY_KPJPCOMMA")],  # 95
    "key_kpenter": [B("KEY_KPENTER")],  # 96
    "key_kpslash": [B("KEY_KPSLASH")],  # 98
    "key_kpequal": [B("KEY_KPEQUAL")],  # 117
    "key_kpcomma": [B("KEY_KPCOMMA")],  # 121
    "key_kpleftparen": [B("KEY_KPLEFTPAREN")],  # 179
    "key_kprightparen": [B("KEY_KPRIGHTPAREN")],  # 180
    "key_kp0": [B("KEY_KP0")],  # 82
    "key_kp1": [B("KEY_KP1")],  # 79
    "key_kp2": [B("KEY_KP2")],  # 80
    "key_kp3": [B("KEY_KP3")],  # 81
    "key_kp4": [B("KEY_KP4")],  # 75
    "key_kp5": [B("KEY_KP5")],  # 76
    "key_kp6": [B("KEY_KP6")],  # 77
    "key_kp7": [B("KEY_KP7")],  # 71
    "key_kp8": [B("KEY_KP8")],  # 72
    "key_kp9": [B("KEY_KP9")],  # 73
    "key_f1": [B("KEY_F1")],  # 59
    "key_f2": [B("KEY_F2")],  # 60
    "key_f3": [B("KEY_F3")],  # 61
    "key_f4": [B("KEY_F4")],  # 62
    "key_f5": [B("KEY_F5")],  # 63
    "key_f6": [B("KEY_F6")],  # 64
    "key_f7": [B("KEY_F7")],  # 65
    "key_f8": [B("KEY_F8")],  # 66
    "key_f9": [B("KEY_F9")],  # 67
    "key_f11": [B("KEY_F11")],  # 87
    "key_f12": [B("KEY_F12")],  # 88
    "key_f10": [B("KEY_F10")],  # 68
    "key_f13": [B("KEY_F13")],  # 183
    "key_f14": [B("KEY_F14")],  # 184
    "key_f15": [B("KEY_F15")],  # 185
    "key_f16": [B("KEY_F16")],  # 186
    "key_f17": [B("KEY_F17")],  # 187
    "key_f18": [B("KEY_F18")],  # 188
    "key_f19": [B("KEY_F19")],  # 189
    "key_f20": [B("KEY_F20")],  # 190
    "key_f21": [B("KEY_F21")],  # 191
    "key_f22": [B("KEY_F22")],  # 192
    "key_f23": [B("KEY_F23")],  # 193
    "key_f24": [B("KEY_F24")],  # 194
    "key_playpause": [B("KEY_PLAYPAUSE")],  # 164
    "key_pause": [B("KEY_PAUSE")],  # 119
    "key_mute": [B("KEY_MUTE")],  # 113
    "key_stopcd": [B("KEY_STOPCD")],  # 166
    "key_forward": [B("KEY_FORWARD")],  # 159
    "key_ejectcd": [B("KEY_EJECTCD")],  # 161
    "key_nextsong": [B("KEY_NEXTSONG")],  # 163
    "key_previoussong": [B("KEY_PREVIOUSSONG")],  # 165
    "key_volumedown": [B("KEY_VOLUMEDOWN")],  # 114
    "key_volumeup": [B("KEY_VOLUMEUP")],  # 115
    "key_katakana": [B("KEY_KATAKANA")],  # 90
    "key_hiragana": [B("KEY_HIRAGANA")],  # 91
    "key_henkan": [B("KEY_HENKAN")],  # 92
    "key_katakanahiragana": [B("KEY_KATAKANAHIRAGANA")],  # 93
    "key_muhenkan": [B("KEY_MUHENKAN")],  # 94
    "key_zenkakuhankaku": [B("KEY_ZENKAKUHANKAKU")],  # 85
    "key_hanguel": [B("KEY_HANGUEL")],  # 122
    "key_hanja": [B("KEY_HANJA")],  # 123
    "key_yen": [B("KEY_YEN")],  # 124
    "key_unknown": [B("KEY_UNKNOWN")],  # 240,
    "key_prog1": [B("KEY_PROG1")],  # 148
    "key_prog2": [B("KEY_PROG2")],  # 149,
}

KEYBOARD_MAP_REV: dict[KeyboardButton, int] = {k: v[0] for k, v in _kbd_raw.items()}

KEYBOARD_MAP: dict[int, KeyboardButton] = to_map(_kbd_raw)

__all__ = ["GenericGamepadEvdev", "XBOX_BUTTON_MAP", "XBOX_AXIS_MAP", "B", "to_map"]
