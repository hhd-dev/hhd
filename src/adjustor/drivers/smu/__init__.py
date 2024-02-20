import logging

from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

from adjustor.core.alib import AlibParams, DeviceParams

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

        self.check_pp = platform_profile
        self.old_pp = None
        self.has_pp = False

        self.old_tdp = None
        self.old_boost = None

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
        return out

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
        if new_tdp != self.old_tdp or new_boost != self.old_boost:
            conf["tdp.qam.status"] = "Not Set"
            self.old_tdp = new_tdp
            self.old_boost = new_boost

        if conf["tdp.qam.apply"].to(bool):
            conf["tdp.qam.apply"] = False
            conf["tdp.qam.status"] = "Set"

    def close(self):
        pass


class SmuDriverPlugin(HHDPlugin):

    def __init__(
        self,
        dev: dict[str, DeviceParams],
        cpu: dict[str, AlibParams],
    ) -> None:
        self.name = f"adjustor_smu"
        self.priority = 8
        self.log = "asmu"
        self.enabled = False

        self.dev = dev
        self.cpu = cpu

        for k in dev:
            assert (
                k in cpu
            ), f"Device supports more keys than what is available in its architecture spec. Key '{k}' missing."

    def settings(self):
        if not self.enabled:
            return {}
        out = {
            "tdp": {
                "smu": load_relative_yaml("smu.yml"),
            }
        }

        std = out["tdp"]["smu"]["children"]["std"]["children"]
        for k in list(std):
            if k not in self.cpu:
                del std[k]
        adv = out["tdp"]["smu"]["children"]["std"]["children"]
        for k in list(adv):
            if k not in self.cpu and k != "enable":
                del adv[k]

        return out

    def open(
        self,
        emit,
        context: Context,
    ):
        pass

    def update(self, conf: Config):
        self.enabled = conf["tdp.general.enable"].to(bool)

    def close(self):
        pass
