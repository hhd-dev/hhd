import argparse
import logging
import re
import select
import sys
import time
from threading import Event as TEvent
from typing import Literal, Sequence

from hhd.controller import Button, Consumer, Event, Producer, Axis
from hhd.controller.base import Multiplexer, TouchpadAction
from hhd.controller.lib.hid import enumerate_unique
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.imu import AccelImu, GyroImu
from hhd.controller.virtual.uinput import HHD_PID_VENDOR, UInputDevice
from hhd.plugins import Config, Context, Emitter, get_outputs

from .const import (
    LGO_RAW_INTERFACE_AXIS_MAP,
    LGO_RAW_INTERFACE_BTN_ESSENTIALS,
    LGO_RAW_INTERFACE_BTN_MAP,
    LGO_RAW_INTERFACE_CONFIG_MAP,
    LGO_TOUCHPAD_AXIS_MAP,
    LGO_TOUCHPAD_BUTTON_MAP,
)
from .gyro_fix import GyroFixer
from .hid import RgbCallback

ERROR_DELAY = 1
SELECT_TIMEOUT = 1

logger = logging.getLogger(__name__)

LEN_VID = 0x17EF
LEN_PIDS = {
    0x6182: "xinput",
    0x6183: "dinput",
    0x6184: "dual_dinput",
    0x6185: "fps",
}


def plugin_run(
    conf: Config, emit: Emitter, context: Context, should_exit: TEvent, updated: TEvent
):
    # Remove leftover udev rules
    # unhide_all()
    if (gyro_fix := conf.get("gyro_fix", False)) and conf["gyro"].to(bool):
        gyro_fixer = GyroFixer(int(gyro_fix) if int(gyro_fix) > 10 else 100)
    else:
        gyro_fixer = None

    while not should_exit.is_set():
        try:
            controller_mode = None
            pid = None
            while not controller_mode:
                devs = enumerate_unique(LEN_VID)
                if not devs:
                    logger.error(
                        f"Legion go controllers not found, waiting {ERROR_DELAY}s."
                    )
                    time.sleep(ERROR_DELAY)
                    continue

                for d in devs:
                    if d["product_id"] in LEN_PIDS:
                        pid = d["product_id"]
                        controller_mode = LEN_PIDS[pid]
                        break
                else:
                    logger.error(
                        f"Legion go controllers not found, waiting {ERROR_DELAY}s."
                    )
                    time.sleep(ERROR_DELAY)
                    continue

            conf_copy = conf.copy()
            updated.clear()
            if (
                controller_mode == "xinput"
                and conf["xinput.mode"].to(str) != "disabled"
            ):
                logger.info("Launching emulated controller.")
                if gyro_fixer:
                    gyro_fixer.open()
                controller_loop_xinput(conf_copy, should_exit, updated)
            else:
                if controller_mode != "xinput":
                    logger.info(
                        f"Controllers in non-supported (yet) mode: {controller_mode}."
                    )
                else:
                    logger.info(
                        f"Controllers in xinput mode but emulation is disabled."
                    )
                controller_loop_rest(
                    controller_mode, pid if pid else 2, conf_copy, should_exit, updated
                )
        except Exception as e:
            logger.error(f"Received the following error:\n{type(e)}: {e}")
            logger.error(
                f"Assuming controllers disconnected, restarting after {ERROR_DELAY}s."
            )
            # Raise exception
            if conf.get("debug", False):
                raise e
            time.sleep(ERROR_DELAY)
        finally:
            if gyro_fixer:
                gyro_fixer.close()
            # Remove leftover udev rules
            # unhide_all()


def controller_loop_rest(
    mode: str, pid: int, conf: Config, should_exit: TEvent, updated: TEvent
):
    debug = conf.get("debug", False)
    shortcuts_enabled = conf["shortcuts"].to(bool)
    # FIXME: Sleep when shortcuts are disabled instead of polling raw interface
    if shortcuts_enabled:
        logger.info(f"Launching a shortcuts device.")
    else:
        logger.info(f"Shortcuts disabled. Waiting for controllers to change modes.")

    d_raw = SelectivePassthrough(
        GenericGamepadHidraw(
            vid=[LEN_VID],
            pid=list(LEN_PIDS),
            usage_page=[0xFFA0],
            usage=[0x0001],
            report_size=64,
            axis_map=LGO_RAW_INTERFACE_AXIS_MAP,
            btn_map=LGO_RAW_INTERFACE_BTN_MAP,
            required=True,
        )
    )

    multiplexer = Multiplexer(
        dpad="analog_to_discrete",
        trigger="analog_to_discrete",
        share_to_qam=conf["share_to_qam"].to(bool),
        nintendo_mode=conf["nintendo_mode"].to(bool),
    )
    d_uinput = UInputDevice(
        name=f"HHD Shortcuts (Legion Mode: {mode})",
        pid=HHD_PID_VENDOR | 0x0200 | (pid & 0xF),
        phys=f"phys-hhd-shortcuts-legion-{mode}",
    )

    d_shortcuts = GenericGamepadEvdev(
        vid=[LEN_VID],
        pid=list(LEN_PIDS),
        name=[re.compile(r"Legion-Controller \d-.. Keyboard")],
        capabilities={EC("EV_KEY"): [EC("KEY_1")]},
        required=True,
    )

    try:
        fds = []
        fds.extend(d_raw.open())
        if shortcuts_enabled:
            fds.extend(d_shortcuts.open())
            fds.extend(d_uinput.open())

        while not should_exit.is_set() and not updated.is_set():
            select.select(fds, [], [], SELECT_TIMEOUT)
            evs = multiplexer.process(d_raw.produce(fds))

            if shortcuts_enabled:
                d_shortcuts.produce(fds)
                d_uinput.produce(fds)
                if debug and evs:
                    logger.info(evs)
                d_uinput.consume(evs)
    finally:
        d_uinput.close(True)
        d_shortcuts.close(True)
        d_raw.close(True)


def controller_loop_xinput(conf: Config, should_exit: TEvent, updated: TEvent):
    debug = conf.get("debug", False)

    # Output
    motion = conf["accel"].to(bool) or conf["gyro"].to(bool)
    d_producers, d_outs, d_params = get_outputs(
        conf["xinput"], conf["touchpad"], motion
    )

    # Imu
    d_accel = AccelImu()
    # Legion go has a bit lower sensitivity than it should
    GYRO_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
        "anglvel_x": ("gyro_z", "anglvel", -conf["gyro_scaling"].to(int), None),
        "anglvel_y": ("gyro_x", "anglvel", conf["gyro_scaling"].to(int), None),
        "anglvel_z": ("gyro_y", "anglvel", conf["gyro_scaling"].to(int), None),
        "timestamp": ("gyro_ts", None, 1, None),
    }
    d_gyro = GyroImu(map=GYRO_MAPPINGS, legion_fix=True)

    # Inputs
    d_xinput = GenericGamepadEvdev(
        vid=[0x17EF],
        pid=[0x6182],
        # name=["Generic X-Box pad"],
        capabilities={EC("EV_KEY"): [EC("BTN_A")]},
        required=True,
        hide=True,
    )
    d_touch = GenericGamepadEvdev(
        vid=[0x17EF],
        pid=[0x6182],
        name=[re.compile(".+Touchpad")],  # "  Legion Controller for Windows  Touchpad"
        capabilities={EC("EV_KEY"): [EC("BTN_MOUSE")]},
        btn_map=LGO_TOUCHPAD_BUTTON_MAP,
        axis_map=LGO_TOUCHPAD_AXIS_MAP,
        aspect_ratio=1,
        required=True,
    )
    d_raw = SelectivePassthrough(
        GenericGamepadHidraw(
            vid=[LEN_VID],
            pid=list(LEN_PIDS),
            usage_page=[0xFFA0],
            usage=[0x0001],
            report_size=64,
            axis_map=LGO_RAW_INTERFACE_AXIS_MAP,
            btn_map=LGO_RAW_INTERFACE_BTN_MAP,
            config_map=LGO_RAW_INTERFACE_CONFIG_MAP,
            callback=RgbCallback(),
            required=True,
        )
    )
    # Mute keyboard shortcuts, mute
    d_shortcuts = GenericGamepadEvdev(
        vid=[LEN_VID],
        pid=list(LEN_PIDS),
        name=[re.compile(".+Keyboard")],  # "  Legion Controller for Windows  Keyboard"
        # capabilities={EC("EV_KEY"): [EC("KEY_1")]},
        # report_size=64,
        required=True,
    )

    match conf["swap_legion"].to(str):
        case "disabled":
            swap_guide = None
        case "l_is_start":
            swap_guide = "guide_is_start"
        case "l_is_select":
            swap_guide = "guide_is_select"
        case val:
            assert False, f"Invalid value for `swap_legion`: {val}"

    touch_actions = (
        conf["touchpad.controller"]
        if conf["touchpad.mode"].to(TouchpadAction) == "controller"
        else conf["touchpad.emulation"]
    )

    multiplexer = Multiplexer(
        swap_guide=swap_guide,
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        led="main_to_sides",
        status="both_to_main",
        share_to_qam=conf["share_to_qam"].to(bool),
        touchpad_short=touch_actions["short"].to(TouchpadAction),
        touchpad_right=touch_actions["hold"].to(TouchpadAction),
        select_reboots=conf["select_reboots"].to(bool),
        r3_to_share=conf["m2_to_mute"].to(bool),
        nintendo_mode=conf["nintendo_mode"].to(bool),
    )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 400

    REPORT_DELAY_MAX = 1 / REPORT_FREQ_MIN
    REPORT_DELAY_MIN = 1 / REPORT_FREQ_MAX

    fds = []
    devs = []
    fd_to_dev = {}

    def prepare(m):
        devs.append(m)
        fs = m.open()
        fds.extend(fs)
        for f in fs:
            fd_to_dev[f] = m

    try:
        prepare(d_xinput)
        if conf.get("accel", False):
            prepare(d_accel)
        if conf.get("gyro", False):
            prepare(d_gyro)
        prepare(d_shortcuts)
        if d_params["uses_touch"]:
            prepare(d_touch)
        prepare(d_raw)
        for d in d_producers:
            prepare(d)

        logger.info("Emulated controller launched, have fun!")
        while not should_exit.is_set() and not updated.is_set():
            start = time.perf_counter()
            # Add timeout to call consumers a minimum amount of times per second
            r, _, _ = select.select(fds, [], [], REPORT_DELAY_MAX)
            evs = []
            to_run = set()
            for f in r:
                to_run.add(id(fd_to_dev[f]))

            for d in devs:
                if id(d) in to_run:
                    evs.extend(d.produce(r))

            evs = multiplexer.process(evs)
            if evs:
                if debug:
                    logger.info(evs)

                d_xinput.consume(evs)
                d_raw.consume(evs)

            for d in d_outs:
                d.consume(evs)

            t = time.perf_counter()
            elapsed = t - start
            if elapsed < REPORT_DELAY_MIN:
                time.sleep(REPORT_DELAY_MIN - elapsed)

    except KeyboardInterrupt:
        raise
    finally:
        for d in reversed(devs):
            d.close(True)


class SelectivePassthrough(Producer, Consumer):
    def __init__(
        self,
        parent,
        forward_buttons: Sequence[Button] = ("share", "mode"),
        passthrough: Sequence[Button] = list(
            next(iter(LGO_RAW_INTERFACE_BTN_ESSENTIALS.values()))
        ),
    ):
        self.parent = parent
        self.state = False

        self.forward_buttons = forward_buttons
        self.passthrough = passthrough

        self.to_disable_btn = set()
        self.to_disable_axis = set()

    def open(self) -> Sequence[int]:
        return self.parent.open()

    def close(self, exit: bool) -> bool:
        return self.parent.close(exit)

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        evs: Sequence[Event] = self.parent.produce(fds)

        out = []
        prev_state = self.state
        for ev in evs:
            if ev["type"] == "button" and ev["code"] in self.forward_buttons:
                self.state = ev.get("value", False)

            if ev["type"] == "configuration":
                out.append(ev)
            elif ev["type"] == "button" and ev["code"] in self.passthrough:
                out.append(ev)
            elif ev["type"] == "button" and self.state:
                self.to_disable_btn.add(ev["code"])
            elif ev["type"] == "axis" and self.state:
                self.to_disable_axis.add(ev["code"])

        if self.state:
            # If mode is pressed, forward all events
            return evs
        elif prev_state:
            # If prev_state, meaning the user released the mode or share button
            # turn off all buttons that were pressed during it
            for btn in self.to_disable_btn:
                out.append({"type": "button", "code": btn, "value": False})
            self.to_disable_btn = set()
            for axis in self.to_disable_axis:
                out.append({"type": "axis", "code": axis, "value": 0})
            self.to_disable_axis = set()
            return out
        else:
            # Otherwise, just return the standard buttons
            return out

    def consume(self, events: Sequence[Event]):
        return self.parent.consume(events)
