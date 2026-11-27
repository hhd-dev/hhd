import logging
import select
import time
from threading import Event as TEvent

from hhd.controller import DEBUG_MODE, Multiplexer
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev, enumerate_evs
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.controller.virtual.uinput import UInputDevice
from hhd.plugins import Config, Context, Emitter, get_gyro_state, get_outputs

from .const import (
    TOUCHPAD_ZONES,
    ZOTAC_BTN_MAPPINGS,
    ZOTAC_GYRO_MAPPINGS,
    ZOTAC_PID,
    ZOTAC_VIDS,
)
from .hid import ZotacCmdHidraw, ZotacDialHidraw

FIND_DELAY = 0.1
ERROR_DELAY = 0.3
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3

KBD_VID = 0x0001
KBD_PID = 0x0001

ZONE_RGB_MODES = {
    "disabled": [],
    "solid": ["color"],
    "pulse": ["color", "speed"],
    "strobe": ["color", "speed"],
    "rainbow": ["brightness", "speed"],
    "spiral": ["brightness", "speed"],
    "zotac": ["zotac", "color", "speed"],
}

logger = logging.getLogger(__name__)


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
                UInputDevice.close_volume_cached()
                unhide_all()
            first_disabled = False
            continue
        else:
            first_disabled = True

        try:
            found_device = any(
                v.get("vendor") in ZOTAC_VIDS
                for v in enumerate_evs(pid=ZOTAC_PID).values()
            )
        except Exception:
            logger.warning("Failed finding device, skipping check.")
            time.sleep(LONGER_ERROR_DELAY)
            found_device = True

        if not found_device:
            if first:
                logger.info("Controller not found. Waiting...")
            time.sleep(FIND_DELAY)
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
            first = True
            if DEBUG_MODE:
                raise e
            time.sleep(sleep_time)

    UInputDevice.close_volume_cached()
    unhide_all()


def controller_loop(
    conf: Config, should_exit: TEvent, updated: TEvent, dconf: dict, emit: Emitter
):
    debug = DEBUG_MODE

    # Output
    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        None,
        conf["imu"].to(bool),
        emit=emit,
        rgb_modes=ZONE_RGB_MODES,  # type: ignore
        extra_buttons=dconf.get("extra_buttons", "dual"),
    )
    motion = d_params.get("uses_motion", True)

    # Imu
    d_imu = CombinedImu(
        conf["imu_hz"].to(int),
        get_gyro_state(conf["imu_axis"], dconf.get("mapping", ZOTAC_GYRO_MAPPINGS)),
    )
    d_timer = HrtimerTrigger(conf["imu_hz"].to(int), [HrtimerTrigger.IMU_NAMES])

    # Gamepad (xpad, USB interface 0)
    d_xinput = GenericGamepadEvdev(
        vid=ZOTAC_VIDS,
        pid=[ZOTAC_PID],
        capabilities={EC("EV_KEY"): [EC("BTN_A")]},
        required=True,
        hide=True,
    )

    # Controller keyboard (USB interface 1): Zotac/More buttons and paddles
    d_kbd = GenericGamepadEvdev(
        vid=ZOTAC_VIDS,
        pid=[ZOTAC_PID],
        capabilities={EC("EV_KEY"): [EC("KEY_F17")]},
        btn_map=ZOTAC_BTN_MAPPINGS,
        required=True,
        grab=True,
    )

    # The right dial is declared as a display switch key by the firmware.
    # Grab that device so the desktop does not open its display menu.
    d_dial_sink = GenericGamepadEvdev(
        vid=ZOTAC_VIDS,
        pid=[ZOTAC_PID],
        capabilities={EC("EV_KEY"): [EC("KEY_SWITCHVIDEOMODE")]},
        required=False,
        grab=True,
    )

    d_dials = ZotacDialHidraw(
        left=conf.get("dial_left", "disabled"),
        right=conf.get("dial_right", "volume"),
    )

    d_cmd = ZotacCmdHidraw(
        vibration=int(conf["vibration_strength"].to(str)),
        touchpad_zones={
            src: conf[f"touchpad_clicks.{zone}"].to(str)
            for zone, src in TOUCHPAD_ZONES.items()
        },
    )

    multiplexer = Multiplexer(
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        share_to_qam=True,
        touchpad_right="right_click",
        select_reboots=conf.get("select_reboots", False),
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        params=d_params,
        startselect_chord=conf.get("main_chords", "disabled"),
        swap_guide="select_is_guide" if conf["swap_guide"].to(bool) else None,
    )

    d_volume_btn = UInputDevice(
        name="Handheld Daemon Volume Keyboard",
        phys="phys-hhd-vbtn",
        capabilities={
            EC("EV_KEY"): [
                EC("KEY_VOLUMEUP"),
                EC("KEY_VOLUMEDOWN"),
                EC("KEY_BRIGHTNESSUP"),
                EC("KEY_BRIGHTNESSDOWN"),
            ]
        },
        btn_map={
            "key_volumeup": EC("KEY_VOLUMEUP"),
            "key_volumedown": EC("KEY_VOLUMEDOWN"),
            "key_brightnessup": EC("KEY_BRIGHTNESSUP"),
            "key_brightnessdown": EC("KEY_BRIGHTNESSDOWN"),
        },
        pid=KBD_PID,
        vid=KBD_VID,
        output_timestamps=True,
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
        prepare(d_xinput)
        if motion:
            start_imu = True
            if dconf.get("hrtimer", False):
                start_imu = d_timer.open()
            if start_imu:
                prepare(d_imu)

        prepare(d_volume_btn)
        prepare(d_kbd)
        prepare(d_dial_sink)
        prepare(d_dials)
        prepare(d_cmd)
        for d in d_producers:
            prepare(d)

        logger.info("Emulated controller launched, have fun!")
        while not should_exit.is_set() and not updated.is_set():
            start = time.perf_counter()
            # Add timeout to call consumers a minimum amount of times per second
            r, _, _ = select.select(fds, [], [], REPORT_DELAY_MAX)
            evs = []
            # The dials release their keys on the next iteration
            to_run = {id(d_dials)}
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

            d_cmd.consume(evs)
            for d in d_outs:
                d.consume(evs)

            t = time.perf_counter()
            elapsed = t - start
            if elapsed < REPORT_DELAY_MIN:
                time.sleep(REPORT_DELAY_MIN - elapsed)

    except KeyboardInterrupt:
        raise
    finally:
        try:
            d_timer.close()
        except Exception as e:
            logger.error(f"Error while closing the hrtimer with exception:\n{e}")
            if debug:
                raise e
        for d in reversed(devs):
            try:
                d.close(not updated.is_set())
            except Exception as e:
                logger.error(f"Error while closing device '{d}' with exception:\n{e}")
                if debug:
                    raise e
