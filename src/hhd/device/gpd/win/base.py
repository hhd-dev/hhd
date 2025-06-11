import logging
import re
import select
import time
from threading import Event as TEvent
from typing import Sequence

import evdev

from hhd.controller import DEBUG_MODE, Event, Multiplexer, can_read
from hhd.controller.base import Event
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.plugins import Config, Context, Emitter, get_gyro_state, get_outputs

from .const import (
    GPD_TOUCHPAD_AXIS_MAP,
    GPD_TOUCHPAD_BUTTON_MAP,
    GPD_WIN_DEFAULT_MAPPINGS,
)

ERROR_DELAY = 0.3
SELECT_TIMEOUT = 1
ERROR_DELAY = 0.3
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3

logger = logging.getLogger(__name__)

# Old devices were 2f24:0135
# New 2025 Win mini uses 045e:002d
GPD_WIN_VIDS = [0x2F24, 0x045e]
GPD_WIN_PIDS = [0x0135, 0x002d]
GAMEPAD_VID = 0x045E
GAMEPAD_PID = 0x028E

# Win Max 2
TOUCHPAD_VID = 0x093A
TOUCHPAD_PID = 0x0255
# Win Minis
TOUCHPAD_VID_2 = 0x0911
TOUCHPAD_PID_2 = 0x5288

BACK_BUTTON_DELAY = 0.025

# /dev/input/event17 Microsoft X-Box 360 pad usb-0000:73:00.3-4.1/input0
# bus: 0003, vendor 045e, product 028e, version 0101

# back buttons
# /dev/input/event15   Mouse for Windows usb-0000:73:00.3-4.2/input1
# bus: 0003, vendor 2f24, product 0135, version 0110

# physical keyboard
# /dev/input/event13   Mouse for Windows usb-0000:73:00.3-4.2/input0
# bus: 0003, vendor 2f24, product 0135, version 0110

# hidraw back buttons  {'path': b'/dev/hidraw6',
#    'vendor_id': 12068, 'product_id': 309, 'serial_number': '',
#    'release_number': 256, 'manufacturer_string': ' ',
#    'product_string': 'Mouse for Windows',
#    'usage_page': 1, 'usage': 6, 'interface_number': 1},

LEFT_BUTTONS = {
    EC("KEY_SYSRQ"),
    EC("KEY_F20"),
}

RIGHT_BUTTONS = {
    EC("KEY_PAUSE"),
    EC("KEY_F21"),
}


class BackbuttonsEvdev(GenericGamepadEvdev):
    def __init__(self, *args, **kwargs) -> None:
        self.left_pressed = False
        self.left_released = None
        self.right_pressed = False
        self.right_released = None
        super().__init__(*args, **kwargs)

    def produce(self, fds: Sequence[int]):
        if not self.dev:
            return []

        # GPD events execute micro sequences
        # Inbetween the sequences, there is a ~20ms gap in which the
        # button is not pressed. Therefore, record when the button was
        # pressed and if more than ~25ms has passed, consider it released.
        curr = time.perf_counter()
        out = []
        while self.fd in fds and can_read(self.dev):
            for e in self.dev.read():
                if e.type != EC("EV_KEY"):
                    continue

                pressed = e.value != 0

                if e.code in LEFT_BUTTONS:
                    if pressed:
                        if not self.left_pressed:
                            out.append(
                                {"type": "button", "code": "extra_l1", "value": True}
                            )
                        self.left_pressed = True
                        self.left_released = None
                    else:
                        self.left_released = curr
                if e.code in RIGHT_BUTTONS:
                    if pressed:
                        if not self.right_pressed:
                            out.append(
                                {
                                    "type": "button",
                                    "code": "extra_r1",
                                    "value": True,
                                }
                            )
                        self.right_pressed = True
                        self.right_released = None
                    else:
                        self.right_released = curr

        if self.left_released and curr - self.left_released > BACK_BUTTON_DELAY:
            out.append({"type": "button", "code": "extra_l1", "value": False})
            self.left_released = None
            self.left_pressed = False
        if self.right_released and curr - self.right_released > BACK_BUTTON_DELAY:
            out.append({"type": "button", "code": "extra_r1", "value": False})
            self.right_released = None
            self.right_pressed = False

        return out


def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
):
    first = True
    first_disabled = True
    init = time.perf_counter()
    repeated_fail = False
    while not should_exit.is_set():
        if conf["controller_mode.mode"].to(str) == "disabled":
            time.sleep(ERROR_DELAY)
            if first_disabled:
                unhide_all()
            first_disabled = False
            continue
        else:
            first_disabled = True

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
            if first:
                logger.info("Controller in Mouse mode. Waiting...")
            time.sleep(ERROR_DELAY)
            first = False
            continue

        try:
            logger.info("Launching emulated controller.")
            updated.clear()
            init = time.perf_counter()
            controller_loop(conf.copy(), should_exit, updated, dconf, emit)
            repeated_fail = False
        except Exception as e:
            failed_fast = init + LONGER_ERROR_MARGIN > time.perf_counter()
            sleep_time = (
                LONGER_ERROR_DELAY if repeated_fail and failed_fast else ERROR_DELAY
            )
            repeated_fail = failed_fast
            logger.exception(
                f"Assuming controllers disconnected, restarting after {sleep_time}s."
            )
            # Raise exception
            if DEBUG_MODE:
                import traceback
                logger.error(traceback.format_exc())
            time.sleep(sleep_time)

    # Unhide all devices before exiting
    unhide_all()


def controller_loop(
    conf: Config, should_exit: TEvent, updated: TEvent, dconf: dict, emit: Emitter
):
    debug = DEBUG_MODE
    has_touchpad = dconf.get("touchpad", False)

    # Output
    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        conf["touchpad"] if has_touchpad else None,
        conf["imu"].to(bool),
        emit=emit,
    )
    motion = d_params.get("uses_motion", True)

    # Imu
    d_imu = CombinedImu(
        conf["imu_hz"].to(int),
        get_gyro_state(
            conf["imu_axis"], dconf.get("mapping", GPD_WIN_DEFAULT_MAPPINGS)
        ),
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

    # "PNP0C50:00 0911:5288 Touchpad" on Win Max 2 2023
    # "PNP0C50:00 093A:0255 Touchpad" on Win Mini
    d_touch = GenericGamepadEvdev(
        vid=[TOUCHPAD_VID, TOUCHPAD_VID_2],
        pid=[TOUCHPAD_PID, TOUCHPAD_PID_2],
        name=[re.compile(".+Touchpad")],
        capabilities={EC("EV_KEY"): [EC("BTN_MOUSE")]},
        btn_map=GPD_TOUCHPAD_BUTTON_MAP,
        axis_map=GPD_TOUCHPAD_AXIS_MAP,
        aspect_ratio=1.333,
        required=False,
    )

    # Vendor
    d_kbd_1 = BackbuttonsEvdev(
        vid=GPD_WIN_VIDS,
        pid=GPD_WIN_PIDS,
        capabilities={EC("EV_KEY"): [EC("KEY_SYSRQ"), EC("KEY_PAUSE")]},
        required=True,
        grab=True,
        # btn_map={EC("KEY_SYSRQ"): "extra_l1", EC("KEY_PAUSE"): "extra_r1"},
    )

    match conf["l4r4"].to(str):
        case "l4":
            qam_button = "extra_l1"
            l4r4_enabled = True
            qam_hold = "hhd"
        case "r4":
            qam_button = "extra_r1"
            l4r4_enabled = True
            qam_hold = "hhd"
        case "menu":
            qam_button = "mode"
            l4r4_enabled = True
            qam_hold = "mode"
        case "disabled":
            qam_button = None
            l4r4_enabled = False
            qam_hold = "hhd"
        case _:
            qam_button = None
            l4r4_enabled = True
            qam_hold = "hhd"

    if has_touchpad:
        touch_actions = (
            conf["touchpad.controller"]
            if conf.get("touchpad.mode", None) == "controller"
            else conf["touchpad.emulation"]
        )

        multiplexer = Multiplexer(
            trigger="analog_to_discrete",
            dpad="analog_to_discrete",
            touchpad_short=touch_actions.get("short", "disabled"),
            touchpad_hold=touch_actions.get("hold", "disabled"),
            nintendo_mode=conf["nintendo_mode"].to(bool),
            qam_button=qam_button,
            emit=emit,
            params=d_params,
            # qam_multi_tap=qam_multi_tap, # supports it now
            qam_hold=qam_hold,
            startselect_chord=conf.get("main_chords", "disabled"),
        )
    else:
        multiplexer = Multiplexer(
            trigger="analog_to_discrete",
            dpad="analog_to_discrete",
            nintendo_mode=conf["nintendo_mode"].to(bool),
            qam_button=qam_button,
            emit=emit,
            params=d_params,
            # qam_multi_tap=qam_multi_tap, # supports it now
            qam_hold=qam_hold,
            startselect_chord=conf.get("main_chords", "disabled"),
        )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 400

    if motion:
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
        if l4r4_enabled:
            kbd_fds = d_kbd_1.open()
            fds.extend(kbd_fds)
        else:
            kbd_fds = []
        prepare(d_xinput)
        if motion:
            start_imu = True
            if dconf.get("hrtimer", False):
                start_imu = d_timer.open()
            if start_imu:
                prepare(d_imu)
        if has_touchpad and d_params["uses_touch"]:
            prepare(d_touch)
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
                # skip kbd_1 to always run it
                if f not in kbd_fds:
                    to_run.add(id(fd_to_dev[f]))

            for d in devs:
                if id(d) in to_run:
                    evs.extend(d.produce(r))
            evs.extend(d_kbd_1.produce(r))

            evs = multiplexer.process(evs)
            if evs:
                if debug:
                    logger.info(evs)
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
        try:
            d_kbd_1.close(not updated.is_set())
        except Exception as e:
            logger.error(f"Error while closing device '{d}' with exception:\n{e}")
            if debug:
                raise e
        try:
            d_timer.close()
        except Exception as e:
            logger.error(f"Error while closing device '{d}' with exception:\n{e}")
            if debug:
                raise e
        for d in reversed(devs):
            try:
                d.close(not updated.is_set())
            except Exception as e:
                logger.error(f"Error while closing device '{d}' with exception:\n{e}")
                if debug:
                    raise e
