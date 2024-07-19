import ctypes
import logging
import os
import select
import struct
import time
from fcntl import ioctl
from threading import Event as TEvent
from threading import RLock
from typing import Any, Callable, Sequence

from evdev import InputDevice, list_devices

from hhd.controller import Event as ControllerEvent
from hhd.controller import can_read
from hhd.controller.lib.ioctl import EVIOCGMASK, EVIOCSMASK
from hhd.controller.physical.evdev import B, list_evs, to_map
from hhd.plugins import Context

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 0.1
MONITOR_INTERVAL = 2
OVERLAY_BUTTON_MAP: dict[int, str] = to_map(
    {
        "a": [B("BTN_A")],
        "b": [B("BTN_B")],
        "x": [B("BTN_X")],
        "y": [B("BTN_Y")],
    }
)
OVERLAY_AXIS_MAP: dict[int, str] = to_map(
    {
        # Values should range from -1 to 1
        "ls_x": [B("ABS_X")],
        "ls_y": [B("ABS_Y")],
        # Hat, implemented as axis. Either -1, 0, or 1
        "hat_x": [B("ABS_HAT0X")],
        "hat_y": [B("ABS_HAT0Y")],
    }
)

CONTROLLER_WAKE_BUTTON: dict[int, str] = to_map(
    {
        "mode": [B("BTN_MODE")],
        "b": [B("BTN_B")],
    }
)

TOUCH_WAKE_AXIS: dict[int, str] = to_map(
    {
        "slot": [B("ABS_MT_SLOT")],
        "x": [B("ABS_MT_POSITION_X")],
        "y": [B("ABS_MT_POSITION_Y")],
        "id": [B("ABS_MT_TRACKING_ID")],
    }
)

KEYBOARD_WAKE_KEY: dict[int, str] = to_map(
    {
        "meta": [B("KEY_LEFTMETA")],
    }
)

REPEAT_INITIAL = 0.5
REPEAT_INTERVAL = 0.2

GESTURE_TIME = 0.3
GESTURE_LIM = 0.1
GESTURE_LEN = 0.1

XBOX_B_MAX_PRESS = 0.3
KBD_HOLD_DELAY = 0.8


def grab_buttons(fd: int, typ: int, btns: dict[int, str] | None):
    if btns:
        b_len = max((max(btns) >> 3) + 1, 8)
        mask = bytearray(b_len)
        for b in btns:
            mask[b >> 3] |= 1 << (b & 0x07)
    else:
        mask = bytes([])
        b_len = 0

    c_mask = ctypes.create_string_buffer(bytes(mask))
    data = struct.pack("@ I I L", typ, b_len, ctypes.addressof(c_mask))
    # Before
    # print(bytes(mask).hex())
    ioctl(fd, EVIOCSMASK, data)
    # After
    # ioctl(fd, EVIOCGMASK, data)
    # print(bytes(mask).hex())


def find_devices(current: dict[str, Any] = {}):
    out = {}
    for name, dev in list_evs(True).items():
        if name in current:
            continue

        # Skip HHD devices
        # if "hhd" in dev.get("phys", ""):
        #     continue

        abs = dev.get("byte", {}).get("abs", bytes())
        keys = dev.get("byte", {}).get("key", bytes())

        # Touchscreen is complicated. Should have BTN_TOUCH but not BTN_TOOL_FINGER
        is_touchscreen = True
        major = B("BTN_TOUCH") >> 3
        minor = B("BTN_TOUCH") & 0x07
        if len(keys) <= major or not keys[major] & (1 << minor):
            is_touchscreen = False
        major = B("BTN_TOOL_FINGER") >> 3
        minor = B("BTN_TOOL_FINGER") & 0x07
        if len(keys) > major and keys[major] & (1 << minor):
            is_touchscreen = False

        for cap in TOUCH_WAKE_AXIS:
            major = cap >> 3
            minor = cap & 0x07
            if len(abs) <= major or not abs[major] & (1 << minor):
                is_touchscreen = False
                break

        is_controller = True
        for cap in CONTROLLER_WAKE_BUTTON:
            major = cap >> 3
            minor = cap & 0x07
            if len(keys) <= major or not keys[major] & (1 << minor):
                is_controller = False
                break

        # Avoid laptop keyboards, as they emit left meta on power button hold
        # FIXME: will prevent using laptop keyboards to bring up the menu
        is_keyboard = not dev.get("name", "").startswith("AT Translated")
        for cap in KEYBOARD_WAKE_KEY:
            major = cap >> 3
            minor = cap & 0x07
            if len(keys) <= major or not keys[major] & (1 << minor):
                is_keyboard = False
                break

        if is_touchscreen or is_controller or is_keyboard:
            out[name] = {
                "is_touchscreen": is_touchscreen,
                "is_controller": is_controller,
                "is_keyboard": is_keyboard,
                "pretty": dev.get("name", ""),
                "hash": dev.get("hash", ""),
            }

    return out


def process_touch(emit, state, ev, val):
    print(state)


def process_kbd(emit, state, _, val):
    # Skip repeats
    if val == 2:
        return

    pressed_n = state.get("pressed_n", 0)

    curr = time.time()
    if val:
        state["pressed_n"] = pressed_n + 1
        state["last_pressed"] = curr
    else:
        if pressed_n:
            emit({"type": "special", "event": "kbd_meta_single"})
        state["last_pressed"] = 0


def refresh_kbd(emit, state):
    pressed_n = state.get("pressed_n", 0)
    last_pressed = state.get("last_pressed", 0)
    # last_release = state.get("last_release", 0)
    curr = time.time()

    if pressed_n and last_pressed and curr - last_pressed > KBD_HOLD_DELAY:
        if emit:
            emit({"type": "special", "event": "kbd_meta_hold"})
        state["pressed_n"] = 0
        state["last_pressed"] = 0


def process_ctrl(emit, state, ev, val):
    # Here, we capture the shortcut xbox+b
    # This is a shortcut that is used by steam
    # but only when it is held, so we can use
    # it if its a shortpress
    if ev == "mode":
        state["mode"] = val
        return

    if ev != "b":
        return

    # Mode needs to be pressed
    if not state.get("mode", None):
        return

    if val:
        state["b"] = time.time()
    else:
        if state.get("b", None) and time.time() - state["b"] < XBOX_B_MAX_PRESS:
            logger.info("Xbox+B pressed")
            if emit:
                emit({"type": "special", "event": "qam_external"})
        state["b"] = None


def process_events(emit, dev, evs):
    # Some nice logging to make things easier
    if os.environ.get("HHD_DEBUG", None):
        log = ""
        if dev["is_touchscreen"]:
            for ev in evs:
                if ev.type != B("EV_ABS"):
                    continue
                code = ev.code
                if code not in TOUCH_WAKE_AXIS:
                    continue
                log += f"\n - {TOUCH_WAKE_AXIS[code]}: {ev.value}"
        elif dev["is_controller"]:
            for ev in evs:
                if ev.type != B("EV_KEY"):
                    continue
                code = ev.code
                if code not in CONTROLLER_WAKE_BUTTON:
                    continue
                log += f"\n - {CONTROLLER_WAKE_BUTTON[code]}: {ev.value}"
        elif dev["is_keyboard"]:
            for ev in evs:
                if ev.type != B("EV_KEY"):
                    continue
                code = ev.code
                if code not in KEYBOARD_WAKE_KEY:
                    continue
                if ev.value == 2:
                    continue
                log += f"\n - {KEYBOARD_WAKE_KEY[code]}: {ev.value}"
        if log:
            logger.info(f"'{dev['pretty']}':{log}")

    for ev in evs:
        # The evs list is SYN, however, for gestures do we really care?
        # We can also do some ugly prefiltering here, so that the
        # inner functions are prettier
        if ev.type == B("EV_SYN"):
            continue
        if dev["is_touchscreen"]:
            if ev.type != B("EV_ABS"):
                continue
            if ev.code not in TOUCH_WAKE_AXIS:
                continue
            process_touch(emit, dev["state_touch"], TOUCH_WAKE_AXIS[ev.code], ev.value)
        if dev["is_controller"]:
            if ev.type != B("EV_KEY"):
                continue
            if ev.code not in CONTROLLER_WAKE_BUTTON:
                continue
            process_ctrl(
                emit, dev["state_ctrl"], CONTROLLER_WAKE_BUTTON[ev.code], ev.value
            )
        if dev["is_keyboard"]:
            if ev.type != B("EV_KEY"):
                continue
            if ev.code not in KEYBOARD_WAKE_KEY:
                continue
            process_kbd(emit, dev["state_kbd"], KEYBOARD_WAKE_KEY[ev.code], ev.value)


def refresh_events(emit, dev):
    # if dev["is_touchscreen"]:
    #     refresh_touch(emit, dev["state_touch"])
    # if dev["is_controller"]:
    #     refresh_ctrl(emit, dev["state_ctrl"])
    if dev["is_keyboard"]:
        refresh_kbd(emit, dev["state_kbd"])


def monitor_devices(emit=None, should_exit=None, init=True):
    blacklist = set()
    last_check = 0
    devs = {}
    while not should_exit or not should_exit.is_set():
        if devs:
            # Wait for events
            try:
                r, _, _ = select.select(
                    [d["dev"].fd for d in devs.values()], [], [], REFRESH_INTERVAL
                )
            except Exception:
                pass
        elif not init:
            # If no devices, wait for a bit
            # Except on first run
            time.sleep(MONITOR_INTERVAL)
        init = False

        # Process events
        for name, dev in list(devs.items()):
            d = dev["dev"]
            refresh_events(emit, dev)
            if not d.fd in r:
                continue
            try:
                while can_read(d.fd):
                    process_events(emit, dev, list(d.read()))
            except Exception as e:
                logger.error(
                    f"Device '{dev['pretty']}' has error. Removing. Error:\n{e}"
                )
                blacklist.add(dev["hash"])
                del devs[name]
                try:
                    d.close()
                except Exception:
                    pass

        # Avoid spamming proc
        curr = time.time()
        if curr - last_check < MONITOR_INTERVAL:
            continue

        # Add new devices
        log = ""
        for name, cand in find_devices(devs).items():
            if cand["hash"] in blacklist:
                continue

            try:
                dev = InputDevice(name)

                # Add event filter to avoid CPU use
                # We can just merge the filters, as each device type will have
                # different event codes
                grab_buttons(
                    dev.fd, B("EV_KEY"), {**CONTROLLER_WAKE_BUTTON, **KEYBOARD_WAKE_KEY}
                )
                grab_buttons(dev.fd, B("EV_ABS"), TOUCH_WAKE_AXIS)
                # Mute MSC events as they will wake us up
                grab_buttons(dev.fd, B("EV_MSC"), {})

                devs[name] = {
                    "dev": dev,
                    **cand,
                    "state_touch": {},
                    "state_ctrl": {},
                    "state_kbd": {},
                }
                caps = []
                if cand["is_touchscreen"]:
                    caps.append("Touchscreen")
                    max_x = dev.absinfo(B("ABS_MT_POSITION_X")).max
                    max_y = dev.absinfo(B("ABS_MT_POSITION_Y")).max
                    portrait = max_x < max_y
                    devs[name]["state_touch"].update(
                        {
                            "max_x": max_x,
                            "max_y": max_y,
                            "portrait": portrait,
                        }
                    )
                if cand["is_controller"]:
                    caps.append("Controller")
                if cand["is_keyboard"]:
                    caps.append("Keyboard")
                log += f"\n - '{cand['pretty']}' ({', '.join(caps)})"
            except Exception as e:
                logger.error(f"Failed to open device '{cand['pretty']}'. Error:\n{e}")
                blacklist.add(cand["hash"])

        if log:
            logger.info(f"Found new shortcut devices:{log}")


AXIS_LIMIT = 0.5


class OverlayWriter:
    def __init__(self, stdout) -> None:
        self.state = {}
        self.stdout = stdout
        self._write_lock = RLock()

    def _call(self, cid: int, evs: Sequence[ControllerEvent]):
        if not cid in self.state:
            self.state[cid] = {}

        # Debounce changed events
        curr = time.perf_counter()
        changed = []
        for ev in evs:
            match ev["type"]:
                case "axis":
                    code = ev["code"]
                    act1 = act2 = val1 = val2 = None
                    if code == "ls_x" or code == "hat_x":
                        act1 = "right"
                        act2 = "left"
                        if ev["value"] > AXIS_LIMIT:
                            val1 = True
                            val2 = False
                        elif ev["value"] < -AXIS_LIMIT:
                            val1 = False
                            val2 = True
                        else:
                            val1 = False
                            val2 = False
                    elif code == "ls_y" or code == "hat_y":
                        act1 = "down"
                        act2 = "up"
                        if ev["value"] > AXIS_LIMIT:
                            val1 = True
                            val2 = False
                        elif ev["value"] < -AXIS_LIMIT:
                            val1 = False
                            val2 = True
                        else:
                            val1 = False
                            val2 = False

                    if act1 and act2:
                        for code, val in ((act1, val1), (act2, val2)):
                            if (
                                code not in self.state[cid]
                                or bool(self.state[cid][code]) != val
                            ):
                                changed.append((code, val))
                                self.state[cid][code] = (
                                    curr + REPEAT_INITIAL if val else None
                                )
                case "button":
                    code = ev["code"]
                    if code not in (
                        "a",
                        "b",
                        "x",
                        "y",
                        "rb",
                        "lb",
                        "mode",
                    ):
                        continue
                    val = ev["value"]
                    if (
                        code not in self.state[cid]
                        or bool(self.state[cid][code]) != val
                    ):
                        changed.append((code, val))
                        self.state[cid][code] = curr + REPEAT_INITIAL if val else None

        # Ignore guide combos
        if self.state[cid].get("mode", None):
            return

        # Allow holds
        for btn, val in list(self.state[cid].items()):
            if not val:
                continue
            if val < curr:
                changed.append((btn, True))
                self.state[cid][btn] = curr + REPEAT_INTERVAL

        # Process changed events
        cmds = ""
        for code, val in changed:
            if val:
                cmds += f"action:{code}\n"
            elif code == "x":
                cmds += f"action:x_up\n"

        # Write them out
        if cmds:
            self.write(cmds)

    def __call__(self, cid: int, evs: Sequence[ControllerEvent]):
        with self._write_lock:
            return self._call(cid, evs)

    def write(self, cmds: str):
        try:
            with self._write_lock:
                self.stdout.write(cmds)
                self.stdout.flush()
        except Exception:
            pass

    def reset(self):
        with self._write_lock:
            self.state = {}
