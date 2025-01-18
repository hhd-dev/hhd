import logging
import re
import select
import time
from threading import Event as TEvent
from typing import Sequence

from hhd.controller import Button, Consumer, Event, Producer, DEBUG_MODE
from hhd.controller.lib.hide import unhide_all
from hhd.controller.base import Multiplexer
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev, enumerate_evs
from hhd.controller.virtual.uinput import HHD_PID_VENDOR, UInputDevice
from hhd.plugins import Config, Context, Emitter, get_outputs

from .const import (
    GOS_INTERFACE_AXIS_MAP,
    GOS_INTERFACE_BTN_ESSENTIALS,
    GOS_INTERFACE_BTN_MAP,
)
from .hid import LegionHidraw, RgbCallback

FIND_DELAY = 0.1
ERROR_DELAY = 0.5
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3
SELECT_TIMEOUT = 1

logger = logging.getLogger(__name__)

GOS_VID = 0x1A86
GOS_XINPUT = 0xE310
GOS_PIDS = {
    GOS_XINPUT: "xinput",
    0xE311: "dinput",
}


def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    others: dict,
):
    reset = others.get("reset", False)
    init = time.perf_counter()
    repeated_fail = False

    while not should_exit.is_set():
        try:
            controller_mode = None
            pid = None
            first = True
            while not controller_mode and not should_exit.is_set():
                devs = enumerate_evs(vid=GOS_VID)
                if not devs:
                    if first:
                        first = False
                        logger.warning(f"Legion Go S controller not found, waiting...")
                    time.sleep(FIND_DELAY)
                    continue

                for d in devs.values():
                    if d.get("product", None) in GOS_PIDS:
                        pid = d["product"]
                        controller_mode = GOS_PIDS[pid]
                        break
                else:
                    logger.error(
                        f"Legion Go S controller not found, waiting {ERROR_DELAY}s."
                    )
                    time.sleep(ERROR_DELAY)
                    continue

            if not controller_mode:
                # If should_exit was set controller_mode will be null
                continue

            conf_copy = conf.copy()
            updated.clear()
            if (
                controller_mode == "xinput"
                and conf["xinput.mode"].to(str) != "disabled"
            ):
                logger.info("Launching emulated controller.")
                init = time.perf_counter()
                controller_loop_xinput(conf_copy, should_exit, updated, emit, reset)
            else:
                if controller_mode != "xinput":
                    logger.info(
                        f"Controller in non-supported (yet) mode: {controller_mode}."
                    )
                else:
                    logger.info(f"Controller in xinput mode but emulation is disabled.")
                init = time.perf_counter()
                controller_loop_rest(
                    pid if pid else 2,
                    conf_copy,
                    should_exit,
                    updated,
                    emit,
                    reset,
                )
            repeated_fail = False
        except Exception as e:
            failed_fast = init + LONGER_ERROR_MARGIN > time.perf_counter()
            sleep_time = (
                LONGER_ERROR_DELAY if repeated_fail and failed_fast else ERROR_DELAY
            )
            repeated_fail = failed_fast
            logger.error(f"Received the following error:\n{type(e)}: {e}")
            logger.error(
                f"Assuming controller disconnected, restarting after {sleep_time}s."
            )
            # Raise exception
            if DEBUG_MODE:
                try:
                    import traceback

                    traceback.print_exc()
                except Exception:
                    pass
            time.sleep(sleep_time)
        reset = False

    # Unhide all devices before exiting
    unhide_all()


def controller_loop_rest(
    pid: int,
    conf: Config,
    should_exit: TEvent,
    updated: TEvent,
    emit: Emitter,
    reset: bool,
):
    debug = DEBUG_MODE
    shortcuts_enabled = conf["shortcuts"].to(bool)
    # FIXME: Sleep when shortcuts are disabled instead of polling raw interface
    if shortcuts_enabled:
        logger.info(f"Launching a shortcuts device.")
    else:
        logger.info(f"Shortcuts disabled. Waiting for controllers to change modes.")

    d_raw = SelectivePassthrough(
        LegionHidraw(
            vid=[GOS_VID],
            pid=list(GOS_PIDS),
            usage_page=[0xFFA0],
            usage=[0x0001],
            report_size=64,
            interface=6,
            axis_map={None: GOS_INTERFACE_AXIS_MAP},
            btn_map={None: GOS_INTERFACE_BTN_MAP},
            required=True,
        ).with_settings(reset=reset),
        passthrough_pressed=True,
    )

    multiplexer = Multiplexer(
        dpad="both",
        trigger="analog_to_discrete",
        share_to_qam=True,
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
    )
    d_uinput = UInputDevice(
        name=f"HHD Shortcuts (Legion Mode: dinput)",
        pid=HHD_PID_VENDOR | 0x0200 | (pid & 0xF),
        phys=f"phys-hhd-shortcuts-gos",
    )

    d_shortcuts = GenericGamepadEvdev(
        vid=[GOS_VID],
        pid=list(GOS_PIDS),
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


def controller_loop_xinput(
    conf: Config, should_exit: TEvent, updated: TEvent, emit: Emitter, reset: bool
):
    debug = DEBUG_MODE

    # Output

    d_producers, d_outs, d_params = get_outputs(
        conf["xinput"],
        None,
        conf["imu"].to(bool),
        emit=emit,
        rgb_modes={
            "disabled": [],
            "solid": ["color"],
            "pulse": ["color", "speed"],
            "rainbow": ["brightness", "speed"],
            "spiral": ["brightness", "speed"],
        },
    )
    swap_legion = conf["swap_legion"].to(bool)

    # Inputs
    d_xinput = GenericGamepadEvdev(
        vid=[GOS_VID],
        pid=[GOS_XINPUT],
        # name=["Generic X-Box pad"],
        capabilities={EC("EV_KEY"): [EC("BTN_A")]},
        required=True,
        hide=True,
    )
    d_raw = SelectivePassthrough(
        LegionHidraw(
            vid=[GOS_VID],
            pid=list(GOS_PIDS),
            usage_page=[0xFFA0],
            usage=[0x0001],
            report_size=64,
            interface=6,
            axis_map={None: GOS_INTERFACE_AXIS_MAP},
            btn_map={None: GOS_INTERFACE_BTN_MAP},
            callback=RgbCallback(),
            required=True,
        ).with_settings(
            reset=reset,
        )
    )

    # Mute keyboard shortcuts, mute
    d_shortcuts = GenericGamepadEvdev(
        vid=[GOS_VID],
        pid=list(GOS_PIDS),
        name=[re.compile(".+Keyboard")],  # "  Legion Controller for Windows  Keyboard"
        # capabilities={EC("EV_KEY"): [EC("KEY_1")]},
        # report_size=64,
        required=True,
    )

    multiplexer = Multiplexer(
        trigger="analog_to_discrete",
        dpad="both",
        share_to_qam=True,
        swap_guide="guide_is_select" if swap_legion else None,
        select_reboots=conf["select_reboots"].to(bool),
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        params=d_params,
    )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 500

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
        prepare(d_shortcuts)
        prepare(d_raw)
        for d in d_producers:
            prepare(d)

        ts_count: dict[str, int] = {"left_imu_ts": 0, "right_imu_ts": 0}
        ts_last: dict[str, int] = {"left_imu_ts": 0, "right_imu_ts": 0}

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

            for ev in evs:
                if ev["type"] == "axis" and "_imu_ts" in ev["code"]:
                    # Find diff between previous event
                    last = ts_last[ev["code"]]
                    curr = ev["value"]
                    diff = curr - last
                    if curr < last:
                        diff += 256
                    ts_last[ev["code"]] = curr
                    # 8ms per count
                    ts_count[ev["code"]] += diff * 8_000_000
                    ev["value"] = ts_count[ev["code"]]
                if ev["type"] == "axis" and "gyro" in ev["code"]:
                    v = ev["value"]
                    if (abs(v / 0.001065) // 1) in (254, 255):
                        # Legion go controllers have a bug where they will
                        # randomly output 254 or 255. If that happens, drop event
                        ev["code"] = ""  # type: ignore

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
            try:
                d.close(not updated.is_set())
            except Exception as e:
                logger.error(f"Error while closing device '{d}' with exception:\n{e}")
                if debug:
                    raise e


class SelectivePassthrough(Producer, Consumer):

    def __init__(
        self,
        parent,
        forward_buttons: Sequence[Button] = ("share", "mode"),
        passthrough: Sequence[Button] = list(GOS_INTERFACE_BTN_ESSENTIALS.keys()),
        passthrough_pressed: bool = False,
    ):
        self.parent = parent
        self.state = False

        self.forward_buttons = forward_buttons
        self.passthrough = passthrough
        self.pressed_time = None
        self.pressed_vals = set()
        self.passthrough_pressed = passthrough_pressed

        self.to_disable_btn = set()
        self.to_disable_axis = set()

    def open(self) -> Sequence[int]:
        return self.parent.open()

    def close(self, exit: bool) -> bool:
        return self.parent.close(exit)

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        evs: Sequence[Event] = self.parent.produce(fds)

        out = []
        curr = time.perf_counter()
        if self.passthrough_pressed:
            passthrough = bool(self.pressed_vals)
        else:
            passthrough = self.pressed_time and (curr - self.pressed_time < 1)

        for ev in evs:
            if ev["type"] == "button" and ev["code"] in self.forward_buttons:
                if ev.get("value", False):
                    self.pressed_time = curr
                    self.pressed_vals.add(ev["code"])
                else:
                    self.pressed_vals.discard(ev["code"])

            if ev["type"] == "button" and ev["code"] in self.passthrough:
                out.append(ev)
            elif ev["type"] == "axis" and (
                "imu" in ev["code"] or "accel" in ev["code"] or "gyro" in ev["code"]
            ):
                out.append(ev)

        if passthrough:
            # If mode is pressed, forward all events
            return evs
        else:
            return out

    def consume(self, events: Sequence[Event]):
        return self.parent.consume(events)
