import logging
import os
import shutil
from typing import NamedTuple

logger = logging.getLogger(__name__)

HOME_PATH = "/home"
DISABLED_PATH = "homebrew/plugins/hhd-disabled"
CONFLICTING_PLUGINS = {
    "SimpleDeckyTDP": "homebrew/plugins/SimpleDeckyTDP",
    "PowerControl": "homebrew/plugins/PowerControl",
}


class DeckyPlugin(NamedTuple):
    name: str
    path: str


def find_decky_plugins(home_path: str = HOME_PATH) -> list[DeckyPlugin]:
    found = []
    for user in os.listdir(home_path):
        for name, relative_path in CONFLICTING_PLUGINS.items():
            path = os.path.join(home_path, user, relative_path)
            if os.path.exists(path):
                found.append(DeckyPlugin(name=name, path=path))
    return found


def disable_decky_plugins(home_path: str = HOME_PATH):
    logger.warning("Stopping Decky.")
    try:
        os.system("systemctl stop plugin_loader")
    except Exception as e:
        logger.error(f"Failed to stop Decky:\n{e}")

    try:
        for user in os.listdir(home_path):
            move_path = os.path.join(home_path, user, DISABLED_PATH)
            if os.path.exists(move_path):
                logger.warning(f"Removing old backup path: '{move_path}'")
                shutil.rmtree(move_path)
            os.makedirs(move_path, exist_ok=True)

            for name, relative_path in CONFLICTING_PLUGINS.items():
                path = os.path.join(home_path, user, relative_path)
                if not os.path.exists(path):
                    continue
                new_path = os.path.join(move_path, name)
                logger.warning(f"Moving plugin '{name}' from:\n{path}\nto:\n{new_path}")
                os.rename(path, new_path)
    finally:
        logger.warning("Restarting Decky.")
        try:
            os.system("systemctl start plugin_loader")
        except Exception as e:
            logger.error(f"Failed to restart Decky:\n{e}")
