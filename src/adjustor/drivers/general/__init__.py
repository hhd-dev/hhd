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

logger = logging.getLogger(__name__)


class GeneralPowerPlugin(HHDPlugin):

    def __init__(
        self,
        is_steamdeck: bool = False,
    ) -> None:
        self.name = f"adjustor_general"
        self.priority = 8
        self.log = "gpow"
        self.last_check = None
        self.target = None
        self.old_sched = None
        self.sched_proc = None
        self.ppd_supported = None
        self.tuned_supported = None
        self.is_steamdeck = is_steamdeck
        self.ovr_enabled = False
        self.should_exit = Event()
        self.t_sys = None
        self.currentTarget = None

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

        # TuneD
        if self.tuned_supported is None:
            self.tuned_supported = False
            if tuned := shutil.which('tuned-adm'):
                try:
                    if os.environ.get("HHD_PPD_MASK", None):
                        logger.info("Unmasking TuneD in the case it was masked.")
                        os.system('systemctl unmask tuned')
                    subprocess.run(
                        [tuned,'active'],
                        check=True,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self.tuned_supported = True
                except Exception as e:
                    logger.warning(f"tuned-adm returned with error:\n{e}")


        if not self.ppd_supported and not self.tuned_supported:
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

        if not self.is_steamdeck:
            del sets["children"]["steamdeck_ovr"]

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

        # Handle TuneD
        if self.tuned_supported:
            curr = time.time()
            ppd_tuned_mapping = {
                "power-saver": "powersave",
                "balanced": "balanced",
                "performance": "throughput-performance"
            }

            new_profile = ppd_tuned_mapping.get(conf.get("tdp.general.profile", self.target))
            if new_profile != self.currentTarget and new_profile and self.currentTarget:
                logger.info(f"Setting TuneD profile to '{new_profile}' from '{self.target}'")
                self.currentTarget = new_profile
                try:
                    subprocess.run(
                        [shutil.which('tuned-adm'), "profile", new_profile],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )

                except Exception as e:
                    self.tuned_supported = False
                    logger.warning(f"tuned-adm returned with error:\n{e}")
                    self.tuned_supported = False
            elif not self.last_check or curr - self.last_check > 2:
                # Update profile every 2 seconds
                self.last_check = curr
                try:
                    res = subprocess.run(
                        [shutil.which('tuned-adm'), "active"],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    tuned_ppd_mapping = {
                        "powersave": "power-saver",
                        "balanced": "balanced",
                        "throughput-performance": "performance"
                    }
                    self.currentTarget = res.stdout.decode().split(":")[1].strip()
                    self.target = tuned_ppd_mapping.get(self.currentTarget)  # type: ignore

                    if self.target != conf["tdp.general.profile"].to(str):
                        conf["tdp.general.profile"] = self.target
                except Exception as e:
                    self.tuned_supported = False
                    logger.warning(f"tuned-adm returned with error:\n{e}")
                    self.tuned_supported = False

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
        
        # Handle steamdeck_ovr
        if self.is_steamdeck:
            new_ovr = conf.get("tdp.general.steamdeck_ovr", False)
            if new_ovr and not self.ovr_enabled:
                self.ovr_enabled = True
                logger.info("Starting FUSE mount for /sys (Overclock).")
                from ...fuse import prepare_tdp_mount, start_tdp_client

                stat = prepare_tdp_mount(passhtrough=True)
                if stat:
                    self.t_sys = start_tdp_client(
                        self.should_exit,
                        None,
                        1,
                        15,
                        20,
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
