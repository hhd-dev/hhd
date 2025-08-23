import os
import subprocess
from typing import Literal
import shutil

import time
import signal
from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config
from threading import Event
import logging

from hhd.plugins.plugin import Emitter

logger = logging.getLogger(__name__)

PROFILES = ["performance", "balanced", "power-saver"]
PTYPE = Literal["performance", "balanced", "power-saver"]

def set_power_profile(profile):
    try:
        busctl = shutil.which("busctl")
        if not busctl:
            return None
        subprocess.run(
            [
                busctl,
                "set-property",
                "org.freedesktop.UPower.PowerProfiles",
                "/org/freedesktop/UPower/PowerProfiles",
                "org.freedesktop.UPower.PowerProfiles",
                "ActiveProfile",
                "s",
                profile,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as e:
        logger.warning(f"Could set power profile to '{profile}': {e}")


def get_current_power_profile() -> (
    PTYPE | None
):
    try:
        busctl = shutil.which("busctl")
        if not busctl:
            return None
        res = subprocess.run(
            [
                busctl,
                "get-property",
                "org.freedesktop.UPower.PowerProfiles",
                "/org/freedesktop/UPower/PowerProfiles",
                "org.freedesktop.UPower.PowerProfiles",
                "ActiveProfile",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        profile = res.stdout.decode().strip()
        for p in PROFILES:
            if p in profile:
                return p # type: ignore
    except Exception:
        pass
    logger.warning(f"Could not read power profile. Disabling profile support.")


class GeneralPowerPlugin(HHDPlugin):

    def __init__(
        self,
    ) -> None:
        self.name = f"adjustor_general"
        self.priority = 8
        self.log = "gpow"
        self.last_check = None
        self.target = None
        self.old_sched = None
        self.sched_proc = None
        self.ppd_supported = None
        self.ovr_enabled = False
        self.should_exit = Event()
        self.t_sys = None
        self.currentTarget = None

    def open(self, emit: Emitter, context: Context):
        self.emit = emit
        self.ppd_supported = get_current_power_profile() is not None

        # SchedExt
        self.sets = load_relative_yaml("./settings.yml")
        self.avail_scheds = {}
        self.avail_pretty = {}
        kernel_supports = os.path.isfile("/sys/kernel/sched_ext/state")
        if kernel_supports:
            for sched, pretty in self.sets["children"]["sched"]["options"].items():
                if sched == "disabled":
                    self.avail_pretty[sched] = pretty
                    continue

                exe = shutil.which(sched)
                if exe:
                    self.avail_scheds[sched] = exe
                    self.avail_pretty[sched] = pretty

    def settings(self):
        sets = self.sets

        if not self.ppd_supported:
            del sets["children"]["profile"]

        if self.avail_scheds:
            sets["children"]["sched"]["options"] = self.avail_pretty
        else:
            del sets["children"]["sched"]

        self.logged_boost = True
        return {
            "tdp": {"general": sets},
        }

    def update(self, conf: Config):
        # Handle ppd
        if self.ppd_supported:
            curr = time.time()
            new_profile = conf.get("tdp.general.profile", self.target)
            if new_profile != self.target and new_profile and self.target:
                logger.info(f"Setting power profile to '{new_profile}'")
                set_power_profile(new_profile)
                self.target = new_profile
            elif not self.last_check or curr - self.last_check > 2:
                # Update profile every 2 seconds
                self.last_check = curr
                self.target = get_current_power_profile()
                if self.target is None:
                    self.ppd_supported = False
                    logger.info(f"Power profile support seems to be gone. Disabling.")
                    self.emit({"type": "settings"})
                elif self.target != conf["tdp.general.profile"].to(str):
                    conf["tdp.general.profile"] = self.target

        # Handle sched
        if self.avail_scheds:
            # Check health and print error
            if self.sched_proc and self.sched_proc.poll():
                err = self.sched_proc.poll()
                self.sched_proc = None
                logger.error(
                    f"Scheduler from sched_ext '{self.old_sched}' closed with error code: {err}"
                )

            new_sched = conf.get("tdp.general.sched", "disabled")
            if new_sched != self.old_sched:
                self.close_sched()
                self.old_sched = new_sched
                if new_sched and new_sched != "disabled":
                    logger.info(f"Starting sched_ext scheduler '{new_sched}'")
                    self.sched_proc = subprocess.Popen(
                        self.avail_scheds[new_sched],
                        stderr=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                    )

    def close_sched(self):
        if self.sched_proc is not None:
            logger.info(f"Closing sched_ext scheduler '{self.old_sched}'.")
            self.sched_proc.send_signal(signal.SIGINT)
            self.sched_proc.wait()
            self.sched_proc = None

    def close(self):
        self.close_sched()
        if self.t_sys:
            self.should_exit.set()
            self.t_sys.join()
