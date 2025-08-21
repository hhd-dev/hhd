import logging
import os
import time
from typing import Sequence

from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml

from adjustor.core.platform import set_platform_profile
from adjustor.core.const import DeviceTDPv2
from adjustor.i18n import _

logger = logging.getLogger(__name__)

APPLY_DELAY = 0.7
TDP_DELAY = 0.1
SLEEP_DELAY = 4

TDP_PL3_FN = "/sys/class/firmware-attributes/msi-wmi-platform/attributes/ppt_pl3_fppt/current_value"
TDP_PL2_FN = "/sys/class/firmware-attributes/msi-wmi-platform/attributes/ppt_pl2_sppt/current_value"
TDP_PL1_FN = "/sys/class/firmware-attributes/msi-wmi-platform/attributes/ppt_pl1_spl/current_value"

FAN_CURVE_ENDPOINT = "/sys/class/hwmon"
FAN_CURVE_NAME = "msi_wmi_platform"

# Default MSI Claw AI+ 8 curve is the following
# [0  50  60  70  80  88] temp (C)
# [0  40  49  58  67  75] pwm  (%)
# [0 102 124 147 170 191] / 2.55


# Claw 1st gen
# DC values
#       PL1 PL2
# perf   43  45
# bal    35  35
# power  20  20
#
# AC values
#       PL1 PL2
# perf   35  35
# bal    30  30
# power  20  20

# Claw AI+
# DC values
#       PL1 PL2
# perf   30  37
# bal    12  37
# power   8  37
#
# AC values
#       PL1 PL2
# perf   30  37
# bal    12  37
# power   8  37
#
# Claw 8A
# Both AC/DC values
#       SPL SPPT FPPT
# perf   28   45   55
# bal    20   33   43
# power  15   28   33

POINTS = [0, 50, 60, 70, 80, 88]
DEFAULT_CURVE = [0, 102, 124, 147, 170, 191]


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


def has_msi_driver():
    return os.path.exists(TDP_PL1_FN) and os.path.exists(TDP_PL2_FN)


class MsiDriverPlugin(HHDPlugin):
    def __init__(self, tdp_data: DeviceTDPv2) -> None:
        self.name = f"adjustor_msi"
        self.priority = 6
        self.log = "adjm"
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
        self.new_tdp = None
        self.new_mode = None
        self.old_target = None
        self.pp = None
        self.sys_tdp = False
        self.tdp_data = tdp_data

    def settings(self):
        if not self.enabled:
            self.initialized = False
            self.old_conf = None
            self.startup = True
            return {}

        if not has_msi_driver():
            logger.error("MSI driver not found. Disabling TDP controls.")
            self.initialized = False

            return {"tdp": {"msi": load_relative_yaml("error.yml")}}

        self.initialized = True
        out = {"tdp": {"msi": load_relative_yaml("settings.yml")}}

        # Set units
        out["tdp"]["msi"]["children"]["tdp"]["modes"]["quiet"][
            "unit"
        ] = f"{self.tdp_data['quiet'][0]}W"
        out["tdp"]["msi"]["children"]["tdp"]["modes"]["balanced"][
            "unit"
        ] = f"{self.tdp_data['balanced'][0]}W"

        # Set performance pretty print
        if (
            self.tdp_data.get("performance_dc", None)
            and self.tdp_data["performance_dc"] != self.tdp_data["performance"][0]
        ):
            perf_tdp = (
                f"{self.tdp_data['performance_dc']}W/{self.tdp_data['performance'][0]}W"
            )
        else:
            perf_tdp = f"{self.tdp_data['performance']}W"
        out["tdp"]["msi"]["children"]["tdp"]["modes"]["performance"]["unit"] = perf_tdp

        # Set custom pretty print
        if (
            self.tdp_data.get("max_tdp_dc", None)
            and self.tdp_data["max_tdp_dc"] != self.tdp_data["max_tdp"]
        ):
            custom_tdp = f"→ {self.tdp_data['max_tdp_dc']}W/{self.tdp_data['max_tdp']}W"
        else:
            custom_tdp = f"→ {self.tdp_data['max_tdp']}W"
        out["tdp"]["msi"]["children"]["tdp"]["modes"]["custom"]["unit"] = custom_tdp

        # Fix custom slider
        custom_sel = out["tdp"]["msi"]["children"]["tdp"]["modes"]["custom"][
            "children"
        ]["tdp"]
        custom_sel["min"] = self.tdp_data["min_tdp"]
        custom_sel["max"] = self.tdp_data["max_tdp"]
        custom_sel["default"] = self.tdp_data["balanced"][0]

        # Add overclocking
        if not self.enforce_limits and self.tdp_data.get("max_tdp_oc", None):
            out["tdp"]["msi"]["children"]["tdp"]["modes"]["custom"]["children"]["tdp"][
                "max"
            ] = self.tdp_data["max_tdp_oc"]

        # Remove cycle for laptops (for now)
        if not self.tdp_data.get("supports_cycle", None):
            del out["tdp"]["msi"]["children"]["cycle_tdp"]

        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

        # TODO: Remove me once the autoload issue is fixed
        os.system("modprobe msi_wmi_platform")

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
            self.old_conf = conf["tdp.msi"]
            return

        curr = time.perf_counter()

        #
        # TDP
        #
        new_target = None
        new_tdp = self.new_tdp
        self.new_tdp = None
        new_mode = self.new_mode
        self.new_mode = None
        if new_tdp:
            mode = "custom"
            conf["tdp.msi.tdp.mode"] = mode
        elif new_mode:
            mode = new_mode
            conf["tdp.msi.tdp.mode"] = mode
        else:
            mode = conf["tdp.msi.tdp.mode"].to(str)
        self.mode = mode

        tdp_reset = False
        if mode is not None and mode != self.old_conf["tdp.mode"].to(str):
            if not new_tdp:
                self.sys_tdp = False
            tdp_reset = True

        if mode is not None and self.startup:
            tdp_reset = True

        # Handle EPP for presets
        if tdp_reset and mode != "custom":
            match mode:
                case "quiet":
                    set_platform_profile("low-power")
                    spl, sppt, fppt = self.tdp_data["quiet"]
                    set_tdp("pl1_spl", TDP_PL1_FN, spl)
                    set_tdp("pl2_sppt", TDP_PL2_FN, sppt)
                    if fppt is not None:
                        set_tdp("pl3_fppt", TDP_PL3_FN, fppt)
                    new_target = "power"
                case "balanced":
                    set_platform_profile("balanced")
                    spl, sppt, fppt = self.tdp_data["balanced"]
                    set_tdp("pl1_spl", TDP_PL1_FN, spl)
                    set_tdp("pl2_sppt", TDP_PL2_FN, sppt)
                    if fppt is not None:
                        set_tdp("pl3_fppt", TDP_PL3_FN, fppt)
                    new_target = "balanced"
                case _:  # "performance":
                    set_platform_profile("performance")
                    spl, sppt, fppt = self.tdp_data["performance"]
                    set_tdp("pl1_spl", TDP_PL1_FN, spl)
                    set_tdp("pl2_sppt", TDP_PL2_FN, sppt)
                    if fppt is not None:
                        set_tdp("pl3_fppt", TDP_PL3_FN, fppt)
                    new_target = "performance"

        # In custom mode, re-apply settings with debounce
        tdp_set = False
        if mode == "custom":
            # Check user changed values
            if new_tdp:
                steady = new_tdp
                conf["tdp.msi.tdp.custom.tdp"] = steady
            else:
                steady = conf["tdp.msi.tdp.custom.tdp"].to(int)

            if self.enforce_limits:
                if steady < self.tdp_data["min_tdp"]:
                    steady = self.tdp_data["min_tdp"]
                    conf["tdp.msi.tdp.custom.tdp"] = steady
                elif steady > self.tdp_data["max_tdp"]:
                    steady = self.tdp_data["max_tdp"]
                    conf["tdp.msi.tdp.custom.tdp"] = steady

            steady_updated = steady and steady != self.old_conf["tdp.custom.tdp"].to(
                int
            )
            if not new_tdp and steady_updated:
                self.sys_tdp = False

            steady_updated |= tdp_reset

            if self.startup and (
                steady > self.tdp_data["max_tdp"] or steady < self.tdp_data["min_tdp"]
            ):
                logger.warning(
                    f"TDP ({steady}) outside the device spec. Resetting for stability reasons."
                )
                steady = min(
                    max(steady, self.tdp_data["min_tdp"]), self.tdp_data["max_tdp"]
                )
                conf["tdp.msi.tdp.custom.tdp"] = steady
                steady_updated = True

            boost = conf["tdp.msi.tdp.custom.boost"].to(bool)
            boost_updated = boost != self.old_conf["tdp.custom.boost"].to(bool)

            # If yes, queue an update
            # Debounce
            if self.startup or steady_updated or boost_updated:
                self.queue_tdp = curr + APPLY_DELAY

            tdp_set = self.queue_tdp and self.queue_tdp < curr
            if tdp_set:
                if steady < self.tdp_data["min_tdp"]:
                    steady = 5
                if steady < self.tdp_data["balanced_min"]:
                    set_platform_profile("low-power")
                    new_target = "power"
                elif steady < self.tdp_data["performance_min"]:
                    set_platform_profile("balanced")
                    new_target = "balanced"
                else:
                    set_platform_profile("performance")
                    new_target = "performance"

                self.queue_tdp = None
                if boost:
                    if os.path.exists(TDP_PL3_FN):
                        time.sleep(TDP_DELAY)
                        set_tdp(
                            "fast",
                            TDP_PL3_FN,
                            min(
                                max(
                                    steady,
                                    self.tdp_data["max_tdp_fppt"]
                                    or self.tdp_data["max_tdp"],
                                ),
                                (
                                    int(
                                        steady
                                        * self.tdp_data["max_tdp_fppt"]
                                        / self.tdp_data["max_tdp"]
                                    )
                                    if self.tdp_data["max_tdp_fppt"]
                                    else steady
                                ),
                            ),
                        )
                    time.sleep(TDP_DELAY)
                    set_tdp(
                        "slow",
                        TDP_PL2_FN,
                        min(
                            max(
                                steady,
                                self.tdp_data["max_tdp_sppt"]
                                or self.tdp_data["max_tdp"],
                            ),
                            (
                                int(
                                    steady
                                    * self.tdp_data["max_tdp_sppt"]
                                    / self.tdp_data["max_tdp"]
                                )
                                if self.tdp_data["max_tdp_sppt"]
                                else steady
                            ),
                        ),
                    )
                    time.sleep(TDP_DELAY)
                    set_tdp("steady", TDP_PL1_FN, steady)
                else:
                    if os.path.exists(TDP_PL3_FN):
                        time.sleep(TDP_DELAY)
                        set_tdp("fast", TDP_PL3_FN, steady)
                    time.sleep(TDP_DELAY)
                    set_tdp("slow", TDP_PL2_FN, steady)
                    time.sleep(TDP_DELAY)
                    set_tdp("steady", TDP_PL1_FN, steady)

        if new_target and new_target != self.old_target:
            self.old_target = new_target
            self.emit({"type": "energy", "status": new_target})
            self.pp = new_target

        # Handle fan curve resets
        if conf["tdp.msi.fan.manual.reset"].to(bool):
            conf["tdp.msi.fan.manual.reset"] = False
            for k, v in zip(POINTS, DEFAULT_CURVE):
                conf[f"tdp.msi.fan.manual.st{k}"] = v

        manual_fan_curve = conf["tdp.msi.fan.mode"].to(str) == "manual"

        # Check if fan curve has changed
        # Use debounce logic on these changes
        if ((tdp_reset and mode != "custom") or tdp_set) and manual_fan_curve:
            self.queue_fan = curr + APPLY_DELAY

        for i in POINTS:
            if conf[f"tdp.msi.fan.manual.st{i}"].to(int) != self.old_conf[
                f"fan.manual.st{i}"
            ].to(int):
                self.queue_fan = curr + APPLY_DELAY
        # If mode changes, only apply curve if set to manual
        # otherwise disable and reset tdp
        if conf["tdp.msi.fan.mode"].to(str) != self.old_conf["fan.mode"].to(str):
            if conf["tdp.msi.fan.mode"].to(str) == "manual":
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
                if conf["tdp.msi.fan.mode"].to(str) == "manual":
                    set_fan_curve(
                        POINTS,
                        [
                            min(
                                int(conf[f"tdp.msi.fan.manual.st{i}"].to(int) * 2.55),
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
            conf["tdp.msi.sys_tdp"] = _("Steam is controlling TDP")
        else:
            conf["tdp.msi.sys_tdp"] = ""

        # Save current config
        self.cycle_tdp = self.tdp_data.get("supports_cycle", False) and conf.get(
            "tdp.msi.cycle_tdp", False
        )
        self.old_conf = conf["tdp.msi"]

        if self.startup:
            self.startup = False

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
            elif (
                ev["type"] == "acpi"
                and ev["event"] in ("ac", "dc")
                and not self.queue_tdp
            ):
                logger.info(
                    f"Power adapter status switched to '{ev['event']}', resetting TDP."
                )
                self.queue_tdp = time.time() + APPLY_DELAY
            elif (
                self.cycle_tdp
                and ev["type"] == "special"
                and ev["event"] == "xbox_y_internal"
            ) or (ev["type"] == "special" and ev["event"] == "tdp_cycle"):
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
