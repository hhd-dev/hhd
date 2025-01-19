import logging
import select
import time
from threading import Event as TEvent
from typing import Sequence

from hhd.controller import DEBUG_MODE, Axis, Event, Multiplexer, can_read
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.evdev import DINPUT_AXIS_POSTPROCESS, AbsAxis
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import (
    GamepadButton,
    GenericGamepadEvdev,
    enumerate_evs,
    to_map,
)
from hhd.controller.physical.hidraw import GenericGamepadHidraw, enumerate_unique
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.plugins import Config, Context, Emitter, get_limits, get_outputs

from .const import config_rgb
from .hid import RgbCallback, switch_mode

SELECT_TIMEOUT = 1

logger = logging.getLogger(__name__)

ASUS_VID = 0x0B05
ALLY_PID = 0x1ABE
ALLY_X_PID = 0x1B4C
GAMEPAD_VID = 0x045E
GAMEPAD_PID = 0x028E

ALLY_MAPPINGS: dict[str, tuple[Axis, str | None, float, float | None]] = {
    "accel_x": ("accel_x", "accel", 1, None),
    "accel_y": ("accel_z", "accel", 1, None),
    "accel_z": ("accel_y", "accel", -1, None),
    "anglvel_x": ("gyro_x", "anglvel", 1, None),
    "anglvel_y": ("gyro_z", "anglvel", 1, None),
    "anglvel_z": ("gyro_y", "anglvel", -1, None),
    "timestamp": ("imu_ts", None, 1, None),
}

LIMIT_DEFAULTS = lambda allyx: {
    "s_min": 0 if allyx else 5,
    "s_max": 0x60 if allyx else 0x40,
    "t_min": 5,
    "t_max": 0x60 if allyx else 0x40,
    # ally x vibration motor is too strong
    "vibration": 50 if allyx else 100,
}

MODE_DELAY = 0.15
VIBRATION_DELAY = 0.1
VIBRATION_ON: Event = {
    "type": "rumble",
    "code": "main",
    "strong_magnitude": 0.5,
    "weak_magnitude": 0.5,
}
VIBRATION_OFF: Event = {
    "type": "rumble",
    "code": "main",
    "strong_magnitude": 0,
    "weak_magnitude": 0,
}

FIND_DELAY = 0.1
ERROR_DELAY = 0.3
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3

# TODO: Work with upstream on the xpad (?) driver
# LB = BTN_WEST
# RB = BTN_Z
# X = BTN_C
# A = BTN_SOUTH
# B = BTN_EAST
# Y = BTN_NORTH
# Start (Menu) = BTN_TR
# Select (View) = BTN_TL
# RT = ABS_RZ
# LT = ABS_Z
# L3 = BTN_TL2
# R3 = BTN_TR2
ALLY_X_BUTTON_MAP: dict[int, GamepadButton] = to_map(
    {
        # Gamepad
        "a": [EC("BTN_SOUTH")],
        "b": [EC("BTN_EAST")],
        "x": [EC("BTN_C")],
        "y": [EC("BTN_NORTH")],
        # Sticks
        "ls": [EC("BTN_TL2")],
        "rs": [EC("BTN_TR2")],
        # Bumpers
        "lb": [EC("BTN_WEST")],
        "rb": [EC("BTN_Z")],
        # Select
        "start": [EC("BTN_TR")],
        "select": [EC("BTN_TL")],
        # Misc
        # "mode": [EC("BTN_MODE")],
    }
)

ALLY_X_AXIS_MAP: dict[int, AbsAxis] = to_map(
    {
        # Sticks
        # Values should range from -1 to 1
        "ls_x": [EC("ABS_X")],
        "ls_y": [EC("ABS_Y")],
        "rs_x": [EC("ABS_RX")],
        "rs_y": [EC("ABS_RY")],
        # Triggers
        # Values should range from -1 to 1
        "rt": [EC("ABS_Z")],
        "lt": [EC("ABS_RZ")],
        # Hat, implemented as axis. Either -1, 0, or 1
        "hat_x": [EC("ABS_HAT0X")],
        "hat_y": [EC("ABS_HAT0Y")],
    }
)


class AllyHidraw(GenericGamepadHidraw):
    def __init__(self, *args, kconf={}, rgb_boot, rgb_charging, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.kconf = kconf
        self.mouse_mode = False
        self.rgb_boot = rgb_boot
        self.rgb_charging = rgb_charging
        self.late_init = None

    def open(self) -> Sequence[int]:
        self.queue: list[tuple[Event, float]] = []
        a = super().open()
        if self.dev:
            logger.info(f"Switching Ally Controller to gamepad mode.")
            # Setup leds so they dont interfere after this
            self.dev.write(config_rgb(self.rgb_boot, self.rgb_charging))
            switch_mode(self.dev, "default", self.kconf, first=True)

        self.mouse_mode = False
        self.late_init = time.perf_counter()
        return a

    def produce(self, fds: Sequence[int]) -> Sequence[Event]:
        # If we can not read return
        if not self.fd or not self.dev:
            return []

        # Process events
        curr = time.perf_counter()
        out: Sequence[Event] = []

        # Remove up to one queued event
        if len(self.queue):
            ev, ofs = self.queue[0]
            if ofs < curr:
                out.append(ev)
                self.queue.pop(0)

        # Force a re-init after 5 seconds in case the MCU did not get the message
        # Hopefully this fixes the back buttons on the og ally.
        if self.late_init and curr > self.late_init + 5:
            logger.info(f"Re-initializing controller.")
            self.late_init = None
            if not self.mouse_mode:
                switch_mode(self.dev, "default", self.kconf, first=True)

        # Read new events
        while can_read(self.fd):
            rep = self.dev.read(self.report_size)
            # logger.warning(f"Received the following report (debug):\n{rep.hex()}")
            if rep[0] != 0x5A:
                continue

            match rep[1]:
                case 0xA6:
                    # action = "left"
                    out.append({"type": "button", "code": "mode", "value": True})
                    self.queue.append(
                        (
                            {"type": "button", "code": "mode", "value": False},
                            curr + MODE_DELAY,
                        )
                    )
                case 0x38:
                    # action = "right"
                    out.append({"type": "button", "code": "share", "value": True})
                    self.queue.append(
                        (
                            {"type": "button", "code": "share", "value": False},
                            curr + MODE_DELAY,
                        )
                    )
                case 0xA7:
                    # right hold
                    # Mode switch
                    if self.mouse_mode:
                        switch_mode(self.dev, "default", self.kconf)
                        self.mouse_mode = False
                        out.append(VIBRATION_ON)
                        self.queue.append((VIBRATION_OFF, curr + VIBRATION_DELAY))
                    else:
                        switch_mode(self.dev, "mouse", self.kconf)
                        self.mouse_mode = True
                        out.append(VIBRATION_ON)
                        self.queue.append((VIBRATION_OFF, curr + VIBRATION_DELAY))
                        self.queue.append((VIBRATION_ON, curr + 2 * VIBRATION_DELAY))
                        self.queue.append((VIBRATION_OFF, curr + 3 * VIBRATION_DELAY))
                case 0xA8:
                    # action = "right_hold_release"
                    pass  # kind of useless

        return out


class AllyXHidraw(GenericGamepadHidraw):
    def open(self) -> Sequence[int]:
        super().open()
        # Drop all events
        return []

    def consume(self, events: Sequence[Event]) -> None:
        if not self.dev:
            return

        for ev in events:
            if ev["type"] != "rumble":
                continue

            if ev["code"] != "main":
                logger.warning(
                    f"Received rumble event with unsupported side: {ev['code']}"
                )
                continue

            "0d 0f 00 00 31 31 ff 00 eb"
            cmd = bytes(
                [
                    0x0D,
                    0x0F,
                    0x00,
                    0x00,
                    min(100, int(ev["weak_magnitude"] * 100)),
                    min(100, int(ev["strong_magnitude"] * 100)),
                    0xFF,
                    0x00,
                    0xEB,
                ]
            )
            self.dev.write(cmd)


def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    ally_x: bool,
):
    init = time.perf_counter()
    repeated_fail = False
    first = True
    while not should_exit.is_set():
        try:
            gamepad_devs = enumerate_evs(vid=GAMEPAD_VID)
            nkey_devs = enumerate_unique(vid=ASUS_VID)

            if (not gamepad_devs and not ally_x) or not nkey_devs:
                if first:
                    first = False
                    logger.warning(f"Ally controller not found, waiting...")
                time.sleep(FIND_DELAY)
                continue

            logger.info("Launching emulated controller.")
            updated.clear()
            init = time.perf_counter()
            controller_loop(conf.copy(), should_exit, updated, emit, ally_x)
            repeated_fail = False
        except Exception as e:
            first = True
            failed_fast = init + LONGER_ERROR_MARGIN > time.perf_counter()
            sleep_time = (
                LONGER_ERROR_DELAY if repeated_fail and failed_fast else ERROR_DELAY
            )
            repeated_fail = failed_fast
            logger.error(f"Received the following error:\n{type(e)}:")

            try:
                import traceback

                traceback.print_exc()
            except Exception:
                pass

            logger.error(
                f"Assuming controllers disconnected, restarting after {sleep_time}s."
            )
            # Raise exception
            if DEBUG_MODE:
                raise e
            time.sleep(sleep_time)

    # Unhide all devices before exiting
    unhide_all()


def controller_loop(
    conf: Config, should_exit: TEvent, updated: TEvent, emit: Emitter, ally_x: bool
):
    debug = DEBUG_MODE

    # Output
    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        None,
        conf["imu"].to(bool),
        emit=emit,
        rgb_modes={
            "disabled": [],
            "solid": ["color"],
            "pulse": ["color", "speedd"],
            "duality": ["dual", "speedd"],
            "rainbow": ["brightnessd"],
            "spiral": ["brightnessd", "speedd", "direction"],
        },
        rgb_zones="quad",
    )
    motion = d_params.get("uses_motion", True)

    # Imu
    d_imu = CombinedImu(conf["imu_hz"].to(int), ALLY_MAPPINGS, gyro_scale="0.000266")
    d_timer = HrtimerTrigger(conf["imu_hz"].to(int), [HrtimerTrigger.IMU_NAMES])

    # Inputs
    if ally_x:
        d_xinput = GenericGamepadEvdev(
            vid=[ASUS_VID],
            pid=[ALLY_X_PID],
            btn_map=ALLY_X_BUTTON_MAP,
            axis_map=ALLY_X_AXIS_MAP,
            # name=["Generic X-Box pad"],
            capabilities={EC("EV_KEY"): [EC("BTN_A")]},
            required=True,
            postprocess=DINPUT_AXIS_POSTPROCESS,
            hide=True,
        )
        d_allyx = AllyXHidraw(
            vid=[ASUS_VID],
            pid=[ALLY_X_PID],
            usage_page=[0x0F],
            usage=[0x21],
            required=True,
        )
    else:
        d_xinput = GenericGamepadEvdev(
            vid=[GAMEPAD_VID],
            pid=[GAMEPAD_PID],
            # name=["Generic X-Box pad"],
            capabilities={EC("EV_KEY"): [EC("BTN_A")]},
            required=True,
            hide=True,
            postprocess={},  # remove calibration as its supported by the GUI
        )
        d_allyx = None

    # Vendor
    kconf = get_limits(conf["limits"], defaults=LIMIT_DEFAULTS(ally_x))
    d_vend = AllyHidraw(
        vid=[ASUS_VID],
        pid=[ALLY_PID, ALLY_X_PID],
        usage_page=[0xFF31],
        usage=[0x0080],
        required=True,
        rgb_boot=conf.get("rgb_boot", False),
        rgb_charging=conf.get("rgb_charging", False),
        callback=RgbCallback(),
        kconf=kconf,
    )

    # Grab shortcut keyboards
    d_kbd_1 = GenericGamepadEvdev(
        vid=[ASUS_VID],
        pid=[ALLY_PID, ALLY_X_PID],
        capabilities={EC("EV_KEY"): [EC("KEY_F23")]},
        required=True,
        grab=False,
        btn_map={EC("KEY_F17"): "extra_l1", EC("KEY_F18"): "extra_r1"},
    )
    d_kbd_grabbed = False

    multiplexer = Multiplexer(
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        share_to_qam=True,
        select_reboots=conf["select_reboots"].to(bool),
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        swap_guide="select_is_guide" if conf["swap_armory"].to(bool) else None,
        qam_no_release=not conf["swap_armory"].to(bool),
        params=d_params,
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
        if d_allyx:
            prepare(d_allyx)
        if motion:
            if d_timer.open():
                prepare(d_imu)
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

            d_vend.consume(evs)
            d_xinput.consume(evs)
            if d_allyx:
                d_allyx.consume(evs)

            for d in d_outs:
                d.consume(evs)

            if d_vend.mouse_mode and d_kbd_grabbed and d_kbd_1.dev:
                try:
                    d_kbd_1.dev.ungrab()
                except Exception:
                    pass
                d_kbd_grabbed = False
            elif not d_vend.mouse_mode and not d_kbd_grabbed and d_kbd_1.dev:
                try:
                    d_kbd_1.dev.grab()
                except Exception:
                    pass
                d_kbd_grabbed = True

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
