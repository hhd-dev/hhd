import logging
import time
from typing import Sequence, cast

from hhd.plugins import Context, Event, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

from adjustor.core.lenovo import (
    MIN_CURVE,
    TdpMode,
    get_bios_version,
    get_charge_limit,
    get_full_fan_speed,
    get_power_light,
    get_power_light_v1,
    get_tdp_mode,
    set_charge_limit,
    set_fan_curve,
    set_fast_tdp,
    set_full_fan_speed,
    set_power_light,
    set_power_light_v1,
    set_slow_tdp,
    set_steady_tdp,
    set_tdp_mode,
)
from adjustor.i18n import _

logger = logging.getLogger(__name__)

APPLY_DELAY = 0.5
TDP_DELAY = 0


class LenovoDriverPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_lenovo"
        self.priority = 6
        self.log = "adjl"
        self.enabled = False
        self.initialized = False
        self.enforce_limits = True
        self.startup = True
        self.old_conf = None
        self.sys_tdp = False
        self.fan_curve_set = False
        self.notify_tdp = False

        bios_version = get_bios_version()
        logger.info(f"Lenovo BIOS version: {bios_version}")
        self.power_light_v2 = bios_version >= 35

        self.queue_fan = None
        self.queue_tdp = None
        self.new_tdp = None
        self.new_mode = None
        self.old_target = None

    def settings(self):
        if not self.enabled:
            self.initialized = False
            self.old_conf = None
            self.startup = True
            return {}

        self.initialized = True
        out = {"tdp": {"lenovo": load_relative_yaml("settings.yml")}}
        if not self.power_light_v2:
            del out["tdp"]["lenovo"]["children"]["power_light_sleep"]
        if not self.enforce_limits:
            out["tdp"]["lenovo"]["children"]["tdp"]["modes"]["custom"]["children"][
                "tdp"
            ]["max"] = 40
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
            self.fan_curve_set = False
            return

        #
        # Checks
        #

        # Initialize values so we do not query them all the time
        tdp_reset = self.startup
        if self.startup:
            conf["tdp.lenovo.ffss"] = get_full_fan_speed()
            if self.power_light_v2:
                conf["tdp.lenovo.power_light"] = get_power_light(suspend=False)
                conf["tdp.lenovo.power_light_sleep"] = get_power_light(suspend=True)
            else:
                conf["tdp.lenovo.power_light"] = get_power_light_v1()

            conf["tdp.lenovo.charge_limit"] = get_charge_limit()

        # If not old config, exit, as values can not be set
        if not self.old_conf:
            self.old_conf = conf["tdp.lenovo"]
            return

        curr = time.time()

        #
        # Other options
        #
        ffss = conf["tdp.lenovo.ffss"].to(bool)
        if ffss is not None and ffss != self.old_conf["ffss"].to(bool):
            set_full_fan_speed(ffss)

        power_light = conf["tdp.lenovo.power_light"].to(bool)
        if power_light is not None and power_light != self.old_conf["power_light"].to(
            bool
        ):
            if self.power_light_v2:
                set_power_light(power_light, suspend=False)
            else:
                set_power_light_v1(power_light)
        if self.power_light_v2:
            power_light_sleep = conf["tdp.lenovo.power_light_sleep"].to(bool)
            if (
                power_light_sleep != self.old_conf["power_light_sleep"].to(bool)
                and power_light_sleep is not None
            ):
                set_power_light(power_light_sleep, suspend=True)

        charge_limit = conf["tdp.lenovo.charge_limit"].to(bool)
        if charge_limit is not None and charge_limit != self.old_conf[
            "charge_limit"
        ].to(bool):
            set_charge_limit(charge_limit)

        #
        # TDP
        #

        # Update tdp mode if user changed through the app
        new_target = None
        new_tdp = self.new_tdp
        self.new_tdp = None
        new_mode = self.new_mode
        self.new_mode = None
        if new_tdp:
            # For TDP values received from steam, set the appropriate
            # mode to get a better experience.
            if new_tdp == 8:
                mode = "quiet"
            elif new_tdp == 15:
                mode = "balanced"
            elif new_tdp == 20:
                mode = "performance"
            else:
                mode = "custom"
            conf["tdp.lenovo.tdp.mode"] = mode
        elif new_mode:
            mode = new_mode
            conf["tdp.lenovo.tdp.mode"] = mode
        else:
            mode = conf["tdp.lenovo.tdp.mode"].to(str)
        if mode is not None and mode != self.old_conf["tdp.mode"].to(str):
            set_tdp_mode(cast(TdpMode, mode))
            tdp_reset = True

        # Grab from power button
        new_mode = get_tdp_mode()
        if new_mode != mode:
            if not new_tdp:
                self.sys_tdp = False
            tdp_reset = True
        conf["tdp.lenovo.tdp.mode"] = new_mode

        # Reset fan curve on mode change
        # Has to happen before setting the stdp, ftdp values, in case
        # we are in custom mode
        fan_mode = conf["tdp.lenovo.fan.mode"].to(str)
        if fan_mode != self.old_conf["fan.mode"].to(str) and fan_mode != "manual":
            tdp_mode = get_tdp_mode()
            if tdp_mode:
                set_tdp_mode("performance")
                time.sleep(TDP_DELAY)
                set_tdp_mode(tdp_mode)
                tdp_reset = True

        # Handle EPP for presets
        if tdp_reset and new_mode != "custom":
            match new_mode:
                case "quiet":
                    new_target = "power"
                case "balanced":
                    new_target = "balanced"
                case "performance":
                    new_target = "performance"

        # In custom mode, re-apply settings with debounce
        if new_mode == "custom":
            # Check user changed values
            steady = conf["tdp.lenovo.tdp.custom.tdp"].to(int)
            if new_tdp:
                steady = new_tdp
                conf["tdp.lenovo.tdp.custom.tdp"] = steady

            old_steady = steady
            if self.enforce_limits:
                steady = min(max(steady, 4), 30)
            else:
                steady = min(max(steady, 0), 50)
            if old_steady != steady:
                conf["tdp.lenovo.tdp.custom.tdp"] = steady

            steady_updated = steady and steady != self.old_conf["tdp.custom.tdp"].to(
                int
            )
            if steady_updated and not new_tdp:
                self.sys_tdp = False

            if self.startup and (steady > 30 or steady < 7):
                logger.warning(
                    f"TDP ({steady}) outside the device spec. Resetting for stability reasons."
                )
                steady = 30
                conf["tdp.lenovo.tdp.custom.tdp"] = 30
                steady_updated = True

            boost = conf["tdp.lenovo.tdp.custom.boost"].to(bool)
            boost_updated = boost != self.old_conf["tdp.custom.boost"].to(bool)

            # If yes, queue an update
            # Debounce
            if steady_updated or boost_updated or tdp_reset:
                self.queue_tdp = curr + APPLY_DELAY

            if self.queue_tdp and self.queue_tdp < curr:
                self.queue_tdp = None
                if boost:
                    set_steady_tdp(steady)
                    time.sleep(TDP_DELAY)
                    set_slow_tdp(steady + 2)
                    time.sleep(TDP_DELAY)
                    set_fast_tdp(min(42, int(steady * 41 / 30)))
                else:
                    set_steady_tdp(steady)
                    time.sleep(TDP_DELAY)
                    set_slow_tdp(steady)
                    time.sleep(TDP_DELAY)
                    set_fast_tdp(steady)

                # Handle EPP for custom mode
                if steady < 12:
                    new_target = "power"
                elif steady <= 20:
                    new_target = "balanced"
                else:
                    new_target = "performance"

        # Handle EPP application
        if new_target and new_target != self.old_target:
            self.old_target = new_target
            self.emit({"type": "energy", "status": new_target})

        # Fan curve stuff
        # If tdp reset, so was the curve
        if tdp_reset:
            # 2x to apply after tdp
            self.queue_fan = curr + 2 * APPLY_DELAY

        # Handle fan curve resets
        if conf["tdp.lenovo.fan.manual.reset"].to(bool):
            conf["tdp.lenovo.fan.manual.reset"] = False
            for i, v in enumerate(MIN_CURVE):
                conf[f"tdp.lenovo.fan.manual.st{(i + 1)*10}"] = v

        # Handle fan curve limits
        for i, v in enumerate(MIN_CURVE):
            val = conf[f"tdp.lenovo.fan.manual.st{(i + 1)*10}"].to(int)
            old_val = val
            if conf["tdp.lenovo.fan.manual.enforce_limits"].to(bool) and val < v:
                val = v

            val = max(min(val, 115), 0)
            if old_val != val:
                conf[f"tdp.lenovo.fan.manual.st{(i + 1)*10}"] = val

        # Check if fan curve has changed
        # Use debounce logic on these changes
        for i in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            if conf[f"tdp.lenovo.fan.manual.st{i}"].to(int) != self.old_conf[
                f"fan.manual.st{i}"
            ].to(int):
                self.queue_fan = curr + APPLY_DELAY

        apply_curve = (
            self.queue_fan and self.queue_fan < curr
        ) or not self.fan_curve_set
        if conf["tdp.lenovo.fan.mode"].to(str) == "manual" and apply_curve:
            try:
                set_fan_curve(
                    [
                        conf[f"tdp.lenovo.fan.manual.st{i}"].to(int)
                        for i in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
                    ]
                )
            except Exception as e:
                logger.error(f"Could not set fan curve. Error:\n{e}")
            self.fan_curve_set = True
            self.queue_fan = None

        # Show steam message
        if self.sys_tdp:
            conf["tdp.lenovo.cycle_info"] = _("Steam is controlling TDP")
        else:
            conf["tdp.lenovo.cycle_info"] = _("Legion L + Y changes TDP Mode")

        # Save current config
        self.old_conf = conf["tdp.lenovo"]

        if self.notify_tdp:
            self.notify_tdp = False
            print(new_mode)
            if conf.get("tdp.lenovo.tdp_rgb", False):
                self.emit({"type": "special", "event": f"tdp_cycle_{new_mode}"})  # type: ignore

        if self.startup:
            self.startup = False

    def notify(self, events: Sequence[Event]):
        for ev in events:
            if ev["type"] == "tdp":
                self.new_tdp = ev["tdp"]
                self.sys_tdp = ev["tdp"] is not None
            if ev["type"] == "ppd":
                match ev["status"]:
                    case "power":
                        self.new_mode = "quiet"
                    case "balanced":
                        self.new_mode = "balanced"
                    case "performance":
                        self.new_mode = "performance"
            print(ev)
            if ev["type"] == "acpi" and ev.get("event", None) == "tdp":
                self.notify_tdp = True

    def close(self):
        pass
