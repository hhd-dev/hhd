import ctypes
import logging
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


def grab_buttons(fd: int, typ: int, btns: dict[int, str] | None):
    if btns:
        b_len = max((max(btns) >> 3) + 1, 8)
        mask = bytearray(b_len)
        for b in btns:
            mask[b >> 3] = 1 << (b & 0x07)
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
        if "hhd" in dev.get("phys", ""):
            continue

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


def process_events(dev, evs):
    print(f"{dev['pretty']}:\n{evs}")


def monitor_devices(emit=None, should_exit=None):
    blacklist = set()
    last_check = 0
    # FIXME: Maybe set to true? Will cause errors as it will compete
    # with controller emulation on startup
    init = False
    devs = {}
    while not should_exit or not should_exit.is_set():
        if devs:
            # Wait for events
            try:
                select.select(
                    [d["dev"].fd for d in devs.values()], [], [], MONITOR_INTERVAL
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
            try:
                while can_read(d.fd):
                    process_events(dev, list(d.read()))
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

                devs[name] = {"dev": dev, **cand}
                caps = []
                if cand["is_touchscreen"]:
                    caps.append("Touchscreen")
                if cand["is_controller"]:
                    caps.append("Touchscreen")
                if cand["is_keyboard"]:
                    caps.append("Touchscreen")
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
