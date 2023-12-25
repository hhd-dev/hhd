import argparse
import fcntl
import logging
import os
from os.path import join
from select import select
from threading import Condition, Lock, Event as TEvent
from time import sleep
from typing import Sequence
import signal
import pkg_resources

from .logging import setup_logger, set_log_plugin, update_log_plugins
from .plugins import Emitter, Event, HHDAutodetect, HHDPlugin
from .plugins.settings import (
    load_profile_yaml,
    load_state_yaml,
    merge_settings,
    save_profile_yaml,
    save_state_yaml,
)
from .utils import expanduser, fix_perms, get_context

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


def main():
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

    # Setup temporary logger for permission retrieval
    ctx = get_context(user)
    if not ctx:
        print(f"Could not get user information. Exiting...")
        return

    detectors: dict[str, HHDAutodetect] = {}
    plugins: dict[str, Sequence[HHDPlugin]] = {}
    log_plugins: Sequence[tuple[str, str]] = []
    log_plugins.append(("hhd", "main"))
    cfg_fds = []
    try:
        set_log_plugin("main")
        setup_logger(join(CONFIG_DIR, "log"), ctx=ctx)

        for autodetect in pkg_resources.iter_entry_points("hhd.plugins"):
            log_plugins.append((autodetect.module_name, autodetect.name))
            detectors[autodetect.name] = autodetect.resolve()

        logger.info(f"Found plugin providers: {', '.join(list(detectors))}")

        logger.info(f"Running autodetection...")
        for name, autodetect in detectors.items():
            plugins[name] = autodetect([])

        plugin_str = "Loaded the following plugins:"
        for pkg_name, sub_plugins in plugins.items():
            plugin_str += (
                f"\n  - {pkg_name:>8s}: {', '.join(p.name for p in sub_plugins)}"
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
            set_log_plugin(getattr(p, "log") if hasattr(p, "log") else "ukwn")
            p.open(emit, ctx)
            update_log_plugins()
        set_log_plugin("main")

        # Compile initial configuration
        settings = merge_settings([p.settings() for p in sorted_plugins])
        state_fn = expanduser(join(CONFIG_DIR, "state.yml"), ctx)

        # Load profiles
        profiles = {}
        templates = {}
        conf = load_state_yaml(state_fn, settings)
        profile_dir = expanduser(join(CONFIG_DIR, "profiles"), ctx)
        os.makedirs(profile_dir, exist_ok=True)
        fix_perms(profile_dir, ctx)

        # Monitor config files for changes
        initialized = TEvent()
        should_exit = TEvent()
        signal.signal(signal.SIGPOLL, lambda sig, frame: initialized.clear())
        signal.signal(signal.SIGINT, lambda sig, frame: should_exit.set())
        signal.signal(signal.SIGTERM, lambda sig, frame: should_exit.set())

        while not should_exit.is_set():
            #
            # Configuration
            #

            # Initialize if files changed
            if not initialized.is_set():
                set_log_plugin("main")
                logger.info(f"Reloading configuration.")
                conf = load_state_yaml(state_fn, settings)
                profiles = {}
                templates = {}

                for fn in os.listdir(profile_dir):
                    if not fn.endswith(".yml"):
                        continue
                    name = fn.replace(".yml", "")
                    s = load_profile_yaml(join(profile_dir, fn))
                    if name.startswith("_"):
                        templates[name] = s
                    else:
                        profiles[name] = s
                if profiles:
                    logger.info(
                        f"Loaded the following profiles (and state):\n[{', '.join(profiles)}]"
                    )
                else:
                    logger.info(f"No profiles found.")

                # Monitor files for changes
                for fd in cfg_fds:
                    try:
                        os.close(fd)
                    except Exception:
                        pass
                cfg_fds = []
                cfg_fns = [
                    CONFIG_DIR,
                    join(CONFIG_DIR, "profiles"),
                ]
                for fn in cfg_fns:
                    fd = os.open(expanduser(fn, ctx), os.O_RDONLY)
                    fcntl.fcntl(
                        fd,
                        fcntl.F_NOTIFY,
                        fcntl.DN_CREATE | fcntl.DN_DELETE | fcntl.DN_MODIFY,
                    )
                    cfg_fds.append(fd)
                initialized.set()
                logger.info(f"Initialization Complete!")

            #
            # Plugin loop
            #

            for p in reversed(sorted_plugins):
                set_log_plugin(getattr(p, "log") if hasattr(p, "log") else "ukwn")
                p.prepare(conf)
                update_log_plugins()

            for p in sorted_plugins:
                set_log_plugin(getattr(p, "log") if hasattr(p, "log") else "ukwn")
                p.update(conf)
                update_log_plugins()
            set_log_plugin("ukwn")

            # Save existing profiles if open
            if save_state_yaml(state_fn, settings, conf):
                fix_perms(state_fn, ctx)
            for name, prof in profiles.items():
                fn = join(profile_dir, name + ".yml")
                if save_profile_yaml(fn, settings, prof):
                    fix_perms(fn, ctx)

            # Add template config
            if save_profile_yaml(
                join(profile_dir, "_template.yml"),
                settings,
                templates.get("_template", None),
            ):
                fix_perms(join(profile_dir, "_template.yml"), ctx)

            if not should_exit.is_set():
                sleep(1)

        set_log_plugin("main")
        logger.info(f"HHD Daemon received interrupt, stopping plugins and exiting.")
    finally:
        for fd in cfg_fds:
            try:
                os.close(fd)
            except Exception:
                pass
        for plugs in plugins.values():
            for p in plugs:
                set_log_plugin("main")
                logger.info(f"Stopping plugin `{p.name}`.")
                set_log_plugin(getattr(p, "log") if hasattr(p, "log") else "ukwn")
                p.close()


if __name__ == "__main__":
    main()
