import argparse
import logging
import re
import select
import sys
import time
from typing import Sequence, cast

from hhd.controller import Button, Consumer, Event, Producer
from hhd.controller.base import Multiplexer, can_read
from hhd.controller.lib.hid import enumerate_unique
from hhd.controller.physical.evdev import GenericGamepadEvdev
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.imu import AccelImu, GyroImu
from hhd.controller.virtual.ds5 import DualSense5Edge, TouchpadCorrectionType
from hhd.controller.virtual.uinput import UInputDevice

from .const import (
    LGO_RAW_INTERFACE_AXIS_MAP,
    LGO_RAW_INTERFACE_BTN_ESSENTIALS,
    LGO_RAW_INTERFACE_BTN_MAP,
    LGO_RAW_INTERFACE_CONFIG_MAP,
    LGO_TOUCHPAD_AXIS_MAP,
    LGO_TOUCHPAD_BUTTON_MAP,
)
from .hid import rgb_callback
from .gyro_fix import GyroFixer

ERROR_DELAY = 1

logger = logging.getLogger(__name__)

LEN_VID = 0x17EF
LEN_PIDS = {
    0x6182: "xinput",
    0x6183: "dinput",
    0x6184: "dual_dinput",
    0x6185: "fps",
}


def main(as_plugin=False):
    if not as_plugin:
        from hhd import setup_logger

        setup_logger()

    parser = argparse.ArgumentParser(
        prog="HHD: LegionGo Controller Plugin",
        description="This plugin remaps the legion go controllers to a DS5 controller and restores all functionality.",
    )
    parser.add_argument(
        "-a",
        "--d-accel",
        action="store_false",
        help="Dissable accelerometer (recommended since not used by steam, .5%% core utilisation).",
        dest="accel",
    )
    parser.add_argument(
        "-g",
        "--d-gyro",
        action="store_false",
        help="Disable gyroscope (.5%% core utilisation).",
        dest="gyro",
    )
    parser.add_argument(
        "-gf",
        "--gyro-fix",
        action="store_true",
        help="Samples the gyro to avoid needing a custom driver.",
        dest="gyro_fix",
    )
    parser.add_argument(
        "-l",
        "--swap-legion",
        action="store_true",
        help="Swaps Legion buttons with start, select.",
        dest="swap_legion",
    )
    parser.add_argument(
        "-s",
        "--share-to-qam",
        action="store_true",
        help="Maps the share button (Legion R) to Guide + A",
        dest="share_to_qam",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Prints events as they happen.",
        dest="debug",
    )
    parser.add_argument(
        "-t",
        "--touchpad",
        help='How to fit the legion go touchpad into the DS5 ("stretch", "crop_center", "crop_start", "crop_end", "contain_start", "contain_end", "contain_center")',
        default=None,
    )
    if as_plugin:
        args = parser.parse_args(sys.argv[2:])
    else:
        args = parser.parse_args()

    accel = args.accel
    gyro = args.gyro
    swap_legion = args.swap_legion
    debug = args.debug
    touchpad_mode = cast(TouchpadCorrectionType | None, args.touchpad)
    gyro_fix = args.gyro_fix
    share_to_qam = args.share_to_qam
    plugin_run(
        accel=accel,
        gyro=gyro,
        swap_legion=swap_legion,
        touchpad_mode=touchpad_mode,
        gyro_fix=gyro_fix,
        share_to_qam=share_to_qam,
        debug=debug,
    )


def plugin_run(
    accel: bool = False,
    gyro: bool = True,
    swap_legion: bool = False,
    touchpad_mode: TouchpadCorrectionType | None = "crop_end",
    gyro_fix: bool | int = True,
    share_to_qam: bool = True,
    led_support: bool = True,
    debug: bool = False,
    **_,
):
    if gyro_fix:
        gyro_fixer = GyroFixer(int(gyro_fix) if int(gyro_fix) > 10 else 65)
    else:
        gyro_fixer = None

    while True:
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

            match controller_mode:
                case "xinput":
                    logger.info("Launching DS5 controller instance.")
                    if gyro_fixer:
                        gyro_fixer.open()
                    controller_loop_xinput(
                        accel=accel,
                        gyro=gyro,
                        swap_legion=swap_legion,
                        share_to_qam=share_to_qam,
                        touchpad_mode=touchpad_mode,
                        led_support=led_support,
                        debug=debug,
                    )
                case _:
                    logger.info(
                        f"Controllers in non-supported (yet) mode: {controller_mode}. Launching a shortcuts device."
                    )
                    controller_loop_rest(
                        controller_mode, pid if pid else 2, share_to_qam, debug
                    )
        except Exception as e:
            logger.error(f"Received the following error:\n{e}")
            logger.error(
                f"Assuming controllers disconnected, restarting after {ERROR_DELAY}s."
            )
            if gyro_fixer:
                gyro_fixer.close()
            time.sleep(ERROR_DELAY)
        except KeyboardInterrupt:
            if gyro_fixer:
                gyro_fixer.close()
            logger.info("Received KeyboardInterrupt, exiting...")
            return


def controller_loop_rest(mode: str, pid: int, share_to_qam: bool, debug: bool = False):
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

    multiplexer = Multiplexer(dpad="analog_to_discrete", share_to_qam=share_to_qam)
    d_uinput = UInputDevice(name=f"HHD Shortcuts Device (Legion Mode: {mode})", pid=pid)

    d_shortcuts = GenericGamepadEvdev(
        vid=[LEN_VID],
        pid=list(LEN_PIDS),
        name=[re.compile(r"Legion-Controller \d-.. Keyboard")],
        required=True,
    )

    try:
        fds = []
        fds.extend(d_raw.open())
        fds.extend(d_shortcuts.open())
        fds.extend(d_uinput.open())

        while True:
            select.select(fds, [], [])
            d_shortcuts.produce(fds)
            d_uinput.produce(fds)
            evs = multiplexer.process(d_raw.produce(fds))
            if debug and evs:
                logger.info(evs)
            d_uinput.consume(evs)
    finally:
        d_shortcuts.close(True)
        d_raw.close(True)
        d_uinput.close(True)


def controller_loop_xinput(
    accel: bool = True,
    gyro: bool = True,
    swap_legion: str | bool = False,
    share_to_qam: bool = False,
    touchpad_mode: TouchpadCorrectionType | None = None,
    led_support: bool = True,
    debug: bool = False,
):
    # Output
    d_ds5 = DualSense5Edge(
        touchpad_method=touchpad_mode if touchpad_mode else "crop_end"
    )

    # Imu
    d_accel = AccelImu()
    d_gyro = GyroImu()

    # Inputs
    d_xinput = GenericGamepadEvdev(
        [0x17EF],
        [0x6182],
        ["Generic X-Box pad"],
        required=True,
    )
    d_touch = GenericGamepadEvdev(
        [0x17EF],
        [0x6182],
        ["  Legion Controller for Windows  Touchpad"],
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
            callback=rgb_callback if led_support else None,
            required=True,
        )
    )
    # Mute keyboard shortcuts, mute
    d_shortcuts = GenericGamepadEvdev(
        vid=[LEN_VID],
        pid=list(LEN_PIDS),
        name=["  Legion Controller for Windows  Keyboard"],
        # report_size=64,
        required=True,
    )

    match swap_legion:
        case True:
            swap_guide = "guide_is_select"
        case False:
            swap_guide = None
        case "l_is_start":
            swap_guide = "guide_is_start"
        case "l_is_select":
            swap_guide = "guide_is_select"
        case _:
            assert False, "Invalid value for `swap_legion`."

    multiplexer = Multiplexer(
        swap_guide=swap_guide,
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        led="main_to_sides",
        status="both_to_main",
        share_to_qam=share_to_qam,
    )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 400

    REPORT_DELAY_MAX = 1 / REPORT_FREQ_MIN
    REPORT_DELAY_MIN = 1 / REPORT_FREQ_MAX

    fds = []
    devs = []
    fd_to_dev = {}

    def prepare(m):
        fs = m.open()
        devs.append(m)
        fds.extend(fs)
        for f in fs:
            fd_to_dev[f] = m

    try:
        if accel:
            prepare(d_accel)
        if gyro:
            prepare(d_gyro)
        prepare(d_xinput)
        prepare(d_shortcuts)
        prepare(d_touch)
        prepare(d_raw)
        prepare(d_ds5)

        logger.info("DS5 controller instance launched, have fun!")
        while True:
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

                d_ds5.consume(evs)
                d_xinput.consume(evs)
                d_raw.consume(evs)

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
        for d in devs:
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
        return super().close(exit)

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
            elif ev["type"] == "button":
                self.to_disable_btn.add(ev["code"])
            elif ev["type"] == "axis":
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
