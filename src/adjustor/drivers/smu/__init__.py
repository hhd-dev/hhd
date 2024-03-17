import logging
import time

from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

from adjustor.core.alib import AlibParams, DeviceParams, alib
from adjustor.core.platform import get_platform_choices, set_platform_profile

logger = logging.getLogger(__name__)

PP_DELAY = 0.2
APPLY_DELAY = 1


class SmuQamPlugin(HHDPlugin):

    def __init__(
        self,
        dev: dict[str, DeviceParams],
        pp_map: list[tuple[str, int]] | None,
        init_tdp: bool = True,
    ) -> None:
        self.name = f"adjustor_smu_qam"
        self.priority = 7
        self.log = "smuq"
        self.enabled = False
        self.initialized = False
        self.dev = dev
        self.enforce_limits = True
        self.emit = None
        self.old_conf = None
        self.startup = True
        self.queued = None

        self.old_tdp = None
        self.old_boost = None
        self.is_set = False
        self.lims = self.dev.get("skin_limit", self.dev.get("stapm_limit", None))

        # Workaround for debugging on the legion go
        # Avoids sending SMU commands that will conflict with Lenovo TDP on
        # startup
        self.init_tdp = init_tdp

        if pp_map:
            self.pps = get_platform_choices() or []
            if self.pps:
                self.pp_map = pp_map
            else:
                logger.warning(
                    f"Platform profile map was provided but device does not have platform profiles."
                )
                self.pp_map = None
        else:
            self.pps = []
            self.pp_map = None

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
        ), f"Device params do not include skin limit or stapm limit to set tdp."

        dmin, smin, default, smax, dmax = lims
        if self.enforce_limits:
            out["tdp"]["qam"]["children"]["tdp"].update(
                {"min": smin, "max": smax, "default": default}
            )
        else:
            out["tdp"]["qam"]["children"]["tdp"].update(
                {"min": dmin, "max": dmax, "default": default}
            )

        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def update(self, conf: Config):
        self.enabled = conf["hhd.settings.tdp_enable"].to(bool)
        self.enforce_limits = conf["hhd.settings.enforce_limits"].to(bool)
        if not self.enabled or not self.initialized:
            self.startup = self.init_tdp
            return

        curr = time.time()
        new_tdp = conf["tdp.qam.tdp"].to(int)
        if self.startup and self.lims:
            _, smin, _, smax, _ = self.lims
            if smin and new_tdp < smin:
                logger.warning(
                    f"Device TDP ({new_tdp}) too low for startup, adjusting."
                )
                new_tdp = smin
                conf["tdp.qam.tdp"] = smin
            if smax and new_tdp > smax:
                logger.warning(
                    f"Device TDP ({new_tdp}) too low for startup, adjusting."
                )
                new_tdp = smax
                conf["tdp.qam.tdp"] = smax

        new_boost = conf["tdp.qam.boost"].to(bool)
        changed = (
            (new_tdp != self.old_tdp or new_boost != self.old_boost)
            and self.old_tdp is not None
            and self.old_boost is not None
        )
        if self.startup or changed:
            self.queued = curr + APPLY_DELAY
            self.is_set = False

            conf["tdp.smu.std.skin_limit"] = new_tdp
            conf["tdp.smu.std.stapm_limit"] = new_tdp

            if self.pp_map and conf["tdp.smu.platform_profile"].to(str) != "disabled":
                pp = self.pp_map[0][0]
                for npp, tdp in self.pp_map:
                    if tdp < new_tdp and npp in self.pps:
                        pp = npp
                conf["tdp.smu.platform_profile"] = pp

            if new_boost:
                try:
                    fmax = self.dev["fast_limit"].smax
                    smax = self.dev["stapm_limit"].smax
                    assert fmax and smax

                    conf["tdp.smu.std.fast_limit"] = int(new_tdp * (fmax / smax))
                    conf["tdp.smu.std.slow_limit"] = min(
                        new_tdp + 2, conf["tdp.smu.std.fast_limit"].to(int)
                    )
                except Exception as e:
                    logger.error(f"Setting boost failed with error:\n{e}")
                    conf["tdp.qam.boost"] = False
            else:
                conf["tdp.smu.std.slow_limit"] = new_tdp
                conf["tdp.smu.std.fast_limit"] = new_tdp

        if self.startup or (self.queued and self.queued < curr):
            self.startup = False
            self.queued = None
            conf["tdp.smu.apply"] = True

        self.old_tdp = new_tdp
        self.old_boost = new_boost

    def close(self):
        pass


class SmuDriverPlugin(HHDPlugin):

    def __init__(
        self,
        dev: dict[str, DeviceParams],
        cpu: dict[str, AlibParams],
        platform_profile: bool = True,
    ) -> None:
        self.name = f"adjustor_smu"
        self.priority = 9
        self.log = "asmu"
        self.enabled = False
        self.initialized = False
        self.enforce_limits = True

        self.dev = dev
        self.cpu = cpu

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
        pass

    def update(self, conf: Config):
        self.enabled = conf["hhd.settings.tdp_enable"].to(bool)
        self.enforce_limits = conf["hhd.settings.enforce_limits"].to(bool)
        if not self.enabled or not self.initialized:
            return

        if self.enforce_limits:
            for k, v in conf["tdp.smu.std"].to(dict).items():
                if k in self.dev:
                    mmin, mmax = self.dev[k].smin, self.dev[k].smax
                    if v < mmin:
                        conf["tdp.smu.std", k] = mmin
                    if v > mmax:
                        conf["tdp.smu.std", k] = mmax
            for k, v in conf["tdp.smu.adv"].to(dict).items():
                if k in self.dev and k != "enable":
                    mmin, mmax = self.dev[k].smin, self.dev[k].smax
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

        if set(new_vals.items()) != set(self.old_vals.items()):
            self.is_set = False

        if self.has_pp:
            new_pp = conf["tdp.smu.platform_profile"].to(str)
            if new_pp != self.old_pp and new_pp != "disabled":
                self.is_set = False
            self.old_pp = new_pp

        if conf["tdp.smu.apply"].to(bool):
            conf["tdp.smu.apply"] = False

            if self.has_pp:
                cpp = conf["tdp.smu.platform_profile"].to(str)
                if cpp != "disabled":
                    logger.info(f"Setting platform profile to '{cpp}'")
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

    def close(self):
        pass
