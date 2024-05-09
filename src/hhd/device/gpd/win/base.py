import logging
import re
import select
import time
from threading import Event as TEvent
from typing import Sequence

import evdev

from hhd.controller import DEBUG_MODE, Event, Multiplexer, can_read
from hhd.controller.base import Event, TouchpadAction
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

GPD_WIN_4_VID = 0x2F24
GPD_WIN_4_PID = 0x0135
GAMEPAD_VID = 0x045E
GAMEPAD_PID = 0x028E

TOUCHPAD_VID = 0x093A
TOUCHPAD_PID = 0x0255
TOUCHPAD_VID_2 = 0x0911
TOUCHPAD_PID_2 = 0x5288

BACK_BUTTON_DELAY = 0.07

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


class GpdWin4Hidraw(GenericGamepadHidraw):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

    def open(self) -> Sequence[int]:
        self.left_pressed = None
        self.right_pressed = None
        self.last_pressed = None
        self.clear_ts = None

        self.queue: list[tuple[Event, float]] = []
        return super().open()

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        # If we can not read return
        if not self.fd or not self.dev:
            return []

        # Process events
        curr = time.perf_counter()
        out: Sequence[Event] = []

        # Read new events
        left_pressed = None
        right_pressed = None
        while can_read(self.fd):
            rep = self.dev.read(self.report_size)

            # l4 = 0x46
            # r4 = 0x48
            # both = l4 + r4
            # when both l4/r4 held, rep[2] and rep[3] will both be active
            #   they will be the same known values for l4 and r4
            #   but the order is not guaranteed to be consistent
            check = rep[2] + rep[3]
            match check:
                case 0x46:
                    # action = "left/l4"
                    left_pressed = True
                    self.last_pressed = "left"
                    self.clear_ts = None
                case 0x48:
                    # action = "right/r4"
                    right_pressed = True
                    self.last_pressed = "right"
                    self.clear_ts = None
                case 0x8E:
                    # both l4 and r4 are being pressed
                    left_pressed = True
                    right_pressed = True
                    self.clear_ts = None
                case _:  # 0x00:
                    # This occurs only when one button is pressed
                    # So in case both are remove one
                    if self.last_pressed == "right" and self.left_pressed:
                        left_pressed = False
                    if self.last_pressed == "left" and self.right_pressed:
                        right_pressed = False
                    self.clear_ts = curr + BACK_BUTTON_DELAY

        if self.clear_ts and self.clear_ts < curr:
            # Reset after timeout
            if self.left_pressed:
                out.append({"type": "button", "code": "extra_l1", "value": False})
                self.left_pressed = False
            if self.right_pressed:
                out.append({"type": "button", "code": "extra_r1", "value": False})
                self.right_pressed = False
            self.clear_ts = None
        else:
            # If no timeout, update
            # Left, right will be none if no events were received
            # If they were, they will be true/false
            # If that conflicts with the saved values, send events.
            if left_pressed is not None and self.left_pressed != left_pressed:
                out.append(
                    {"type": "button", "code": "extra_l1", "value": left_pressed}
                )
                self.left_pressed = left_pressed

            if right_pressed is not None and self.right_pressed != right_pressed:
                out.append(
                    {"type": "button", "code": "extra_r1", "value": right_pressed}
                )
                self.right_pressed = right_pressed
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
    init = time.perf_counter()
    repeated_fail = False
    while not should_exit.is_set():
        if conf["controller_mode.mode"].to(str) == "disabled":
            time.sleep(ERROR_DELAY)
            continue

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
            logger.error(f"Received the following error:\n{type(e)}: {e}")
            logger.error(
                f"Assuming controllers disconnected, restarting after {sleep_time}s."
            )
            # Raise exception
            if DEBUG_MODE:
                raise e
            time.sleep(sleep_time)


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
    d_vend = GpdWin4Hidraw(
        vid=[GPD_WIN_4_VID],
        pid=[GPD_WIN_4_PID],
        usage_page=[0x0001],
        usage=[0x0006],
        required=True,
    )

    d_kbd_1 = GenericGamepadEvdev(
        vid=[GPD_WIN_4_VID],
        pid=[GPD_WIN_4_PID],
        # TODO: Verify capability check does not cause regressions
        capabilities={EC("EV_KEY"): [EC("KEY_SYSRQ"), EC("KEY_PAUSE")]},
        required=False,
        grab=True,
        # btn_map={EC("KEY_SYSRQ"): "extra_l1", EC("KEY_PAUSE"): "extra_r1"},
    )

    match conf["l4r4"].to(str):
        case "l4":
            qam_button = "extra_l1"
            l4r4_enabled = True
        case "r4":
            qam_button = "extra_r1"
            l4r4_enabled = True
        case "disabled":
            qam_button = None
            l4r4_enabled = False
        case _:
            qam_button = None
            l4r4_enabled = True

    if has_touchpad:
        touch_actions = (
            conf["touchpad.controller"]
            if conf["touchpad.mode"].to(TouchpadAction) == "controller"
            else conf["touchpad.emulation"]
        )

        multiplexer = Multiplexer(
            trigger="analog_to_discrete",
            dpad="analog_to_discrete",
            touchpad_short=touch_actions["short"].to(TouchpadAction),
            touchpad_hold=touch_actions["hold"].to(TouchpadAction),
            nintendo_mode=conf["nintendo_mode"].to(bool),
            qam_button=qam_button,
            emit=emit,
            params=d_params,
            qam_multi_tap=False,
        )
    else:
        multiplexer = Multiplexer(
            trigger="analog_to_discrete",
            dpad="analog_to_discrete",
            nintendo_mode=conf["nintendo_mode"].to(bool),
            qam_button=qam_button,
            emit=emit,
            params=d_params,
            qam_multi_tap=False,
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
        d_vend.open()
        prepare(d_xinput)
        if motion:
            start_imu = True
            if dconf.get("hrtimer", False):
                start_imu = d_timer.open()
            if start_imu:
                prepare(d_imu)
        if has_touchpad and d_params["uses_touch"]:
            prepare(d_touch)
        if l4r4_enabled:
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
            evs.extend(d_vend.produce(r))

            evs = multiplexer.process(evs)
            if evs:
                if debug:
                    logger.info(evs)

                # d_vend.consume(evs)
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
            d_vend.close(not updated.is_set())
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
