import logging
import os
import select
import time
from threading import Event as TEvent

from hhd.controller import DEBUG_MODE, Multiplexer
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev, enumerate_evs
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.controller.physical.rgb import LedDevice, is_led_supported
from hhd.controller.virtual.uinput import UInputDevice
from hhd.plugins import Config, Context, Emitter, get_gyro_state, get_outputs

from .const import BTN_MAPPINGS, DEFAULT_MAPPINGS, TECNO_RAW_INTERFACE_BTN_MAP

FIND_DELAY = 0.1
ERROR_DELAY = 0.3
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3

logger = logging.getLogger(__name__)


GAMEPAD_VID = 0x045E
GAMEPAD_PID = 0x028E

MSI_CLAW_VID = 0x0DB0
MSI_CLAW_PID = 0x1901

TECNO_VID = 0x2993
TECNO_PID = 0x2001

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
            match dconf.get("type", None):
                case "tecno":
                    vid = TECNO_VID
                case "claw":
                    vid = MSI_CLAW_VID
                case _:
                    vid = GAMEPAD_VID
            found_device = bool(enumerate_evs(vid=vid))
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
            # Raise exception
            if DEBUG_MODE:
                raise e
            time.sleep(sleep_time)

    # Unhide all devices before exiting and close keyboard cache
    UInputDevice.close_volume_cached()
    unhide_all()


def controller_loop(
    conf: Config, should_exit: TEvent, updated: TEvent, dconf: dict, emit: Emitter
):
    debug = DEBUG_MODE
    dtype = dconf.get("type", "generic")
    dgyro = dconf.get("display_gyro", True)

    # Output
    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        None,
        dgyro and conf["imu"].to(bool),
        emit=emit,
        rgb_modes={"disabled": [], "solid": ["color"]} if is_led_supported() else None,
    )
    motion = d_params.get("uses_motion", True)

    # Imu
    if dgyro:
        d_imu = CombinedImu(
            conf["imu_hz"].to(int),
            get_gyro_state(conf["imu_axis"], dconf.get("mapping", DEFAULT_MAPPINGS)),
        )
    else:
        d_imu = None
    d_timer = HrtimerTrigger(conf["imu_hz"].to(int), [HrtimerTrigger.IMU_NAMES])

    # Inputs
    d_xinput = GenericGamepadEvdev(
        vid=[GAMEPAD_VID, MSI_CLAW_VID, TECNO_VID],
        pid=[GAMEPAD_PID, MSI_CLAW_PID, TECNO_PID],
        # name=["Generic X-Box pad"],
        capabilities={EC("EV_KEY"): [EC("BTN_A")]},
        required=True,
        hide=True,
    )

    d_kbd_1 = GenericGamepadEvdev(
        vid=[KBD_VID],
        pid=[KBD_PID],
        required=False,
        grab=True,
        btn_map=dconf.get("btn_mapping", BTN_MAPPINGS),
    )
    d_kbd_2 = None

    kargs = {}
    if dtype == "tecno":
        kargs = {
            "keyboard_is": "steam_qam",
            "qam_hhd": True,
        }

    multiplexer = Multiplexer(
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        share_to_qam=True,
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        params=d_params,
        **kargs,
    )

    d_volume_btn = UInputDevice(
        name="Handheld Daemon Volume Keyboard",
        phys="phys-hhd-vbtn",
        capabilities={EC("EV_KEY"): [EC("KEY_VOLUMEUP"), EC("KEY_VOLUMEDOWN")]},
        btn_map={
            "key_volumeup": EC("KEY_VOLUMEUP"),
            "key_volumedown": EC("KEY_VOLUMEDOWN"),
        },
        pid=KBD_PID,
        vid=KBD_VID,
        output_timestamps=True,
    )

    d_rgb = LedDevice()
    if d_rgb.supported:
        logger.info(f"RGB Support activated through kernel driver.")

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
        if dconf.get("claw", False):
            # Wait a bit to get the controller to appear during boot
            d_vend = GenericGamepadHidraw(
                vid=[MSI_CLAW_VID],
                pid=[MSI_CLAW_PID],
                usage_page=[0xFFA0],
                usage=[0x0001],
                required=True,
            )
            try:
                time.sleep(1)
                d_vend.open()
                assert d_vend.dev
                d_vend.dev.write(
                    bytes([0x0F, 0x00, 0x00, 0x3C, 0x24, 0x01, 0x00, 0x00])
                )
            finally:
                d_vend.close(True)
        if dtype == "tecno":
            d_kbd_2 = GenericGamepadHidraw(
                vid=[TECNO_VID],
                pid=[TECNO_PID],
                usage_page=[0xFFA0],
                usage=[0x0001],
                required=True,
                btn_map=TECNO_RAW_INTERFACE_BTN_MAP,
            )

        prepare(d_xinput)
        if motion and d_imu:
            start_imu = True
            if dconf.get("hrtimer", False):
                start_imu = d_timer.open()
            if start_imu:
                prepare(d_imu)
        prepare(d_volume_btn)
        prepare(d_kbd_1)
        if d_kbd_2:
            prepare(d_kbd_2)
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

            d_rgb.consume(evs)
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
