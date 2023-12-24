import argparse
import logging
import os
from multiprocessing import Process
from os.path import join
from threading import Condition, Lock
from typing import Sequence

import pkg_resources

from .logging import setup_logger
from .plugins import Emitter, Event, HHDAutodetect, HHDPlugin
from .plugins.settings import (
    load_state_yaml,
    load_profile_yaml,
    save_profile_yaml,
    save_state_yaml,
    merge_settings,
)
from .utils import expanduser, get_context, fix_perms

logger = logging.getLogger(__name__)

CONFIG_DIR = os.environ.get("HHD_CONFIG_DIR", "~/.config/hhd")

ERROR_DELAY = 5


class EmitHolder(Emitter):
    def __init__(self) -> None:
        self._events = []
        self._lock = Lock()
        self._condition = Condition(self._lock)

    def __call__(self, event: Event | Sequence[Event]) -> None:
        with self._lock:
            if isinstance(event, Sequence):
                self._events.extend(event)
            else:
                self._events.append(event)
            self._condition.notify_all()

    def get_events(self, timeout: int = -1):
        with self._lock:
            if not self._events and timeout != -1:
                self._condition.wait()
            ev = self._events
            self._events = []
            return ev


def main(user: str | None = None):
    # Setup temporary logger for permission retrieval
    ctx = get_context(user)
    if not ctx:
        print(f"Could not get user information. Exiting...")
        return

    detectors: dict[str, HHDAutodetect] = {}
    plugins: dict[str, Sequence[HHDPlugin]] = {}
    try:
        setup_logger(join(CONFIG_DIR, "log"), ctx=ctx)

        for autodetect in pkg_resources.iter_entry_points("hhd.plugins"):
            detectors[autodetect.name] = autodetect.resolve()

        logger.info(f"Found plugin providers: {', '.join(list(detectors))}")

        logger.info(f"Running autodetection...")
        for name, autodetect in detectors.items():
            plugins[name] = autodetect([])

        plugin_str = "Loaded the following plugins:"
        for pkg_name, sub_plugins in plugins.items():
            plugin_str += (
                f"\n  - {pkg_name:>15s}: {', '.join(p.name for p in sub_plugins)}"
            )
        logger.info(plugin_str)

        # Get sorted plugins
        sorted_plugins: Sequence[HHDPlugin] = []
        for plugs in plugins.values():
            sorted_plugins.extend(plugs)
        sorted_plugins.sort(key=lambda x: x.priority)

        if not sorted_plugins:
            logger.error(f"No plugins started, exiting...")
            return

        # Open plugins
        emit = EmitHolder()
        for p in sorted_plugins:
            p.open(emit, ctx)

        # Compile initial configuration
        settings = merge_settings([p.settings() for p in sorted_plugins])
        state_fn = expanduser(join(CONFIG_DIR, "state.yml"), ctx)
        conf = load_state_yaml(state_fn, settings)

        # Load profiles
        profiles = {}
        profile_dir = expanduser(join(CONFIG_DIR, "profiles"), ctx)
        os.makedirs(profile_dir, exist_ok=True)
        fix_perms(profile_dir, ctx)
        for fn in os.listdir(profile_dir):
            if not fn.endswith(".yml"):
                continue
            name = fn.replace(".yml", "")
            profiles[name] = load_profile_yaml(join(profile_dir, fn))
        if profiles:
            logger.info(f"Loaded the following profiles:\n[{', '.join(profiles)}]")
        else:
            logger.info(f"No profiles found.")

        if save_state_yaml(state_fn, settings, conf):
            fix_perms(state_fn, ctx)
        for name, prof in profiles.items():
            fn = join(profile_dir, name + ".yml")
            if save_profile_yaml(fn, settings, prof):
                fix_perms(fn, ctx)

        # from rich import get_console

        # get_console().print(conf.conf)
        # get_console().print(settings)

        # logger.info(f"Monitoring plugin status, and restarting if necessary.")
        # while True:
        #     exited = select.select(list(running_plugins), [], [])[0]
        #     for fd in exited:
        #         pkg_name, plugin, proc = running_plugins.pop(fd)
        #         if not proc.exitcode:
        #             # Plugin exited normally, not restarting
        #             logger.info(f"Plugin '{plugin['name']}' exited normally.")
        #             continue

        #         logger.error(
        #             f"Plugin '{plugin['name']}' crashed. Restarting in {ERROR_DELAY}s."
        #         )
        #         time.sleep(ERROR_DELAY)
        #         proc = launch_plugin(pkg_name, plugin, perms)
        #         if proc:
        #             running_plugins[proc.sentinel] = (pkg_name, plugin, proc)
        #     time.sleep(ERROR_DELAY)
    except KeyboardInterrupt:
        logger.info(
            f"HHD Daemon received KeyboardInterrupt, stopping plugins and exiting."
        )
    finally:
        for plugs in plugins.values():
            for plug in plugs:
                plug.close()


if __name__ == "__main__":
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
    main(user)
