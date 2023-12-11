import logging
import os
import select
import shutil

from multiprocessing import Process
import time

import pkg_resources
import yaml

from hhd import setup_logger
from .plugins import HHDPluginV1

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.expanduser(
    os.path.join(os.environ.get("HHD_CONFIG_DIR", "~/.config/hhd"), "plugins")
)

ERROR_DELAY = 5


def launch_plugin(pkg_name: str, plugin: HHDPluginV1):
    if plugin["config"]:
        cfg_fn = os.path.join(CONFIG_DIR, plugin["name"] + ".yaml")

        if not plugin["autodetect"]():
            logger.debug(f"Plugin '{plugin['name']}' determined it should not run.")
            return None

        if not os.path.isfile(cfg_fn):
            logger.warn(
                f"Config file for plugin '{plugin['name']}' not found below, using default:\n{cfg_fn}"
            )
            os.makedirs(CONFIG_DIR, exist_ok=True)
            shutil.copy(plugin["config"], cfg_fn)

        with open(cfg_fn, "r") as f:
            cfg = yaml.safe_load(f)

        if "config_version" in plugin and plugin["config_version"] != cfg.get(
            "version", 0
        ):
            logger.warn(
                f"Config file for plugin '{plugin['name']}' is outdated, replacing with default:\n{cfg_fn}"
            )
            os.makedirs(CONFIG_DIR, exist_ok=True)
            shutil.copy(plugin["config"], cfg_fn)

            with open(cfg_fn, "r") as f:
                cfg = yaml.safe_load(f)
    else:
        cfg = {}

    logger.info(f"Launching plugin {pkg_name}.{plugin['name']}")
    proc = Process(target=plugin["run"], kwargs=cfg)
    proc.start()
    return proc


def main():
    running_plugins: dict[int, tuple[str, HHDPluginV1, Process]] = {}
    try:
        setup_logger()
        plugins = {}
        for plugin in pkg_resources.iter_entry_points("hhd.plugins"):
            plugins[plugin.name] = plugin.resolve()

        logger.info(f"Found plugin providers: {','.join(list(plugins))}")
        plugin_str = "With the following plugins:"
        for pkg_name, sub_plugins in plugins.items():
            plugin_str += (
                f"\n  - {pkg_name:10s}: {', '.join(p['name'] for p in sub_plugins)}"
            )
        logger.info(plugin_str)

        for pkg_name, sub_plugins in plugins.items():
            for plugin in sub_plugins:
                proc = launch_plugin(pkg_name, plugin)
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
                proc = launch_plugin(pkg_name, plugin)
                if proc:
                    running_plugins[proc.sentinel] = (pkg_name, plugin, proc)
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
