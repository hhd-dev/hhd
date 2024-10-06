import logging
import os
import subprocess
import sys
from threading import Thread
from typing import Literal
import shutil
import time
import signal

from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

from adjustor.fuse.gpu import (
    get_igpu_status,
    set_cpu_boost,
    set_epp_mode,
    set_gpu_auto,
    set_gpu_manual,
    set_powersave_governor,
    can_use_nonlinear,
    set_frequency_scaling,
)

logger = logging.getLogger(__name__)

APPLY_DELAY = 0.25


def _ppd_client(emit, proc):
    os.set_blocking(proc.stdin.fileno(), False)

    while True:
        if proc.poll() is not None:
            break
        line = proc.stdout.readline().decode().strip()
        if not line:
            break
        if line not in ("power", "balanced", "performance"):
            logger.error(f"Invalid PPD mode: {line}")
            continue
        emit({"type": "ppd", "status": line})


def _open_ppd_server(emit):
    logger.info("Launching PPD server.")
    proc = subprocess.Popen(
        [sys.executable, "-m", "adjustor.drivers.amd.ppd"],
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    t = Thread(target=_ppd_client, args=(emit, proc))
    t.start()
    return proc, t


class AmdGPUPlugin(HHDPlugin):

    def __init__(
        self,
    ) -> None:
        self.name = f"adjustor_ppd"
        self.priority = 8
        self.log = "agpu"
        self.core_available = False
        self.core_enabled = False
        self.enabled = False
        self.ppd_conflict = False
        self.initialized = False
        self.supports_boost = False
        self.supports_sched = False
        self.min_freq = None
        self.avail_scheds = {}

        self.proc = None
        self.t = None

        self.queue = None
        self.queue_gpu = None
        self.sched_proc = None
        self.old_ppd = False
        self.old_freq = None
        self.old_sched = "disabled"
        self.old_boost = None
        self.old_epp = None
        self.old_target = None
        self.old_min_freq = None
        self.target: Literal["power", "balanced", "performance"] = "balanced"

        self.logged_boost = False
        self.logged_error = False

    def settings(self):
        if not self.core_enabled:
            self.initialized = False
            self.core_available = False
            return {}

        status = get_igpu_status()
        if not status:
            self.core_available = False
            if not self.logged_error:
                logger.error(
                    "Could not get frequency status. Disabling AMD GPU plugin."
                )
                self.logged_error = True
            return {}

        sets = load_relative_yaml("./settings.yml")
        self.core_available = True
        if not self.enabled:
            self.initialized = False
            return {"hhd": {"settings": sets["core"]}}

        self.ppd_conflict = False
        try:
            out = subprocess.check_output(
                [
                    "systemctl",
                    "list-units",
                    "-t",
                    "service",
                    "--full",
                    # "--all",
                    "--plain",
                    "--no-legend",
                ]
            )
            for line in out.decode().splitlines():
                line = line.lower()
                if "masked" in line:
                    continue
                if "not-found" in line:
                    continue
                if "inactive" in line:
                    continue
                if "power-profiles-daemon" in line or "tuned" in line:
                    self.ppd_conflict = True
                    break
        except Exception as e:
            logger.error(f"Failed to check for PPD conflict:\n{e}")

        if self.ppd_conflict and os.environ.get("HHD_PPD_MASK", None):
            logger.warning(
                "PPD conflict detected but HHD_PPD_MASK is set. Masking PPD/TuneD."
            )
            # Mask and disable
            os.system("systemctl mask power-profiles-daemon.service")
            os.system("systemctl disable --now power-profiles-daemon.service")
            os.system("systemctl mask tuned.service")
            os.system("systemctl disable --now tuned.service")
            # Keep going without check to avoid obscure errors
            self.ppd_conflict = False

        if self.ppd_conflict:
            self.initialized = False
            return {
                "tdp": {"amd_energy": sets["conflict"]},
                "hhd": {"settings": sets["core"]},
            }

        self.initialized = True

        # Initialize frequency settings
        manual_freq = sets["enabled"]["children"]["gpu_freq"]["modes"]["manual"][
            "children"
        ]["frequency"]
        upper_freq = sets["enabled"]["children"]["gpu_freq"]["modes"]["upper"][
            "children"
        ]["frequency"]
        min_freq = sets["enabled"]["children"]["gpu_freq"]["modes"]["range"][
            "children"
        ]["min"]
        max_freq = sets["enabled"]["children"]["gpu_freq"]["modes"]["range"][
            "children"
        ]["max"]

        manual_freq["default"] = ((status.freq_min + status.freq_max) // 200) * 100
        upper_freq["default"] = status.freq_max
        min_freq["default"] = status.freq_min
        max_freq["default"] = status.freq_max
        for freq in (manual_freq, min_freq, max_freq, upper_freq):
            freq["min"] = status.freq_min
            freq["max"] = status.freq_max
        self.min_freq = status.freq_min

        self.supports_boost = status.cpu_boost is not None
        if self.supports_boost:
            if not self.logged_boost:
                logger.info(f"CPU Boost toggling is supported.")
        else:
            if not self.logged_boost:
                logger.warning(f"CPU Boost toggling is not supported.")
            del sets["enabled"]["children"]["mode"]["modes"]["manual"]["children"][
                "cpu_boost"
            ]

        self.supports_nonlinear = can_use_nonlinear()
        if not self.supports_nonlinear:
            del sets["enabled"]["children"]["mode"]["modes"]["manual"]["children"][
                "cpu_min_freq"
            ]

        self.supports_epp = status.epp_avail is not None
        if self.supports_epp:
            epp = sets["enabled"]["children"]["mode"]["modes"]["manual"]["children"][
                "cpu_pref"
            ]
            epp["options"] = {
                k: v for k, v in epp["options"].items() if k in status.epp_avail
            }
        else:
            del sets["enabled"]["children"]["mode"]["modes"]["manual"]["children"][
                "cpu_pref"
            ]

        self.avail_scheds = {}
        avail_pretty = {}
        kernel_supports = os.path.isfile("/sys/kernel/sched_ext/state")
        if kernel_supports:
            for sched, pretty in sets["enabled"]["children"]["mode"]["modes"]["manual"][
                "children"
            ]["sched"]["options"].items():
                if sched == "disabled":
                    avail_pretty[sched] = pretty
                    continue

                exe = shutil.which(sched)
                if exe:
                    self.avail_scheds[sched] = exe
                    avail_pretty[sched] = pretty

        if self.avail_scheds:
            sets["enabled"]["children"]["mode"]["modes"]["manual"]["children"]["sched"][
                "options"
            ] = avail_pretty
        else:
            del sets["enabled"]["children"]["mode"]["modes"]["manual"]["children"][
                "sched"
            ]

        self.logged_boost = True
        return {
            "tdp": {"amd_energy": sets["enabled"]},
            "hhd": {"settings": sets["core"]},
        }

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def notify(self, events):
        for event in events:
            if event["type"] == "energy":
                self.target = event["status"]
                try:
                    if self.proc and self.proc.stdin:
                        self.proc.stdin.write(f"{self.target}\n".encode())
                        self.proc.stdin.flush()
                except Exception as e:
                    logger.error(f"Failed to send PPD mode:\n{e}")
                    self.close_ppd()

    def update(self, conf: Config):
        self.core_enabled = conf["hhd.settings.tdp_enable"].to(bool)
        if not self.core_enabled or not self.core_available:
            return

        enabled = conf["hhd.settings.amd_energy_enable"].to(bool)
        if enabled != self.enabled:
            self.emit({"type": "settings"})
        self.enabled = enabled

        if self.ppd_conflict and conf.get("tdp.amd_energy.enable", False):
            conf["tdp.amd_energy.enable"] = False
            self.emit({"type": "settings"})

        if not self.initialized:
            return

        new_ppd = conf["hhd.settings.amd_energy_ppd"].to(bool)
        if new_ppd != self.old_ppd:
            self.old_ppd = new_ppd
            if new_ppd:
                try:
                    self.proc, self.t = _open_ppd_server(self.emit)
                    # Fixup target in case it came before
                    if self.proc.stdin and self.target:
                        self.proc.stdin.write(f"{self.target}\n".encode())
                        self.proc.stdin.flush()
                except Exception as e:
                    logger.error(f"Failed to open PPD server:\n{e}")
                    self.close_ppd()
            else:
                self.close_ppd()

        curr = time.perf_counter()
        if conf["tdp.amd_energy.mode.mode"].to(str) == "auto":
            if self.target != self.old_target:
                self.old_target = self.target
                self.queue = curr + APPLY_DELAY

            if self.queue is not None and curr >= self.queue:
                self.queue = None
                logger.info(
                    f"Handling energy settings for power profile '{self.target}'."
                )
                try:
                    match self.target:
                        case "balanced":
                            if self.supports_epp:
                                set_powersave_governor()
                                set_epp_mode("balance_power")
                            if self.supports_boost:
                                set_cpu_boost(True)
                            set_frequency_scaling(nonlinear=False)
                        case "performance":
                            if self.supports_epp:
                                set_powersave_governor()
                                set_epp_mode("balance_power")
                            if self.supports_boost:
                                set_cpu_boost(True)
                            set_frequency_scaling(nonlinear=True)
                        case _:  # power
                            if self.supports_epp:
                                set_powersave_governor()
                                set_epp_mode("power")
                            if self.supports_boost:
                                set_cpu_boost(False)
                            set_frequency_scaling(nonlinear=False)
                except Exception as e:
                    logger.error(f"Failed to set energy mode:\n{e}")

            # Unless it is set manually, use the default scheduler.
            self.close_sched()
            self.old_sched = None
            self.old_boost = None
            self.old_epp = None
            self.old_min_freq = None
        else:
            self.old_target = None
            if self.supports_boost:
                new_boost = conf["tdp.amd_energy.mode.manual.cpu_boost"].to(bool)
                if new_boost != self.old_boost:
                    self.old_boost = new_boost
                    try:
                        set_cpu_boost(new_boost == "enabled")
                        # Set frequency scaling again, as max frequency
                        # changes depending on whether boost is supported
                        if self.supports_nonlinear:
                            set_frequency_scaling(
                                nonlinear=conf[
                                    "tdp.amd_energy.mode.manual.cpu_min_freq"
                                ].to(str)
                                == "nonlinear"
                            )
                    except Exception as e:
                        logger.error(f"Failed to set CPU boost:\n{e}")

            if self.supports_epp:
                new_epp = conf["tdp.amd_energy.mode.manual.cpu_pref"].to(str)
                if new_epp != self.old_epp:
                    self.old_epp = new_epp
                    try:
                        # Set governor to powersave as well
                        set_powersave_governor()
                        set_epp_mode(new_epp)  # type: ignore
                    except Exception as e:
                        logger.error(f"Failed to set EPP mode:\n{e}")

            if self.supports_nonlinear:
                new_min_freq = conf["tdp.amd_energy.mode.manual.cpu_min_freq"].to(str)
                if new_min_freq != self.old_min_freq:
                    self.old_min_freq = new_min_freq
                    try:
                        set_frequency_scaling(nonlinear=new_min_freq == "nonlinear")
                    except Exception as e:
                        logger.error(f"Failed to set minimum CPU frequency:\n{e}")

            if self.avail_scheds:
                # Check health and print error
                if self.sched_proc and self.sched_proc.poll():
                    err = self.sched_proc.poll()
                    self.sched_proc = None
                    logger.error(
                        f"Scheduler from sched_ext '{self.old_sched}' closed with error code: {err}"
                    )

                new_sched = conf.get("tdp.amd_energy.mode.manual.sched", "disabled")
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

        # Apply GPU settings
        new_gpu = conf["tdp.amd_energy.gpu_freq.mode"].to(str)
        match new_gpu:
            case "manual":
                f = conf["tdp.amd_energy.gpu_freq.manual.frequency"].to(int)
                new_freq = (f, f)
            case "upper":
                f = conf["tdp.amd_energy.gpu_freq.upper.frequency"].to(int)
                new_freq = (self.min_freq or f, f)
            case "range":
                min_f = conf["tdp.amd_energy.gpu_freq.range.min"].to(int)
                max_f = conf["tdp.amd_energy.gpu_freq.range.max"].to(int)
                if max_f < min_f:
                    max_f = min_f
                    conf["tdp.amd_energy.gpu_freq.range.max"] = min_f
                new_freq = (min_f, max_f)
            case _:
                new_freq = None

        if new_freq != self.old_freq:
            self.old_freq = new_freq
            self.queue_gpu = curr + APPLY_DELAY

        if self.queue_gpu is not None and curr >= self.queue_gpu:
            self.queue_gpu = None
            try:
                if new_freq:
                    set_gpu_manual(*new_freq)
                else:
                    set_gpu_auto()
            except Exception as e:
                logger.error(f"Failed to set GPU mode:\n{e}")

    def close_ppd(self):
        if self.proc is not None:
            self.proc.send_signal(signal.SIGINT)
            self.proc.wait()
            self.proc = None
        if self.t is not None:
            self.t.join()
            self.t = None

    def close_sched(self):
        if self.sched_proc is not None:
            logger.info(f"Closing sched_ext scheduler '{self.old_sched}'.")
            self.sched_proc.send_signal(signal.SIGINT)
            self.sched_proc.wait()
            self.sched_proc = None

    def close(self):
        self.close_ppd()
        self.close_sched()
