import logging
import re
import select
import time
from threading import Event as TEvent
from typing import Sequence

import evdev

from hhd.controller import Axis, Event, Multiplexer, can_read
from hhd.controller.base import Event, TouchpadAction
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.controller.virtual.uinput import UInputDevice
from hhd.plugins import Config, Context, Emitter, get_outputs

from .const import (
    AYANEO_TOUCHPAD_AXIS_MAP,
    AYANEO_TOUCHPAD_BUTTON_MAP,
    AYANEO_DEFAULT_MAPPINGS,
)

ERROR_DELAY = 1
SELECT_TIMEOUT = 1

logger = logging.getLogger(__name__)

from .const import (
    AYANEO_DEFAULT_MAPPINGS,
)

GAMEPAD_VID = 0x045E
GAMEPAD_PID = 0x028E

KBD_VID = 0x0001
KBD_PID = 0x0001

BACK_BUTTON_DELAY = 0.1


def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
):
    first = True
    while not should_exit.is_set():
        found_gamepad = False
        try:
            for d in evdev.list_devices():
                dev = evdev.InputDevice(d)
                if dev.info.vendor == GAMEPAD_VID and dev.info.product == GAMEPAD_PID:
                    found_gamepad = True
                    break
        except Exception:
            logger.warning("Failed finding device, skipping check.")
            found_gamepad = True

        if not found_gamepad:
            time.sleep(ERROR_DELAY)
            if first:
                logger.info("Controller in Mouse mode. Waiting...")
            first = False
            continue

        try:
            logger.info("Launching emulated controller.")
            updated.clear()
            controller_loop(conf.copy(), should_exit, updated, dconf)
        except Exception as e:
            logger.error(f"Received the following error:\n{type(e)}: {e}")
            logger.error(
                f"Assuming controllers disconnected, restarting after {ERROR_DELAY}s."
            )
            first = True
            # Raise exception
            if conf.get("debug", False):
                raise e
            time.sleep(ERROR_DELAY)


def controller_loop(conf: Config, should_exit: TEvent, updated: TEvent, dconf: dict):
    debug = conf.get("debug", False)
    has_touchpad = "touchpad" in conf

    # Output
    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        conf["touchpad"] if has_touchpad else None,
        conf["imu"].to(bool),
    )

    # Imu
    d_imu = CombinedImu(
        conf["imu_hz"].to(int),
        dconf.get("mapping", AYANEO_DEFAULT_MAPPINGS),
        # gyro_scale="0.000266", #TODO: Find what this affects
    )
    d_timer = HrtimerTrigger(conf["imu_hz"].to(int), [HrtimerTrigger.IMU_NAMES])

    # Inputs
    d_xinput = GenericGamepadEvdev(
        vid=[GAMEPAD_VID],
        pid=[GAMEPAD_PID],
        # name=["Generic X-Box pad"],
        capabilities={EC("EV_KEY"): [EC("BTN_A")]},
        required=True,
        hide=True,
    )

    # d_touch = GenericGamepadEvdev(
    #     vid=[TOUCHPAD_VID, TOUCHPAD_VID_2],
    #     pid=[TOUCHPAD_PID, TOUCHPAD_PID_2],
    #     name=[re.compile(".+Touchpad")],
    #     capabilities={EC("EV_KEY"): [EC("BTN_MOUSE")]},
    #     btn_map=AYANEO_TOUCHPAD_BUTTON_MAP,
    #     axis_map=AYANEO_TOUCHPAD_AXIS_MAP,
    #     aspect_ratio=1.333,
    #     required=False,
    # )

    d_kbd_1 = GenericGamepadEvdev(
        vid=[KBD_VID],
        pid=[KBD_PID],
        required=False,
        grab=True,
        btn_map={
            EC("KEY_F15"): "extra_l1",
            EC("KEY_F16"): "extra_r1",
            EC("KEY_F17"): "mode",
            EC("KEY_D"): "share",
            EC("KEY_VOLUMEUP"): "key_volumeup",
            EC("KEY_VOLUMEDOWN"): "key_volumedown",
        },
    )

    if has_touchpad:
        touch_actions = (
            conf["touchpad.controller"]
            if conf["touchpad.mode"].to(TouchpadAction) == "controller"
            else conf["touchpad.emulation"]
        )

        multiplexer = Multiplexer(
            trigger="analog_to_discrete",
            dpad="analog_to_discrete",
            share_to_qam=conf["share_to_qam"].to(bool),
            touchpad_short=touch_actions["short"].to(TouchpadAction),
            touchpad_hold=touch_actions["hold"].to(TouchpadAction),
            nintendo_mode=conf["nintendo_mode"].to(bool),
        )
    else:
        multiplexer = Multiplexer(
            trigger="analog_to_discrete",
            dpad="analog_to_discrete",
            share_to_qam=conf["share_to_qam"].to(bool),
            nintendo_mode=conf["nintendo_mode"].to(bool),
        )

    d_volume_btn = UInputDevice(
        name="Handheld Daemon Volume Keyboard (Ayaneo)",
        phys="phys-hhd-ayaneo-vbtn",
        capabilities={EC("EV_KEY"): [EC("KEY_VOLUMEUP"), EC("KEY_VOLUMEDOWN")]},
        btn_map={
            "key_volumeup": EC("KEY_VOLUMEUP"),
            "key_volumedown": EC("KEY_VOLUMEDOWN"),
        },
        pid=KBD_PID,
        vid=KBD_VID,
        output_timestamps=True,
    )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 400

    if conf["imu"].to(bool):
        REPORT_FREQ_MAX = max(REPORT_FREQ_MAX, conf["imu_hz"].to(float))

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
        # d_vend.open()
        prepare(d_xinput)
        if conf.get("imu", False):
            start_imu = True
            if dconf.get("hrtimer", False):
                start_imu = d_timer.open()
            if start_imu:
                prepare(d_imu)
        # if has_touchpad and d_params["uses_touch"]:
        #     prepare(d_touch)
        prepare(d_volume_btn)
        prepare(d_kbd_1)
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

                d_volume_btn.consume(evs)
                d_xinput.consume(evs)

            for d in d_outs:
                d.consume(evs)

            # If unbounded, the total number of events per second is the sum of all
            # events generated by the producers.
            # For Legion go, that would be 100 + 100 + 500 + 30 = 730
            # Since the controllers of the legion go only update at 500hz, this is
            # wasteful.
            # By setting a target refresh rate for the report and sleeping at the
            # end, we ensure that even if multiple fds become ready close to each other
            # they are combined to the same report, limiting resource use.
            # Ideally, this rate is smaller than the report rate of the hardware controller
            # to ensure there is always a report from that ready during refresh
            t = time.perf_counter()
            elapsed = t - start
            if elapsed < REPORT_DELAY_MIN:
                time.sleep(REPORT_DELAY_MIN - elapsed)

    except KeyboardInterrupt:
        raise
    finally:
        # d_vend.close(True)
        d_timer.close()
        for d in reversed(devs):
            d.close(True)
