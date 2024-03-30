import ctypes
import struct
import time
from fcntl import ioctl
from threading import Event as TEvent
from threading import RLock
from typing import Callable, Sequence, cast

from evdev import InputDevice, ecodes, list_devices

from hhd.controller import Event as ControllerEvent
from hhd.controller import SpecialEvent
from hhd.controller.lib.ioctl import EVIOCGMASK, EVIOCSMASK
from hhd.controller.physical.evdev import B, to_map
from hhd.plugins import Context

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

WAKE_BUTTON_MAP: dict[int, str] = to_map(
    {
        "mode": [B("BTN_MODE")],
        "b": [B("BTN_B")],
    }
)
WAKE_AXIS_MAP = {}

REPEAT_INITIAL = 0.5
REPEAT_INTERVAL = 0.2


def grab_buttons(fd: int, typ: int, btns: dict[int, str]):
    b_len = max((max(btns) >> 3) + 1, 8)
    mask = bytearray(b_len)
    for b in btns:
        mask[b // 8] = 1 << (b % 8)

    c_mask = ctypes.create_string_buffer(bytes(mask))
    data = struct.pack("@ I I L", typ, b_len, ctypes.addressof(c_mask))
    ioctl(fd, EVIOCSMASK, data)
    # ioctl(fd, EVIOCGMASK, data)


def monitor_controllers(
    grab: TEvent,
    should_exit: TEvent,
    ctx: Context,
    emit: Callable[[SpecialEvent], None],
    callback: Callable[[SpecialEvent], None],
):
    controllers = {}
    grabbed = None

    while not should_exit.is_set():
        curr = time.perf_counter()

        for path in list_devices():
            if path in controllers:
                continue
            dev = InputDevice(path)

        time.sleep(2)


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
                    ):
                        continue
                    val = ev["value"]
                    if (
                        code not in self.state[cid]
                        or bool(self.state[cid][code]) != val
                    ):
                        changed.append((code, val))
                        self.state[cid][code] = curr + REPEAT_INITIAL if val else None

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
