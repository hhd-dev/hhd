import logging
import time
from threading import Event as TEvent, Lock, Thread
from typing import Sequence
import os

from hhd.plugins import Context, Event, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

from adjustor.core.alib import AlibParams, DeviceParams, alib
from adjustor.core.fan import fan_worker, get_fan_info
from adjustor.core.platform import get_platform_choices, set_platform_profile
from adjustor.i18n import _

logger = logging.getLogger(__name__)

APPLY_DELAY = 0.7


def set_charge_limit(bat: str, lim: int):
    try:
        logger.info(f"Setting charge limit to {lim:d} %.")
        with open(bat, "w") as f:
            f.write(f"{lim}\n")
        return True
    except Exception as e:
        logger.error(f"Failed to write battery limit with error:\n{e}")
        return False


def set_charge_bypass_type(bat: str, type: str):
    match type:
        case "disabled":
            val = "Standard"
        case "awake":
            val = "BypassS0"
        case "always":
            val = "Bypass"
        case _:
            logger.error(f"Invalid charge bypass type: {type}")
            return False

    try:
        logger.info(f"Setting charge type to '{val}' (for bypass '{type}').")
        with open(bat, "w") as f:
            f.write(f"{val}\n")
        return True
    except Exception as e:
        logger.error(f"Failed to write battery bypass with error:\n{e}")
        return False


def set_charge_bypass_behaviour(bat: str, type: str):
    match type:
        case "disabled":
            val = "auto"
        case "awake":
            val = "inhibit-charge-awake"
        case "always":
            val = "inhibit-charge"
        case _:
            logger.error(f"Invalid charge bypass type: {type}")
            return False

    try:
        logger.info(f"Setting charge type to '{val}' (for bypass '{type}').")
        with open(bat, "w") as f:
            f.write(f"{val}\n")
        return True
    except Exception as e:
        logger.error(f"Failed to write battery bypass with error:\n{e}")
        return False


def set_charge_bypass(bat: str, type: str):
    if "charge_type" in bat:
        return set_charge_bypass_type(bat, type)
    elif "charge_behaviour" in bat:
        return set_charge_bypass_behaviour(bat, type)
    else:
        logger.error(f"Unknown charge bypass file: {bat}")
        return False


class BatteryPlugin(HHDPlugin):

    def __init__(self, always_enable: bool = False) -> None:
        self.name = f"adjustor_battery"
        self.priority = 9
        self.log = "batt"
        self.enabled = False
        self.initialized = False
        self.startup = False

        self.queue_charge_limit = None
        self.charge_bypass_fn = None
        self.bypass_awake = True
        self.charge_limit_fn = None
        self.charge_bypass_prev = None
        self.charge_limit_prev = None

        self.always_enable = always_enable

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}

        self.initialized = True
        out = {"tdp": {"battery": load_relative_yaml("battery.yml")}}

        if not self.charge_limit_fn:
            del out["tdp"]["battery"]["children"]["charge_limit"]
        if not self.charge_bypass_fn:
            del out["tdp"]["battery"]["children"]["charge_bypass"]
        elif not self.bypass_awake:
            del out["tdp"]["battery"]["children"]["charge_bypass"]["options"]["awake"]

        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit
        self.startup = True

        for bat in os.listdir("/sys/class/power_supply"):
            if not bat.startswith("BAT"):
                continue

            with open(f"/sys/class/power_supply/{bat}/type") as f:
                if "Battery" not in f.read():
                    continue

            base = f"/sys/class/power_supply/{bat}"
            if os.path.exists(f"{base}/charge_control_end_threshold"):
                self.charge_limit_fn = f"{base}/charge_control_end_threshold"
            if os.path.exists(f"{base}/charge_type"):
                try:
                    with open("/sys/devices/virtual/dmi/id/sys_vendor") as f:
                        supports = "ONE-NETBOOK" in f.read()
                except Exception:
                    supports = False

                if supports:
                    self.charge_bypass_fn = f"{base}/charge_type"
                    self.bypass_awake = True
                else:
                    logger.warning(
                        "Found charge type, but charge bypass is only supported on OneXPlayer currently."
                    )
                    self.charge_bypass_fn = None
                    self.bypass_awake = False
            if os.path.exists(f"{base}/charge_behaviour"):
                self.charge_bypass_fn = f"{base}/charge_behaviour"
                try:
                    with open(self.charge_bypass_fn) as f:
                        self.bypass_awake = "inhibit-charge-awake" in f.read()
                except Exception:
                    logger.error(
                        "Failed to read charge behaviour file, assuming it is not supported."
                    )
                    self.charge_bypass_fn = None
                    self.bypass_awake = False
            if self.charge_bypass_fn or self.charge_limit_fn:
                logger.info(
                    f"Found battery '{bat}' with:\nBattery Bypass:\n{self.charge_bypass_fn}\nBattery Limit:\n{self.charge_limit_fn}."
                )
                break

    def update(self, conf: Config):
        self.enabled = self.always_enable or conf.get("hhd.settings.tdp_enable", False)

        if not self.initialized:
            return

        curr = time.time()

        if self.charge_bypass_fn:
            bypass = conf["tdp.battery.charge_bypass"].to(str)
            if self.charge_bypass_prev != bypass:
                self.charge_bypass_prev = bypass

                if bypass != "disabled" or not self.startup:
                    set_charge_bypass(self.charge_bypass_fn, bypass)

        # Charge limit
        if self.charge_limit_fn:
            lim = conf["tdp.battery.charge_limit"].to(str)
            if lim != self.charge_limit_prev:
                self.queue_charge_limit = curr + APPLY_DELAY
                self.charge_limit_prev = lim

            if self.startup or (
                self.queue_charge_limit and self.queue_charge_limit < curr
            ):
                self.queue_charge_limit = None
                self.charge_limit_prev = lim

                match lim:
                    case "p65":
                        set_charge_limit(self.charge_limit_fn, 65)
                    case "p70":
                        set_charge_limit(self.charge_limit_fn, 70)
                    case "p80":
                        set_charge_limit(self.charge_limit_fn, 80)
                    case "p85":
                        set_charge_limit(self.charge_limit_fn, 85)
                    case "p90":
                        set_charge_limit(self.charge_limit_fn, 90)
                    case "p95":
                        set_charge_limit(self.charge_limit_fn, 95)
                    case "disabled":
                        # Avoid writing charge limit on startup if
                        # disabled, so that if user does not use us
                        # we do not overwrite their setting.
                        if not self.startup:
                            set_charge_limit(self.charge_limit_fn, 100)

        self.startup = False
