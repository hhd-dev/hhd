import logging
import os

from hhd.plugins.plugin import (
    Context,
    expanduser,
    fix_perms,
    get_context,
    is_steam_gamepad_running,
    restore_priviledge,
    run_steam_command,
    switch_priviledge,
)

logger = logging.getLogger(__name__)

DISTRO_NAMES = ("manjaro", "bazzite", "ubuntu", "arch")
GIT_HHD = "git+https://github.com/hhd-dev/hhd"
GIT_ADJ = "git+https://github.com/hhd-dev/adjustor"
HHD_DEV_DIR = "/run/hhd/dev"


def get_distro_color():
    match get_os():
        case "manjaro":
            return 115
        case "bazzite":
            return 265
        case "arch":
            return 195
        case "ubuntu":
            return 340
        case "red_gold" | "red_gold_ba":
            return 28
        case "blood_orange" | "blood_orange_ba":
            return 18
        case _:
            return 30


def hsb_to_rgb(h: int, s: int | float, v: int | float):
    # https://www.rapidtables.com/convert/color/hsv-to-rgb.html
    if h >= 360:
        h = 359
    s = s / 100
    v = v / 100

    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c

    if h < 60:
        rgb = (c, x, 0)
    elif h < 120:
        rgb = (x, c, 0)
    elif h < 180:
        rgb = (0, c, x)
    elif h < 240:
        rgb = (0, x, c)
    elif h < 300:
        rgb = (x, 0, c)
    else:
        rgb = (c, 0, x)

    return [int((v + m) * 255) for v in rgb]


def get_os() -> str:
    if name := os.environ.get("HHD_DISTRO", None):
        logger.warning(f"Distro override using an environment variable to '{name}'.")
        return name

    try:
        with open("/etc/os-release") as f:
            os_release = f.read().strip().lower()
    except Exception as e:
        logger.error(f"Could not read os information, error:\n{e}")
        return "ukn"

    distro = None
    for name in DISTRO_NAMES:
        if name in os_release:
            logger.info(f"Running under Linux distro '{name}'.")
            distro = name

    try:
        # Match just product name
        # if a device exists here its officially supported
        with open("/sys/devices/virtual/dmi/id/product_name") as f:
            dmi = f.read().strip()

        # if "jupiter" in dmi.lower() or "onexplayer" in dmi.lower():
        #     if distro == "bazzite":
        #         distro = "blood_orange_ba"
        #     else:
        #         distro = "blood_orange"

        if "ONEXPLAYER F1 EVA-02" in dmi:
            if distro == "bazzite":
                distro = "red_gold_ba"
            else:
                distro = "red_gold"
    except Exception as e:
        logger.error(f"Could not read product name, error:\n{e}")

    if distro is not None:
        return distro

    logger.info(f"Running under an unknown Linux distro.")
    return "ukn"


def get_ac_status_fn() -> str | None:
    BASE_DIR = "/sys/class/power_supply"
    fn = None
    try:
        for name in os.listdir(BASE_DIR):
            if name.startswith("AC") or name.startswith("ADP"):
                fn = name
                break
        if fn is None:
            logger.error(
                f"Could not find AC status file. Power supply directory:\n{os.listdir(BASE_DIR)}"
            )
            return None

        return os.path.join(BASE_DIR, fn, "online")
    except Exception as e:
        logger.error(f"Could not read power supply directory, error:\n{e}")
        return None


def get_ac_status(fn: str | None) -> bool | None:
    if fn is None:
        return None
    if not os.path.exists(fn):
        return None
    try:
        with open(fn) as f:
            return f.read().strip() != "Discharging"
    except Exception as e:
        return None


__all__ = [
    "get_os",
    "is_steam_gamepad_running",
    "fix_perms",
    "expanduser",
    "restore_priviledge",
    "switch_priviledge",
    "get_context",
    "Context",
    "run_steam_command",
    "get_ac_status",
    "get_ac_status_fn",
]
