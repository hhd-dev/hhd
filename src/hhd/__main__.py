import argparse
import logging
import os
import select
import shutil
import subprocess
import time
from multiprocessing import Process
from os.path import join
from typing import NamedTuple

import pkg_resources
import yaml

from .logging import setup_logger
from .plugins import HHDPluginV1
from .utils import Perms, expanduser, get_perms, switch_priviledge

logger = logging.getLogger(__name__)

CONFIG_DIR = os.environ.get("HHD_CONFIG_DIR", "~/.config/hhd")

ERROR_DELAY = 5


def launch_plugin(pkg_name: str, plugin: HHDPluginV1, perms: Perms):
    plugin_dir = expanduser(join(CONFIG_DIR, "plugins"), perms)

    if plugin["config"]:
        cfg_fn = join(plugin_dir, plugin["name"] + ".yaml")

        if not plugin["autodetect"]():
            logger.debug(f"Plugin '{plugin['name']}' determined it should not run.")
            return None

        if not os.path.isfile(cfg_fn):
            logger.warn(
                f"Config file for plugin '{plugin['name']}' not found below, using default:\n{cfg_fn}"
            )
            os.makedirs(plugin_dir, exist_ok=True)
            shutil.copy(plugin["config"], cfg_fn)

        with open(cfg_fn, "r") as f:
            cfg = yaml.safe_load(f)

        if "config_version" in plugin and plugin["config_version"] != cfg.get(
            "version", 0
        ):
            logger.warn(
                f"Config file for plugin '{plugin['name']}' is outdated, replacing with default:\n{cfg_fn}"
            )
            os.makedirs(plugin_dir, exist_ok=True)
            shutil.copy(plugin["config"], cfg_fn)

            with open(cfg_fn, "r") as f:
                cfg = yaml.safe_load(f)
    else:
        cfg = {}

    # Add perms in case a plugin needs them
    cfg = {**cfg, "perms": perms}

    logger.info(f"Launching plugin {pkg_name}.{plugin['name']}")

    # Run plugin priviledged, in case it does not deal with the user
    switch_priviledge(perms, True)
    proc = Process(target=plugin["run"], kwargs=cfg)
    proc.start()
    switch_priviledge(perms, False)

    return proc


def main():
    # Set up permissions
    parser = argparse.ArgumentParser(
        prog="HHD: Handheld Daemon main interface.",
        description="Handheld Daemon is a daemon for managing the quirks inherent in handheld devices.",
    )
    parser.add_argument(
        "-u",
        "--user",
        default=None,
        help="The user whose home directory will be used to store the files (~/.config/hhd).",
        dest="user",
    )
    args = parser.parse_args()
    user = args.user

    # Setup temporary logger for permission retreival
    perms = get_perms(user)
    if not perms:
        print(f"Could not get user information. Exiting...")
        return

    running_plugins: dict[int, tuple[str, HHDPluginV1, Process]] = {}
    try:
        # Drop privileges for initial set-up
        switch_priviledge(perms, False)
        setup_logger(
            join(CONFIG_DIR, "log"), perms=perms
        )

        plugins = {}
        for plugin in pkg_resources.iter_entry_points("hhd.plugins"):
            plugins[plugin.name] = plugin.resolve()

        logger.info(f"Found plugin providers: {', '.join(list(plugins))}")
        plugin_str = "With the following plugins:"
        for pkg_name, sub_plugins in plugins.items():
            plugin_str += (
                f"\n  - {pkg_name:>15s}: {', '.join(p['name'] for p in sub_plugins)}"
            )
        logger.info(plugin_str)

        for pkg_name, sub_plugins in plugins.items():
            for plugin in sub_plugins:
                proc = launch_plugin(pkg_name, plugin, perms)
                if proc:
                    running_plugins[proc.sentinel] = (pkg_name, plugin, proc)

        if not running_plugins:
            logger.error(f"No plugins started, exiting...")
            return

        logger.info(f"Monitoring plugin status, and restarting if necessary.")
        while True:
            exited = select.select(list(running_plugins), [], [])[0]
            for fd in exited:
                pkg_name, plugin, proc = running_plugins.pop(fd)
                if not proc.exitcode:
                    # Plugin exited normally, not restarting
                    logger.info(f"Plugin '{plugin['name']}' exited normally.")
                    continue

                logger.error(
                    f"Plugin '{plugin['name']}' crashed. Restarting in {ERROR_DELAY}s."
                )
                time.sleep(ERROR_DELAY)
                proc = launch_plugin(pkg_name, plugin, perms)
                if proc:
                    running_plugins[proc.sentinel] = (pkg_name, plugin, proc)
            time.sleep(ERROR_DELAY)
    except KeyboardInterrupt:
        logger.info(
            f"HHD Daemon received KeyboardInterrupt, stopping plugins and exiting."
        )
    finally:
        for _, _, process in running_plugins.values():
            process.terminate()
            process.join()


if __name__ == "__main__":
    main()
