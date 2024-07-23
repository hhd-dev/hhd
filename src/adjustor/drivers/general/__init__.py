import os
import subprocess
from typing import Literal
import shutil

import time
import signal
from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config
import logging

logger = logging.getLogger(__name__)


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

    def settings(self):
        sets = load_relative_yaml("./settings.yml")

        # PPD
        if self.ppd_supported is None:
            self.ppd_supported = False
            if ppc := shutil.which('powerprofilesctl'):
                try:
                    if os.environ.get("HHD_PPD_MASK", None):
                        logger.info("Unmasking Power Profiles Daemon in the case it was masked.")
                        os.system('systemctl unmask power-profiles-daemon')
                    subprocess.run(
                        [ppc],
                        check=True,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self.ppd_supported = True
                except Exception as e:
                    logger.warning(f"powerprofilectl returned with error:\n{e}")

        if not self.ppd_supported:
            del sets["children"]["profile"]

        # SchedExt
        self.avail_scheds = {}
        avail_pretty = {}
        kernel_supports = os.path.isfile("/sys/kernel/sched_ext/state")
        if kernel_supports:
            for sched, pretty in sets["children"]["sched"]["options"].items():
                if sched == "disabled":
                    avail_pretty[sched] = pretty
                    continue

                exe = shutil.which(sched)
                if exe:
                    self.avail_scheds[sched] = exe
                    avail_pretty[sched] = pretty

        if self.avail_scheds:
            sets["children"]["sched"]["options"] = avail_pretty
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
                self.target = new_profile
                try:
                    subprocess.run(
                        [shutil.which('powerprofilesctl'), "set", new_profile],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                except Exception as e:
                    self.ppd_supported = False
                    logger.warning(f"powerprofilesctl returned with error:\n{e}")
                    self.ppd_supported = False
            elif not self.last_check or curr - self.last_check > 2:
                # Update profile every 2 seconds
                self.last_check = curr
                try:
                    res = subprocess.run(
                        [shutil.which('powerprofilesctl'), "get"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    self.target = res.stdout.decode().strip()  # type: ignore
                    if self.target != conf["tdp.general.profile"].to(str):
                        conf["tdp.general.profile"] = self.target
                except Exception as e:
                    self.ppd_supported = False
                    logger.warning(f"powerprofilectl returned with error:\n{e}")
                    self.ppd_supported = False

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
