import logging
import time
from collections.abc import Sequence
from threading import Event as TEvent
from threading import Lock, Thread

from adjustor.core.alib import AlibParams, DeviceParams, alib
from adjustor.core.fan import fan_worker, get_fan_info
from adjustor.core.platform import get_platform_choices, set_platform_profile
from adjustor.i18n import _
from hhd.plugins import Context, Event, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

logger = logging.getLogger(__name__)

PP_DELAY = 0.2
APPLY_DELAY = 1
SLEEP_DELAY = 4

DEFAULT_EDGE = {
    40: 30,
    45: 30,
    50: 40,
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


class SmuQamPlugin(HHDPlugin):

    def __init__(
        self,
        dev: dict[str, DeviceParams],
        pp_map: list[tuple[str, list[str], int, int]] | None,
        pp_enable: bool = True,
        init_tdp: bool = True,
        dock_aware: bool = False,
        dc_cap: dict[str, int] | None = None,
    ) -> None:
        self.name = "adjustor_smu_qam"
        self.priority = 7
        self.log = "smuq"
        self.enabled = False
        self.initialized = False
        self.dev = dev
        self.enforce_limits = True
        self.old_enforce = None
        self.dock_aware = dock_aware
        self.dc_cap = dc_cap
        self.on_ac = True  # assume AC until determined otherwise
        self.old_on_ac = None
        self.emit = None
        self.old_conf = None
        self.startup = True
        self.queued = None
        self.sys_tdp = False

        self.old_tdp = None
        self.old_boost = None
        self.new_tdp = None
        self.is_set = False
        self.lims = self.dev.get("skin_limit", self.dev.get("stapm_limit", None))

        self.fan_info = None
        self.fan_t = None
        self.fan_should_exit = TEvent()
        self.fan_junction = TEvent()
        self.fan_lock = Lock()
        self.fan_curve = {}
        self.fan_state = {}

        # Workaround for debugging on the legion go
        # Avoids sending SMU commands that will conflict with Lenovo TDP on
        # startup
        self.init_tdp = init_tdp

        self.pp_map = pp_map
        if pp_enable and pp_map:
            self.pps = get_platform_choices() or []
            if not self.pps:
                logger.warning(
                    "Platform profile map was provided but device does not have platform profiles."
                )
        else:
            self.pps = []

    def _effective_smax(self, key: str = "skin_limit") -> int | None:
        """Get the effective safe maximum for a parameter, considering power state.

        On battery (on_ac=False) with a dc_cap configured, the battery-mode
        cap is used instead of the device's default smax. This prevents
        exceeding the device's safe TDP on battery power."""
        base_smax = self.dev[key].smax if key in self.dev else None
        if not self.on_ac and self.dc_cap and key in self.dc_cap:
            return self.dc_cap[key]
        return base_smax

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}

        self.initialized = True
        out = {"tdp": {"qam": load_relative_yaml("qam.yml")}}

        # Set device limits based on stapm
        lims = self.lims
        assert (
            lims
        ), "Device params do not include skin limit or stapm limit to set tdp."

        dmin, smin, default, smax, dmax = lims
        if not self.enforce_limits:
            out["tdp"]["qam"]["children"]["tdp"].update(
                {"min": dmin, "max": dmax, "default": default}
            )
        else:
            eff_smax = self._effective_smax("skin_limit") or smax
            out["tdp"]["qam"]["children"]["tdp"].update(
                {"min": smin, "max": eff_smax, "default": default}
            )

        if not self.fan_info:
            del out["tdp"]["qam"]["children"]["fan"]
        else:
            base = out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_edge"][
                "children"
            ]["st40"]
            reset = out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_edge"][
                "children"
            ].pop("reset")
            for k, v in DEFAULT_EDGE.items():
                out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_edge"][
                    "children"
                ][f"st{k}"] = {**base, "title": f"{k}C", "default": v}
            out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_edge"]["children"][
                "reset"
            ] = reset
            reset = out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_junction"][
                "children"
            ].pop("reset")
            for k, v in DEFAULT_TCTL.items():
                out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_junction"][
                    "children"
                ][f"st{k}"] = {**base, "title": f"{k}C", "default": v}
            out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_junction"][
                "children"
            ]["reset"] = reset

            if self.fan_info["tctl"] is None:
                del out["tdp"]["qam"]["children"]["fan"]["modes"]["manual_junction"]

        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit
        self.fan_info = get_fan_info()
        try:
            from hhd.utils import get_ac_status, get_ac_status_fn
            ac = get_ac_status(get_ac_status_fn())
            if ac is not None:
                self.on_ac = ac
        except Exception:
            pass

    def update(self, conf: Config):
        self.enabled = conf["hhd.settings.tdp_ready"].to(bool)
        user_enforce = conf["hhd.settings.enforce_limits"].to(bool)
        dock_running = conf.get("cooling_dock.dock_running", False)
        # Dock-aware devices relax the enforced cap while the cooling dock is
        # actively running on AC power (e.g. SUPER X: 75W -> 120W).
        # On battery power, limits are always enforced to protect the battery.
        self.enforce_limits = user_enforce and not (
            dock_running and self.dock_aware and self.on_ac
        )
        dock_changed = self.enforce_limits != self.old_enforce
        self.old_enforce = self.enforce_limits

        # Track power state changes to re-clamp TDP on AC/DC transitions.
        power_changed = self.on_ac != self.old_on_ac
        self.old_on_ac = self.on_ac

        if (dock_changed or power_changed) and self.emit:
            self.emit({"type": "settings"})

        if not self.enabled or not self.initialized:
            self.startup = self.init_tdp
            return

        curr = time.perf_counter()
        sys_tdp = False
        if self.new_tdp:
            new_tdp = self.new_tdp
            self.new_tdp = None
            sys_tdp = True
            conf["tdp.qam.tdp"] = new_tdp
        else:
            new_tdp = conf["tdp.qam.tdp"].to(int)

        if (self.startup or dock_changed or power_changed) and self.lims and self.enforce_limits:
            smin = self.lims.smin
            smax = self._effective_smax("skin_limit")

            if smin and new_tdp < smin:
                logger.warning(
                    f"Device TDP ({new_tdp}) too low for startup, adjusting."
                )
                new_tdp = smin
                conf["tdp.qam.tdp"] = smin
            if smax and new_tdp > smax:
                logger.warning(
                    f"Device TDP ({new_tdp}W) exceeds safe limit ({smax}W), clamping."
                )
                new_tdp = smax
                conf["tdp.qam.tdp"] = smax

        new_boost = conf["tdp.qam.boost"].to(bool)
        changed = (
            (new_tdp != self.old_tdp or new_boost != self.old_boost)
            and self.old_tdp is not None
            and self.old_boost is not None
        )
        if changed and not sys_tdp:
            self.sys_tdp = False

        if self.startup or changed or dock_changed or power_changed:
            self.queued = curr + APPLY_DELAY
            self.is_set = False

            conf["tdp.smu.std.skin_limit"] = new_tdp
            conf["tdp.smu.std.stapm_limit"] = new_tdp

            if self.pp_map:
                pp = ep = self.pp_map[0][0]
                for nep, npps, tdp, target in self.pp_map:
                    if tdp < new_tdp:
                        ep = nep
                        for npp in npps:
                            if npp in self.pps:
                                pp = npp
                if (
                    self.pps
                    and conf.get("tdp.smu.platform_profile", "disabled") != "disabled"
                ):
                    conf["tdp.smu.platform_profile"] = pp
                conf["tdp.smu.energy_policy"] = ep

            if new_boost:
                try:
                    # Use the unlocked (dmax) limits when the dock is running
                    # so boost scales correctly up to the ALIB cap.
                    # On battery, use DC cap for boost if available.
                    if not self.enforce_limits:
                        fmax = self.dev["fast_limit"].max
                        smax = self.dev["stapm_limit"].max
                    else:
                        fmax = self._effective_smax("fast_limit")
                        smax = self._effective_smax("stapm_limit")
                    assert fmax and smax

                    conf["tdp.smu.std.fast_limit"] = int(
                        round(new_tdp * (fmax / smax))
                    )
                    conf["tdp.smu.std.slow_limit"] = min(
                        new_tdp + 2, conf["tdp.smu.std.fast_limit"].to(int)
                    )
                except Exception as e:
                    logger.error(f"Setting boost failed with error:\n{e}")
                    conf["tdp.qam.boost"] = False
            else:
                conf["tdp.smu.std.slow_limit"] = new_tdp
                conf["tdp.smu.std.fast_limit"] = new_tdp

        # Show status message about TDP limits
        if self.sys_tdp:
            conf["tdp.qam.sys_tdp"] = _("Steam is controlling TDP")
        elif self.enforce_limits and not self.on_ac and self.dc_cap:
            eff = self._effective_smax("skin_limit")
            conf["tdp.qam.sys_tdp"] = f"TDP limited to {eff}W (on battery)"
        elif self.dock_aware and self.enforce_limits and not dock_running:
            conf["tdp.qam.sys_tdp"] = f"TDP limited to {self.lims.smax}W (dock not connected)"
        else:
            conf["tdp.qam.sys_tdp"] = ""

        if self.startup or (self.queued and self.queued < curr):
            self.startup = False
            self.queued = None
            conf["tdp.smu.apply"] = True

        self.old_tdp = new_tdp
        self.old_boost = new_boost

        if self.fan_info:
            mode = conf["tdp.qam.fan.mode"].to(str)
            if mode != "disabled":
                with self.fan_lock:
                    if conf[f"tdp.qam.fan.{mode}.reset"].to(bool):
                        conf[f"tdp.qam.fan.{mode}.reset"] = False
                        curve = DEFAULT_EDGE if "edge" in mode else DEFAULT_TCTL
                        for k, v in curve.items():
                            if f"tdp.qam.fan.{mode}.st{k}" in conf:
                                conf[f"tdp.qam.fan.{mode}.st{k}"] = v

                    for k, v in conf[f"tdp.qam.fan.{mode}"].to(dict).items():
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
                        conf[f"tdp.qam.fan.{mode}.info"] = (
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
                            self.fan_info,
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

    def notify(self, events: Sequence[Event]):
        for ev in events:
            if ev["type"] == "tdp":
                self.sys_tdp = True
                self.new_tdp = ev["tdp"]
                self.sys_tdp = ev["tdp"] is not None

            if ev["type"] == "ppd" and self.pp_map:
                for ep, pps, tdp, target in self.pp_map:
                    if ep == ev["status"]:
                        self.new_tdp = target
                        break
                else:
                    logger.warning(f"Energy profile '{ev['status']}' not found in map.")

            if ev["type"] == "special" and ev.get("event", None) == "wakeup":
                logger.info(
                    f"Waking up from sleep, resetting TDP after {SLEEP_DELAY} seconds."
                )
                self.queued = time.perf_counter() + SLEEP_DELAY

            # AC/DC power state changes: re-clamp TDP to the appropriate
            # safe limit on the next update() cycle.
            if ev["type"] == "acpi" and ev.get("event") in ("ac", "dc"):
                new_ac = ev["event"] == "ac"
                if new_ac != self.on_ac:
                    logger.info(
                        f"Power state changed to {'AC' if new_ac else 'battery'}, "
                        f"re-evaluating TDP limits."
                    )
                    self.on_ac = new_ac

    def close(self):
        if self.fan_t:
            self.fan_should_exit.set()
            self.fan_t.join()
            self.fan_t = None
            self.fan_state = {}


class SmuDriverPlugin(HHDPlugin):

    def __init__(
        self,
        dev: dict[str, DeviceParams],
        cpu: dict[str, AlibParams],
        platform_profile: bool = True,
        dock_aware: bool = False,
        dc_cap: dict[str, int] | None = None,
    ) -> None:
        self.name = "adjustor_smu"
        self.priority = 9
        self.log = "asmu"
        self.enabled = False
        self.initialized = False
        self.enforce_limits = True
        self.old_enforce = True
        self.dock_aware = dock_aware
        self.dc_cap = dc_cap
        self.on_ac = True  # assume AC until determined otherwise
        self.old_on_ac = True

        self.dev = dev
        self.cpu = cpu

        self.old_target = None
        self.check_pp = platform_profile
        self.has_pp = False
        self.old_pp = None
        self.old_vals = {}
        self.is_set = False

        for k in dev:
            assert (
                k in cpu
            ), f"Device supports more keys than what is available in its architecture spec. Key '{k}' missing."

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}
        self.initialized = True
        out = {
            "tdp": {
                "smu": load_relative_yaml("smu.yml"),
            }
        }

        # Limit platform profile choices or remove
        choices = get_platform_choices()
        if choices and self.check_pp:
            options = out["tdp"]["smu"]["children"]["platform_profile"]["options"]
            for c in list(options):
                if c not in choices and c != "disabled":
                    del options[c]
            self.has_pp = True
        else:
            del out["tdp"]["smu"]["children"]["platform_profile"]
            self.has_pp = False

        # Remove unsupported instructions
        # Add absolute limits based on CPU
        std = out["tdp"]["smu"]["children"]["std"]["children"]
        for k in list(std):
            if k in self.cpu:
                lims = self.cpu[k]
                std[k].update({"min": lims.min, "max": lims.max})
            else:
                del std[k]
        adv = out["tdp"]["smu"]["children"]["std"]["children"]
        for k in list(adv):
            if k in self.cpu and k != "enable":
                lims = self.cpu[k]
                std[k].update({"min": lims.min, "max": lims.max})
            else:
                del adv[k]

        # Set sane defaults based on device
        std = out["tdp"]["smu"]["children"]["std"]["children"]
        for k in list(std):
            if k in self.dev:
                std[k]["default"] = self.dev[k].default
        adv = out["tdp"]["smu"]["children"]["std"]["children"]
        for k in list(adv):
            if k in self.dev and k != "enable":
                adv[k]["default"] = self.dev[k].default

        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit
        try:
            from hhd.utils import get_ac_status, get_ac_status_fn
            ac = get_ac_status(get_ac_status_fn())
            if ac is not None:
                self.on_ac = ac
        except Exception:
            pass

    def update(self, conf: Config):
        self.enabled = conf["hhd.settings.tdp_ready"].to(bool)
        user_enforce = conf["hhd.settings.enforce_limits"].to(bool)
        dock_running = conf.get("cooling_dock.dock_running", False)
        self.enforce_limits = user_enforce and not (
            dock_running and self.dock_aware and self.on_ac
        )
        dock_changed = self.enforce_limits != self.old_enforce
        self.old_enforce = self.enforce_limits

        power_changed = self.on_ac != self.old_on_ac
        self.old_on_ac = self.on_ac

        if not self.enabled or not self.initialized:
            return

        if self.enforce_limits:
            for k, v in conf["tdp.smu.std"].to(dict).items():
                if k in self.dev:
                    mmin = self.dev[k].smin
                    mmax = self.dev[k].smax
                    # On battery, use the DC cap if available
                    if not self.on_ac and self.dc_cap and k in self.dc_cap:
                        mmax = self.dc_cap[k]
                    if v < mmin:
                        conf["tdp.smu.std", k] = mmin
                    if v > mmax:
                        conf["tdp.smu.std", k] = mmax
            for k, v in conf["tdp.smu.adv"].to(dict).items():
                if k in self.dev and k != "enable":
                    mmin = self.dev[k].smin
                    mmax = self.dev[k].smax
                    if not self.on_ac and self.dc_cap and k in self.dc_cap:
                        mmax = self.dc_cap[k]
                    if v < mmin:
                        conf["tdp.smu.adv", k] = mmin
                    if v > mmax:
                        conf["tdp.smu.adv", k] = mmax

        new_vals = {}
        for k, v in conf["tdp.smu.std"].to(dict[str, int]).items():
            new_vals[k] = v
        if conf["tdp.smu.adv.enable"].to(bool):
            for k, v in conf["tdp.smu.adv"].to(dict[str, int]).items():
                if k != "enable":
                    new_vals[k] = v

        if (
            set(new_vals.items()) != set(self.old_vals.items())
            or dock_changed
            or power_changed
        ):
            self.is_set = False

        if self.has_pp:
            new_pp = conf["tdp.smu.platform_profile"].to(str)
            if new_pp != self.old_pp and new_pp != "disabled":
                self.is_set = False
            self.old_pp = new_pp

        # Inform ppd instantly to avoid lag in slider
        new_target = conf["tdp.smu.energy_policy"].to(str)
        if new_target != self.old_target:
            self.old_target = new_target
            self.emit({"type": "energy", "status": new_target})  # type: ignore

        # Force re-apply when the dock connects/disconnects or power state changes
        # so the clamped limits reach the CPU immediately instead of waiting for a
        # manual Apply (or the SmuQamPlugin's delayed queue).
        if conf["tdp.smu.apply"].to(bool) or dock_changed or power_changed:
            conf["tdp.smu.apply"] = False

            if self.has_pp:
                cpp = conf["tdp.smu.platform_profile"].to(str)
                if cpp != "disabled":
                    set_platform_profile(cpp)
                    time.sleep(PP_DELAY)

            alib(
                new_vals,
                self.cpu,
                limit="device" if self.enforce_limits else "cpu",
                dev=self.dev,
            )
            self.is_set = True

        self.old_vals = new_vals
        if self.is_set:
            conf["tdp.smu.status"] = "Set"
        else:
            conf["tdp.smu.status"] = "Not Set"

    def notify(self, events: Sequence[Event]):
        for ev in events:
            # AC/DC power state: update on_ac so the next update() cycle
            # clamps TDP values using the correct limits.
            if ev["type"] == "acpi" and ev.get("event") in ("ac", "dc"):
                self.on_ac = ev["event"] == "ac"

    def close(self):
        pass
