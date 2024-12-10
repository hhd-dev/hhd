import logging
import os
import time
from typing import Sequence

from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml

from adjustor.core.platform import set_platform_profile
from adjustor.i18n import _

logger = logging.getLogger(__name__)

APPLY_DELAY = 0.7
TDP_DELAY = 0.1
SLEEP_DELAY = 4
MIN_TDP = 7
MAX_TDP = 30
# FIXME: add AC/DC values
MAX_TDP_BOOST = 35

FTDP_FN = "/sys/devices/platform/asus-nb-wmi/ppt_fppt"
STDP_FN = "/sys/devices/platform/asus-nb-wmi/ppt_pl2_sppt"
CTDP_FN = "/sys/devices/platform/asus-nb-wmi/ppt_pl1_spl"
EXTREME_FN = "/sys/devices/platform/asus-nb-wmi/mcu_powersave"
EXTREME_ENABLE = bool(os.environ.get("HHD_ALLY_POWERSAVE", None))
# This setting can really mess up the controller
EXTREME_STARTUP_DELAY = 12
EXTREME_DELAY = 3.8

FAN_CURVE_ENDPOINT = "/sys/class/hwmon"
FAN_CURVE_NAME = "asus_custom_fan_curve"

# Default Ally curve is the following
# [40 45 55 63 68 74 74 74]
# [10 20 66 86 132 188 188 188] / 2.55
# [ 4  8  ]

# Unplugged values
#       STAPM Slow Fast
# perf  25 30 35
# bal   15 20 25
# power 10 14 17
#
# Plugged in values
# perf  30 43 53
# bal   15 20 25
# power 10 14 17

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
    def __init__(self, allyx: bool = False) -> None:
        self.name = f"adjustor_asus"
        self.priority = 6
        self.log = "adja"
        self.enabled = False
        self.initialized = False
        self.enforce_limits = True
        self.startup = True
        self.old_conf = None
        self.mode = None
        self.cycle_tdp = None

        self.extreme_standby = None
        self.extreme_supported = None

        self.queue_fan = None
        self.queue_tdp = None
        self.queue_charge_limit = None
        self.queue_extreme = time.perf_counter() + EXTREME_STARTUP_DELAY
        self.new_tdp = None
        self.new_mode = None
        self.old_target = None
        self.pp = None
        self.sys_tdp = False
        self.allyx = allyx

    def settings(self):
        if not self.enabled:
            self.initialized = False
            self.old_conf = None
            self.startup = True
            return {}

        self.initialized = True
        out = {"tdp": {"asus": load_relative_yaml("settings.yml")}}

        path_exists = os.path.exists(EXTREME_FN)
        extreme_supported = EXTREME_ENABLE and path_exists
        if self.extreme_supported is None:
            logger.info(
                f"Extreme standby enabled: {EXTREME_ENABLE}, file exists: {extreme_supported}. Enabled: {extreme_supported}"
            )
        self.extreme_supported = extreme_supported
        if not self.extreme_supported:
            del out["tdp"]["asus"]["children"]["extreme_standby"]

        # Set units
        if self.allyx:
            out["tdp"]["asus"]["children"]["tdp_v2"]["modes"]["quiet"]["unit"] = "13W"
            out["tdp"]["asus"]["children"]["tdp_v2"]["modes"]["balanced"][
                "unit"
            ] = "17W"
            out["tdp"]["asus"]["children"]["tdp_v2"]["modes"]["performance"][
                "unit"
            ] = "25/30W"
        else:
            out["tdp"]["asus"]["children"]["tdp_v2"]["modes"]["quiet"]["unit"] = "10W"
            out["tdp"]["asus"]["children"]["tdp_v2"]["modes"]["balanced"][
                "unit"
            ] = "15W"
            out["tdp"]["asus"]["children"]["tdp_v2"]["modes"]["performance"][
                "unit"
            ] = "25/30W"

        if not self.enforce_limits:
            out["tdp"]["asus"]["children"]["tdp_v2"]["modes"]["custom"]["children"][
                "tdp"
            ]["max"] = 50
        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

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

        curr = time.perf_counter()

        # Charge limit
        lim = conf["tdp.asus.charge_limit"].to(str)
        if (self.startup and lim != "disabled") or (
            lim != self.old_conf["charge_limit"].to(str)
        ):
            self.queue_charge_limit = curr + APPLY_DELAY

        if self.queue_charge_limit and self.queue_charge_limit < curr:
            self.queue_charge_limit = None
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
        new_target = None
        new_tdp = self.new_tdp
        self.new_tdp = None
        new_mode = self.new_mode
        self.new_mode = None
        if new_tdp:
            # For TDP values received from steam, set the appropriate
            # mode to get a better experience.
            # if new_tdp == (13 if ally_x else 10):
            #     mode = "quiet"
            # elif new_tdp == (17 if ally_x else 15):
            #     mode = "balanced"
            # elif new_tdp == 25 or new_tdp == 30:
            #     mode = "performance"
            # else:
            #     mode = "custom"
            mode = "custom"
            conf["tdp.asus.tdp_v2.mode"] = mode
        elif new_mode:
            mode = new_mode
            conf["tdp.asus.tdp_v2.mode"] = mode
        else:
            mode = conf["tdp.asus.tdp_v2.mode"].to(str)
        self.mode = mode

        tdp_reset = False
        if mode is not None and mode != self.old_conf["tdp_v2.mode"].to(str):
            if not new_tdp:
                self.sys_tdp = False
            tdp_reset = True

        if mode is not None and self.startup:
            tdp_reset = True

        # Handle EPP for presets
        if tdp_reset and mode != "custom":
            match mode:
                case "quiet":
                    set_platform_profile("quiet")
                    new_target = "power"
                case "balanced":
                    set_platform_profile("balanced")
                    new_target = "balanced"
                case _:  # "performance":
                    set_platform_profile("performance")
                    new_target = "performance"

        # In custom mode, re-apply settings with debounce
        tdp_set = False
        if mode == "custom":
            # Check user changed values
            if new_tdp:
                steady = new_tdp
                conf["tdp.asus.tdp_v2.custom.tdp"] = steady
            else:
                steady = conf["tdp.asus.tdp_v2.custom.tdp"].to(int)

            if self.enforce_limits:
                if steady < MIN_TDP:
                    steady = MIN_TDP
                    conf["tdp.asus.tdp_v2.custom.tdp"] = steady
                elif steady > MAX_TDP:
                    steady = MAX_TDP
                    conf["tdp.asus.tdp_v2.custom.tdp"] = steady

            steady_updated = steady and steady != self.old_conf["tdp_v2.custom.tdp"].to(
                int
            )
            if not new_tdp and steady_updated:
                self.sys_tdp = False

            steady_updated |= tdp_reset

            if self.startup and (steady > MAX_TDP or steady < MIN_TDP):
                logger.warning(
                    f"TDP ({steady}) outside the device spec. Resetting for stability reasons."
                )
                steady = min(max(steady, MIN_TDP), MAX_TDP)
                conf["tdp.asus.tdp_v2.custom.tdp"] = steady
                steady_updated = True

            boost = conf["tdp.asus.tdp_v2.custom.boost"].to(bool)
            boost_updated = boost != self.old_conf["tdp_v2.custom.boost"].to(bool)

            # If yes, queue an update
            # Debounce
            if self.startup or steady_updated or boost_updated:
                self.queue_tdp = curr + APPLY_DELAY

            tdp_set = self.queue_tdp and self.queue_tdp < curr
            if tdp_set:
                if steady < 5:
                    steady = 5
                if steady < (15 if self.allyx else 13):
                    set_platform_profile("quiet")
                    new_target = "power"
                elif steady < (22 if self.allyx else 20):
                    set_platform_profile("balanced")
                    new_target = "balanced"
                else:
                    set_platform_profile("performance")
                    new_target = "performance"

                self.queue_tdp = None
                if boost:
                    # TODO: Use different boost values depending on whether plugged in
                    time.sleep(TDP_DELAY)
                    set_tdp(
                        "fast",
                        FTDP_FN,
                        min(max(steady, MAX_TDP_BOOST), int(steady * 35 / 25)),
                    )
                    time.sleep(TDP_DELAY)
                    set_tdp(
                        "slow",
                        STDP_FN,
                        min(max(steady, MAX_TDP_BOOST), int(steady * 30 / 25)),
                    )
                    time.sleep(TDP_DELAY)
                    set_tdp("steady", CTDP_FN, steady)
                else:
                    time.sleep(TDP_DELAY)
                    set_tdp("fast", FTDP_FN, steady)
                    time.sleep(TDP_DELAY)
                    set_tdp("slow", STDP_FN, steady)
                    time.sleep(TDP_DELAY)
                    set_tdp("steady", CTDP_FN, steady)

        if new_target and new_target != self.old_target:
            self.old_target = new_target
            self.emit({"type": "energy", "status": new_target})
            self.pp = new_target

        # Handle fan curve resets
        if conf["tdp.asus.fan.manual.reset"].to(bool):
            conf["tdp.asus.fan.manual.reset"] = False
            for k, v in zip(POINTS, DEFAULT_CURVE):
                conf[f"tdp.asus.fan.manual.st{k}"] = v

        manual_fan_curve = conf["tdp.asus.fan.mode"].to(str) == "manual"

        # Handle fan curve limits by Asus
        # by enforcing minimum values based on power profile
        # which is a proxy of the current platform profile but still
        # a bit of a hack. TODO: Get the exact limits.
        # FIXME: Revisit limits
        # if manual_fan_curve:
        #     match self.pp:
        #         case "balanced":
        #             min_val = 45
        #         case "performance":
        #             min_val = 60
        #         case _:  # quiet
        #             min_val = 17

        #     for k in POINTS:
        #         if conf[f"tdp.asus.fan.manual.st{k}"].to(int) < min_val:
        #             conf[f"tdp.asus.fan.manual.st{k}"] = min_val

        # Check if fan curve has changed
        # Use debounce logic on these changes
        if ((tdp_reset and mode != "custom") or tdp_set) and manual_fan_curve:
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
        if apply_curve or tdp_set:
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

        # Show steam message
        if self.sys_tdp:
            conf["tdp.asus.sys_tdp"] = _("Steam is controlling TDP")
        else:
            conf["tdp.asus.sys_tdp"] = ""

        # Save current config
        self.cycle_tdp = conf["tdp.asus.cycle_tdp"].to(bool)
        self.old_conf = conf["tdp.asus"]

        if self.startup:
            self.startup = False

        # Extreme standby
        if self.extreme_supported:
            standby = conf["tdp.asus.extreme_standby"].to(bool)
            if self.extreme_standby is not None and self.extreme_standby != standby:
                self.queue_extreme = curr + EXTREME_DELAY
            self.extreme_standby = standby

            if self.queue_extreme and self.queue_extreme < curr:
                self.queue_extreme = None
                try:
                    nval = standby == "enabled"
                    with open(EXTREME_FN, "r") as f:
                        cval = f.read().strip() == "1"
                    if nval != cval:
                        logger.info(f"Setting extreme standby to '{standby}'")
                        with open(EXTREME_FN, "w") as f:
                            f.write("1" if standby == "enabled" else "0")
                    else:
                        logger.info(f"Extreme standby already set to '{standby}'")
                except Exception as e:
                    logger.error(f"Could not set extreme standby. Error:\n{e}")

    def notify(self, events: Sequence[Event]):
        for ev in events:
            if ev["type"] == "tdp":
                self.new_tdp = ev["tdp"]
                self.sys_tdp = ev["tdp"] is not None
            elif ev["type"] == "ppd":
                match ev["status"]:
                    case "power":
                        self.new_mode = "quiet"
                    case "balanced":
                        self.new_mode = "balanced"
                    case "performance":
                        self.new_mode = "performance"
            elif ev["type"] == "special" and ev.get("event", None) == "wakeup":
                logger.info(
                    f"Waking up from sleep, resetting TDP after {SLEEP_DELAY} seconds."
                )
                self.queue_tdp = time.time() + SLEEP_DELAY
            elif self.cycle_tdp and ev["type"] == "special" and ev["event"] == "xbox_y":
                match self.mode:
                    case "quiet":
                        self.new_mode = "balanced"
                        event = "tdp_cycle_balanced"
                    case "balanced":
                        self.new_mode = "performance"
                        event = "tdp_cycle_performance"
                    case "performance":
                        self.new_mode = "custom"
                        event = "tdp_cycle_custom"
                    case "custom":
                        self.new_mode = "quiet"
                        event = "tdp_cycle_quiet"
                    case _:
                        self.new_mode = "balanced"
                        event = "tdp_cycle_balanced"

                logger.info(f"Cycling TDP to '{self.new_mode}'")
                if self.emit:
                    self.emit({"type": "special", "event": event})

    def close(self):
        pass
