import logging
import os
import select
import time
from threading import Event as TEvent


from hhd.controller import Multiplexer, DEBUG_MODE
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev, enumerate_evs
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.controller.virtual.uinput import UInputDevice
from hhd.controller.physical.hidraw import enumerate_unique
from hhd.plugins import Config, Context, Emitter, get_gyro_state, get_outputs
from .serial import SerialDevice, get_serial
from .hid_v1 import OxpHidraw
from .hid_v2 import OxpHidrawV2
from .const import BTN_MAPPINGS, DEFAULT_MAPPINGS, BTN_MAPPINGS_NONTURBO

FIND_DELAY = 0.1
ERROR_DELAY = 0.3
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3
TURBO_DELAY = 5
TURBO_CONTROLLER_CHECK = 2

logger = logging.getLogger(__name__)


GAMEPAD_VID = 0x045E
GAMEPAD_PID = 0x028E

KBD_VID = 0x0001
KBD_PID = 0x0001

X1_MINI_VID = 0x1A86
X1_MINI_PID = 0xFE00
X1_MINI_PAGE = 0xFF00
X1_MINI_USAGE = 0x0001

XFLY_VID = 0x1A2C
XFLY_PID = 0xB001
XFLY_PAGE = 0xFF01
XFLY_USAGE = 0x0001

BACK_BUTTON_DELAY = 0.1

RGB_MODES_FULL = {
    "disabled": [],
    "oxp": ["oxp", "oxp-secondary"],
    "solid": ["color"],
    "duality": ["dual"],
}
RGB_MODES_STICKS = {
    "disabled": [],
    "oxp": ["oxp"],
    "solid": ["color"],
}


def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    turbo: bool = False,
):
    first = True
    init = time.perf_counter()
    repeated_fail = False
    switch_to_turbo = None
    first_disabled = True

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
            found_device = bool(enumerate_evs(vid=GAMEPAD_VID, pid=GAMEPAD_PID))
        except Exception:
            logger.warning("Failed finding device, skipping check.")
            time.sleep(LONGER_ERROR_DELAY)
            found_device = True

        try:
            protocol = dconf.get("protocol", None)
            # Serial device is always present
            # Hid devices might not be, wait a bit for them
            match protocol:
                case "hid_v1":
                    found_vendor = bool(
                        enumerate_unique(
                            vid=X1_MINI_VID,
                            pid=X1_MINI_PID,
                            usage_page=X1_MINI_PAGE,
                            usage=X1_MINI_USAGE,
                        )
                    )
                case "hid_v2":
                    found_vendor = bool(
                        enumerate_unique(
                            vid=XFLY_VID,
                            pid=XFLY_PID,
                            usage_page=XFLY_PAGE,
                            usage=XFLY_USAGE,
                        )
                    )
                case "hid_v1_g1":
                    found_vendor = bool(
                        enumerate_unique(
                            vid=XFLY_VID,
                            pid=XFLY_PID,
                            usage_page=XFLY_PAGE,
                            usage=XFLY_USAGE,
                        )
                    )
                case "mixed":
                    found_vendor = bool(
                        enumerate_unique(
                            vid=XFLY_VID,
                            pid=XFLY_PID,
                            usage_page=XFLY_PAGE,
                            usage=XFLY_USAGE,
                        )
                    ) and bool(get_serial()[0])
                case "serial":
                    found_vendor = bool(get_serial()[0])
                case _:
                    found_vendor = True
        except Exception:
            logger.warning("Failed finding vendor device, skipping check.")
            found_vendor = True

        turbo_start = False
        if not found_device or not found_vendor:
            curr = time.perf_counter()
            if first:
                logger.info("Controller not found. Waiting...")
                switch_to_turbo = curr + TURBO_DELAY
            time.sleep(FIND_DELAY)
            first = False
            if found_vendor and turbo and switch_to_turbo and curr > switch_to_turbo:
                logger.info("Switching to turbo only button mode")
                updated.clear()
                turbo_start = True
                first = False
            else:
                continue

        try:
            logger.info("Launching emulated controller.")
            updated.clear()
            init = time.perf_counter()
            if turbo_start:
                turbo_loop(conf.copy(), should_exit, updated, dconf, emit)
            else:
                controller_loop(conf.copy(), should_exit, updated, dconf, emit, turbo)
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
            # Raise exception
            if DEBUG_MODE:
                raise e
            time.sleep(sleep_time)

    # Close the volume keyboard cache
    UInputDevice.close_volume_cached()
    unhide_all()


def find_vendor(prepare, turbo, protocol: str | None):
    d_ser = SerialDevice(turbo=turbo, required=True)
    d_hidraw = OxpHidraw(
        vid=[X1_MINI_VID],
        pid=[X1_MINI_PID],
        usage_page=[X1_MINI_PAGE],
        usage=[X1_MINI_USAGE],
        turbo=turbo,
        required=True,
    )
    d_hidraw_v2 = OxpHidrawV2(
        vid=[XFLY_VID],
        pid=[XFLY_PID],
        usage_page=[XFLY_PAGE],
        usage=[XFLY_USAGE],
        turbo=turbo,
        required=True,
    )
    d_hidraw_g1 = OxpHidraw(
        vid=[XFLY_VID],
        pid=[XFLY_PID],
        usage_page=[XFLY_PAGE],
        usage=[XFLY_USAGE],
        turbo=turbo,
        required=True,
        g1=True,
    )

    if protocol in ["serial", "mixed"]:
        try:
            prepare(d_ser)
            # OneXFly uses serial only for the buttons and hidraw for RGB
            # Initialize V2 selectcively on that one
            try:
                if d_ser.buttons_only:
                    if protocol == "serial":
                        logger.warning(
                            f"Device has protocol 'serial', but 'mixed' was detected."
                        )
                    prepare(d_hidraw_v2)
                return [d_ser, d_hidraw_v2]
            except Exception as e:
                logger.info(
                    f"Could not find V2 hidraw vendor device, RGB will not work, error:\n{e}"
                )
                return [d_ser]
        except Exception as e:
            pass

    if protocol == "hid_v1":
        try:
            prepare(d_hidraw)
            logger.info("Found OXP V1 hidraw vendor device.")
            return [d_hidraw]
        except Exception as e:
            pass

    if protocol == "hid_v1_g1":
        try:
            prepare(d_hidraw_g1)
            logger.info("Found OXP V1 hidraw vendor device.")
            return [d_hidraw_g1]
        except Exception as e:
            pass

    if protocol == "hid_v2":
        try:
            prepare(d_hidraw_v2)
            logger.info("Found OXP V2 hidraw vendor device.")
            return [d_hidraw_v2]
        except Exception as e:
            pass

    logger.error("No vendor device found, RGB and back buttons will not work.")
    return []


def turbo_loop(
    conf: Config,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    emit: Emitter,
):
    debug = DEBUG_MODE

    # Output
    if dconf.get("rgb_secondary", False):
        rgb_modes = RGB_MODES_FULL
    elif dconf.get("rgb", True):
        rgb_modes = RGB_MODES_STICKS
    else:
        rgb_modes = None

    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        None,
        conf["imu"].to(bool),
        emit=emit,
        rgb_modes=rgb_modes,  # type: ignore
        controller_disabled=True,
    )

    d_kbd_1 = GenericGamepadEvdev(
        vid=[KBD_VID],
        pid=[KBD_PID],
        required=False,
        grab=True,
        btn_map=BTN_MAPPINGS,
    )

    share_reboots = False
    last_controller_check = 0
    keyboard_is = "keyboard"
    qam_hhd = False
    qam_no_release = False
    if conf.get("turbo_reboots", False):
        share_reboots = True
    match conf.get("extra_buttons", "separate"):
        case "separate":
            keyboard_is = "steam_qam"
            qam_hhd = True
        case "combo":
            keyboard_is = "qam"
            qam_hhd = False
        case "combo_hhd":
            keyboard_is = "qam"
            qam_hhd = True

    multiplexer = Multiplexer(
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        share_to_qam=True,
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        params=d_params,
        share_reboots=share_reboots,
        keyboard_is=keyboard_is,
        swap_guide="start_is_keyboard" if conf.get("swap_face", False) else None,
        qam_hhd=qam_hhd,
        qam_no_release=qam_no_release,
        keyboard_no_release=not conf.get("swap_face", False),
    )

    if dconf.get("x1", False) and conf.get("volume_reverse", False):
        logger.info("Reversing volume buttons.")
        btn_map = {
            "key_volumedown": EC("KEY_VOLUMEUP"),
            "key_volumeup": EC("KEY_VOLUMEDOWN"),
        }
    else:
        btn_map = {
            "key_volumeup": EC("KEY_VOLUMEUP"),
            "key_volumedown": EC("KEY_VOLUMEDOWN"),
        }

    d_volume_btn = UInputDevice(
        name="Handheld Daemon Volume Keyboard",
        phys="phys-hhd-vbtn",
        capabilities={EC("EV_KEY"): [EC("KEY_VOLUMEUP"), EC("KEY_VOLUMEDOWN")]},
        btn_map=btn_map,  # type: ignore
        pid=KBD_PID,
        vid=KBD_VID,
        output_timestamps=True,
        volume_keyboard=True,
    )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 25

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
        prepare(d_volume_btn)
        d_vend = find_vendor(prepare, True, dconf.get("protocol", None))
        d_vend_id = [id(d) for d in d_vend]

        for d in d_producers:
            prepare(d)
        prepare(d_kbd_1)

        logger.info(
            "Turbo only mode started, the turbo button of the device will still work."
        )
        while not should_exit.is_set() and not updated.is_set():
            start = time.perf_counter()

            if start - last_controller_check > TURBO_CONTROLLER_CHECK:
                last_controller_check = start
                try:
                    found_device = bool(enumerate_evs(vid=GAMEPAD_VID, pid=GAMEPAD_PID))
                except Exception:
                    logger.warning("Failed finding device, skipping check.")
                    found_device = True
                if found_device:
                    logger.info("Controller found, switching to controller mode.")
                    break

            r, _, _ = select.select(fds, [], [], REPORT_DELAY_MAX)
            evs = []
            to_run = set()
            for f in r:
                to_run.add(id(fd_to_dev[f]))

            for d in devs:
                d_id = id(d)
                if d_id in to_run or d_id in d_vend_id:
                    evs.extend(d.produce(r))

            evs = multiplexer.process(evs)
            if evs:
                if debug:
                    logger.info(evs)

                d_volume_btn.consume(evs)

            for d in d_vend:
                d.consume(evs)
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


def controller_loop(
    conf: Config,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    emit: Emitter,
    turbo: bool = False,
):
    debug = DEBUG_MODE

    # Output
    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        None,
        conf["imu"].to(bool),
        emit=emit,
        rgb_modes=(
            RGB_MODES_FULL if dconf.get("rgb_secondary", False) else RGB_MODES_STICKS  # type: ignore
        ),
    )
    motion = d_params.get("uses_motion", True)

    # Imu
    d_imu = CombinedImu(
        conf["imu_hz"].to(int),
        get_gyro_state(conf["imu_axis"], dconf.get("mapping", DEFAULT_MAPPINGS)),
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

    if turbo:
        # Switch buttons if turbo is enabled.
        # This only affects AOKZOE and OneXPlayer devices with
        # that button that have the nonturbo mapping as default
        mappings = BTN_MAPPINGS
    else:
        mappings = BTN_MAPPINGS_NONTURBO

    d_kbd_1 = GenericGamepadEvdev(
        vid=[KBD_VID],
        pid=[KBD_PID],
        required=False,
        grab=True,
        btn_map=mappings,
    )
    # Touchpad keyboard
    d_kbd_2 = GenericGamepadEvdev(
        vid=[0x6080],
        pid=[0x8060],
        required=True,
        grab=False,
        btn_map=BTN_MAPPINGS,
        capabilities={EC("EV_KEY"): [EC("KEY_D")]},
        requires_start=True,
    )

    share_reboots = False
    keyboard_is = "keyboard"
    qam_hhd = False
    qam_no_release = False
    if turbo:
        if conf.get("turbo_reboots", False):
            share_reboots = True
        match conf.get("extra_buttons", "separate"):
            case "separate":
                keyboard_is = "steam_qam"
                qam_hhd = True
            case "combo":
                keyboard_is = "qam"
                qam_hhd = False
            case "combo_hhd":
                keyboard_is = "qam"
                qam_hhd = True
    else:
        qam_no_release = True

    multiplexer = Multiplexer(
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        share_to_qam=True,
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        params=d_params,
        share_reboots=share_reboots,
        keyboard_is=keyboard_is,
        swap_guide="start_is_keyboard" if conf.get("swap_face", False) else None,
        qam_hhd=qam_hhd,
        qam_no_release=qam_no_release,
        keyboard_no_release=not conf.get("swap_face", False),
    )

    if dconf.get("x1", False) and conf.get("volume_reverse", False):
        logger.info("Reversing volume buttons.")
        btn_map = {
            "key_volumedown": EC("KEY_VOLUMEUP"),
            "key_volumeup": EC("KEY_VOLUMEDOWN"),
        }
    else:
        btn_map = {
            "key_volumeup": EC("KEY_VOLUMEUP"),
            "key_volumedown": EC("KEY_VOLUMEDOWN"),
        }

    d_volume_btn = UInputDevice(
        name="Handheld Daemon Volume Keyboard",
        phys="phys-hhd-vbtn",
        capabilities={EC("EV_KEY"): [EC("KEY_VOLUMEUP"), EC("KEY_VOLUMEDOWN")]},
        btn_map=btn_map,  # type: ignore
        pid=KBD_PID,
        vid=KBD_VID,
        output_timestamps=True,
        volume_keyboard=True,
    )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 125

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
        d_vend = find_vendor(prepare, turbo, dconf.get("protocol", None))
        d_vend_id = [id(d) for d in d_vend]
        if dconf.get("g1", False):
            prepare(d_kbd_2)
        prepare(d_xinput)
        if motion:
            start_imu = True
            if dconf.get("hrtimer", False):
                start_imu = d_timer.open()
            if start_imu:
                prepare(d_imu)
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
                d_id = id(d)
                if d_id in to_run or d_id in d_vend_id:
                    evs.extend(d.produce(r))

            evs = multiplexer.process(evs)
            if evs:
                if debug:
                    logger.info(evs)

                d_volume_btn.consume(evs)
                d_xinput.consume(evs)

            for d in d_vend:
                d.consume(evs)
            for d in d_outs:
                d.consume(evs)

            t = time.perf_counter()
            elapsed = t - start
            if elapsed < REPORT_DELAY_MIN:
                time.sleep(REPORT_DELAY_MIN - elapsed)

    except KeyboardInterrupt:
        raise
    finally:
        # d_vend.close(not updated.is_set())
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
