import logging

from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

from adjustor.core.alib import AlibParams, DeviceParams, alib

logger = logging.getLogger(__name__)


def get_platform_choices():
    try:
        with open("/sys/firmware/acpi/platform_profile_choices", "r") as f:
            return f.read().strip().split(" ")
    except Exception:
        logger.info(
            f"Could not enumerate platform profile choices. Disabling platform profile."
        )
        return None


def set_platform_profile(prof: str):
    try:
        with open("/sys/firmware/acpi/platform_profile", "w") as f:
            f.write(prof)
        return True
    except Exception as e:
        logger.error(f"Could not set platform profile with error:\n{e}")
        return False


def get_platform_profile():
    try:
        with open("/sys/firmware/acpi/platform_profile", "r") as f:
            return f.read().replace("\n", "")
    except Exception as e:
        logger.error(f"Could not read platform profile with error:\n{e}")
        return None


class SmuQamPlugin(HHDPlugin):

    def __init__(
        self, dev: dict[str, DeviceParams], platform_profile: bool = True
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

        self.check_pp = platform_profile
        self.old_pp = None
        self.has_pp = False

        self.old_tdp = None
        self.old_boost = None
        self.is_set = False

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}

        self.initialized = True
        out = {"tdp": {"qam": load_relative_yaml("qam.yml")}}

        # Limit platform profile choices or remove
        choices = get_platform_choices()
        if choices and self.check_pp:
            options = out["tdp"]["qam"]["children"]["platform_profile"]["options"]
            for c in list(options):
                if c not in choices:
                    del options[c]
            self.has_pp = True
        else:
            del out["tdp"]["qam"]["children"]["platform_profile"]
            self.has_pp = False

        # Set device limits based on stapm
        lims = self.dev.get("skin_limit", self.dev.get("stapm_limit", None))
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
        self.enabled = conf["tdp.general.enable"].to(bool)
        self.enforce_limits = conf["tdp.general.enforce_limits"].to(bool)
        if not self.enabled or not self.initialized:
            return

        if self.has_pp:
            cpp = conf["tdp.qam.platform_profile"].to(str)

            if cpp and cpp != self.old_pp:
                logger.info(f"Setting platform profile to '{cpp}'")
                set_platform_profile(cpp)

            pp = get_platform_profile()
            conf["tdp.qam.platform_profile"] = pp
            self.old_pp = pp

        new_tdp = conf["tdp.qam.tdp"].to(int)
        new_boost = conf["tdp.qam.boost"].to(bool)
        changed = (
            (new_tdp != self.old_tdp or new_boost != self.old_boost)
            and self.old_tdp is not None
            and self.old_boost is not None
        )
        if changed or conf["tdp.qam.apply"].to(bool):
            self.is_set = False

            conf["tdp.smu.std.skin_limit"] = new_tdp
            conf["tdp.smu.std.stapm_limit"] = new_tdp
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

        self.old_tdp = new_tdp
        self.old_boost = new_boost
        if conf["tdp.qam.apply"].to(bool):
            conf["tdp.qam.apply"] = False
            conf["tdp.smu.apply"] = True
            self.is_set = True

        if self.is_set:
            conf["tdp.qam.status"] = "Set"
        else:
            conf["tdp.qam.status"] = "Not Set"

    def close(self):
        pass


class SmuDriverPlugin(HHDPlugin):

    def __init__(
        self,
        dev: dict[str, DeviceParams],
        cpu: dict[str, AlibParams],
    ) -> None:
        self.name = f"adjustor_smu"
        self.priority = 9
        self.log = "asmu"
        self.enabled = False
        self.initialized = False
        self.enforce_limits = True

        self.dev = dev
        self.cpu = cpu

        self.old_vals = {}

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
        self.enabled = conf["tdp.general.enable"].to(bool)
        self.enforce_limits = conf["tdp.general.enforce_limits"].to(bool)
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
            conf["tdp.smu.status"] = "Not Set"

        if conf["tdp.smu.apply"].to(bool):
            conf["tdp.smu.apply"] = False
            alib(
                new_vals,
                self.cpu,
                limit="device" if self.enforce_limits else "cpu",
                dev=self.dev,
            )
            conf["tdp.smu.status"] = "Set"

        self.old_vals = new_vals

    def close(self):
        pass
