import argparse
import fcntl
import logging
import os
import signal
import subprocess
import sys
from os.path import join
from threading import Condition
from threading import Event as TEvent
from threading import RLock
from time import sleep
from typing import Sequence

import pkg_resources

from .logging import set_log_plugin, setup_logger, update_log_plugins
from .plugins import (
    Config,
    Emitter,
    Event,
    HHDAutodetect,
    HHDPlugin,
    HHDSettings,
    load_relative_yaml,
)
from .plugins.settings import (
    Validator,
    get_default_state,
    load_blacklist_yaml,
    load_profile_yaml,
    load_state_yaml,
    merge_settings,
    save_blacklist_yaml,
    save_profile_yaml,
    get_settings_hash,
    save_state_yaml,
    validate_config,
)
from .utils import expanduser, fix_perms, get_context, switch_priviledge

logger = logging.getLogger(__name__)

CONFIG_DIR = os.environ.get("HHD_CONFIG_DIR", "~/.config/hhd")

ERROR_DELAY = 5
INIT_DELAY = 0.4
POLL_DELAY = 2


class EmitHolder(Emitter):
    def __init__(self, condition: Condition) -> None:
        self._events = []
        self._condition = condition

    def __call__(self, event: Event | Sequence[Event]) -> None:
        with self._condition:
            if isinstance(event, Sequence):
                self._events.extend(event)
            else:
                self._events.append(event)
            self._condition.notify_all()

    def get_events(self, timeout: int = -1) -> Sequence[Event]:
        with self._condition:
            if not self._events and timeout != -1:
                self._condition.wait()
            ev = self._events
            self._events = []
            return ev

    def has_events(self):
        with self._condition:
            return bool(self._events)


def notifier(ev: TEvent, cond: Condition):
    def _inner(sig, frame):
        with cond:
            ev.set()
            cond.notify_all()

    return _inner


def print_token(ctx):
    token_fn = expanduser(join(CONFIG_DIR, "token"), ctx)

    try:
        with open(token_fn, "r") as f:
            token = f.read().strip()

        logger.info(f'Current HHD token (for user "{ctx.name}") is: "{token}"')
    except Exception as e:
        logger.error(f"Token not found or could not be read, error:\n{e}")
        logger.info(
            "Enable the http endpoint to generate a token automatically.\n"
            + "Or place it under '~/.config/hhd/token' manually.\n"
            + "'chown 600 ~/.config/hhd/token' for security reasons!"
        )


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
    parser.add_argument(
        "command",
        nargs="*",
        default=[],
        help="The command to run. If empty, run as daemon. Right now, only the command `token` is supported.",
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
    cfg_fds = []

    # HTTP data
    https = None
    prev_http_cfg = None
    updated = False

    # Check we are in a virtual environment
    # TODO: Improve
    exe_python = sys.executable

    try:
        # Create nested hhd dir
        # This might mess up permissions in upward directories
        # So try to deescalate
        hhd_dir = expanduser(CONFIG_DIR, ctx)
        try:
            switch_priviledge(ctx, False)
            os.makedirs(hhd_dir, exist_ok=True)
            switch_priviledge(ctx, True)
            fix_perms(hhd_dir, ctx)
        except Exception:
            pass

        # Remove old dir
        try:
            os.rename(
                join(hhd_dir, "plugins"), join(hhd_dir, "plugins_old_USE_STATEYML")
            )
        except Exception:
            pass

        set_log_plugin("main")
        setup_logger(join(CONFIG_DIR, "log"), ctx=ctx)

        if args.command:
            if args.command[0] == "token":
                print_token(ctx)
                return
            else:
                logger.error(f"Command '{args.command[0]}' is unknown. Ignoring...")

        # Use blacklist
        blacklist_fn = join(hhd_dir, "plugins.yml")
        blacklist = load_blacklist_yaml(blacklist_fn)

        logger.info(f"Running autodetection...")

        detector_names = []
        for autodetect in pkg_resources.iter_entry_points("hhd.plugins"):
            name = autodetect.name
            detector_names.append(name)
            if name in blacklist:
                logger.info(f"Skipping blacklisted provider '{name}'.")
            else:
                detectors[autodetect.name] = autodetect.resolve()

        # Save new blacklist file
        save_blacklist_yaml(blacklist_fn, detector_names, blacklist)
        fix_perms(blacklist_fn, ctx)

        logger.info(f"Found plugin providers: {', '.join(list(detectors))}")

        for name, autodetect in detectors.items():
            plugins[name] = autodetect([])

        plugin_str = "Loaded the following plugins:"
        for pkg_name, sub_plugins in plugins.items():
            if not sub_plugins:
                continue
            plugin_str += (
                f"\n  - {pkg_name:>8s}: {', '.join(p.name for p in sub_plugins)}"
            )
        logger.info(plugin_str)

        # Get sorted plugins
        sorted_plugins: Sequence[HHDPlugin] = []
        for plugs in plugins.values():
            sorted_plugins.extend(plugs)
        sorted_plugins.sort(key=lambda x: x.priority)
        validator: Validator = lambda tags, config, value: any(
            p.validate(tags, config, value) for p in sorted_plugins
        )

        if not sorted_plugins:
            logger.error(f"No plugins started, exiting...")
            return

        # Open plugins
        lock = RLock()
        cond = Condition(lock)
        emit = EmitHolder(cond)
        for p in sorted_plugins:
            set_log_plugin(getattr(p, "log") if hasattr(p, "log") else "ukwn")
            p.open(emit, ctx)
            update_log_plugins()
        set_log_plugin("main")

        # Compile initial configuration
        state_fn = expanduser(join(CONFIG_DIR, "state.yml"), ctx)
        token_fn = expanduser(join(CONFIG_DIR, "token"), ctx)
        settings: HHDSettings = {}
        shash = None

        # Load profiles
        profiles = {}
        templates = {}
        conf = Config({})
        profile_dir = expanduser(join(CONFIG_DIR, "profiles"), ctx)
        os.makedirs(profile_dir, exist_ok=True)
        fix_perms(profile_dir, ctx)

        # Monitor config files for changes
        should_initialize = TEvent()
        initial_run = True
        should_exit = TEvent()
        signal.signal(signal.SIGPOLL, notifier(should_initialize, cond))
        signal.signal(signal.SIGINT, notifier(should_exit, cond))
        signal.signal(signal.SIGTERM, notifier(should_exit, cond))

        while not should_exit.is_set():
            #
            # Configuration
            #

            # Initialize if files changed
            if should_initialize.is_set() or initial_run:
                # wait a bit to allow other processes to save files
                if not initial_run:
                    sleep(INIT_DELAY)
                initial_run = False
                set_log_plugin("main")
                logger.info(f"Reloading configuration.")

                # Settings
                hhd_settings = {"hhd": load_relative_yaml("settings.yml")}
                # TODO: Improve check
                try:
                    if "venv" not in exe_python:
                        del hhd_settings["hhd"]["settings"]["children"]["update_stable"]
                        del hhd_settings["hhd"]["settings"]["children"]["update_beta"]
                except Exception as e:
                    logger.warning(f"Could not hide update settings. Error:\n{e}")
                settings = merge_settings(
                    [*[p.settings() for p in sorted_plugins], hhd_settings]
                )
                shash = get_settings_hash(settings)

                # State
                new_conf = load_state_yaml(state_fn, settings)
                if not new_conf:
                    if conf.conf:
                        logger.warning(f"Using previous configuration.")
                    else:
                        logger.info(f"Using default configuration.")
                        conf = get_default_state(settings)
                else:
                    conf = new_conf

                try:
                    from importlib.metadata import version

                    conf["hhd.settings.version"] = version("hhd")
                except Exception:
                    pass

                # Profiles
                profiles = {}
                templates = {}
                os.makedirs(profile_dir, exist_ok=True)
                fix_perms(profile_dir, ctx)
                for fn in os.listdir(profile_dir):
                    if not fn.endswith(".yml"):
                        continue
                    name = fn.replace(".yml", "")
                    s = load_profile_yaml(join(profile_dir, fn))
                    if s:
                        validate_config(s, settings, validator, use_defaults=False)
                        if name.startswith("_"):
                            templates[name] = s
                        else:
                            # Profiles are shared so lock when accessing
                            # Configs have their own locks and are safe
                            with lock:
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
                        fcntl.fcntl(fd, fcntl.F_NOTIFY, 0)
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
                        fcntl.DN_CREATE
                        | fcntl.DN_DELETE
                        | fcntl.DN_MODIFY
                        | fcntl.DN_RENAME
                        | fcntl.DN_MULTISHOT,
                    )
                    cfg_fds.append(fd)

                should_initialize.clear()
                logger.info(f"Initialization Complete!")

            # Initialize http server
            http_cfg = conf["hhd.http"]
            if http_cfg != prev_http_cfg:
                prev_http_cfg = http_cfg
                if https:
                    https.close()
                if http_cfg["enable"].to(bool):
                    from .http import HHDHTTPServer

                    port = http_cfg["port"].to(int)
                    localhost = http_cfg["localhost"].to(bool)
                    use_token = http_cfg["token"].to(bool)

                    # Generate security token
                    if use_token:
                        if not os.path.isfile(token_fn):
                            import hashlib
                            import random

                            token = hashlib.sha256(
                                str(random.random()).encode()
                            ).hexdigest()[:12]
                            with open(token_fn, "w") as f:
                                os.chmod(token_fn, 0o600)
                                f.write(token)
                            fix_perms(token_fn, ctx)
                        else:
                            with open(token_fn, "r") as f:
                                token = f.read().strip()
                    else:
                        token = None

                    set_log_plugin("rest")
                    https = HHDHTTPServer(localhost, port, token)
                    https.update(settings, conf, profiles, emit)
                    https.open()
                    update_log_plugins()
                    set_log_plugin("main")

            #
            # Plugin loop
            #

            # Process events
            settings_changed = False
            for ev in emit.get_events():
                match ev["type"]:
                    case "settings":
                        settings_changed = True
                    case "profile":
                        new_conf = ev["config"]
                        if new_conf:
                            with lock:
                                profiles[ev["name"]] = ev["config"]
                            validate_config(
                                profiles[ev["name"]],
                                settings,
                                validator,
                                use_defaults=False,
                            )
                        else:
                            with lock:
                                if ev["name"] in profiles:
                                    del profiles[ev["name"]]
                    case "apply":
                        if ev["name"] in profiles:
                            conf.update(profiles[ev["name"]].conf)
                    case "state":
                        conf.update(ev["config"].conf)
                    case other:
                        logger.error(f"Invalid event type submitted: '{other}'")

            # Validate config
            validate_config(conf, settings, validator)

            # If settings changed, the configuration needs to reload
            # but it needs to be saved first
            if settings_changed:
                should_initialize.set()

            # Plugins are promised that once they emit a
            # settings change they are not called with the old settings
            if not settings_changed:
                #
                # Plugin event loop
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

            # Notify that events were applied
            # Before saving to reduce delay (yaml files take 100ms :( )
            if https:
                https.update(settings, conf, profiles, emit)

            #
            # Save loop
            #

            has_new = should_initialize.is_set()
            saved = False
            # Save existing profiles if open
            if save_state_yaml(state_fn, settings, conf, shash):
                fix_perms(state_fn, ctx)
                saved = True
                conf.updated = False
            for name, prof in profiles.items():
                fn = join(profile_dir, name + ".yml")
                if save_profile_yaml(fn, settings, prof, shash):
                    fix_perms(fn, ctx)
                    saved = True
                    prof.updated = False
            for prof in os.listdir(profile_dir):
                if prof.startswith("_") or not prof.endswith(".yml"):
                    continue
                name = prof[:-4]
                if name not in profiles:
                    fn = join(profile_dir, prof)
                    try:
                        new_fn = fn + ".bak"
                        os.rename(fn, new_fn)
                        saved = True
                    except Exception as e:
                        logger.error(
                            f"Failed removing profile {name} at:\n{fn}\nWith error:\n{e}"
                        )

            # Add template config
            if save_profile_yaml(
                join(profile_dir, "_template.yml"),
                settings,
                templates.get("_template", None),
                shash,
            ):
                fix_perms(join(profile_dir, "_template.yml"), ctx)
                saved = True

            if not has_new and saved:
                # We triggered the interrupt, clear
                should_initialize.clear()

            upd_stable = conf.get("hhd.settings.update_stable", False)
            upd_beta = conf.get("hhd.settings.update_beta", False)

            if upd_stable or upd_beta:
                set_log_plugin("main")
                conf["hhd.settings.update_stable"] = False
                conf["hhd.settings.update_beta"] = False

                switch_priviledge(ctx, False)
                try:
                    logger.info(f"Updating Handheld Daemon.")
                    if "venv" in exe_python:
                        subprocess.check_call(
                            [
                                exe_python,
                                "-m",
                                "pip",
                                "uninstall",
                                "-y",
                                "hhd",
                            ]
                        )
                        subprocess.check_call(
                            [
                                exe_python,
                                "-m",
                                "pip",
                                "install",
                                "--upgrade",
                                "--cache-dir",
                                "/tmp/__hhd_update_cache",
                                (
                                    "git+https://github.com/hhd-dev/hhd"
                                    if upd_beta
                                    else "hhd"
                                ),
                            ]
                        )
                        updated = True
                    else:
                        logger.error(
                            f"Could not update, python executable is not within a venv (checked for 'venv' in path name):\n{exe_python}"
                        )
                except Exception as e:
                    logger.error(f"Error while updating:\n{e}")
                switch_priviledge(ctx, True)

                if updated:
                    should_exit.set()

            # Wait for events
            with lock:
                if (
                    not should_exit.is_set()
                    and not settings_changed
                    and not should_initialize.is_set()
                    and not emit.has_events()
                ):
                    cond.wait(timeout=POLL_DELAY)

        set_log_plugin("main")
        logger.info(f"Received interrupt or updated. Stopping plugins and exiting.")
    finally:
        for fd in cfg_fds:
            try:
                os.close(fd)
            except Exception:
                pass
        if https:
            set_log_plugin("main")
            logger.info("Shutting down the REST API.")
            https.close()
        for plugs in plugins.values():
            for p in plugs:
                set_log_plugin("main")
                logger.info(f"Stopping plugin `{p.name}`.")
                set_log_plugin(getattr(p, "log") if hasattr(p, "log") else "ukwn")
                p.close()

    if updated:
        # Use error code to restart service
        sys.exit(-1)


if __name__ == "__main__":
    main()
