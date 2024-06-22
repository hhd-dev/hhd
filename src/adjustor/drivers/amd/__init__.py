import logging

from hhd.plugins import Context, HHDPlugin, load_relative_yaml
from hhd.plugins.conf import Config

from adjustor.fuse.gpu import (
    get_igpu_status,
    set_gpu_auto,
    set_gpu_manual,
    set_cpu_boost,
)

logger = logging.getLogger(__name__)


class AmdGPUPlugin(HHDPlugin):

    def __init__(
        self,
    ) -> None:
        self.name = f"adjustor_gpu"
        self.priority = 8
        self.log = "agpu"
        self.enabled = False
        self.initialized = False
        self.old_mode = None
        self.old_freq = None
        self.supports_boost = False
        self.old_boost = None
        self.logged_boost = False

    def settings(self):
        if not self.enabled:
            self.initialized = False
            return {}

        status = get_igpu_status()
        if not status:
            logger.error("Could not get frequency status. Disabling AMD GPU plugin.")
            return {}

        self.initialized = True
        sets = load_relative_yaml("./settings.yml")

        freq = sets["children"]["level"]["modes"]["manual"]["children"]["frequency"]
        freq["min"] = status.freq_min
        freq["max"] = status.freq_max
        freq["default"] = ((status.freq_min + status.freq_max) // 200) * 100

        self.supports_boost = status.cpu_boost is not None
        if self.supports_boost:
            if not self.logged_boost:
                logger.info(f"CPU Boost toggling is supported.")
        else:
            if not self.logged_boost:
                logger.warning(f"CPU Boost toggling is not supported.")
            del sets["children"]["cpu_boost"]
        self.logged_boost = True
        return {"tdp": {"amd_gpu": sets}}

    def open(
        self,
        emit,
        context: Context,
    ):
        self.emit = emit

    def update(self, conf: Config):
        self.enabled = conf["hhd.settings.tdp_enable"].to(bool)
        if not self.initialized:
            return

        new_mode = conf["tdp.amd_gpu.level.mode"].to(str)
        new_freq = conf["tdp.amd_gpu.level.manual.frequency"].to(int)
        if new_mode != self.old_mode or new_freq != self.old_freq:
            self.old_mode = new_mode
            self.old_freq = new_freq

            try:
                if new_mode == "manual":
                    set_gpu_manual(new_freq)
                else:
                    set_gpu_auto()
            except Exception as e:
                logger.error(f"Failed to set GPU mode:\n{e}")

        if self.supports_boost:
            new_boost = conf["tdp.amd_gpu.cpu_boost"].to(bool)
            if new_boost != self.old_boost:
                self.old_boost = new_boost
                try:
                    set_cpu_boost(new_boost)
                except Exception as e:
                    logger.error(f"Failed to set CPU boost:\n{e}")

    def close(self):
        pass
