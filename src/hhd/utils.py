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
        case _:
            return 30


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

    for name in DISTRO_NAMES:
        if name in os_release:
            logger.info(f"Running under Linux distro '{name}'.")
            return name

    logger.info(f"Running under an unknown Linux distro.")
    return "ukn"


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
]
