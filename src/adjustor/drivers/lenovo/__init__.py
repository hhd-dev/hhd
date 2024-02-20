import logging

from hhd.plugins import Context, HHDPlugin, HHDSettings, load_relative_yaml
from hhd.plugins.conf import Config
from typing import cast

from adjustor.core.lenovo import (
    TdpMode,
    get_fan_curve,
    get_fast_tdp,
    get_full_fan_speed,
    get_power_light,
    get_steady_tdp,
    get_tdp_mode,
    set_fast_tdp,
    set_full_fan_speed,
    set_power_light,
    set_slow_tdp,
    set_steady_tdp,
    set_tdp_mode,
    set_fan_curve,
)

logger = logging.getLogger(__name__)


class LenovoDriverPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_lenovo"
        self.priority = 6
        self.log = "adjl"
        self.enabled = False
        self.initialized = False
        self.startup = True
        self.old_conf = None
        self.fan_curve_set = False

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}
        self.initialized = True
        return {"tdp": {"lenovo": load_relative_yaml("settings.yml")}}

    def open(
        self,
        emit,
        context: Context,
    ):
        pass

    def update(self, conf: Config):
        self.enabled = conf["tdp.general.enable"].to(bool)
        if not self.enabled or not self.initialized:
            return

        if self.old_conf:
            # Update device if something changed
            mode = conf["tdp.lenovo.tdp.mode"].to(str)
            if mode != self.old_conf["tdp.mode"].to(str):
                set_tdp_mode(cast(TdpMode, mode))
                self.fan_curve_set = False

            if mode == "custom":
                steady = conf["tdp.lenovo.tdp.custom.tdp"].to(int)
                steady_updated = steady and steady != self.old_conf[
                    "tdp.custom.tdp"
                ].to(int)
                if steady_updated:
                    set_steady_tdp(steady)

                boost = conf["tdp.lenovo.tdp.custom.boost"].to(bool)
                if (
                    steady_updated
                    or boost != self.old_conf["tdp.custom.boost"].to(bool)
                ) and boost is not None:
                    if boost:
                        set_slow_tdp(steady + 2)
                        set_fast_tdp(min(54, int(steady * 41 // 30)))
                    else:
                        set_slow_tdp(steady)
                        set_fast_tdp(steady)

            # Other options
            ffss = conf["tdp.lenovo.ffss"].to(bool)
            if ffss != self.old_conf["ffss"].to(bool):
                set_full_fan_speed(ffss)

            power_light = conf["tdp.lenovo.power_light"].to(bool)
            if power_light != self.old_conf["power_light"].to(bool):
                set_power_light(power_light)

            # Reset fan curve on mode change
            mode = conf["tdp.lenovo.fan.mode"].to(str)
            if mode != self.old_conf["fan.mode"].to(str) and mode != "manual":
                tdp_mode = get_tdp_mode()
                if tdp_mode:
                    set_tdp_mode("performance")
                    set_tdp_mode(tdp_mode)

            # Fan curve stuff, implies initialization
            if conf["tdp.lenovo.fan.manual.reset"].to(bool):
                conf["tdp.lenovo.fan.manual.reset"] = False
                conf["tdp.lenovo.fan.manual.st10"] = 44
                conf["tdp.lenovo.fan.manual.st20"] = 48
                conf["tdp.lenovo.fan.manual.st30"] = 55
                conf["tdp.lenovo.fan.manual.st40"] = 60
                conf["tdp.lenovo.fan.manual.st50"] = 71
                conf["tdp.lenovo.fan.manual.st60"] = 79
                conf["tdp.lenovo.fan.manual.st70"] = 87
                conf["tdp.lenovo.fan.manual.st80"] = 87
                conf["tdp.lenovo.fan.manual.st90"] = 100
                conf["tdp.lenovo.fan.manual.st100"] = 100

            if conf["tdp.lenovo.fan.manual.enforce_limits"].to(bool):
                if conf["tdp.lenovo.fan.manual.st10"].to(int) < 44:
                    conf["tdp.lenovo.fan.manual.st10"] = 44
                if conf["tdp.lenovo.fan.manual.st20"].to(int) < 48:
                    conf["tdp.lenovo.fan.manual.st20"] = 48
                if conf["tdp.lenovo.fan.manual.st30"].to(int) < 55:
                    conf["tdp.lenovo.fan.manual.st30"] = 55
                if conf["tdp.lenovo.fan.manual.st40"].to(int) < 60:
                    conf["tdp.lenovo.fan.manual.st40"] = 60
                if conf["tdp.lenovo.fan.manual.st50"].to(int) < 71:
                    conf["tdp.lenovo.fan.manual.st50"] = 71
                if conf["tdp.lenovo.fan.manual.st60"].to(int) < 79:
                    conf["tdp.lenovo.fan.manual.st60"] = 79
                if conf["tdp.lenovo.fan.manual.st70"].to(int) < 87:
                    conf["tdp.lenovo.fan.manual.st70"] = 87
                if conf["tdp.lenovo.fan.manual.st80"].to(int) < 87:
                    conf["tdp.lenovo.fan.manual.st80"] = 87
                if conf["tdp.lenovo.fan.manual.st90"].to(int) < 100:
                    conf["tdp.lenovo.fan.manual.st90"] = 100
                if conf["tdp.lenovo.fan.manual.st100"].to(int) < 100:
                    conf["tdp.lenovo.fan.manual.st100"] = 100

            if conf["tdp.lenovo.fan.mode"].to(str) == "manual" and conf[
                "tdp.lenovo.fan.manual.apply"
            ].to(bool):
                conf["tdp.lenovo.fan.manual.apply"] = False
                self.fan_curve_set = True
                set_fan_curve(
                    [
                        conf["tdp.lenovo.fan.manual.st10"].to(int),
                        conf["tdp.lenovo.fan.manual.st20"].to(int),
                        conf["tdp.lenovo.fan.manual.st30"].to(int),
                        conf["tdp.lenovo.fan.manual.st40"].to(int),
                        conf["tdp.lenovo.fan.manual.st50"].to(int),
                        conf["tdp.lenovo.fan.manual.st60"].to(int),
                        conf["tdp.lenovo.fan.manual.st70"].to(int),
                        conf["tdp.lenovo.fan.manual.st80"].to(int),
                        conf["tdp.lenovo.fan.manual.st90"].to(int),
                        conf["tdp.lenovo.fan.manual.st100"].to(int),
                    ]
                )

        # Initialize values so we do not query them all the time
        if self.startup:
            conf["tdp.lenovo.ffss"] = get_full_fan_speed()
            conf["tdp.lenovo.power_light"] = get_power_light()

            arr = get_fan_curve()
            if arr:
                conf["tdp.lenovo.fan.manual.st10"] = arr[0]
                conf["tdp.lenovo.fan.manual.st20"] = arr[1]
                conf["tdp.lenovo.fan.manual.st30"] = arr[2]
                conf["tdp.lenovo.fan.manual.st40"] = arr[3]
                conf["tdp.lenovo.fan.manual.st50"] = arr[4]
                conf["tdp.lenovo.fan.manual.st60"] = arr[5]
                conf["tdp.lenovo.fan.manual.st70"] = arr[6]
                conf["tdp.lenovo.fan.manual.st80"] = arr[7]
                conf["tdp.lenovo.fan.manual.st90"] = arr[8]
                conf["tdp.lenovo.fan.manual.st100"] = arr[9]
            self.startup = False

        # Update TDP values
        conf["tdp.lenovo.tdp.mode"] = get_tdp_mode()
        if self.old_conf and conf["tdp.lenovo.tdp.mode"].to(str) != self.old_conf[
            "tdp.mode"
        ].to(str):
            self.fan_curve_set = False
        if conf["tdp.lenovo.tdp.mode"].to(str) == "custom":
            steady = get_steady_tdp()
            fast = get_fast_tdp()
            if not isinstance(steady, int) or not isinstance(fast, int):
                logger.error(f"Could not read tdp values.")
                return
            conf["tdp.lenovo.tdp.custom.tdp"] = steady
            conf["tdp.lenovo.tdp.custom.boost"] = fast > steady + 2

        if self.fan_curve_set:
            conf["tdp.lenovo.fan.manual.status"] = "Set"
        else:
            conf["tdp.lenovo.fan.manual.status"] = "Not Set"
        self.old_conf = conf["tdp.lenovo"]

    def close(self):
        pass
