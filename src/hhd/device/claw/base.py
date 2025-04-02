import logging
import select
import time
from threading import Event as TEvent

from hhd.controller import DEBUG_MODE, Multiplexer, can_read
from hhd.controller.lib.hide import unhide_all
from hhd.controller.physical.hidraw import GenericGamepadHidraw
from hhd.controller.physical.evdev import B as EC
from hhd.controller.physical.evdev import GenericGamepadEvdev, enumerate_evs
from hhd.controller.virtual.uinput import UInputDevice
from hhd.plugins import Config, Context, Emitter, get_outputs
from hhd.controller.physical.evdev import DINPUT_AXIS_POSTPROCESS, AbsAxis
from hhd.controller.physical.evdev import (
    GamepadButton,
    GenericGamepadEvdev,
    enumerate_evs,
    to_map,
)
from typing import Sequence
from hhd.controller import DEBUG_MODE, Event, Multiplexer

from .const import MSI_CLAW_MAPPINGS

FIND_DELAY = 0.1
ERROR_DELAY = 0.3
LONGER_ERROR_DELAY = 3
LONGER_ERROR_MARGIN = 1.3

logger = logging.getLogger(__name__)

CLAW_SET_DINPUT = bytes([0x0F, 0x00, 0x00, 0x3C, 0x24, 0x02])

MSI_CLAW_VID = 0x0DB0
MSI_CLAW_XINPUT_PID = 0x1901
MSI_CLAW_DINPUT_PID = 0x1902

KBD_VID = 0x0001
KBD_PID = 0x0001

BACK_BUTTON_DELAY = 0.1


def set_rgb_cmd(brightness, red, green, blue):
    return bytes(
        [
            # Preamble
            0x0F,
            0x00,
            0x00,
            0x3C,
            # Write first profile
            0x21,
            0x01,
            # Start at
            0x01,
            0xFA,
            # Write 31 bytes
            0x20,
            # Index, Frame num, Effect, Speed, Brightness
            0x00,
            0x01,
            0x09,
            0x03,
            max(0, min(100, int(brightness * 100))),
        ]
    ) + 9 * bytes([red, green, blue])


class ClawDInputHidraw(GenericGamepadHidraw):

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.init = False

    def consume(self, events: Sequence[Event]) -> None:
        if not self.dev:
            return

        for ev in events:
            if ev["type"] == "rumble" and ev["code"] == "main":
                # Same as dualshock 4
                # "0501 0000 right left"
                cmd = bytes(
                    [
                        0x05,
                        0x01,
                        0x00,
                        0x00,
                        min(255, int(ev["weak_magnitude"] * 255)),
                        min(255, int(ev["strong_magnitude"] * 255)),
                    ]
                )
                self.dev.write(cmd)
            elif ev["type"] == "led":
                if ev["mode"] == "solid":
                    cmd = set_rgb_cmd(
                        ev["brightness"],
                        ev["red"],
                        ev["green"],
                        ev["blue"],
                    )
                    self.dev.write(cmd)
                elif ev["mode"] == "disabled":
                    cmd = set_rgb_cmd(
                        0,
                        0,
                        0,
                        0,
                    )
                    self.dev.write(cmd)

    def set_dinput_mode(self):
        if not self.dev:
            return

        # Set the device to dinput mode
        self.dev.write(CLAW_SET_DINPUT)


DINPUT_BUTTON_MAP: dict[int, GamepadButton] = to_map(
    {
        # Gamepad
        "a": [EC("BTN_B")],
        "b": [EC("BTN_C")],
        "x": [EC("BTN_A")],
        "y": [EC("BTN_NORTH")],
        # Sticks
        "ls": [EC("BTN_SELECT")],
        "rs": [EC("BTN_START")],
        # Bumpers
        "lb": [EC("BTN_WEST")],
        "rb": [EC("BTN_Z")],
        # Select
        "start": [EC("BTN_TR2")],
        "select": [EC("BTN_TL2")],
        # Misc
        "extra_l1": [EC("BTN_TRIGGER_HAPPY")],
        "extra_r1": [0x013F],
    }
)
DINPUT_AXIS_MAP: dict[int, AbsAxis] = to_map(
    {
        # Sticks
        # Values should range from -1 to 1
        "ls_x": [EC("ABS_X")],
        "ls_y": [EC("ABS_Y")],
        "rs_x": [EC("ABS_Z")],
        "rs_y": [EC("ABS_RZ")],
        # Triggers
        # Values should range from -1 to 1
        "rt": [EC("ABS_RX")],
        "lt": [EC("ABS_RY")],
        # Hat, implemented as axis. Either -1, 0, or 1
        "hat_x": [EC("ABS_HAT0X")],
        "hat_y": [EC("ABS_HAT0Y")],
    }
)


def plugin_run(
    conf: Config,
    emit: Emitter,
    context: Context,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    woke_up: TEvent,
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
            is_xinput = bool(enumerate_evs(vid=MSI_CLAW_VID, pid=MSI_CLAW_XINPUT_PID))
            found_device = bool(
                enumerate_evs(vid=MSI_CLAW_VID, pid=MSI_CLAW_DINPUT_PID)
            )
        except Exception:
            logger.warning("Failed finding device, skipping check.")
            time.sleep(LONGER_ERROR_DELAY)
            found_device = True
            is_xinput = False

        if is_xinput:
            d_vend = ClawDInputHidraw(
                vid=[MSI_CLAW_VID],
                pid=[MSI_CLAW_XINPUT_PID],
                usage_page=[0xFFA0],
                usage=[0x0001],
                required=True,
            )
            try:
                d_vend.open()
                d_vend.set_dinput_mode()
                d_vend.close(True)
                time.sleep(2)
            except Exception as e:
                logger.error(f"Failed to set device into dinput mode.\n{type(e)}: {e}")
                time.sleep(1)

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
            controller_loop(conf.copy(), should_exit, updated, dconf, emit, woke_up)
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


class DesktopDetectorEvdev(GenericGamepadEvdev):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.desktop = False

    def produce(self, fds: Sequence[int]):
        if not self.dev or self.fd not in fds:
            return []

        while can_read(self.fd):
            for e in self.dev.read():
                self.desktop = True

        return []


def controller_loop(
    conf: Config,
    should_exit: TEvent,
    updated: TEvent,
    dconf: dict,
    emit: Emitter,
    woke_up: TEvent,
):
    debug = DEBUG_MODE

    # Output
    d_producers, d_outs, d_params = get_outputs(
        conf["controller_mode"],
        None,
        emit=emit,
        rgb_modes={"disabled": [], "solid": ["color"]},
    )

    # Inputs
    d_xinput = GenericGamepadEvdev(
        vid=[MSI_CLAW_VID],
        pid=[MSI_CLAW_DINPUT_PID],
        # name=["Generic X-Box pad"],
        capabilities={EC("EV_KEY"): [EC("BTN_A")]},
        required=True,
        hide=True,
        btn_map=DINPUT_BUTTON_MAP,
        axis_map=DINPUT_AXIS_MAP,
        postprocess=DINPUT_AXIS_POSTPROCESS,
    )

    d_kbd_1 = GenericGamepadEvdev(
        vid=[KBD_VID],
        pid=[KBD_PID],
        required=False,
        grab=True,
        btn_map=dconf.get("btn_mapping", MSI_CLAW_MAPPINGS),
    )

    # Mute these so after suspend we do not get stray keypresses
    d_kbd_2 = DesktopDetectorEvdev(
        vid=[MSI_CLAW_VID],
        pid=[MSI_CLAW_DINPUT_PID],
        required=False,
        grab=True,
        capabilities={EC("EV_KEY"): [EC("KEY_ESC")]},
    )
    d_mouse = DesktopDetectorEvdev(
        vid=[MSI_CLAW_VID],
        pid=[MSI_CLAW_DINPUT_PID],
        required=False,
        grab=True,
        capabilities={EC("EV_KEY"): [EC("BTN_MOUSE")]},
    )

    kargs = {}

    multiplexer = Multiplexer(
        trigger="analog_to_discrete",
        dpad="analog_to_discrete",
        share_to_qam=True,
        select_reboots=conf.get("select_reboots", False),
        nintendo_mode=conf["nintendo_mode"].to(bool),
        emit=emit,
        params=d_params,
        startselect_chord=conf.get("main_chords", "disabled"),
        swap_guide="select_is_guide" if conf["swap_guide"].to(bool) else None,
        keyboard_no_release=True,
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

    d_vend = ClawDInputHidraw(
        vid=[MSI_CLAW_VID],
        pid=[MSI_CLAW_DINPUT_PID],
        usage_page=[0xFFF0],
        usage=[0x0040],
        required=True,
    )

    REPORT_FREQ_MIN = 25
    REPORT_FREQ_MAX = 400

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
        prepare(d_volume_btn)
        prepare(d_kbd_1)
        prepare(d_kbd_2)
        prepare(d_mouse)
        for d in d_producers:
            prepare(d)
        prepare(d_vend)

        logger.info("Emulated controller launched, have fun!")
        switch_to_dinput = None
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

            # Detect if we are in desktop mode through events
            desktop_mode = d_mouse.desktop or d_kbd_2.desktop
            d_mouse.desktop = False
            d_kbd_2.desktop = False

            if desktop_mode or (switch_to_dinput and start > switch_to_dinput):
                logger.info("Setting controller to dinput mode.")
                d_vend.set_dinput_mode()
                switch_to_dinput = None
            # elif woke_up.is_set():
            #     woke_up.clear()
            #     # Switch to dinput after 4 seconds without input to avoid
            #     # being stuck in desktop mode, as not all buttons trigger
            #     # the other quirk (especially bumpers)
            #     switch_to_dinput = time.perf_counter() + 4

            evs = multiplexer.process(evs)
            if evs:
                switch_to_dinput = None
                if debug:
                    logger.info(evs)

                d_volume_btn.consume(evs)
                d_xinput.consume(evs)
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
        d_vend.close(not updated.is_set())
        for d in reversed(devs):
            try:
                d.close(not updated.is_set())
            except Exception as e:
                logger.error(f"Error while closing device '{d}' with exception:\n{e}")
                if debug:
                    raise e
