# TODO: Add attribution and license
# created based on implementation from HandyGCCS
# https://github.com/ShadowBlip/HandyGCCS/blob/10bf0da2bbe06b4e6c608e157f26628b6d848042/src/handycon/utilities.py

import logging
import os
import select
import subprocess
from time import perf_counter, sleep
from typing import Sequence, cast

import evdev
from evdev import ecodes as e

logger = logging.getLogger(__name__)

POWER_BUTTON_NAMES = ["Power Button"]
POWER_BUTTON_PHYS = ["LNXPWRBN/button/input0", "PNP0C0C/button/input0"]
STEAM_PID = os.path.expanduser("~/.steam/steam.pid")
STEAM_EXE = os.path.expanduser("~/.steam/root/ubuntu12_32/steam")
STEAM_WAIT_DELAY = 2
LONG_PRESS_DELAY = 2.5


def B(b: str):
    return cast(int, getattr(evdev.ecodes, b))


def is_steam_gamescope_running():
    pid = None
    try:
        with open(STEAM_PID) as f:
            pid = f.read().strip()

        steam_cmd_path = f"/proc/{pid}/cmdline"
        if not os.path.exists(steam_cmd_path):
            return False

        # Use this and line to determine if Steam is running in DeckUI mode.
        with open(steam_cmd_path, "rb") as f:
            steam_cmd = f.read()
        is_deck_ui = b"-gamepadui" in steam_cmd
        if not is_deck_ui:
            return False
    except Exception as e:
        return False
    return True


def run_steam_command(command: str):
    global home_path
    try:
        result = subprocess.run([STEAM_EXE, "-ifrunning", command])
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Received error when running steam command `{command}`\n{e}")
    return False


def register_power_button() -> evdev.InputDevice | None:
    for device in [evdev.InputDevice(path) for path in evdev.list_devices()]:
        if device.name in POWER_BUTTON_NAMES and device.phys in POWER_BUTTON_PHYS:
            device.grab()
            logger.info(f"Captured power button '{device.name}': '{device.phys}'")
            return device
    return None


def run_steam_shortpress():
    return run_steam_command("steam://shortpowerpress")


def run_steam_longpress():
    return run_steam_command("steam://longpowerpress")


def power_button_run(**conf):
    power_button_timer()


def power_button_timer():
    dev = None
    try:
        pressed_time = None
        while True:
            # Initial check for steam
            if not is_steam_gamescope_running():
                # Close devices
                if dev:
                    dev.close()
                    dev = None
                logger.info(f"Waiting for steam to launch.")
                while not is_steam_gamescope_running():
                    sleep(STEAM_WAIT_DELAY)

            if not dev:
                logger.info(f"Steam is running, hooking power button.")
                dev = register_power_button()
            if not dev:
                logger.error(f"Power button not found, disabling plugin.")
                return

            # Add timeout to release the button if steam exits.
            delay = LONG_PRESS_DELAY if pressed_time else STEAM_WAIT_DELAY
            r = select.select([dev.fd], [], [], delay)[0]

            # Handle press logic
            if r:
                # Handle button event
                ev = dev.read_one()
                logger.info(ev)
                if ev.type == B("EV_KEY"):
                    logger.info(ev)
                if ev.type == B("EV_KEY") and ev.code == B("KEY_POWER"):
                    curr_time = perf_counter()
                    if ev.value:
                        pressed_time = curr_time
                        press_type = "initial_press"
                    elif pressed_time:
                        if curr_time - pressed_time > LONG_PRESS_DELAY:
                            press_type = "long_press"
                        else:
                            press_type = "short_press"
                        pressed_time = None
                    else:
                        press_type = "release_without_press"
                else:
                    press_type = "no_press"
            elif pressed_time:
                # Button was pressed but we hit a timeout, that means
                # it is a long press
                press_type = "long_press"
            else:
                # Otherwise, no press
                press_type = "no_press"

            issue_systemctl = False
            match press_type:
                case "long_press":
                    logger.info("Executing long press.")
                    issue_systemctl = not run_steam_longpress()
                case "short_press":
                    logger.info("Executing short press.")
                    issue_systemctl = not run_steam_shortpress()
                case "initial_press":
                    logger.info("Power button pressed down.")
                case "release_without_press":
                    logger.error("Button released without being pressed.")

            if issue_systemctl:
                logger.error(
                    "Power button action did not work. Calling `systemctl suspend`"
                )
                os.system("systemctl suspend")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Received exception, exitting:\n{e}")
    finally:
        if dev:
            dev.close()
