import logging
import os
import select
import time
from threading import Event as TEvent

from hhd.controller import DEBUG_MODE, Multiplexer
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.evdev import XBOX_BUTTON_MAP
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev, enumerate_evs
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.imu import CombinedImu, HrtimerTrigger
from hhd.controller.virtual.uinput import UInputDevice
from hhd.i18n import _
from hhd.plugins import Config, Context, Emitter, get_gyro_state, get_outputs

from .const import (
    AYA3_INIT,
    AYA_CHECK,
    AYA_CUSTOM,
    DEFAULT_MAPPINGS,
    AYA_SAVE,
    get_cfg_commands,
)


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

AYA_TIMEOUT = 300
AYA_SAVE_TIMEOUT = 1500
AYA_ATTEMPTS = 3
AYA_VERIFY_EJECT = 20
AYA_MIN_EJECT = 3

_reset = True
_cfg = {
    "mode": None,
    "red": 0,
    "green": 0,
    "blue": 0,
    "brightness": 1,
}

CONTROLLER_POWER = (
    "/sys/class/firmware-attributes/ayaneo-ec/attributes/controller_power/current_value"
)
CONTROLLER_MODULES = "/sys/class/firmware-attributes/ayaneo-ec/attributes/controller_modules/current_value"


def write_cmd(dev, r: bytes, timeout: int = AYA_TIMEOUT):
    if DEBUG_MODE:
        logger.info(f"Send: {r[1:].hex()}")
    dev.write(r)

    # Read response
    for _ in range(AYA_ATTEMPTS):
        res = dev.read(timeout=timeout)
        if DEBUG_MODE:
            logger.info(f"Recv: {res.hex() if res else 'None'}")
        # Match IDs
        if res and res[3] == r[4]:
            break

    return res


LEFT_MODULES = {
    0x02: _("Cross Film / Joystick"),
    0x04: _("Cross / Joystick"),
    0x06: _("Cross / Touchpad"),
    0x08: _("Direction / Joystick"),
    0x42: _("Joystick / Cross Film"),
    0x44: _("Joystick / Cross"),
    0x46: _("Touchpad / Cross"),
    0x48: _("Joystick / Direction"),
}

RIGHT_MODULES = {
    0x10: _("ABXY \\ Joystick"),
    0x12: _("ABXY \\ Touchpad"),
    0x14: _("ABXYCZ"),
    0x16: _("ABXY Film \\ Joystick"),
    0x50: _("Joystick \\ ABXY"),
    0x52: _("Touchpad \\ ABXY"),
    0x54: _("ABXYCZ [R]"),
    0x56: _("Joystick \\ ABXY Film"),
}

MODULE_UKN = _("Unknown")
MODULE_EJECTING = _("Ejecting...")
MODULE_ACTIVATING = _("Activating...")
MODULE_UNPOWERED = _("Unpowered")
MODULE_DISCONNECTED = _("Disconnected")
MODULE_DISABLED = _("Paused")


class Ayaneo3Hidraw(GenericGamepadHidraw):

    def __init__(self, *args, vibration: str, config: Config, emit, **kwargs):
        super().__init__(*args, **kwargs)
        self.vibration = vibration
        self.config = config
        self.emit = emit

    def init(self):
        if not self.dev:
            return

        for cmd in AYA3_INIT:
            write_cmd(self.dev, to_bytes(cmd))

    def cfg(self):
        # Send init immediately after sleep
        if _cfg["mode"] is not None:
            self.send_cfg(reset=False)

    def send_cfg(self, reset: bool = False, left: bool = False, right: bool = False):
        cmds = get_cfg_commands(
            rgb_mode=_cfg["mode"] or "disabled",
            r=_cfg["red"],
            g=_cfg["green"],
            b=_cfg["blue"],
            brightness=_cfg["brightness"],
            reset=reset,
            eject_left=left,
            eject_right=right,
            vibration=self.vibration,  # type: ignore[call-arg]
        )
        for cmd in cmds:
            write_cmd(self.dev, cmd)

    def save(self):
        if not self.dev:
            return

        # Save current config
        write_cmd(self.dev, AYA_SAVE, timeout=AYA_SAVE_TIMEOUT)

    def reset(self):
        self.send_cfg(reset=True)
        time.sleep(0.5)
        self.send_cfg(reset=False)

    def check(self, init=False):
        for i in range(AYA_ATTEMPTS):
            res = write_cmd(self.dev, AYA_CHECK)
            if not res:
                time.sleep(0.3)
                continue
            left = res[32]
            right = res[33]
            if not right or not left:
                time.sleep(0.3)
                continue

            # left_module = left & 0x3F
            # left_rotated = left >> 6
            vl = LEFT_MODULES.get(left, MODULE_UKN)
            refresh = self.config.get("info_left", None) != vl
            self.config["info_left"] = vl
            # right_module = right & 0x3F
            # right_rotated = right >> 6
            vr = RIGHT_MODULES.get(right, MODULE_UKN)
            refresh |= self.config.get("info_right", None) != vr
            self.config["info_right"] = vr
            if refresh:
                self.emit([])
            break

        if res and res[18] == 1:
            logger.info("Switching into custom mode.")
            time.sleep(1)
            write_cmd(self.dev, AYA_CUSTOM)
            time.sleep(2)
            write_cmd(self.dev, AYA_CHECK)
            return True
        else:
            logger.info("Controller module check passed.")

    def eject(self, left: bool = False, right: bool = False):
        if left:
            self.config["info_left"] = MODULE_EJECTING
        if right:
            self.config["info_right"] = MODULE_EJECTING
        if left or right:
            self.emit([])

        self.send_cfg(reset=False, left=left, right=right)
        self.handle_eject()

    def handle_eject(self, throw=False):
        start = time.perf_counter()
        for _ in range(AYA_VERIFY_EJECT):
            res = write_cmd(self.dev, AYA_CHECK)
            time.sleep(0.4)
            # wait after last check too
            if res and res[19] & ~0x11 == 0:
                logger.info("Eject verified.")
                break

        time_waited = time.perf_counter() - start
        if time_waited < AYA_MIN_EJECT:
            time.sleep(AYA_MIN_EJECT - time_waited)

        if os.path.exists(CONTROLLER_POWER):
            with open(CONTROLLER_POWER, "w") as f:
                f.write("off")
            time.sleep(0.5)
            logger.info("Controller power turned off.")
        else:
            logger.warning("Kernel driver for modules is missing. Sleeping.")
            os.system("systemctl suspend")

        if throw:
            raise RuntimeError("Turned off controller. Restarting.")

    def consume(self, events):
        if not self.dev:
            return

        got_rgb = False
        for ev in events:
            if ev["type"] != "led":
                continue

            mode = ev["mode"]

            if mode not in ["disabled", "solid", "pulse", "rainbow"]:
                logger.error(f"Invalid RGB mode: {mode}")
                continue

            # Only send RGB command if colors change
            got_rgb = (
                _cfg["mode"] != mode
                or _cfg["red"] != ev["red"]
                or _cfg["green"] != ev["green"]
                or _cfg["blue"] != ev["blue"]
                or _cfg["brightness"] != ev.get("brightness", 1)
            )
            _cfg["mode"] = mode
            _cfg["red"] = ev["red"]
            _cfg["green"] = ev["green"]
            _cfg["blue"] = ev["blue"]
            _cfg["brightness"] = ev.get("brightness", 1)

        if got_rgb:
            self.send_cfg()


def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    others: Config,
):
    first = True
    first_disabled = True
    init = time.perf_counter()
    repeated_fail = False

    if others.get("info_left", None) is None:
        others["info_left"] = MODULE_UNPOWERED
    if others.get("info_right", None) is None:
        others["info_right"] = MODULE_UNPOWERED

    while not should_exit.is_set():
        if conf["controller_mode.mode"].to(str) == "disabled":
            # Disable module handling
            others["info_left"] = MODULE_DISABLED
            others["info_right"] = MODULE_DISABLED
            others.pop("reset", False)
            others.pop("pop", None)

            time.sleep(ERROR_DELAY)
            if first_disabled:
                UInputDevice.close_volume_cached()
                unhide_all()
            first_disabled = False
            continue
        else:
            first_disabled = True

        found_device = True
        if os.path.exists(CONTROLLER_MODULES):
            with open(CONTROLLER_MODULES, "r") as f:
                modules = f.read().strip()

            # Check if status should be refreshed
            refresh = False
            if modules == "both":
                found_device = True

                # Update status
                if others.get("info_right", None) in (
                    MODULE_DISCONNECTED,
                    MODULE_UNPOWERED,
                ):
                    others["info_right"] = MODULE_ACTIVATING
                    refresh = True
                if others.get("info_left", None) in (
                    MODULE_DISCONNECTED,
                    MODULE_UNPOWERED,
                ):
                    others["info_left"] = MODULE_ACTIVATING
                    refresh = True
            else:
                if first:
                    logger.info(
                        f"Controller modules are set to '{modules}', waiting for 'both' to be connected."
                    )
                found_device = False

                # Update status
                if modules != "left":
                    refresh |= others.get("info_left", None) != MODULE_DISCONNECTED
                    others["info_left"] = MODULE_DISCONNECTED
                if modules != "right":
                    refresh |= others.get("info_right", None) != MODULE_DISCONNECTED
                    others["info_right"] = MODULE_DISCONNECTED
                if modules == "right":
                    if others.get("info_right", None) == MODULE_DISCONNECTED:
                        others["info_right"] = MODULE_UNPOWERED
                        refresh = True
                if modules == "left":
                    if others.get("info_left", None) == MODULE_DISCONNECTED:
                        others["info_left"] = MODULE_UNPOWERED
                        refresh = True

                # Turning off controller power if not connected
                if os.path.exists(CONTROLLER_POWER):
                    with open(CONTROLLER_POWER, "w") as f:
                        f.write("off")

            if refresh:
                emit([])

        pop = others.pop("pop", None)
        if pop:
            others.pop("reset", False)
        if (found_device or pop) and os.path.exists(CONTROLLER_POWER):
            with open(CONTROLLER_POWER, "r") as f:
                power = f.read().strip()
            if power != "on":
                logger.info(
                    f"Controller power is set to '{power}', powering on controller."
                )
                with open(CONTROLLER_POWER, "w") as f:
                    f.write("on")
                time.sleep(1)

        if pop:
            logger.info(f"Popping controller module {pop}.")
            d_vend = Ayaneo3Hidraw(
                vid=[AYA_VID],
                pid=[AYA_PID],
                required=True,
                application=[0xFF000001],
                vibration=conf.get("vibration", "medium"),
                config=others,
                emit=emit,
            )
            try:
                d_vend.open()
                d_vend.eject(
                    left=pop in ["both", "left"], right=pop in ["both", "right"]
                )
                found_device = False
            except Exception as e:
                logger.error(f"Failed to pop controller module {pop} with error:\n{e}")
                if DEBUG_MODE:
                    raise e
            finally:
                d_vend.close(True)

        try:
            if not bool(enumerate_evs(vid=GAMEPAD_VID, pid=GAMEPAD_PID)):
                found_device = False
        except Exception:
            logger.warning("Failed finding device, skipping check.")
            time.sleep(LONGER_ERROR_DELAY)

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
            reset = others.pop("reset", False)
            controller_loop(
                conf.copy(), should_exit, updated, dconf, emit, others, reset
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
    conf: Config,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    emit: Emitter,
    others: Config,
    reset: bool = False,
):
    global _reset

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
        rgb_init_times=1,
        extra_buttons=dconf.get("extra_buttons", "dual"),
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
            EC("KEY_D"): "keyboard",
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
        vibration=conf.get("vibration", "medium"),
        config=others,
        emit=emit,
    )

    kargs = {}
    if dtype == "tecno":
        kargs = {
            "keyboard_is": "steam_qam",
            "qam_hhd": True,
        }

    match conf.get("swap_guide", "oem"):
        case "traditional":
            swap_guide = "aya_traditional"
        case "traditional_rev":
            swap_guide = "aya_traditional_rev"
        case _:
            swap_guide = None

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
        swap_guide=swap_guide,
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
        prepare(d_kbd_1)
        if d_kbd_2:
            prepare(d_kbd_2)
        for d in d_producers:
            prepare(d)

        prepare(d_vend)
        changed_mode = d_vend.check()
        if reset or _reset or changed_mode:
            d_vend.init()
            if not changed_mode:
                d_vend.reset()
            d_vend.save()
            reset = False
            _reset = False
        else:
            d_vend.cfg()

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
