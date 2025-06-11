import ctypes
import logging
import os
import select
import struct
import time
from fcntl import ioctl
from threading import RLock
from typing import Any, Sequence
import stat

from evdev import InputDevice

from hhd.controller import Event as ControllerEvent
from hhd.controller.lib.ioctl import EVIOCSMASK, EVIOCGRABCLEAN
from hhd.controller.physical.evdev import B, list_evs, to_map
from hhd.controller.virtual.uinput.monkey import UInput, UInputMonkey

from .const import get_touchscreen_quirk
from .x11 import is_gamescope_running

logger = logging.getLogger(__name__)

ENHANCED_HIDING = bool(os.environ.get("HHD_EVIOC_IOCTL", False))

REFRESH_INTERVAL = 0.1
MONITOR_INTERVAL = 2
OVERLAY_BUTTON_MAP: dict[int, str] = to_map(
    {
        "a": [B("BTN_A")],
        "b": [B("BTN_B")],
        "x": [B("BTN_X")],
        "y": [B("BTN_Y")],
        "lb": [B("BTN_TL")],
        "rb": [B("BTN_TR")],
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
        "select": [B("BTN_SELECT")],
        "mode": [B("BTN_MODE")],
        "b": [B("BTN_B")],
        "y": [B("BTN_Y")],
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
        "ctrl": [B("KEY_LEFTCTRL")],
        "3": [B("KEY_3")],
        "4": [B("KEY_4")],
    }
)

REPEAT_INITIAL = 0.5
REPEAT_INTERVAL = 0.2

GESTURE_TIME = 0.4
# Inspired by Ruineka's old
# gamescope gestures (pre 3.14)
GESTURE_END = 0.03
GESTURE_START = 0.02
GESTURE_TOP_RATIO = 0.33

XBOX_B_MAX_PRESS = 0.3
KBD_HOLD_DELAY = 0.5

# Cached vars
EV_ABS = B("EV_ABS")
EV_KEY = B("EV_KEY")
EV_SYN = B("EV_SYN")
HHD_DEBUG = os.environ.get("HHD_DEBUG", None)


class QamHandlerKeyboard:
    def __init__(self) -> None:
        self.uinput = None

    def _open(self):
        if self.uinput:
            return True

        args = {
            "events": {
                B("EV_KEY"): [
                    B("KEY_LEFTCTRL"),
                    B("KEY_1"),
                    B("KEY_2"),
                ]
            },
            "name": "Handheld Daemon Steam Events",
            "phys": "phys-hhd-qam",
        }
        try:
            self.uinput = UInputMonkey(**args)
            return True
        except Exception:
            try:
                self.uinput = UInput(**args)
                return True
            except Exception as e:
                pass
        return False

    def __call__(self, expanded=False) -> Any:
        if not is_gamescope_running():
            # Ctrl+1/2 do nothing outside gamescope
            return False
        if not self._open():
            return False
        if not self.uinput:
            return False

        try:
            btn = B("KEY_1") if expanded else B("KEY_2")
            self.uinput.write(B("EV_KEY"), B("KEY_LEFTCTRL"), 1)
            self.uinput.write(B("EV_KEY"), btn, 1)
            self.uinput.syn()
            time.sleep(0.3)
            self.uinput.write(B("EV_KEY"), btn, 0)
            self.uinput.write(B("EV_KEY"), B("KEY_LEFTCTRL"), 0)
            self.uinput.syn()
            return True
        except Exception as e:
            logger.error(f"Could not send keyboard event. Error:\n{e}")
            return False

    def screenshot(self) -> bool:
        if not self._open():
            return False
        if not self.uinput:
            return False

        try:
            btn = B("KEY_F12")
            self.uinput.write(B("EV_KEY"), btn, 1)
            self.uinput.syn()
            time.sleep(0.1)
            self.uinput.write(B("EV_KEY"), btn, 0)
            self.uinput.syn()
            return True
        except Exception as e:
            logger.error(f"Could not send screenshot event. Error:\n{e}")
            return False

    def close(self):
        if self.uinput:
            self.uinput.close()
            self.uinput = None


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


def find_devices(
    current: dict[str, Any] = {},
    keyboard: bool = True,
    controllers: bool = True,
    touchscreens: bool = True,
):
    out = {}
    for name, dev in list_evs(True).items():
        if name in current:
            continue

        # Skip HHD devices
        if "hhd" in dev.get("phys", "") or (
            # Allow bluetooth controllers that contain uhid and phys, while
            # blocking hhd devices that contain uhid but not phys
            "uhid" in dev.get("sysfs", "")
            and not dev.get("phys", "")
        ):
            continue

        # Skip Steam virtual devices
        # Vendor=28de Product=11ff
        if dev.get("vendor", 0) == 0x28DE and dev.get("product", 0) == 0x11FF:
            continue

        abs = dev.get("byte", {}).get("abs", bytes())
        keys = dev.get("byte", {}).get("key", bytes())

        # Touchscreen is complicated. Should have BTN_TOUCH but not BTN_TOOL_FINGER
        is_touchscreen = touchscreens
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

        is_controller = controllers
        for cap in CONTROLLER_WAKE_BUTTON:
            major = cap >> 3
            minor = cap & 0x07
            if len(keys) <= major or not keys[major] & (1 << minor):
                is_controller = False
                break

        # Avoid laptop keyboards, as they emit left meta on power button hold
        # FIXME: will prevent using laptop keyboards to bring up the menu
        is_keyboard = keyboard and not dev.get("name", "").startswith("AT Translated")
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
                "vid": dev.get("vendor", 0),
                "pid": dev.get("product", 0),
            }

    return out


def process_touch(emit, state, ev, val):
    # Check if the gesture should be kept
    invalidated = False
    if ev == "slot" and val:
        # Second finger, remove the gesture
        invalidated = True
    elif ev == "id" and val == -1:
        # Finger removed, remove the gesture
        invalidated = True
        # This is the only time we remove the
        # start_time as well, so gestures can resume.
        state["start_time"] = 0

    if invalidated:
        state["start_x"] = 0
        state["start_y"] = 0
        state["last_x"] = 0
        state["last_y"] = 0
        state["grab"] = False
        return

    start_time = state.get("start_time", 0)
    curr = time.time()
    if start_time and curr - start_time > GESTURE_TIME:
        # User took too long, stop processing gestures
        # until finger is released
        return

    # After this point, we only use coordinates
    if ev not in ("x", "y"):
        return

    # Swap names around to avoid
    # Confusion with portrait displays
    if state["portrait"]:
        if ev == "x":
            ev = "y"
            max_ev = state["max_x"]
        elif ev == "y":
            ev = "x"
            max_ev = state["max_y"]
    else:
        max_ev = state[f"max_{ev}"]

    if state["flip_x"] and ev == "x":
        val = max_ev - val
    if state["flip_y"] and ev == "y":
        val = max_ev - val

    if not start_time:
        state["start_time"] = curr

    # Save old values
    v = val / max_ev
    state[f"start_{ev}"] = state[f"start_{ev}"] if state.get(f"start_{ev}", 0) else v
    state[f"last_{ev}"] = v

    # Begin handler
    start_x = state.get("start_x", 0)
    start_y = state.get("start_y", 0)
    last_x = state.get("last_x", 0)
    last_y = state.get("last_y", 0)

    if not start_x or not start_y:
        return
    if not last_x or not last_y:
        return

    if (
        start_x < GESTURE_START
        or start_x > 1 - GESTURE_START
        or start_y > 1 - GESTURE_START
    ):
        state["grab"] = True

    # logger.info(
    #     f"{start_x:.2f}:{start_y:.2f} -> {last_x:.2f}:{last_y:.2f} = ({dx:5.2f}, {dy:5.2f})"
    # )

    handled = False
    if start_x < GESTURE_START and last_x > GESTURE_END:
        semi = "top" if start_y < GESTURE_TOP_RATIO else "bottom"
        if emit:
            emit({"type": "special", "event": f"swipe_right_{semi}"})
        handled = True
    elif start_x > 1 - GESTURE_START and last_x < 1 - GESTURE_END:
        semi = "top" if start_y < GESTURE_TOP_RATIO else "bottom"
        if emit:
            emit({"type": "special", "event": f"swipe_left_{semi}"})
        handled = True
    elif start_y > 1 - GESTURE_START and last_y < 1 - GESTURE_END:
        if emit:
            emit({"type": "special", "event": "swipe_bottom"})
        handled = True
    elif start_y < GESTURE_START and last_y > GESTURE_END:
        if emit:
            emit({"type": "special", "event": "swipe_top"})
        handled = True

    if handled:
        state["start_x"] = 0
        state["start_y"] = 0
        state["last_x"] = 0
        state["last_y"] = 0
        state["grab"] = False


def process_kbd(emit, state, ev, val):
    if ev == "ctrl":
        state["ctrl"] = val
        return
    if ev == "3" and val and state.get("ctrl", 0):
        if emit:
            emit({"type": "special", "event": "kbd_ctrl_3"})
    if ev == "4" and val and state.get("ctrl", 0):
        if emit:
            emit({"type": "special", "event": "kbd_ctrl_4"})

    # Skip repeats
    if val == 2:
        return

    if not ev == "meta":
        return

    pressed_n = state.get("pressed_n", 0)

    curr = time.time()
    if val:
        state["pressed_n"] = pressed_n + 1
        state["last_pressed"] = curr
    else:
        if pressed_n:
            emit({"type": "special", "event": "kbd_meta_press"})
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
    if ev == "select":
        state["select"] = val
        return

    if ev != "b" and ev != "y":
        return

    # Mode needs to be pressed
    if not state.get("mode", None) and not state.get("select", None):
        return

    if val:
        state[ev] = time.time()
    else:
        if state.get(ev, None) and time.time() - state[ev] < XBOX_B_MAX_PRESS:
            logger.info(f"Xbox+{ev} pressed")
            if emit:
                emit(
                    {
                        "type": "special",
                        "event": f"xbox_{ev}",
                        "data": {"uniq": state.get("uniq", None)},
                    }
                )
        state[ev] = None


def process_events(emit, dev, evs):
    # Some nice logging to make things easier
    if HHD_DEBUG:
        log = ""
        if dev["is_touchscreen"]:
            for ev in evs:
                if ev.type != EV_ABS:
                    continue
                code = ev.code
                if code not in TOUCH_WAKE_AXIS:
                    continue
                log += f"\n - {TOUCH_WAKE_AXIS[code]}: {ev.value}"
        elif dev["is_controller"]:
            for ev in evs:
                if ev.type != EV_KEY:
                    continue
                code = ev.code
                if code not in CONTROLLER_WAKE_BUTTON:
                    continue
                log += f"\n - {CONTROLLER_WAKE_BUTTON[code]}: {ev.value}"
        elif dev["is_keyboard"]:
            for ev in evs:
                if ev.type != EV_KEY:
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
        if ev.type == EV_SYN:
            continue

        if dev["is_touchscreen"] and ev.type == EV_ABS and ev.code in TOUCH_WAKE_AXIS:
            process_touch(emit, dev["state_touch"], TOUCH_WAKE_AXIS[ev.code], ev.value)

        if (
            dev["is_controller"]
            and ev.type == EV_KEY
            and ev.code in CONTROLLER_WAKE_BUTTON
        ):
            process_ctrl(
                emit, dev["state_ctrl"], CONTROLLER_WAKE_BUTTON[ev.code], ev.value
            )

        if dev["is_keyboard"] and ev.type == EV_KEY and ev.code in KEYBOARD_WAKE_KEY:
            process_kbd(emit, dev["state_kbd"], KEYBOARD_WAKE_KEY[ev.code], ev.value)


def refresh_events(emit, dev):
    # if dev["is_touchscreen"]:
    #     refresh_touch(emit, dev["state_touch"])
    # if dev["is_controller"]:
    #     refresh_ctrl(emit, dev["state_ctrl"])
    if dev["is_keyboard"]:
        refresh_kbd(emit, dev["state_kbd"])


def intercept_devices(devs, activate: bool):
    failed = []
    for id, dev in devs.items():
        if not dev["is_controller"]:
            continue
        d = dev["dev"]
        if activate:
            try:
                grab_buttons(
                    d.fd,
                    B("EV_KEY"),
                    {
                        **CONTROLLER_WAKE_BUTTON,
                        **KEYBOARD_WAKE_KEY,
                        **OVERLAY_BUTTON_MAP,
                    },
                )
                grab_buttons(d.fd, B("EV_ABS"), OVERLAY_AXIS_MAP)

                if not dev.get("grabbed", False):
                    fallback = True
                    if ENHANCED_HIDING:
                        try:
                            ioctl(d.fd, EVIOCGRABCLEAN, 1)
                            fallback = False
                        except Exception:
                            pass
                    if fallback:
                        d.grab()
                    dev["grabbed"] = True
                logger.info(f" - '{dev['pretty']}'")
            except Exception:
                logger.warning(f" - Failed: '{dev['pretty']}'")
                failed.append((id, dev))
        else:
            try:
                if dev.get("grabbed", False):
                    d.ungrab()
                    dev["grabbed"] = False

                grab_buttons(
                    d.fd,
                    B("EV_KEY"),
                    {
                        **CONTROLLER_WAKE_BUTTON,
                        **KEYBOARD_WAKE_KEY,
                    },
                )
                grab_buttons(d.fd, B("EV_ABS"), {})
                logger.info(f" - '{dev['pretty']}'")
            except Exception:
                logger.warning(f" - Failed: '{dev['pretty']}'")
                failed.append((id, dev))
    return failed


def intercept_events(emit, intercept_num, cid, dinput, smax, evs):
    if not emit:
        return

    out = []
    for ev in evs:
        if ev.type == EV_SYN:
            continue

        if ev.type == EV_KEY and ev.code in OVERLAY_BUTTON_MAP:
            out.append(
                {
                    "type": "button",
                    "code": OVERLAY_BUTTON_MAP[ev.code],
                    "value": ev.value,
                }
            )
        elif ev.type == EV_ABS and ev.code in OVERLAY_AXIS_MAP:
            code = OVERLAY_AXIS_MAP[ev.code]

            if "ls" in code:
                if dinput:
                    v = min(1, max(-1, 2 * ev.value / smax - 1))
                else:
                    v = min(1, max(-1, ev.value / smax))
            else:
                v = ev.value

            out.append(
                {
                    "type": "axis",
                    "code": code,
                    "value": v,
                }
            )

    emit.intercept(cid + intercept_num, out)


def device_shortcut_loop(
    emit=None,
    should_exit=None,
    init=True,
    keyboard: bool = True,
    controllers: bool = True,
    touchscreens: bool = True,
    disable_touchscreens: bool = False,
    touch_correction: dict | None = None,
):
    blacklist = set()
    last_check = 0
    intercept = False
    intercept_num = 0
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
        should_intercept = emit and emit.should_intercept()
        if any(dev["is_controller"] for dev in devs.values()):
            failed = []
            if not intercept and should_intercept:
                intercept = True
                intercept_num += 1
                logger.info("Intercepting other controllers:")
                failed = intercept_devices(devs, True)
            elif intercept and not should_intercept:
                intercept = False
                logger.info("Stopping intercepting other controllers:")
                failed = intercept_devices(devs, False)
            for id, f in failed:
                blacklist.add(f["hash"])
                try:
                    del devs[id]
                except Exception:
                    pass

        for name, dev in list(devs.items()):
            d = dev["dev"]
            refresh_events(emit, dev)
            if not d.fd in r:
                # Run interception so that holding button repeats work
                if should_intercept and dev["is_controller"]:
                    intercept_events(
                        emit,
                        intercept_num,
                        dev["hash"],
                        dev["dinput"],
                        dev["stick_max"],
                        [],
                    )
                continue

            try:
                if dev["is_controller"] and os.stat(name).st_mode & stat.S_IRGRP == 0:
                    logger.info(f"Removing hidden device: '{dev['pretty']}'")
                    blacklist.add(cand["hash"])
                    del devs[name]
                    try:
                        d.close()
                    except Exception:
                        pass
                    continue

                e = list(d.read())
                # print(e)
                process_events(emit, dev, e)
                if should_intercept and dev["is_controller"]:
                    intercept_events(
                        emit,
                        intercept_num,
                        dev["hash"],
                        dev["dinput"],
                        dev["stick_max"],
                        e,
                    )
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
        for name, cand in find_devices(
            devs,
            keyboard=keyboard,
            touchscreens=touchscreens or disable_touchscreens,
            controllers=controllers,
        ).items():
            if cand["hash"] in blacklist:
                continue

            try:
                if os.stat(name).st_mode & stat.S_IRGRP == 0:
                    continue

                dev = InputDevice(name)

                if cand["is_touchscreen"] and disable_touchscreens:
                    # Grab touchscreen if requested
                    fallback = True
                    if ENHANCED_HIDING:
                        try:
                            ioctl(dev.fd, EVIOCGRABCLEAN, 1)
                            fallback = False
                        except Exception:
                            pass
                    if fallback:
                        dev.grab()

                # Add event filters to avoid CPU use
                # Do controllers and keyboards together as buttons do not consume much
                if cand["is_controller"] or cand["is_keyboard"]:
                    grab_buttons(
                        dev.fd,
                        B("EV_KEY"),
                        {**CONTROLLER_WAKE_BUTTON, **KEYBOARD_WAKE_KEY},
                    )
                else:
                    grab_buttons(dev.fd, B("EV_KEY"), {})

                # Abs events
                # Touchscreen, joystick, etc. We only care about touchscreens
                if cand["is_touchscreen"]:
                    grab_buttons(dev.fd, B("EV_ABS"), TOUCH_WAKE_AXIS)
                else:
                    grab_buttons(dev.fd, B("EV_ABS"), {})

                # Rel events are not used
                # They contain e.g., scroll events, mouse movements
                grab_buttons(dev.fd, B("EV_REL"), {})
                # MSC Events are not used
                # They contain e.g., scan codes
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
                    max_x = dev.absinfo(B("ABS_MT_POSITION_X")).max
                    max_y = dev.absinfo(B("ABS_MT_POSITION_Y")).max

                    # Default quirks
                    portrait = max_x < max_y
                    flip_x = not portrait  # just the way it is
                    flip_y = False

                    quirk, pretty = get_touchscreen_quirk(
                        vid=dev.info.vendor, pid=dev.info.product
                    )
                    if touch_correction:
                        portrait = touch_correction.get("portrait", False)
                        flip_x = touch_correction.get("flip_x", False)
                        flip_y = touch_correction.get("flip_y", False)
                        caps.append(
                            f"Touchscreen[manual, portrait={portrait}, x={flip_x}, y={flip_y}]"
                        )
                    elif quirk:
                        portrait = quirk.portrait
                        flip_x = quirk.flip_x
                        flip_y = quirk.flip_y
                        caps.append(f"Touchscreen[{pretty}]")
                    else:
                        caps.append(
                            f"Touchscreen[auto, portrait={portrait}, x={flip_x}, y={flip_y}]"
                        )

                    devs[name]["state_touch"].update(
                        {
                            "max_x": max_x,
                            "max_y": max_y,
                            "portrait": portrait,
                            "flip_x": flip_x,
                            "flip_y": flip_y,
                        }
                    )
                if cand["is_controller"]:
                    try:
                        stick_max = dev.absinfo(B("ABS_X")).max
                        dinput = not dev.absinfo(B("ABS_X")).min
                    except Exception:
                        stick_max = 2**16
                        dinput = False
                    devs[name]["dinput"] = dinput
                    devs[name]["state_ctrl"].update({"uniq": dev.uniq})
                    devs[name]["stick_max"] = stick_max
                    caps.append(f"Controller[dinput={dinput}, smax={stick_max}]")
                if cand["is_keyboard"]:
                    caps.append("Keyboard")
                log += f"\n - '{cand['pretty']}' [{cand['vid']:04x}:{cand['pid']:04x}] ({', '.join(caps)})"
            except Exception as e:
                logger.error(f"Failed to open device '{cand['pretty']}'. Error:\n{e}")
                blacklist.add(cand["hash"])

        if log:
            logger.info(f"Found new shortcut devices:{log}")


AXIS_LIMIT = 0.5


class OverlayWriter:
    def __init__(self, stdout, mute: bool = True) -> None:
        self.state = {}
        self.stdout = stdout
        self._write_lock = RLock()

        if mute:
            # We support intercepting all controllers now
            self.write("cmd:mute\n")

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
