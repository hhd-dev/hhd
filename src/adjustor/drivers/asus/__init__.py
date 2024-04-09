import logging
import time
from typing import cast
import os

from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config
from adjustor.core.platform import get_platform_choices, set_platform_profile

logger = logging.getLogger(__name__)

APPLY_DELAY = 1.5
TDP_DELAY = 0.2
MIN_TDP_START = 7
MAX_TDP_START = 30
MAX_TDP = 54

FTDP_FN = "/sys/devices/platform/asus-nb-wmi/ppt_fppt"
STDP_FN = "/sys/devices/platform/asus-nb-wmi/ppt_pl2_sppt"
CTDP_FN = "/sys/devices/platform/asus-nb-wmi/ppt_pl1_spl"

FAN_CURVE_ENDPOINT = "/sys/class/hwmon"
FAN_CURVE_NAME = "asus_custom_fan_curve"

# Default Ally curve is the following
# [40 45 55 63 68 74 74 74]
# [10 20 66 86 132 188 188 188] / 2.55
# [ 4  8  ]

POINTS = [30, 40, 50, 60, 70, 80, 90, 100]
MIN_CURVE = [2, 5, 17, 17, 17, 17, 17, 17]
DEFAULT_CURVE = [5, 10, 20, 35, 55, 75, 75, 75]


def set_charge_limit(lim: int):
    try:
        # FIXME: Hardcoded path, should match using another characteristic
        logger.info(f"Setting charge limit to {lim:d} %.")
        with open(
            "/sys/class/power_supply/BAT0/charge_control_end_threshold", "w"
        ) as f:
            f.write(f"{lim}\n")
        return True
    except Exception as e:
        logger.error(f"Failed to write battery limit with error:\n{e}")
        return False


def set_tdp(pretty: str, fn: str, val: int):
    logger.info(f"Setting tdp value '{pretty}' to {val} by writing to:\n{fn}")
    try:
        with open(fn, "w") as f:
            f.write(f"{val}\n")
        return True
    except Exception as e:
        logger.error(f"Failed writing value with error:\n{e}")
        return False


def find_fan_curve_dir():
    for dir in os.listdir(FAN_CURVE_ENDPOINT):
        name_fn = os.path.join(FAN_CURVE_ENDPOINT, dir, "name")
        with open(name_fn, "r") as f:
            name = f.read().strip()
        if name == FAN_CURVE_NAME:
            return os.path.join(FAN_CURVE_ENDPOINT, dir)
    return None


def set_fan_curve(points: list[int], curve: list[int]):
    point_str = ",".join([f"{p:> 4d} C" for p in points])
    curve_str = ",".join([f"{p:> 4d} /" for p in curve])
    logger.info(f"Setting the following fan curve:\n{point_str}\n{curve_str} 255")

    dir = find_fan_curve_dir()
    if not dir:
        logger.error(f"Could not find hwmon with name:\n'{FAN_CURVE_NAME}'")
        return False

    for fan in (1, 2):
        for i, (temp, speed) in enumerate(zip(points, curve)):
            with open(os.path.join(dir, f"pwm{fan}_auto_point{i+1}_temp"), "w") as f:
                f.write(f"{temp}")
            with open(os.path.join(dir, f"pwm{fan}_auto_point{i+1}_pwm"), "w") as f:
                f.write(f"{speed}")

    for fan in (1, 2):
        with open(os.path.join(dir, f"pwm{fan}_enable"), "w") as f:
            f.write(f"1")
        if fan == 1:
            time.sleep(TDP_DELAY)

    return True


def disable_fan_curve():
    logger.info(f"Disabling custom fan curve.")

    dir = find_fan_curve_dir()
    if not dir:
        logger.error(f"Could not find hwmon with name:\n'{FAN_CURVE_NAME}'")
        return False

    for fan in (1, 2):
        with open(os.path.join(dir, f"pwm{fan}_enable"), "w") as f:
            f.write(f"2")
        if fan == 1:
            time.sleep(TDP_DELAY)

    return True


class AsusDriverPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_asus"
        self.priority = 6
        self.log = "adja"
        self.enabled = False
        self.initialized = False
        self.enforce_limits = True
        self.startup = True
        self.old_conf = None

        self.queue_fan = None
        self.queue_tdp = None

    def settings(self):
        if not self.enabled:
            self.initialized = False
            self.old_conf = None
            self.startup = True
            return {}

        self.initialized = True
        out = {"tdp": {"asus": load_relative_yaml("settings.yml")}}
        if not self.enforce_limits:
            out["tdp"]["asus"]["children"]["tdp"]["max"] = 50
        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        pass

    def update(self, conf: Config):
        self.enabled = conf["hhd.settings.tdp_enable"].to(bool)
        new_enforce_limits = conf["hhd.settings.enforce_limits"].to(bool)
        new_lims = new_enforce_limits != self.enforce_limits
        self.enforce_limits = new_enforce_limits

        if not self.enabled or not self.initialized or new_lims:
            self.old_conf = None
            self.startup = True
            return

        # If not old config, exit, as values can not be set
        if not self.old_conf:
            self.old_conf = conf["tdp.asus"]
            return

        curr = time.time()

        # Charge limit
        lim = conf["tdp.asus.charge_limit"].to(str)
        if (self.startup and lim != "disabled") or (
            lim != self.old_conf["charge_limit"].to(str)
        ):
            match lim:
                case "p65":
                    set_charge_limit(65)
                case "p70":
                    set_charge_limit(70)
                case "p80":
                    set_charge_limit(80)
                case "p85":
                    set_charge_limit(85)
                case "p90":
                    set_charge_limit(90)
                case "p95":
                    set_charge_limit(95)
                case "disabled":
                    # Avoid writing charge limit on startup if
                    # disabled
                    if not self.startup:
                        set_charge_limit(100)

        #
        # TDP
        #

        # Reset fan curve on mode change
        # Has to happen before setting the stdp, ftdp values, in case
        # we are in custom mode
        fan_mode = conf["tdp.asus.fan.mode"].to(str)
        if fan_mode != self.old_conf["fan.mode"].to(str) and fan_mode != "manual":
            pass

        # Check user changed values
        steady = conf["tdp.asus.tdp"].to(int)

        steady_updated = steady and steady != self.old_conf["tdp"].to(int)

        if self.startup and (steady > MAX_TDP_START or steady < MIN_TDP_START):
            logger.warning(
                f"TDP ({steady}) outside the device spec. Resetting for stability reasons."
            )
            steady = min(max(steady, MIN_TDP_START), MAX_TDP_START)
            conf["tdp.asus.tdp"] = steady
            steady_updated = True

        boost = conf["tdp.asus.boost"].to(bool)
        boost_updated = boost != self.old_conf["boost"].to(bool)

        # If yes, queue an update
        # Debounce
        if self.startup or steady_updated or boost_updated:
            self.queue_tdp = curr + APPLY_DELAY

        tdp_set = self.queue_tdp and self.queue_tdp < curr
        if tdp_set:
            if steady < 5:
                steady = 5
            if steady < 13:
                set_platform_profile("quiet")
            elif steady < 20:
                set_platform_profile("balanced")
            else:
                set_platform_profile("performance")

            self.queue_tdp = None
            if boost:
                time.sleep(TDP_DELAY)
                set_tdp("fast", FTDP_FN, min(MAX_TDP, int(steady * 53 / 30)))
                time.sleep(TDP_DELAY)
                set_tdp("slow", STDP_FN, min(MAX_TDP, int(steady * 43 / 30)))
                time.sleep(TDP_DELAY)
                set_tdp("steady", CTDP_FN, steady)
            else:
                time.sleep(TDP_DELAY)
                set_tdp("fast", FTDP_FN, steady)
                time.sleep(TDP_DELAY)
                set_tdp("slow", STDP_FN, steady)
                time.sleep(TDP_DELAY)
                set_tdp("steady", CTDP_FN, steady)

        # Handle fan curve resets
        if conf["tdp.asus.fan.manual.reset"].to(bool):
            conf["tdp.asus.fan.manual.reset"] = False
            for k, v in zip(POINTS, DEFAULT_CURVE):
                conf[f"tdp.asus.fan.manual.st{k}"] = v

        # # Handle fan curve limits
        # if conf["tdp.asus.fan.manual.enforce_limits"].to(bool):
        #     for k, v in zip(POINTS, MIN_CURVE):
        #         if conf[f"tdp.asus.fan.manual.st{k}"].to(int) < v:
        #             conf[f"tdp.asus.fan.manual.st{k}"] = v

        # Check if fan curve has changed
        # Use debounce logic on these changes
        if tdp_set and conf["tdp.asus.fan.mode"].to(str) == "manual":
            self.queue_fan = curr + APPLY_DELAY
        for i in POINTS:
            if conf[f"tdp.asus.fan.manual.st{i}"].to(int) != self.old_conf[
                f"fan.manual.st{i}"
            ].to(int):
                self.queue_fan = curr + APPLY_DELAY
        # If mode changes, only apply curve if set to manual
        # otherwise disable and reset tdp
        if conf["tdp.asus.fan.mode"].to(str) != self.old_conf["fan.mode"].to(str):
            if conf["tdp.asus.fan.mode"].to(str) == "manual":
                self.queue_fan = curr + APPLY_DELAY
            else:
                try:
                    disable_fan_curve()
                except Exception as e:
                    logger.error(f"Could not disable fan curve. Error:\n{e}")
                self.queue_tdp = curr + APPLY_DELAY

        apply_curve = self.queue_fan and self.queue_fan < curr
        if apply_curve:
            try:
                if conf["tdp.asus.fan.mode"].to(str) == "manual":
                    set_fan_curve(
                        POINTS,
                        [
                            min(
                                int(conf[f"tdp.asus.fan.manual.st{i}"].to(int) * 2.55),
                                255,
                            )
                            for i in POINTS
                        ],
                    )
            except Exception as e:
                logger.error(f"Could not set fan curve. Error:\n{e}")
            self.queue_fan = None

        # Save current config
        self.old_conf = conf["tdp.asus"]

        if self.startup:
            self.startup = False

    def close(self):
        pass
