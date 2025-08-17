import logging
import os
import select
import time
from threading import Event as TEvent

from hhd.controller import DEBUG_MODE, Multiplexer
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import (
    GenericGamepadEvdev,
    enumerate_evs,
    XBOX_BUTTON_MAP,
)
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.controller.virtual.uinput import UInputDevice
from hhd.plugins import Config, Context, Emitter, get_gyro_state, get_outputs
from .const import DEFAULT_MAPPINGS, AYA3_INIT, get_cfg_commands


def to_bytes(s: str):
    return bytes.fromhex(s.replace(" ", ""))


FIND_DELAY = 0.1
ERROR_DELAY = 0.3
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3

logger = logging.getLogger(__name__)

GAMEPAD_VID = 0x045E
GAMEPAD_PID = 0x028E

KBD_VID = 0x0001
KBD_PID = 0x0001

AYA_VID = 0x1C4F
AYA_PID = 0x0002

AYA_TIMEOUT = 100

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

_reset = True

class Ayaneo3Hidraw(GenericGamepadHidraw):
    def open(self):
        out = super().open()
        if not out:
            return out
        if not self.dev:
            return out

        for r in AYA3_INIT:
            r = to_bytes(r)
            logger.info(f"Send: {r.hex()}")
            self.dev.write(r)
            res = self.dev.read(timeout=AYA_TIMEOUT)
            logger.info(f"Recv: {res.hex() if res else 'None'}")
        return out

    def consume(self, events):
        global _reset

        if not self.dev:
            return

        for ev in events:
            if ev["type"] != "led":
                continue

            mode = ev["mode"]

            if mode not in ["disabled", "solid", "pulse", "rainbow"]:
                logger.error(f"Invalid RGB mode: {mode}")
                continue

            cmds = get_cfg_commands(
                rgb_mode=mode,
                r=ev["red"],
                g=ev["green"],
                b=ev["blue"],
                brightness=ev.get("brightness", 1),
                reset=_reset,
            )
            _reset = False
            for cmd in cmds:
                logger.info(f"Send: {cmd.hex()}")
                self.dev.write(cmd)
                res = self.dev.read(timeout=AYA_TIMEOUT)
                logger.info(f"Recv: {res.hex() if res else 'None'}")


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
        rgb_modes=(
            {"disabled": [], "solid": ["color"], "pulse": ["color"], "rainbow": []}
            if dconf.get("rgb", False)
            else None
        ),
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
        vid=[GAMEPAD_VID],
        pid=[GAMEPAD_PID],
        capabilities={EC("EV_KEY"): [EC("BTN_A")]},
        required=True,
        hide=True,
        btn_map={**XBOX_BUTTON_MAP, EC("BTN_MODE"): "share"},
    )

    d_kbd_1 = GenericGamepadEvdev(
        vid=[KBD_VID],
        pid=[KBD_PID],
        required=False,
        grab=False,
        btn_map={
            EC("KEY_F23"): "mode",
        },
    )
    d_kbd_2 = GenericGamepadEvdev(
        vid=[AYA_VID],
        pid=[AYA_PID],
        required=True,
        grab=True,
        capabilities={EC("EV_KEY"): [EC("KEY_F21")]},
        btn_map={
            EC("KEY_F24"): "keyboard",
            EC("KEY_F21"): "extra_l2",
            EC("KEY_F22"): "extra_r2",
            EC("KEY_L"): "extra_l1",
            EC("KEY_R"): "extra_r1",
        },
    )
    d_vend = Ayaneo3Hidraw(
        vid=[AYA_VID],
        pid=[AYA_PID],
        required=True,
        application=[0xFF000001],
    )

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
        select_reboots=conf.get("select_reboots", False),
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        params=d_params,
        startselect_chord=conf.get("main_chords", "disabled"),
        keyboard_is="qam",
        qam_hhd=True,
        swap_guide="select_is_guide" if conf["swap_guide"].to(bool) else None,
        **kargs,
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
        if motion and d_imu:
            start_imu = True
            if dconf.get("hrtimer", False):
                start_imu = d_timer.open()
            if start_imu:
                prepare(d_imu)
        prepare(d_vend)
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

                d_xinput.consume(evs)

            if d_vend:
                d_vend.consume(evs)
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
