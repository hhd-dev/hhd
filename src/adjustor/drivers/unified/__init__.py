import logging
import os
import time
from threading import Event as TEvent
from threading import Lock, Thread
from typing import NamedTuple, Sequence

from adjustor.core.fan import FanInfo, fan_worker, get_fan_info
from adjustor.i18n import _
from hhd.plugins import Config, Context, Event, HHDPlugin, load_relative_yaml

logger = logging.getLogger(__name__)

APPLY_DELAY = 0.7
TDP_DELAY = 0.1
SLEEP_DELAY = 4

#
# Platform profiles interface
#

DEFAULT_MODE = "balanced"

PP_PATH = "/sys/class/platform-profile/"

PP_KNOWN = {
    "amd-dptc": {
        "low-power": _("Low Power"),
        "quiet": _("Quiet"),
        "balanced": _("Balanced"),
        "performance": _("Performance"),
        "custom": _("Custom"),
    },
    "lenovo-wmi-gamezone": {
        "low-power": _("Quiet"),
        "balanced": _("Balanced"),
        "performance": _("Performance"),
        "custom": _("Custom"),
    },
}


class PPData(NamedTuple):
    fn: str
    pp: str
    provider: str
    has_custom: bool
    profiles: tuple[tuple[str, str], ...]


def get_profiles() -> PPData | None:
    for pp in os.listdir(PP_PATH):
        if not pp.startswith("platform-profile"):
            continue

        try:
            with open(os.path.join(PP_PATH, pp, "name"), "r") as f:
                fn = f.read().strip()
        except Exception:
            continue

        provider = None
        for known in PP_KNOWN:
            if fn.startswith(known):
                provider = known
                break
        if not provider:
            continue
        try:
            with open(os.path.join(PP_PATH, pp, "choices"), "r") as f:
                choices = f.read().strip().split(" ")
        except Exception:
            logger.error(f"Could not read choices for PP provider {fn}")
            continue

        has_custom = "custom" in choices and "custom" in PP_KNOWN[provider]

        profiles = tuple(
                (k, v) for k, v in PP_KNOWN[provider].items() if k in choices
            )

        if not profiles:
            logger.info(f"Found no profiles for: '{pp}', '{fn}'")
            continue

        return PPData(
            fn=fn,
            pp=pp,
            provider=provider,
            has_custom=has_custom,
            profiles=profiles,
        )


def setup_modes(data: PPData, obj: dict):
    has_default = False
    for sys, pretty in data.profiles:
        obj["modes"][sys] = {
            "type": "container",
            "title": pretty,
        }
        if sys == DEFAULT_MODE:
            has_default = True
    obj["default"] = DEFAULT_MODE if has_default else data.profiles[-1][0]


def set_mode(data: PPData, profile: str):
    try:
        logger.info(
            f"Setting platform profile for '{data.fn}'{' (\'' + data.provider + '\')' if data.fn != data.provider else ''} to '{profile}'"
        )
        with open(os.path.join(PP_PATH, data.pp, "profile"), "w") as f:
            f.write(profile)
        return True
    except Exception as e:
        logger.error(f"Could not set platform profile with error:\n{e}")
        return False


#
# Firmware Attributes interface
#

SYS_ATTR_KNOWN = ["amd-dptc", "lenovo-wmi-other"]
SYS_ATTR_PATH = "/sys/class/firmware-attributes/"
SYS_ATTR_MID = "attributes"
TDP_PL3_FN = "ppt_pl3_fppt"
TDP_PL2_FN = "ppt_pl2_sppt"
TDP_PL1_FN = "ppt_pl1_spl"

MIN_VAL = "min_value"
MAX_VAL = "max_value"
DEF_VAL = "default_value"
CUR_VAL = "current_value"

PL1_TO_ENERGY_MAP = [
    (15, (6, 12)),
    (30, (10, 20)),
    (80, (25, 45)),
    (130, (30, 60)),
]


class FwattrData(NamedTuple):
    fn: str
    provider: str
    pl1: tuple[int, int | None, int]
    pl2: tuple[int, int | None, int] | None = None
    pl3: tuple[int, int | None, int] | None = None


def get_tdp_values(mode_provider: str | None = None):
    for fn in os.listdir(SYS_ATTR_PATH):
        # WMI convention means we have cruft -N suffix
        provider = None
        for s in SYS_ATTR_KNOWN:
            if fn.startswith(s):
                provider = s
                break
        if not provider:
            continue

        data = {}
        for v, tdp_fn in [
            ("pl1", TDP_PL1_FN),
            ("pl2", TDP_PL2_FN),
            ("pl3", TDP_PL3_FN),
        ]:
            try:
                with open(
                    os.path.join(SYS_ATTR_PATH, fn, SYS_ATTR_MID, tdp_fn, MIN_VAL)
                ) as f:
                    min_val = int(f.read().strip())
                with open(
                    os.path.join(SYS_ATTR_PATH, fn, SYS_ATTR_MID, tdp_fn, MAX_VAL)
                ) as f:
                    max_val = int(f.read().strip())
            except Exception:
                continue

            try:
                with open(
                    os.path.join(SYS_ATTR_PATH, fn, SYS_ATTR_MID, tdp_fn, DEF_VAL)
                ) as f:
                    def_val = int(f.read().strip())
            except Exception:
                def_val = None

            data[v] = (min_val, def_val, max_val)

        if "pl1" not in data:
            logger.error(f"Provider '{fn}' has partial TDP data: {data}")
            return

        return FwattrData(fn=fn, provider=provider, **data)


def setup_tdp_values(data: FwattrData, obj):
    obj["unit"] = f"→ {data.pl1[2]}"
    obj["children"] = load_relative_yaml("./tdp.yml")
    obj["children"]["tdp"]["min"] = data.pl1[0]
    obj["children"]["tdp"]["default"] = data.pl1[1] or 15  # not the best
    obj["children"]["tdp"]["max"] = data.pl1[2]


def set_tdp(tdp_fn: str, data: FwattrData, val: int):
    fn = os.path.join(SYS_ATTR_PATH, data.fn, SYS_ATTR_MID, tdp_fn, CUR_VAL)
    logger.info(f"Setting tdp value '{tdp_fn}' to {val} by writing to:\n{fn}")
    try:
        with open(fn, "w") as f:
            f.write(f"{val}\n")
        return True
    except Exception as e:
        logger.error(f"Failed writing value with error:\n{e}")
        return False


#
# Hwmon managed fan curve
#

HWMON = "/sys/class/hwmon"

DEFAULT_EDGE = {
    40: 45,
    45: 45,
    50: 45,
    55: 45,
    60: 55,
    65: 60,
    70: 70,
    80: 85,
    90: 100,
}
DEFAULT_TCTL = {
    40: 40,
    50: 45,
    60: 50,
    70: 80,
    80: 90,
    90: 100,
    100: 100,
}

FanCurve = tuple[tuple[int, int], ...]


class ManagedFan(NamedTuple):
    info: FanInfo
    edge: FanCurve
    tctl: FanCurve | None

def get_fan():
    info = get_fan_info()
    if not info:
        return
    return ManagedFan(
        info=info,
        edge=tuple((k, v) for k, v in DEFAULT_EDGE.items()),
        tctl=tuple((k, v) for k, v in DEFAULT_EDGE.items()) if info["tctl"] else None,
    )


def setup_fan(data: ManagedFan, obj):
    if isinstance(data, ManagedFan):
        obj.update(load_relative_yaml("./fan/managed.yml"))
        for target, curve in [
            ("manual_edge", data.edge),
            ("manual_junction", data.tctl),
        ]:
            if curve is None:
                del obj["modes"][target]
                continue
            temps = {}
            for temp, cc in curve:
                temps[f"st{temp}"] = {
                    "tags": ["slim"],
                    "type": "int",
                    "min": 0,
                    "max": 100,
                    "step": 2,
                    "unit": "%",
                    "title": f"{temp}C",
                    "default": cc,
                }
            obj["modes"][target]["children"] = {
                "info": obj["modes"][target]["children"]["info"],
                **temps,
                "reset": obj["modes"][target]["children"]["reset"],
            }


class UnifiedDriverPlugin(HHDPlugin):
    def __init__(self) -> None:
        self.name = f"adjustor_unified"
        self.priority = 6
        self.log = "adju"
        self.enabled = False
        self.initialized = False

        self.profiles = get_profiles()
        if self.profiles and self.profiles.has_custom:
            self.tdp = get_tdp_values(self.profiles.fn)
        else:
            self.tdp = None
        self.fan = get_fan()

        self.mode = None
        self.new_mode = None
        self.new_tdp = None
        self.queue_tdp = None
        self.old_target = None
        self.sys_tdp = False

        # Managed Fan
        self.fan_t = None
        self.fan_should_exit = TEvent()
        self.fan_junction = TEvent()
        self.fan_lock = Lock()
        self.fan_curve = {}
        self.fan_state = {}

    def is_supported(self):
        return self.profiles is not None

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}
        
        logger.info(f"Profile data: {self.profiles}\nTDP data: {self.tdp}")

        self.initialized = True
        out = {"tdp": {"unified": load_relative_yaml("settings.yml")}}

        assert self.profiles
        setup_modes(self.profiles, out["tdp"]["unified"]["children"]["tdp"])
        if self.tdp:
            setup_tdp_values(
                self.tdp, out["tdp"]["unified"]["children"]["tdp"]["modes"]["custom"]
            )
        else:
            del out["tdp"]["unified"]["children"]["tdp"]["modes"]["custom"]
        if self.fan:
            setup_fan(self.fan, out["tdp"]["unified"]["children"]["fan"])
        else:
            del out["tdp"]["unified"]["children"]["fan"]

        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def update(self, conf: Config):
        self.enabled = conf["hhd.settings.tdp_ready"].to(bool)

        if not self.enabled or not self.initialized:
            self.old_conf = None
            self.startup = True
            return

        # If not old config, exit, as values can not be set
        if not self.old_conf:
            self.old_conf = conf["tdp.unified"]
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
        assert self.profiles
        if new_tdp:
            mode = "custom"
            conf["tdp.unified.tdp.mode"] = mode
        elif new_mode:
            mode = new_mode
            conf["tdp.unified.tdp.mode"] = mode
        else:
            mode = conf["tdp.unified.tdp.mode"].to(str)
        self.mode = mode

        tdp_reset = False
        if mode is not None and mode != self.old_conf["tdp.mode"].to(str):
            if not new_tdp:
                self.sys_tdp = False
            tdp_reset = True

        if mode is not None and self.startup:
            tdp_reset = True

        # Show steam message
        if self.sys_tdp:
            conf["tdp.unified.sys_tdp"] = _("Steam is controlling TDP")
        else:
            conf["tdp.unified.sys_tdp"] = ""

        #
        # TDP Management
        #

        # Set TDP and handle EPP
        if tdp_reset and mode != "custom":
            set_mode(self.profiles, mode)
            match mode:
                case "quiet" | "low-power":
                    new_target = "power"
                case "balanced":
                    new_target = "balanced"
                case _:  # "performance":
                    new_target = "performance"

        # In custom mode, re-apply settings with debounce
        tdp_set = False
        if mode == "custom" and self.tdp:
            # Check user changed values
            if new_tdp:
                steady = new_tdp
                conf["tdp.unified.tdp.custom.tdp"] = steady
            else:
                steady = conf["tdp.unified.tdp.custom.tdp"].to(int)

            # Bounds check
            if steady < self.tdp.pl1[0]:
                steady = self.tdp.pl1[0]
                conf["tdp.unified.tdp.custom.tdp"] = steady
            elif steady > self.tdp.pl1[2]:
                steady = self.tdp.pl1[2]
                conf["tdp.unified.tdp.custom.tdp"] = steady

            # Update steam text
            steady_updated = steady and steady != self.old_conf["tdp.custom.tdp"].to(
                int
            )
            if not new_tdp and steady_updated:
                self.sys_tdp = False

            steady_updated |= tdp_reset
            boost = conf["tdp.unified.tdp.custom.boost"].to(bool)
            boost_updated = boost != self.old_conf["tdp.custom.boost"].to(bool)

            # If yes, queue an update
            # Debounce
            if self.startup or steady_updated or boost_updated:
                self.queue_tdp = curr + APPLY_DELAY

            tdp_set = self.queue_tdp and self.queue_tdp < curr
            if tdp_set:
                # Fixup EPP
                # Find target mapping for energy settings
                max_pl1 = self.tdp.pl1[2]
                for max_val, (balance, performance) in PL1_TO_ENERGY_MAP:
                    if max_pl1 <= max_val:
                        balance_min = balance
                        performance_min = performance
                        break
                else:
                    balance_min, performance_min = PL1_TO_ENERGY_MAP[-1][1]

                if steady < balance_min:
                    new_target = "power"
                elif steady < performance_min:
                    new_target = "balanced"
                else:
                    new_target = "performance"

                self.queue_tdp = None
                set_mode(self.profiles, "custom")
                set_tdp(TDP_PL1_FN, self.tdp, steady)
                if boost:
                    if self.tdp.pl2:
                        pl2 = min(steady + 2, self.tdp.pl2[2])
                        set_tdp(TDP_PL2_FN, self.tdp, pl2)
                    if self.tdp.pl3:
                        # Interpolate here
                        pl3 = min(
                            int(steady * self.tdp.pl3[2] / self.tdp.pl1[2]), self.tdp.pl3[2]
                        )
                        set_tdp(TDP_PL3_FN, self.tdp, pl3)
                else:
                    if self.tdp.pl2:
                        set_tdp(TDP_PL2_FN, self.tdp, steady)
                    if self.tdp.pl3:
                        set_tdp(TDP_PL3_FN, self.tdp, steady)

        # Apply new target
        if new_target and new_target != self.old_target:
            self.old_target = new_target
            self.emit({"type": "energy", "status": new_target})

        #
        # Fan Settings for Managed fans
        #

        if self.fan and isinstance(self.fan, ManagedFan):
            mode = conf["tdp.unified.fan.mode"].to(str)
            if mode != "disabled":
                with self.fan_lock:
                    if conf[f"tdp.unified.fan.{mode}.reset"].to(bool):
                        conf[f"tdp.unified.fan.{mode}.reset"] = False
                        curve = self.fan.edge if "edge" in mode else self.fan.tctl
                        assert curve, f"Curve is missing for mode '{mode}'. This should not be possible."
                        for k, v in curve:
                            if f"tdp.unified.fan.{mode}.st{k}" in conf:
                                conf[f"tdp.unified.fan.{mode}.st{k}"] = v

                    for k, v in conf[f"tdp.unified.fan.{mode}"].to(dict).items():
                        if not k.startswith("st"):
                            continue
                        self.fan_curve[int(k[2:])] = v / 100
                    if self.fan_state:
                        s = self.fan_state
                        fan_speed = (
                            f"{s['v_curr']*100:.1f}% @ {s['t_target']}C"
                            if s["in_setpoint"]
                            else f"{s['v_curr']*100:.1f}% → {s['v_target']*100:.1f}%"
                        )
                        conf[f"tdp.unified.fan.{mode}.info"] = (
                            f"{fan_speed} ({', '.join(map(str, s['v_rpm']))} RPM)\n"
                            + (
                                f"Tctl: {s['t_junction']:.2f}C, "
                                if s["t_junction"] is not None
                                else ""
                            )
                            + f"Edge: {s['t_edge']:.2f}C\n"
                        )
                    if "junction" in mode:
                        self.fan_junction.set()
                    else:
                        self.fan_junction.clear()

                if not self.fan_t:
                    self.fan_should_exit.clear()
                    self.fan_t = Thread(
                        target=fan_worker,
                        args=(
                            self.fan.info,
                            self.fan_should_exit,
                            self.fan_lock,
                            self.fan_curve,
                            self.fan_state,
                            self.fan_junction,
                        ),
                    )
                    self.fan_t.start()
            else:
                if self.fan_t:
                    self.fan_should_exit.set()
                    self.fan_t.join()
                    self.fan_t = None
                    self.fan_state = {}

        # Finish
        self.old_conf = conf["tdp.unified"]
        if self.startup:
            self.startup = False

    def notify(self, events: Sequence[Event]):
        for ev in events:
            if ev["type"] == "tdp":
                self.new_tdp = ev["tdp"]
                self.sys_tdp = ev["tdp"] is not None
            elif ev["type"] == "ppd":
                assert self.profiles
                match ev["status"]:
                    case "power":
                        for p, _ in self.profiles.profiles:
                            if p in ("low-power", "quiet"):
                                self.new_mode = p
                                break
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
                old_tdp = self.tdp
                assert self.profiles
                self.tdp = get_tdp_values(self.profiles.fn)
                if old_tdp != self.tdp:
                    self.emit({"type": "settings"})
                    self.initialized = False

                self.queue_tdp = time.time() + APPLY_DELAY
            elif ev["type"] == "special" and ev["event"] == "tdp_cycle":
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
        if self.fan_t:
            self.fan_should_exit.set()
            self.fan_t.join()
            self.fan_t = None
            self.fan_state = {}
